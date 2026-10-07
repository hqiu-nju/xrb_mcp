import argparse
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from xrb_mcp.ingestion.catalogues import is_catalogue_file, iter_catalogue_rows
from xrb_mcp.ingestion.incremental import content_hash
from xrb_mcp.server.config import get_settings


def build_catalogue_database(
    catalogues_dir: Path,
    output_path: Path,
    max_rows_per_catalogue: int | None = None,
) -> dict:
    if not catalogues_dir.is_dir():
        raise FileNotFoundError(f"Catalogue directory not found: {catalogues_dir}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files = [p for p in sorted(catalogues_dir.iterdir()) if p.is_file() and is_catalogue_file(p)]
    summary = {
        "database": str(output_path),
        "catalogues_dir": str(catalogues_dir),
        "catalogues_processed": 0,
        "rows_loaded": 0,
        "files": [],
        "failures": [],
    }
    with sqlite3.connect(output_path) as conn:
        _create_schema(conn)
        # Rebuild the basic snapshot each run to keep results deterministic.
        conn.execute("DELETE FROM catalogue_rows")
        conn.execute("DELETE FROM catalogues")
        for path in files:
            try:
                row_count = _insert_catalogue(conn, path, max_rows_per_catalogue)
                summary["catalogues_processed"] += 1
                summary["rows_loaded"] += row_count
                summary["files"].append({"file": path.name, "status": "loaded", "rows": row_count})
            except Exception as exc:
                summary["failures"].append(
                    {"file": path.name, "error_type": type(exc).__name__, "error": str(exc)}
                )
                summary["files"].append(
                    {"file": path.name, "status": "failed", "error_type": type(exc).__name__}
                )
                logging.exception("catalogue_load_failed file=%s", path.name)
        conn.commit()
    return summary


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalogues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL UNIQUE,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            format TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            column_count INTEGER NOT NULL,
            columns_json TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalogue_rows (
            catalogue_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            row_json TEXT NOT NULL,
            PRIMARY KEY (catalogue_id, row_index),
            FOREIGN KEY (catalogue_id) REFERENCES catalogues (id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalogue_rows_catalogue_id ON catalogue_rows (catalogue_id)"
    )


def _insert_catalogue(
    conn: sqlite3.Connection,
    path: Path,
    max_rows_per_catalogue: int | None,
) -> int:
    file_format, columns, rows = iter_catalogue_rows(path)
    processed_at = datetime.now(UTC).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO catalogues (
            file_name, file_path, file_hash, format, row_count, column_count, columns_json, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            path.name,
            str(path.resolve()),
            content_hash(path),
            file_format,
            0,
            len(columns),
            json.dumps(columns, ensure_ascii=True),
            processed_at,
        ),
    )
    catalogue_id = int(cursor.lastrowid)
    batch: list[tuple[int, int, str]] = []
    row_count = 0
    for row in rows:
        if max_rows_per_catalogue is not None and row_count >= max_rows_per_catalogue:
            break
        row_count += 1
        batch.append(
            (
                catalogue_id,
                row_count,
                json.dumps(row, ensure_ascii=True, sort_keys=True, default=str),
            )
        )
        if len(batch) >= 1000:
            conn.executemany(
                "INSERT INTO catalogue_rows (catalogue_id, row_index, row_json) VALUES (?, ?, ?)",
                batch,
            )
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT INTO catalogue_rows (catalogue_id, row_index, row_json) VALUES (?, ?, ?)",
            batch,
        )
    conn.execute("UPDATE catalogues SET row_count = ? WHERE id = ?", (row_count, catalogue_id))
    return row_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a basic SQLite catalogue database from FITS/ASCII/CSV files"
    )
    parser.add_argument("catalogues_dir", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-rows-per-catalogue", type=int)
    args = parser.parse_args()

    settings = get_settings()
    catalogues_dir = args.catalogues_dir or settings.data_dir / "catalogues"
    output = args.output or settings.data_dir / "processed" / "catalogues_basic.db"

    if args.max_rows_per_catalogue is not None and args.max_rows_per_catalogue < 1:
        parser.error("--max-rows-per-catalogue must be >= 1")

    logging.basicConfig(level=logging.INFO)
    summary = build_catalogue_database(
        catalogues_dir,
        output,
        max_rows_per_catalogue=args.max_rows_per_catalogue,
    )
    print(json.dumps(summary, indent=2))
    raise SystemExit(1 if summary["failures"] else 0)


if __name__ == "__main__":
    main()