import csv
from pathlib import Path
from typing import Any, Iterator


CATALOGUE_SUFFIXES: dict[str, str] = {
    ".ascii": "ascii",
    ".csv": "csv",
    ".dat": "ascii",
    ".ecsv": "ascii",
    ".fit": "fits",
    ".fits": "fits",
    ".fts": "fits",
    ".tab": "ascii",
    ".tsv": "csv",
    ".txt": "ascii",
}


def detect_catalogue_format(path: Path) -> str:
    file_format = CATALOGUE_SUFFIXES.get(path.suffix.lower())
    if not file_format:
        raise ValueError(f"Unsupported catalogue format for {path.name}")
    return file_format


def is_catalogue_file(path: Path) -> bool:
    return path.suffix.lower() in CATALOGUE_SUFFIXES


def read_catalogue(path: Path, preview_rows: int = 5) -> dict[str, Any]:
    if preview_rows < 0:
        raise ValueError("preview_rows must be >= 0")
    if not path.is_file():
        raise FileNotFoundError(path)
    file_format, columns, rows = iter_catalogue_rows(path)
    preview: list[dict[str, Any]] = []
    row_count = 0
    for row in rows:
        row_count += 1
        if len(preview) < preview_rows:
            preview.append(row)
    return {
        "path": str(path),
        "format": file_format,
        "columns": columns,
        "row_count": row_count,
        "preview": preview,
    }


def iter_catalogue_rows(path: Path) -> tuple[str, list[str], Iterator[dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    file_format = detect_catalogue_format(path)
    if file_format == "csv":
        return _iter_csv_rows(path)
    return _iter_astropy_rows(path, file_format)


def _iter_csv_rows(path: Path) -> tuple[str, list[str], Iterator[dict[str, Any]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = _detect_csv_dialect(sample)
        reader = csv.DictReader(handle, dialect=dialect)
        columns = [name for name in (reader.fieldnames or []) if name]

    def rows() -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            dialect = _detect_csv_dialect(handle.read(4096))
            handle.seek(0)
            reader = csv.DictReader(handle, dialect=dialect)
            for row in reader:
                yield {column: row.get(column) for column in columns}

    return "csv", columns, rows()


def _iter_astropy_rows(path: Path, file_format: str) -> tuple[str, list[str], Iterator[dict[str, Any]]]:
    try:
        from astropy.table import Table
    except ImportError as exc:
        raise RuntimeError("Install xrb-mcp[astronomy] to read FITS/ASCII catalogues") from exc
    table = Table.read(path, format="fits" if file_format == "fits" else "ascii")
    columns = [str(name) for name in table.colnames]

    def rows() -> Iterator[dict[str, Any]]:
        for row in table:
            yield {column: _to_python_value(row[column]) for column in columns}

    return file_format, columns, rows()


def _detect_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _to_python_value(value: Any) -> Any:
    masked = getattr(value, "mask", None)
    if masked is True:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    to_python = getattr(value, "item", None)
    if callable(to_python):
        try:
            return to_python()
        except ValueError:
            pass
    return value