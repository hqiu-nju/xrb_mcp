import hashlib
from pathlib import Path


def content_hash(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()
