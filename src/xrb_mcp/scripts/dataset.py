"""Download and verify externally hosted datasets independently of MCP startup."""

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

import httpx

from xrb_mcp.database.portable_schema import (
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    SNAPSHOT_VERSION,
)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _database_record(manifest: dict) -> dict:
    if (
        manifest.get("format") != "xrb-mcp-dataset"
        or manifest.get("format_version") != SNAPSHOT_VERSION
    ):
        raise ValueError("Unsupported dataset format; install a compatible MCP version")
    record = manifest.get("database", {})
    if record.get("filename") != DATABASE_FILENAME:
        raise ValueError(f"Dataset database filename must be {DATABASE_FILENAME}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
        raise ValueError("Dataset database checksum is missing or invalid")
    if type(record.get("size_bytes")) is not int or record["size_bytes"] <= 0:
        raise ValueError("Dataset database size is missing or invalid")
    return record


def _asset_path(directory: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or not relative.parts:
        raise ValueError("Dataset contains an unsafe asset path")
    path = directory.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Dataset asset resolves outside its directory")
    return path


def validate_dataset(directory: Path, verify_assets: bool = False) -> dict:
    """Verify a snapshot's bytes, format, relational integrity and optional originals."""
    directory = Path(directory)
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    record = _database_record(manifest)
    database = directory / DATABASE_FILENAME
    if database.stat().st_size != record["size_bytes"]:
        raise ValueError("Dataset database size does not match the manifest")
    if file_digest(database) != record["sha256"]:
        raise ValueError("Dataset database checksum does not match the manifest")
    from xrb_mcp.retrieval.portable import PortableReader

    with PortableReader(database) as reader:
        metadata = reader.dataset_info()
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("Dataset database integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Dataset contains broken provenance links")
    assets_checked = 0
    for asset in manifest.get("assets", []):
        path = _asset_path(directory, asset["path"])
        if verify_assets and asset.get("available"):
            if not path.is_file():
                raise ValueError(f"Dataset asset is missing: {asset['path']}")
            if path.stat().st_size != asset["size_bytes"] or file_digest(path) != asset["sha256"]:
                raise ValueError(f"Dataset asset checksum mismatch: {asset['path']}")
            assets_checked += 1
    return {
        "valid": True,
        "format_version": SNAPSHOT_VERSION,
        "counts": manifest.get("counts", {}),
        "assets_checked": assets_checked,
        "dataset": metadata,
    }


def _http_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("Dataset download URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Use a dataset URL without embedded credentials")
    return value


def download_dataset(manifest_url: str, output_dir: Path) -> dict:
    """Fetch only the manifest and SQLite index; never fetch PDFs or execute dataset code."""
    _http_url(manifest_url)
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Dataset destination is not empty; choose a new folder")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".xrb-download-", dir=output_dir.parent) as staging:
        stage = Path(staging)
        with httpx.Client(follow_redirects=True, timeout=60) as client:
            with client.stream("GET", manifest_url) as response:
                response.raise_for_status()
                manifest_bytes = bytearray()
                for block in response.iter_bytes():
                    manifest_bytes.extend(block)
                    if len(manifest_bytes) > 4 * 1024 * 1024:
                        raise ValueError("Dataset manifest is too large")
                final_url = _http_url(str(response.url))
            manifest = json.loads(manifest_bytes)
            record = _database_record(manifest)
            database_url = _http_url(urljoin(final_url, DATABASE_FILENAME))
            with client.stream("GET", database_url) as response:
                response.raise_for_status()
                downloaded = 0
                with (stage / DATABASE_FILENAME).open("wb") as stream:
                    for block in response.iter_bytes():
                        downloaded += len(block)
                        if downloaded > record["size_bytes"]:
                            raise ValueError("Downloaded database exceeds the declared size")
                        stream.write(block)
        (stage / MANIFEST_FILENAME).write_bytes(manifest_bytes)
        result = validate_dataset(stage)
        if output_dir.exists():
            # Recheck after network IO; do not overwrite files created during the download.
            if any(output_dir.iterdir()):
                raise ValueError("Dataset destination changed during download")
        stage.replace(output_dir)
        return result


def download_main() -> None:
    parser = argparse.ArgumentParser(description="Download an external XRB dataset index")
    parser.add_argument("manifest_url", help="HTTP(S) link to dataset.json")
    parser.add_argument("--output-dir", type=Path, default=Path("data/dataset"))
    arguments = parser.parse_args()
    print(json.dumps(download_dataset(arguments.manifest_url, arguments.output_dir), indent=2))


def validate_main() -> None:
    parser = argparse.ArgumentParser(description="Verify a portable XRB dataset")
    parser.add_argument("directory", nargs="?", type=Path, default=Path("data/dataset"))
    parser.add_argument(
        "--verify-assets", action="store_true", help="Also verify bundled originals"
    )
    arguments = parser.parse_args()
    print(json.dumps(validate_dataset(arguments.directory, arguments.verify_assets), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("download", "validate"))
    arguments, remaining = parser.parse_known_args()
    import sys

    sys.argv = [sys.argv[0], *remaining]
    if arguments.action == "download":
        download_main()
    else:
        validate_main()
