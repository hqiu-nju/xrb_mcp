"""Build a provenance-preserving source catalogue without altering literature records."""

import argparse
import csv
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.astronomy.catalogue_merge import deduplicate_sources, extract_source_row
from xrb_mcp.ingestion.blackcat import BLACKCAT_URL, fetch_blackcat, parse_blackcat_html
from xrb_mcp.ingestion.catalogues import _to_python_value
from xrb_mcp.ingestion.incremental import content_hash
from xrb_mcp.server.config import get_settings

DEFAULT_FITS_FILES = (
    "HMXB_cat.fits",
    "LMXB_cat.fits",
    "liu2000_lmxb.fit",
    "liu2005_lmc.fit",
    "liu2006.fit",
    "watchdog.fit",
)
CATALOGUE_REFERENCES = {
    "HMXB_cat.fits": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/J/A+A/677/A134",
    "LMXB_cat.fits": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/J/A+A/675/A199",
    "liu2000_lmxb.fit": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/V/106",
    "liu2005_lmc.fit": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/J/A+A/442/1135",
    "liu2006.fit": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/J/A+A/455/1165",
    "watchdog.fit": "https://cdsarc.cds.unistra.fr/viz-bin/ReadMe/J/ApJS/222/15",
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)


def _read_fits(path: Path) -> tuple[dict, list[dict], list[dict]]:
    try:
        from astropy.io import fits
        from astropy.table import Table
    except ImportError as exc:
        raise RuntimeError("Install xrb-mcp[astronomy] to build FITS source catalogues") from exc

    records, supplementary, tables = [], [], []
    with fits.open(path) as hdus, path.open("rb") as original:
        source_hdu = None
        for hdu_index, hdu in enumerate(hdus):
            if not isinstance(hdu, (fits.TableHDU, fits.BinTableHDU)):
                continue
            if source_hdu is None and "Name" in hdu.columns.names:
                source_hdu = hdu_index
            table = Table.read(path, format="fits", hdu=hdu_index)
            tables.append(
                {
                    "hdu": hdu_index,
                    "rows": len(table),
                    "columns": [
                        {"name": c.name, "format": str(c.format), "unit": c.unit}
                        for c in hdu.columns
                    ],
                    "header_cards": [
                        [c.keyword, _to_python_value(c.value), c.comment] for c in hdu.header.cards
                    ],
                }
            )
            for row_index, row in enumerate(table, 1):
                raw = {name: _to_python_value(row[name]) for name in table.colnames}
                # Astropy can interpret a blank ASCII FITS numeric cell as zero.
                # Check the original cells so absent measurements remain absent.
                if isinstance(hdu, fits.TableHDU):
                    offset = hdu.fileinfo()["datLoc"] + (row_index - 1) * hdu.header["NAXIS1"]
                    original.seek(offset)
                    line = original.read(hdu.header["NAXIS1"])
                    cells = {}
                    for column in hdu.columns:
                        width = int(re.match(r"[A-Z](\d+)", str(column.format))[1])
                        start = column.start - 1
                        cell = line[start : start + width].decode("ascii", errors="replace").strip()
                        cells[column.name] = cell
                        if not cell or (
                            column.null is not None and cell == str(column.null).strip()
                        ):
                            raw[column.name] = None
                    raw["_fits_ascii_cells"] = cells
                if hdu_index == source_hdu:
                    records.append(extract_source_row(path.name, row_index, raw))
                else:
                    supplementary.append({"hdu": hdu_index, "row_index": row_index, "raw": raw})
        if source_hdu is None or not records:
            raise ValueError(f"No populated source table with a Name column in {path}")
        metadata = {
            "catalogue": path.name,
            "origin": str(path.resolve()),
            "format": "fits",
            "sha256": content_hash(path),
            "source_hdu": source_hdu,
            "source_rows": len(records),
            "supplementary_rows": len(supplementary),
            "tables": tables,
            "primary_header_cards": [
                [c.keyword, _to_python_value(c.value), c.comment] for c in hdus[0].header.cards
            ],
            "reference_url": CATALOGUE_REFERENCES.get(path.name),
        }
    return metadata, records, supplementary


