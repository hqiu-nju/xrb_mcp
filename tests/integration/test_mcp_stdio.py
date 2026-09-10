import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy.orm import Session

from xrb_mcp.astronomy.source_resolver import register_source
from xrb_mcp.ingestion.metadata import PaperMetadata
from xrb_mcp.ingestion.papers import ingest_paper

pytestmark = pytest.mark.integration


async def test_real_mcp_client_calls_three_tools(empty_committed_database, pdf_factory, tmp_path):
    with Session(empty_committed_database) as session, session.begin():
        register_source(session, "MAXI J1820+070", ["ASASSN-18ey"], "synthetic test fixture")
        result = ingest_paper(
            session,
            pdf_factory(),
            PaperMetadata(
                title="Synthetic MCP test",
                sources=["MAXI J1820+070"],
            ),
            tmp_path,
        )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xrb_mcp.server.main"],
        env={
            **os.environ,
            "XRB_READ_DATABASE_URL": os.environ["XRB_TEST_DATABASE_URL"],
            "XRB_EMBEDDING_BACKEND": "none",
        },
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        assert len((await client.list_tools()).tools) == 3
        for name, arguments in [
            ("get_source", {"source": "ASASSN-18ey"}),
            ("get_paper", {"identifier": result["paper_id"]}),
            ("search_literature", {"query": "radio", "source": "MAXI J1820+070"}),
        ]:
            response = await client.call_tool(name, arguments)
            assert not response.isError, response
            assert response.content
        resource = await client.read_resource("xrb://papers/" + result["paper_id"])
        assert resource.contents
