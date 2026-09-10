import argparse
import json
import logging
from pathlib import Path

from xrb_mcp.scripts.ingest import ingest_file
from xrb_mcp.server.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Incrementally ingest PDFs in an inbox directory")
    parser.add_argument("directory", type=Path, nargs="?")
    args = parser.parse_args()
    directory = args.directory or get_settings().data_dir / "inbox"
    if not directory.is_dir():
        parser.error("Inbox directory does not exist")
    logging.basicConfig(level=logging.INFO)
    failed = 0
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() == ".pdf":
            try:
                result = ingest_file(path)
            except Exception as exc:
                # One failed document must not roll back successfully ingested neighbours.
                result = {"status": "failed", "error_type": type(exc).__name__}
                failed += 1
            print(json.dumps({"file": path.name, **result}))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
