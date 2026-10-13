"""Read the BlackCAT listing without interpreting measurements or BH confirmation."""

import hashlib
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

BLACKCAT_URL = "https://www.astro.puc.cl/BlackCAT/transients.php"
_FIELDS = (
    "blackcat_id",
    "name_counterpart",
    "ra",
    "dec",
    "galactic_longitude_text",
    "galactic_latitude_text",
    "outburst_magnitude_text",
    "quiescent_magnitude_text",
    "distance_kpc_text",
    "peak_flux_text",
    "orbital_period_hours_text",
)


def _text(value: str) -> str:
    return " ".join(value.split())


class _ListingParser(HTMLParser):
    """Collect table rows, preserving line breaks used to separate counterparts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[dict[str, Any]]] = []
        self.table: list[dict[str, Any]] | None = None
        self.row: dict[str, Any] | None = None
        self.cell: dict[str, Any] | None = None
        self.depth = 0
        self.document_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
                self.tables.append(self.table)
        elif self.depth == 1 and tag == "tr":
            self.row = {"cells": [], "style": attributes.get("style", "")}
            assert self.table is not None
            self.table.append(self.row)
        elif self.row is not None and self.depth == 1 and tag in {"td", "th"}:
            self.cell = {"text": [], "links": [], "header": tag == "th"}
            self.row["cells"].append(self.cell)
        elif self.cell is not None:
            if tag == "br":
                self.cell["text"].append("\n")
            elif tag == "a" and attributes.get("href"):
                self.cell["links"].append(attributes["href"])
            elif tag in {"sup", "sub"}:
                # Retain the mathematical role, rather than concatenate asymmetric errors.
                self.cell["text"].append("^{" if tag == "sup" else "_{")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self.table = self.row = self.cell = None
        elif tag == "tr" and self.depth == 1:
            self.row = self.cell = None
        elif tag in {"td", "th"} and self.depth == 1:
            self.cell = None
        elif tag in {"sup", "sub"} and self.cell is not None:
            self.cell["text"].append("}")

    def handle_data(self, data: str) -> None:
        self.document_text.append(data)
        if self.cell is not None:
            self.cell["text"].append(data)


def parse_blackcat_html(html: str, base_url: str = BLACKCAT_URL) -> list[dict[str, Any]]:
    """Return listing rows with names, explicit aliases and unconverted table values.

    ``ra`` and ``dec`` are sexagesimal strings, not degrees. ``raw_fields`` preserves
    every table field using its displayed header. Bounds, units, alternatives and
    errors stay as text. The listing includes candidates and confirmed systems;
    inclusion alone never establishes a dynamically confirmed black hole.
    """
    parser = _ListingParser()
    parser.feed(html)
    parser.close()
    candidates = []
    for table in parser.tables:
        if not table:
            continue
        headers = [_text("".join(cell["text"])) for cell in table[0]["cells"]]
        if len(headers) >= 4 and headers[0] == "ID" and headers[1].startswith("Name"):
            candidates.append((headers, table[1:]))
    if len(candidates) != 1:
        raise ValueError("Expected exactly one BlackCAT source table with ID and Name headers")
    headers, table_rows = candidates[0]
    if (
        len(headers) != len(_FIELDS)
        or not headers[2].startswith("RA")
        or not headers[3].startswith("DEC")
    ):
        raise ValueError(f"Unexpected BlackCAT table schema: {len(headers)} columns")
    rows = []
    ids: set[str] = set()
    for table_row in table_rows:
        cells = table_row["cells"]
        if not cells or all(cell["header"] for cell in cells):
            continue
        if len(cells) != len(headers):
            raise ValueError("BlackCAT source row has an unexpected number of columns")
        values = [_text("".join(cell["text"])) for cell in cells]
        identifier = values[0]
        if not identifier.isdigit() or identifier in ids:
            raise ValueError(f"Invalid or repeated BlackCAT ID: {identifier!r}")
        ids.add(identifier)
        name_lines = [_text(line) for line in "".join(cells[1]["text"]).splitlines() if _text(line)]
        if not name_lines:
            raise ValueError(f"Missing name for BlackCAT ID {identifier}")
        aliases = []
        for line in name_lines[1:]:
            for alias in re.split(r"\s*=\s*", line):
                alias = alias.strip().strip("()").strip()
                if alias and alias != name_lines[0] and alias not in aliases:
                    aliases.append(alias)
        links = cells[1]["links"] or cells[0]["links"]
        row = dict(zip(_FIELDS, values, strict=True))
        row.update(
            name=name_lines[0],
            aliases=aliases,
            source_url=urljoin(base_url, links[0]) if links else base_url,
            catalogue_url=base_url,
            raw_fields=dict(zip(headers, values, strict=True)),
            row_style=table_row["style"],
            compact_object_type="BH candidate",
            bh_status="candidate_or_confirmed_unspecified",
        )
        rows.append(row)
    if not rows:
        raise ValueError("BlackCAT source table is empty")
    return rows


def fetch_blackcat(output_path: Path, url: str = BLACKCAT_URL) -> dict[str, Any]:
    """Save a verified HTML snapshot and return retrieval/checksum provenance."""
    response = httpx.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    html = response.text
    rows = parse_blackcat_html(html, base_url=str(response.url))
    # Store decoded HTML as UTF-8 so a later offline read is unambiguous.
    content = html.encode("utf-8")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    parser = _ListingParser()
    parser.feed(html)
    last_modified = re.search(
        r"Last modified:\s*(\d{1,2}\s+\w+\s+\d{4})",
        _text(" ".join(parser.document_text)),
        flags=re.IGNORECASE,
    )
    return {
        "url": url,
        "resolved_url": str(response.url),
        "path": str(output_path.resolve()),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "row_count": len(rows),
        "page_last_modified": last_modified.group(1) if last_modified else None,
        "http_last_modified": response.headers.get("last-modified"),
        "etag": response.headers.get("etag"),
        "snapshot_encoding": "utf-8",
    }
