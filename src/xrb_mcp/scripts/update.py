import argparse
import fnmatch
import json
import logging
from pathlib import Path

from xrb_mcp.ingestion.catalogues import is_catalogue_file, read_catalogue
from xrb_mcp.scripts.ingest import ingest_file
from xrb_mcp.server.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Incrementally ingest PDFs in an inbox directory")
    parser.add_argument("directory", type=Path, nargs="?")
    parser.add_argument("--recursive", action="store_true", help="Include nested directories")
    parser.add_argument(
        "--metadata-dir", type=Path, help="Sidecar directory mirroring the input directory"
    )
    parser.add_argument(
        "--collection", action="append", default=[], help="Add collection membership"
    )
    parser.add_argument(
        "--exclude", action="append", default=[], help="Exclude relative-path globs (repeatable)"
    )
    args = parser.parse_args()
    directory = args.directory or get_settings().data_dir / "inbox"
    if not directory.is_dir():
        parser.error("Inbox directory does not exist")
    if args.metadata_dir and not args.metadata_dir.is_dir():
        parser.error("Metadata directory does not exist")
    logging.basicConfig(level=logging.INFO)
    failed = 0
    paths = directory.rglob("*") if args.recursive else directory.iterdir()
    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in args.exclude):
            print(json.dumps({"file": relative, "status": "excluded"}))
            continue
        if path.is_file() and path.suffix.lower() == ".pdf":
            try:
                sidecar = (
                    (args.metadata_dir / relative).with_suffix(".json")
                    if args.metadata_dir
                    else None
                )
                result = ingest_file(path, sidecar, args.collection)
            except Exception as exc:
                # One failed document must not roll back successfully ingested neighbours.
                result = {"status": "failed", "error_type": type(exc).__name__}
                failed += 1
            print(json.dumps({"file": relative, **result}))
        elif path.is_file() and is_catalogue_file(path):
            try:
                summary = read_catalogue(path, preview_rows=1)
                result = {
                    "status": "catalogue_read",
                    "format": summary["format"],
                    "row_count": summary["row_count"],
                    "column_count": len(summary["columns"]),
                }
            except Exception as exc:
                result = {"status": "failed", "error_type": type(exc).__name__}
                failed += 1
            print(json.dumps({"file": relative, **result}))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
