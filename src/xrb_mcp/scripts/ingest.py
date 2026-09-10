import argparse
import json
import logging
from pathlib import Path

from xrb_mcp.database.connection import session_scope
from xrb_mcp.ingestion.embeddings import get_embedding_backend
from xrb_mcp.ingestion.metadata import PaperMetadata, read_metadata
from xrb_mcp.ingestion.papers import ingest_paper
from xrb_mcp.server.config import get_settings


def ingest_file(path: Path, metadata_path: Path | None = None) -> dict:
    sidecar = metadata_path or path.with_suffix(".json")
    metadata = read_metadata(sidecar) if sidecar.exists() else PaperMetadata()
    if metadata_path and not metadata_path.is_file():
        raise ValueError("Specified metadata sidecar does not exist")
    settings = get_settings()
    with session_scope() as session:
        return ingest_paper(
            session,
            path,
            metadata,
            settings.data_dir,
            get_embedding_backend(),
            settings.chunk_max_words,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a local PDF and optional JSON metadata")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(ingest_file(args.pdf, args.metadata), indent=2))


if __name__ == "__main__":
    main()
