"""Read-only MCP client example. Run with this project's Conda environment Python."""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from xrb_mcp.server.config import Settings

ROOT = Path(__file__).resolve().parents[2]


async def run(args: argparse.Namespace) -> dict:
    settings = Settings(_env_file=ROOT / ".env")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xrb_mcp.server.main"],
        cwd=ROOT,
        env={
            "XRB_READ_DATABASE_URL": settings.read_database_url.get_secret_value(),
            "XRB_EMBEDDING_BACKEND": settings.embedding_backend,
            "XRB_EMBEDDING_MODEL": settings.embedding_model,
            "XRB_EMBEDDING_REVISION": settings.embedding_revision,
        },
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        names = {tool.name for tool in (await client.list_tools()).tools}
        required = {"get_source", "get_paper", "search_literature"}
        if not required.issubset(names):
            raise RuntimeError("The connected server is missing required XRB tools")

        async def call(name: str, arguments: dict) -> dict:
            result = await client.call_tool(
                name, arguments, read_timeout_seconds=timedelta(seconds=120)
            )
            if result.isError:
                raise RuntimeError(f"{name} failed: {result.content}")
            if result.structuredContent is not None:
                return result.structuredContent
            for content in result.content:
                if content.type == "text":
                    return json.loads(content.text)
            raise RuntimeError(f"{name} returned no JSON content")

        source = await call("get_source", {"source": args.source})
        paper = await call("get_paper", {"identifier": args.paper}) if args.paper else None
        search = await call(
            "search_literature",
            {"query": args.query, "source": args.source, "top_k": args.top_k},
        )
        return {
            "tools": sorted(names),
            "source": source,
            "paper": {
                key: paper.get(key)
                for key in ("id", "title", "publication_year", "doi", "arxiv_id")
            }
            if paper
            else None,
            "search": search,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="Vela X-1")
    parser.add_argument("--query", default="wind")
    parser.add_argument(
        "--paper", default="10.1093/mnras/stab1995", help="Empty string skips lookup"
    )
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")
    print(json.dumps(asyncio.run(run(args)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
