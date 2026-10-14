"""Build a compact, relocatable research dataset outside the code repository history.

PostgreSQL remains the ingestion database. This export contains extracted literature
passages and catalogue measurements; optional originals live beside the SQLite file.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session, defer

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.database.connection import session_scope
from xrb_mcp.database.models import (
    Collection,
    CollectionPaper,
    Paper,
    PaperChunk,
    PaperSource,
    Provenance,
    Source,
)
from xrb_mcp.database.portable_schema import (
    DATABASE_FILENAME,
    MANIFEST_FILENAME,
    SCHEMA,
    SNAPSHOT_VERSION,
)
from xrb_mcp.provenance.citations import evidence_bundle, paper_metadata
from xrb_mcp.retrieval.objects import source_object
from xrb_mcp.server.config import get_settings

_RAW_EXTENSIONS = {
    ".csv",
    ".dat",
    ".ecsv",
    ".fit",
    ".fits",
    ".fts",
    ".htm",
    ".html",
    ".json",
    ".tsv",
    ".txt",
    ".vot",
    ".votable",
    ".xls",
    ".xlsx",
    ".xml",
}
_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "database_url",
    "read_database_url",
    "connection_string",
}
_PATH_KEYS = {
    "path",
    "pdf_path",
    "file_path",
    "local_path",
    "source_path",
    "input_path",
    "output_path",
    "origin",
    "snapshot",
    "filename",
    "source_file",
    "input_file",
}
_MACHINE_PATH = re.compile(
    r"^(?:/(?:Users|home|private|tmp|var|opt|mnt|Volumes|data)(?:/|$)|[A-Za-z]:[\\/]|\\\\)"
)
_EMBEDDED_MACHINE_FILE = re.compile(
    r"(?<![\w:/\\])(?:file://)?"
    r"(?:/(?:Users|home|private|tmp|var|opt|mnt|Volumes|data)/|[A-Za-z]:[\\/]|\\\\)"
    r"[^\r\n;\"<>]*?"
    r"\.(?:pdf|fits?|fts|csv|tsv|ecsv|json|html?|txt|dat|xml|vot(?:able)?|xlsx?|"
    r"sqlite3?|db|sql|png|jpe?g|tex|bib|py|ya?ml)(?![\w/\\]|\.\w)",
    re.IGNORECASE,
)


def _embedded_path_basename(match: re.Match) -> str:
    original = match.group(0).removeprefix("file://")
    return PureWindowsPath(original).name if "\\" in original else Path(original).name


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Archive links must be HTTP or HTTPS URLs")
    if parts.username or parts.password:
        raise ValueError("Archive links cannot contain credentials")
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _SECRET_KEYS and not key.casefold().startswith("x-amz-")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _scrub(value, key: str = ""):
    """Remove internal paths/secrets, leaving scientific strings and URLs intact."""
    if isinstance(value, dict):
        return {
            str(name): _scrub(item, str(name).casefold())
            for name, item in value.items()
            if str(name).casefold() not in _SECRET_KEYS and str(name).casefold() != "pdf_path"
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item, key) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return _safe_url(value)
        absolute = Path(value).is_absolute() or PureWindowsPath(value).is_absolute()
        if _MACHINE_PATH.match(value) or (absolute and key in _PATH_KEYS):
            # A basename retains which original file supported the measurement.
            return PureWindowsPath(value).name if "\\" in value else Path(value).name
        if value.startswith("file://"):
            return Path(urlsplit(value).path).name
        return _EMBEDDED_MACHINE_FILE.sub(_embedded_path_basename, value)
    return value


def _archive_url(base: str | None, name: str) -> str | None:
    if not base:
        return None
    parts = urlsplit(base)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path.rstrip("/") + "/" + quote(name, safe=""),
            parts.query,
            parts.fragment,
        )
    )


def _asset(
    stage: Path,
    assets: dict[str, dict],
    relative: str,
    *,
    kind: str,
    original: Path | None = None,
    include_originals: bool = False,
    sha256: str | None = None,
    archive_url: str | None = None,
) -> dict:
    if include_originals and (original is None or not original.is_file()):
        raise ValueError(f"Referenced original is unavailable: {relative}")
    item = assets.setdefault(
        relative,
        {
            "path": relative,
            "kind": kind,
            "available": False,
            "sha256": sha256,
            "size_bytes": None,
        },
    )
    if archive_url:
        item["archive_url"] = archive_url
    if original is not None and original.is_file():
        actual = _checksum(original)
        if sha256 and actual != sha256:
            raise ValueError(f"Original file checksum differs from its provenance: {relative}")
        if item["sha256"] and actual != item["sha256"]:
            raise ValueError(f"Distinct original files have the same archive name: {relative}")
        item.update(sha256=actual, size_bytes=original.stat().st_size)
        if include_originals:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
            if _checksum(destination) != actual:
                raise RuntimeError(f"Original changed while being copied: {relative}")
            item["available"] = True
    return item


def _original_path(value: str | None, data_dir: Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_file():
        return path
    if data_dir is not None:
        # Stored paths may begin with the former data-directory basename.
        candidates = [data_dir / path, data_dir / "papers" / path.name]
        if path.parts and path.parts[0] == data_dir.name:
            candidates.insert(0, data_dir.parent / path)
        return next((candidate for candidate in candidates if candidate.is_file()), path)
    return path


def _read_catalogue(
    conn: sqlite3.Connection,
    path: Path,
    registry_aliases: dict[str, set[str]],
    stage: Path,
    assets: dict[str, dict],
    *,
    data_dir: Path | None,
    include_originals: bool,
    catalogues_url: str | None,
) -> dict:
    metadata, members = {}, defaultdict(list)
    catalogue_names: dict[str, set[str]] = defaultdict(set)
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Input catalogue database failed its integrity check")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Input catalogue database contains broken provenance links")
        for row in source.execute("SELECT * FROM catalogues ORDER BY catalogue"):
            original_metadata = json.loads(row["metadata_json"])
            name = row["catalogue"]
            origin = original_metadata.get("origin", row["origin"])
            snapshot = original_metadata.get("metadata", {}).get("snapshot")
            original = None
            if snapshot:
                original = Path(snapshot)
            elif isinstance(origin, str) and not origin.startswith(("http://", "https://")):
                original = Path(origin)
            filename = (
                original.name
                if original is not None
                else name
                if Path(name).suffix
                else f"{name}.html"
            )
            if not filename or filename in {".", ".."} or Path(filename).name != filename:
                raise ValueError("Catalogue archive name is invalid")
            if data_dir is not None and (original is None or not original.is_file()):
                candidates = [
                    data_dir / "catalogues" / filename,
                    data_dir / "processed" / "source_catalogue" / filename,
                ]
                original = next(
                    (candidate for candidate in candidates if candidate.is_file()),
                    original,
                )
            relative = "catalogues/" + filename
            asset = _asset(
                stage,
                assets,
                relative,
                kind="catalogue",
                original=original,
                include_originals=include_originals,
                sha256=row["sha256"],
                archive_url=_archive_url(catalogues_url, filename),
            )
            item = _scrub(original_metadata)
            item.update(archive_path=relative, archive_url=asset.get("archive_url"))
            metadata[name] = item
        for row in source.execute("SELECT * FROM catalogue_rows ORDER BY catalogue, row_index"):
            input_metadata = metadata[row["catalogue"]]
            input_reference = {
                key: input_metadata[key]
                for key in (
                    "catalogue",
                    "origin",
                    "format",
                    "sha256",
                    "archive_path",
                    "archive_url",
                    "reference_url",
                    "citation",
                    "citation_url",
                    "classification_note",
                )
                if key in input_metadata
            }
            members[row["source_id"]].append(
                {
                    "catalogue": row["catalogue"],
                    "row_index": row["row_index"],
                    "raw": _scrub(json.loads(row["row_json"])),
                    "normalized": _scrub(json.loads(row["normalized_json"])),
                    "catalogue_input": input_reference,
                }
            )
        for row in source.execute("SELECT * FROM sources ORDER BY source_id"):
            identifier = row["source_id"]
            item = {
                "id": identifier,
                "source_id": identifier,
                "canonical_name": row["canonical_name"],
                "ra_deg": row["ra_deg"],
                "dec_deg": row["dec_deg"],
                "source_classes": json.loads(row["source_classes_json"]),
                "compact_object_types": json.loads(row["compact_object_types_json"]),
                "bh_status": row["bh_status"],
                "aliases": json.loads(row["aliases_json"]),
                "coordinate_origin": json.loads(row["coordinate_origin_json"]),
                "match_methods": json.loads(row["match_methods_json"]),
                "member_rows": members[identifier],
            }
            conn.execute(
                "INSERT INTO catalogue_sources VALUES (?,?)",
                (
                    identifier,
                    _json(_scrub(item)),
                ),
            )
            for name in [item["canonical_name"], *item["aliases"]]:
                catalogue_names[normalize_alias(name)].add(identifier)
        for row in source.execute("SELECT * FROM source_aliases"):
            catalogue_names[normalize_alias(row["alias"])].add(row["source_id"])
        supplementary = [
            {
                "catalogue": row["catalogue"],
                "hdu": row["hdu"],
                "row_index": row["row_index"],
                "raw": _scrub(json.loads(row["row_json"])),
            }
            for row in source.execute("SELECT * FROM supplementary_rows")
        ]
        review = [
            _scrub(json.loads(row[0]))
            for row in source.execute("SELECT review_json FROM review_queue ORDER BY id")
        ]
        matches = [
            _scrub(json.loads(row[0]))
            for row in source.execute("SELECT match_json FROM source_matches ORDER BY id")
        ]
    candidate_links: dict[str, set[str]] = defaultdict(set)
    ambiguous: dict[str, list[dict]] = defaultdict(list)
    for alias, catalogue_ids in sorted(catalogue_names.items()):
        for identifier in sorted(catalogue_ids):
            conn.execute("INSERT INTO catalogue_aliases VALUES (?,?)", (alias, identifier))
        registered = registry_aliases.get(alias, set())
        if not registered:
            continue
        if len(registered) == len(catalogue_ids) == 1:
            candidate_links[next(iter(catalogue_ids))].update(registered)
        else:
            for identifier in catalogue_ids:
                ambiguous[identifier].append(
                    {
                        "normalized_alias": alias,
                        "registered_source_ids": sorted(registered),
                        "catalogue_source_ids": sorted(catalogue_ids),
                    }
                )
    reverse_candidates: dict[str, set[str]] = defaultdict(set)
    for identifier, candidates in candidate_links.items():
        if len(candidates) == 1 and not ambiguous[identifier]:
            reverse_candidates[next(iter(candidates))].add(identifier)
    link_review = []
    for identifier in sorted(candidate_links.keys() | ambiguous.keys()):
        candidates = candidate_links[identifier]
        registered = next(iter(candidates)) if len(candidates) == 1 else None
        reverse = reverse_candidates[registered] if registered is not None else set()
        if len(candidates) == 1 and not ambiguous[identifier] and len(reverse) == 1:
            conn.execute(
                "INSERT INTO catalogue_links VALUES (?,?)",
                (
                    registered,
                    identifier,
                ),
            )
        else:
            link_review.append(
                {
                    "reason": "ambiguous_registered_identity",
                    "catalogue_source_id": identifier,
                    "registered_source_ids": sorted(candidates),
                    "ambiguous_aliases": ambiguous[identifier],
                    "conflicting_catalogue_source_ids": sorted(reverse) if len(reverse) > 1 else [],
                }
            )
    return {
        "catalogues": list(metadata.values()),
        "catalogue_registry_review": link_review,
        "catalogue_review": review,
        "catalogue_matches": matches,
        "catalogue_supplementary_rows": supplementary,
    }


def export_dataset(
    session: Session,
    output_dir: Path,
    catalogue_database: Path | None = None,
    include_embeddings: bool = False,
    include_originals: bool = False,
    data_dir: Path | None = None,
    papers_url: str | None = None,
    catalogues_url: str | None = None,
) -> dict:
    """Publish a validated snapshot; failed staging leaves an existing dataset intact.

    Use a fresh read-only session. PostgreSQL exports use one repeatable-read
    transaction so literature, provenance and source links describe the same state.
    """
    output_dir = Path(output_dir)
    data_dir = Path(data_dir) if data_dir is not None else None
    papers_url, catalogues_url = _safe_url(papers_url), _safe_url(catalogues_url)
    if output_dir.is_symlink():
        raise ValueError("Dataset output directory cannot be a symlink")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("Dataset output must be a directory")
    if (
        output_dir.exists()
        and any(output_dir.iterdir())
        and not (output_dir / MANIFEST_FILENAME).is_file()
    ):
        raise ValueError("Refusing to replace a nonempty directory without a dataset manifest")
    if catalogue_database is not None and not Path(catalogue_database).is_file():
        raise ValueError("Catalogue database does not exist")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    assets: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix=".dataset-export-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "dataset"
        stage.mkdir()
        database = stage / DATABASE_FILENAME
        conn = sqlite3.connect(database)
        try:
            conn.executescript(SCHEMA)
            registry_aliases: dict[str, set[str]] = defaultdict(set)
            for source in session.scalars(select(Source).order_by(Source.normalized_name)):
                item = _scrub(source_object(session, str(source.id)))
                identifier = str(source.id)
                normalized = normalize_alias(source.canonical_name)
                conn.execute(
                    "INSERT INTO sources VALUES (?,?,?)",
                    (
                        identifier,
                        normalized,
                        _json(item),
                    ),
                )
                for alias in [source.canonical_name, *[a["alias"] for a in item["aliases"]]]:
                    registry_aliases[normalize_alias(alias)].add(identifier)
            # Canonical-name/alias collisions are ambiguous even if each source table
            # separately enforces uniqueness. Keep those out of direct lookup links.
            for alias, identifiers in sorted(registry_aliases.items()):
                if len(identifiers) == 1:
                    conn.execute(
                        "INSERT INTO source_aliases VALUES (?,?)",
                        (
                            alias,
                            next(iter(identifiers)),
                        ),
                    )
            papers = {}
            for paper in session.scalars(select(Paper).order_by(Paper.id)):
                identifier = str(paper.id)
                if not re.fullmatch(r"[a-fA-F0-9]{64}", paper.content_hash):
                    raise ValueError("A paper has an invalid content hash")
                filename = paper.content_hash.lower() + ".pdf"
                relative = "papers/" + filename
                asset = _asset(
                    stage,
                    assets,
                    relative,
                    kind="paper",
                    original=_original_path(paper.pdf_path, data_dir),
                    include_originals=include_originals,
                    sha256=paper.content_hash.lower(),
                    archive_url=_archive_url(papers_url, filename),
                )
                item = _scrub(paper_metadata(paper))
                item.update(
                    content_hash=paper.content_hash.lower(),
                    archive_path=relative,
                    archive_url=asset.get("archive_url"),
                )
                conn.execute("INSERT INTO papers VALUES (?,?)", (identifier, _json(item)))
                papers[paper.id] = paper
            for link in session.scalars(select(PaperSource)):
                conn.execute(
                    "INSERT INTO paper_sources VALUES (?,?)",
                    (
                        str(link.paper_id),
                        str(link.source_id),
                    ),
                )
            collections = [
                {"name": item.name, "description": _scrub(item.description)}
                for item in session.scalars(select(Collection).order_by(Collection.name))
            ]
            for link in session.scalars(select(CollectionPaper)):
                conn.execute(
                    "INSERT INTO collection_papers VALUES (?,?)",
                    (
                        link.collection,
                        str(link.paper_id),
                    ),
                )
            chunks_query = (
                select(PaperChunk, Provenance)
                .outerjoin(
                    Provenance,
                    Provenance.chunk_id == PaperChunk.id,
                )
                .order_by(PaperChunk.paper_id, PaperChunk.chunk_index)
            )
            if not include_embeddings:
                chunks_query = chunks_query.options(defer(PaperChunk.embedding))
            for chunk, provenance in session.execute(chunks_query):
                if (
                    provenance is None
                    or provenance.paper_id != chunk.paper_id
                    or provenance.page != chunk.page_start
                    or provenance.section != chunk.section
                ):
                    raise ValueError("Cannot export a chunk without matching paper provenance")
                item = evidence_bundle(papers[chunk.paper_id], chunk, provenance)
                item.pop("paper")
                item.pop("text")
                item.update(subsection=chunk.subsection, token_count=chunk.token_count)
                embedding, model, version, dimension = None, None, None, None
                if include_embeddings and chunk.embedding is not None:
                    vector = np.asarray(chunk.embedding, dtype="<f4")
                    if (
                        vector.ndim != 1
                        or not len(vector)
                        or len(vector) != chunk.embedding_dimension
                        or not np.isfinite(vector).all()
                        or not chunk.embedding_model
                        or not chunk.embedding_version
                        or not np.linalg.norm(vector.astype(np.float64))
                    ):
                        raise ValueError("Cannot export an invalid embedding")
                    embedding = vector.tobytes()
                    model, version, dimension = (
                        chunk.embedding_model,
                        chunk.embedding_version,
                        chunk.embedding_dimension,
                    )
                conn.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        str(chunk.id),
                        str(chunk.paper_id),
                        chunk.chunk_index,
                        chunk.text,
                        _json(_scrub(item)),
                        embedding,
                        model,
                        version,
                        dimension,
                    ),
                )
            catalogue_metadata = {}
            if catalogue_database is not None:
                catalogue_metadata = _read_catalogue(
                    conn,
                    Path(catalogue_database),
                    registry_aliases,
                    stage,
                    assets,
                    data_dir=data_dir,
                    include_originals=include_originals,
                    catalogues_url=catalogues_url,
                )
            if include_originals and data_dir is not None:
                original_catalogues = data_dir / "catalogues"
                if original_catalogues.is_dir():
                    for original in sorted(original_catalogues.iterdir()):
                        if (
                            original.is_file()
                            and not original.name.startswith(".")
                            and original.suffix.casefold() in _RAW_EXTENSIONS
                        ):
                            _asset(
                                stage,
                                assets,
                                "catalogues/" + original.name,
                                kind="catalogue",
                                original=original,
                                include_originals=True,
                                archive_url=_archive_url(catalogues_url, original.name),
                            )
            tables = (
                "sources",
                "source_aliases",
                "papers",
                "paper_sources",
                "collection_papers",
                "chunks",
                "catalogue_sources",
                "catalogue_aliases",
                "catalogue_links",
            )
            counts = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in tables
            }
            counts.update(
                collections=len(collections),
                embeddings=conn.execute(
                    "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL"
                ).fetchone()[0],
                catalogues=len(catalogue_metadata.get("catalogues", [])),
            )
            counts["catalogue_rows"] = sum(
                len(json.loads(row[0])["member_rows"])
                for row in conn.execute("SELECT data_json FROM catalogue_sources")
            )
            manifest = {
                "format": "xrb-mcp-dataset",
                "format_version": SNAPSHOT_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "database": {"filename": DATABASE_FILENAME},
                "counts": counts,
                "flags": {
                    "include_embeddings": include_embeddings,
                    "include_originals": include_originals,
                },
                "external_links": {"papers": papers_url, "catalogues": catalogues_url},
                "embedding_models": [
                    {
                        "model": model,
                        "revision": revision,
                        "dimension": dimension,
                        "chunks": count,
                    }
                    for model, revision, dimension, count in conn.execute(
                        "SELECT embedding_model, embedding_version, embedding_dimension, count(*) "
                        "FROM chunks WHERE embedding IS NOT NULL "
                        "GROUP BY embedding_model, embedding_version, embedding_dimension "
                        "ORDER BY embedding_model, embedding_version, embedding_dimension"
                    )
                ],
                "assets": [assets[key] for key in sorted(assets)],
            }
            metadata = {
                "format_version": SNAPSHOT_VERSION,
                "manifest": manifest,
                "counts": counts,
                "flags": manifest["flags"],
                "external_links": manifest["external_links"],
                "collections": collections,
                **catalogue_metadata,
            }
            conn.executemany(
                "INSERT INTO snapshot_metadata VALUES (?,?)",
                [(key, _json(value)) for key, value in metadata.items()],
            )
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('integrity-check')")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Dataset export contains broken foreign keys")
            conn.commit()
            conn.execute("VACUUM")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Dataset export failed SQLite integrity validation")
        finally:
            conn.close()
        manifest["database"].update(size_bytes=database.stat().st_size, sha256=_checksum(database))
        (stage / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        # Rename the complete directory only after every copy and validation passes.
        backup = Path(temp) / "previous"
        previous = output_dir.exists()
        if previous:
            os.replace(output_dir, backup)
        try:
            os.replace(stage, output_dir)
        except BaseException:
            if previous:
                os.replace(backup, output_dir)
            raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a relocatable XRB MCP research dataset")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--catalogue-database", type=Path)
    parser.add_argument("--include-embeddings", action="store_true")
    parser.add_argument("--include-originals", action="store_true")
    parser.add_argument("--papers-url")
    parser.add_argument("--catalogues-url")
    args = parser.parse_args()
    settings = get_settings()
    default_catalogue = settings.data_dir / "processed" / "source_catalogue" / "sources.db"
    catalogue = args.catalogue_database or (
        default_catalogue if default_catalogue.is_file() else None
    )
    with session_scope(read_only=True) as session:
        manifest = export_dataset(
            session,
            args.output_dir or settings.dataset_dir,
            catalogue_database=catalogue,
            include_embeddings=args.include_embeddings,
            include_originals=args.include_originals,
            data_dir=settings.data_dir,
            papers_url=args.papers_url,
            catalogues_url=args.catalogues_url,
        )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