def build_source_catalogue(
    paths: list[Path],
    output_dir: Path,
    *,
    blackcat_html: Path | None = None,
    include_blackcat: bool = True,
    match_radius_arcsec: float = 5.0,
) -> dict:
    if not paths:
        raise ValueError("At least one FITS catalogue is required")
    if len({p.name for p in paths}) != len(paths):
        raise ValueError("Input catalogue file names must be unique")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, catalogues, supplementary = [], [], {}
    # Read every input before publishing any database or source export.
    for path in paths:
        metadata, records, extra = _read_fits(path)
        catalogues.append(metadata)
        rows.extend(records)
        supplementary[path.name] = extra
    if include_blackcat:
        snapshot = blackcat_html or output_dir / "blackcat_transients.html"
        if blackcat_html is None:
            blackcat_metadata = fetch_blackcat(snapshot)
        else:
            blackcat_metadata = {"url": BLACKCAT_URL, "snapshot": str(snapshot.resolve())}
            metadata_path = snapshot.with_suffix(".metadata.json")
            if metadata_path.is_file():
                saved_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if saved_metadata.get("sha256") == content_hash(snapshot):
                    blackcat_metadata.update(saved_metadata)
        blackcat_rows = parse_blackcat_html(snapshot.read_text(encoding="utf-8"))
        catalogues.append(
            {
                "catalogue": "blackcat",
                "origin": BLACKCAT_URL,
                "format": "html",
                "sha256": content_hash(snapshot),
                "source_rows": len(blackcat_rows),
                "supplementary_rows": 0,
                "metadata": blackcat_metadata,
                "citation": "Corral-Santana et al. (2016), A&A 587, A61",
                "citation_url": "https://www.astro.puc.cl/BlackCAT/citation.php",
                "classification_note": "Catalogue membership includes black-hole candidates.",
            }
        )
        rows.extend(
            extract_source_row("blackcat", i, raw) for i, raw in enumerate(blackcat_rows, 1)
        )

    merged = deduplicate_sources(rows, match_radius_arcsec=match_radius_arcsec)
    sources, matches, review = merged["sources"], merged["matches"], merged["review"]
    for source in sources:
        if {"HMXB", "LMXB"}.issubset(source["source_classes"]):
            review.append(
                {
                    "reason": "source_class_conflict",
                    "source_id": source["source_id"],
                    "canonical_name": source["canonical_name"],
                    "source_classes": source["source_classes"],
                    "catalogue_rows": source["member_keys"],
                }
            )
        compact_types = source.get("compact_object_types", [])
        if any(label.startswith("BH") for label in compact_types) and any(
            label.startswith("NS") for label in compact_types
        ):
            review.append(
                {
                    "reason": "compact_object_class_conflict",
                    "source_id": source["source_id"],
                    "canonical_name": source["canonical_name"],
                    "compact_object_types": compact_types,
                    "catalogue_rows": source["member_keys"],
                }
            )
    member_map = {
        tuple(key): source["source_id"] for source in sources for key in source["member_keys"]
    }
    if len(member_map) != len(rows):
        raise RuntimeError("Source merge did not preserve every input row exactly once")
    export_rows = _export_rows(sources, rows)
    report = {
        "built_at": datetime.now(UTC).isoformat(),
        "input_rows": len(rows),
        "unique_sources": len(sources),
        "duplicate_rows_consolidated": len(rows) - len(sources),
        "catalogues_processed": len(catalogues),
        "catalogues": catalogues,
        "accepted_match_counts": dict(Counter(match["method"] for match in matches)),
        "review_items": len(review),
        "review_reason_counts": dict(Counter(item["reason"] for item in review)),
        "match_radius_arcsec": match_radius_arcsec,
        "sources_without_coordinates": sum(source["ra_deg"] is None for source in sources),
        "classification_note": (
            "Classes are catalogue labels; raw types, limits and conflicts are retained."
        ),
        "coordinate_note": (
            "Modern ICRS and legacy J2000 positions used for identity matching; "
            "each selected position retains its origin."
        ),
        "outputs": {
            key: str((output_dir / name).resolve())
            for key, name in {
                "database": "sources.db",
                "fits": "sources.fits",
                "csv": "sources.csv",
                "review": "source_review.json",
                "matches": "source_matches.json",
                "report": "source_catalogue_report.json",
            }.items()
        },
    }
    # Stage the build. A parse/merge/export failure cannot erase a working snapshot.
    with tempfile.TemporaryDirectory(prefix=".source-build-", dir=output_dir) as staging:
        stage = Path(staging)
        _write_database(stage / "sources.db", catalogues, rows, supplementary, merged, report)
        _write_csv(stage / "sources.csv", export_rows)
        _write_fits(stage / "sources.fits", export_rows, report)
        for name, value in (
            ("source_review.json", review),
            ("source_matches.json", matches),
            ("source_catalogue_report.json", report),
        ):
            (stage / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
        for path in sorted(stage.iterdir()):
            os.replace(path, output_dir / path.name)
    return report


def _export_rows(sources: list[dict], rows: list[dict]) -> list[dict]:
    originals = {(row["catalogue"], row["row_index"]): row for row in rows}
    result = []
    for source in sources:
        members = [originals[tuple(key)] for key in source["member_keys"]]
        result.append(
            {
                "source_id": source["source_id"],
                "canonical_name": source["canonical_name"],
                "ra_deg": source["ra_deg"],
                "dec_deg": source["dec_deg"],
                "pos_err_arcsec": source.get("pos_err_arcsec"),
                "source_classes": _json(source["source_classes"]),
                "compact_object_types": _json(source.get("compact_object_types", [])),
                "bh_status": source.get("bh_status") or "",
                "aliases": _json(source["aliases"]),
                "catalogues": _json(sorted({row["catalogue"] for row in members})),
                "catalogue_rows": _json(source["member_keys"]),
                "coordinate_origin": _json(source["coordinate_origin"]),
                "coordinate_catalogue_row": _json(source.get("coordinate_member_key")),
                "match_methods": _json(source["match_methods"]),
                "entry_count": len(members),
            }
        )
    return result


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_fits(path: Path, rows: list[dict], report: dict) -> None:
    from astropy.table import MaskedColumn, Table

    table = Table()
    for key in rows[0]:
        if key in {"ra_deg", "dec_deg", "pos_err_arcsec"}:
            table[key] = MaskedColumn(
                [row[key] if row[key] is not None else float("nan") for row in rows],
                mask=[row[key] is None for row in rows],
                unit="arcsec" if key == "pos_err_arcsec" else "deg",
            )
        else:
            table[key] = [row[key] for row in rows]
    table.meta.update(
        ORIGIN="XRB MCP source catalogue",
        DATE=report["built_at"].replace("+00:00", ""),
        NINPUT=report["input_rows"],
        NMERGED=report["duplicate_rows_consolidated"],
        RADIUS=report["match_radius_arcsec"],
    )
    table.write(path, format="fits")


def _write_database(path, catalogues, rows, supplementary, merged, report) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE catalogues (
                catalogue TEXT PRIMARY KEY, origin TEXT NOT NULL, format TEXT NOT NULL,
                sha256 TEXT NOT NULL, source_rows INTEGER NOT NULL, metadata_json TEXT NOT NULL
            );
            CREATE TABLE sources (
                source_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL,
                ra_deg REAL, dec_deg REAL, source_classes_json TEXT NOT NULL,
                coordinate_origin_json TEXT NOT NULL, aliases_json TEXT NOT NULL,
                match_methods_json TEXT NOT NULL, compact_object_types_json TEXT NOT NULL,
                bh_status TEXT,
                CHECK ((ra_deg IS NULL) = (dec_deg IS NULL)),
                CHECK (ra_deg >= 0 AND ra_deg < 360), CHECK (dec_deg >= -90 AND dec_deg <= 90)
            );
            CREATE TABLE source_aliases (
                source_id TEXT REFERENCES sources(source_id), alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL, PRIMARY KEY(source_id, normalized_alias)
            );
            CREATE INDEX ix_source_alias_lookup ON source_aliases(normalized_alias);
            CREATE TABLE catalogue_rows (
                catalogue TEXT REFERENCES catalogues(catalogue), row_index INTEGER,
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                row_json TEXT NOT NULL, normalized_json TEXT NOT NULL,
                PRIMARY KEY(catalogue, row_index)
            );
            CREATE INDEX ix_catalogue_source ON catalogue_rows(source_id);
            CREATE TABLE supplementary_rows (
                catalogue TEXT REFERENCES catalogues(catalogue), hdu INTEGER,
                row_index INTEGER, row_json TEXT NOT NULL, PRIMARY KEY(catalogue,hdu,row_index)
            );
            CREATE TABLE source_matches (id INTEGER PRIMARY KEY, method TEXT, match_json TEXT);
            CREATE TABLE review_queue (id INTEGER PRIMARY KEY, reason TEXT, review_json TEXT);
            CREATE TABLE build_metadata (report_json TEXT NOT NULL);
            """
        )
        for item in catalogues:
            conn.execute(
                "INSERT INTO catalogues VALUES (?,?,?,?,?,?)",
                (
                    item["catalogue"],
                    item["origin"],
                    item["format"],
                    item["sha256"],
                    item["source_rows"],
                    _json(item),
                ),
            )
        member_map = {}
        for source in merged["sources"]:
            conn.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    source["source_id"],
                    source["canonical_name"],
                    source["ra_deg"],
                    source["dec_deg"],
                    _json(source["source_classes"]),
                    _json(
                        {
                            "frame": source["coordinate_origin"],
                            "catalogue_row": source.get("coordinate_member_key"),
                            "pos_err_arcsec": source.get("pos_err_arcsec"),
                        }
                    ),
                    _json(source["aliases"]),
                    _json(source["match_methods"]),
                    _json(source.get("compact_object_types", [])),
                    source.get("bh_status"),
                ),
            )
            aliases = {normalize_alias(alias): alias for alias in source["aliases"]}
            conn.executemany(
                "INSERT INTO source_aliases VALUES (?,?,?)",
                [(source["source_id"], alias, normalized) for normalized, alias in aliases.items()],
            )
            member_map.update({tuple(key): source["source_id"] for key in source["member_keys"]})
        for row in rows:
            conn.execute(
                "INSERT INTO catalogue_rows VALUES (?,?,?,?,?)",
                (
                    row["catalogue"],
                    row["row_index"],
                    member_map[(row["catalogue"], row["row_index"])],
                    _json(row["raw"]),
                    _json({key: value for key, value in row.items() if key != "raw"}),
                ),
            )
        for catalogue, extras in supplementary.items():
            conn.executemany(
                "INSERT INTO supplementary_rows VALUES (?,?,?,?)",
                [(catalogue, row["hdu"], row["row_index"], _json(row["raw"])) for row in extras],
            )
        conn.executemany(
            "INSERT INTO source_matches(method,match_json) VALUES (?,?)",
            [(match["method"], _json(match)) for match in merged["matches"]],
        )
        conn.executemany(
            "INSERT INTO review_queue(reason,review_json) VALUES (?,?)",
            [(item["reason"], _json(item)) for item in merged["review"]],
        )
        conn.execute("INSERT INTO build_metadata VALUES (?)", (_json(report),))
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Catalogue database has broken source provenance")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge FITS source catalogues and BlackCAT with provenance"
    )
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--blackcat-html", type=Path, help="Reuse a downloaded BlackCAT HTML snapshot"
    )
    parser.add_argument("--no-blackcat", action="store_true")
    parser.add_argument("--match-radius-arcsec", type=float, default=5.0)
    args = parser.parse_args()
    settings = get_settings()
    paths = args.files or [settings.data_dir / "catalogues" / name for name in DEFAULT_FITS_FILES]
    output = args.output_dir or settings.data_dir / "processed" / "source_catalogue"
    report = build_source_catalogue(
        paths,
        output,
        blackcat_html=args.blackcat_html,
        include_blackcat=not args.no_blackcat,
        match_radius_arcsec=args.match_radius_arcsec,
    )
    print(
        json.dumps({key: value for key, value in report.items() if key != "catalogues"}, indent=2)
    )


if __name__ == "__main__":
    main()
