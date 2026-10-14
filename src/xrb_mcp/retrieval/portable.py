"""Read a portable snapshot without opening PostgreSQL or the original papers.

The lexical query grammar is deliberately smaller than raw FTS5: ordinary terms
are ANDed, double quotes preserve phrases, OR separates groups, and a leading
minus excludes a term or phrase from the whole query. Other punctuation is
tokenized as text; FTS column selectors, NEAR, prefixes, and parentheses are not
operators. This keeps natural questions and malformed input out of FTS5 syntax.
SQLite's FTS5 documentation defines quoted strings and ascending BM25 ranking:
https://www.sqlite.org/fts5.html
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.astronomy.source_resolver import UnknownSource
from xrb_mcp.database.portable_schema import SNAPSHOT_VERSION
from xrb_mcp.ingestion.embeddings import EmbeddingBackend, checked_embeddings
from xrb_mcp.ingestion.metadata import PaperMetadata
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.ranking import reciprocal_rank_fusion

_DATASET_ERROR = "Portable dataset unavailable or invalid; ask the operator to check it"
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _relative_archive_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


def _public_data(value: Any) -> Any:
    """Omit internal paths even if an incorrectly built snapshot includes them."""
    if isinstance(value, list):
        return [_public_data(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"pdf_path", "database_url", "read_database_url"}:
            continue
        if isinstance(item, str):
            if key == "archive_path" and not _relative_archive_path(item):
                continue
            path_key = key in {"path", "origin", "snapshot", "database"} or key.endswith(
                ("_path", "_dir")
            )
            if path_key and (item.startswith(("/", "~", "file:")) or _WINDOWS_PATH.match(item)):
                continue
        result[key] = _public_data(item)
    return result


def _compile_fts_query(query: str) -> str | None:
    """Compile web-style input to a constrained, quoted FTS5 expression.

    Unclosed quotes extend to the end; leading/trailing OR is ignored. Negative
    clauses apply to all OR groups. Negative-only and punctuation-only queries
    have no lexical matches rather than selecting every document.
    """
    groups: list[list[str]] = [[]]
    excluded: list[str] = []
    offset = 0
    term_count = 0
    while offset < len(query):
        if query[offset].isspace():
            offset += 1
            continue
        negative = query[offset] == "-"
        if negative:
            offset += 1
        quoted = offset < len(query) and query[offset] == '"'
        if quoted:
            offset += 1
            end = query.find('"', offset)
            end = len(query) if end < 0 else end
            text = query[offset:end]
            offset = min(end + 1, len(query))
        else:
            end = offset
            while end < len(query) and not query[end].isspace() and query[end] != '"':
                end += 1
            text = query[offset:end]
            offset = end
        if not negative and not quoted and text.casefold() == "or":
            if groups[-1]:
                groups.append([])
            continue
        words = _WORDS.findall(text)
        if not words:
            continue
        term_count += len(words)
        if term_count > 256:
            raise ValueError("Portable search queries support at most 256 terms")
        # Only compiler-generated quotes/operators reach MATCH. Punctuation
        # within a term becomes a phrase under the same unicode61 tokenizer.
        phrase = '"' + " ".join(words) + '"'
        if negative:
            excluded.append(phrase)
        else:
            groups[-1].append(phrase)
    positive = [" AND ".join(group) for group in groups if group]
    if not positive:
        return None
    expression = " OR ".join(f"({group})" for group in positive)
    if excluded:
        expression = f"({expression}) NOT (" + " OR ".join(excluded) + ")"
    return expression


class PortableReader:
    """A context-managed, read-only reader for the versioned SQLite snapshot."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._metadata: dict[str, Any] = {}

    def __enter__(self) -> PortableReader:
        if self._connection is not None:
            raise ValueError("Portable dataset reader is already open")
        try:
            uri = self.path.resolve(strict=True).as_uri() + "?mode=ro"
            self._connection = sqlite3.connect(uri, uri=True)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA query_only = ON")
            self._connection.execute("PRAGMA trusted_schema = OFF")
            metadata = self._connection.execute(
                "SELECT key, value_json FROM snapshot_metadata"
            ).fetchall()
            self._metadata = {row["key"]: json.loads(row["value_json"]) for row in metadata}
            version = self._metadata.get("format_version")
            if type(version) is not int or version != SNAPSHOT_VERSION:
                raise ValueError(
                    f"Unsupported portable dataset format; expected version {SNAPSHOT_VERSION}"
                )
            # A version marker alone does not establish that the schema is complete.
            for table, columns in (
                ("sources", "id, normalized_name, data_json"),
                ("source_aliases", "normalized_alias, source_id"),
                ("papers", "id, data_json"),
                ("paper_sources", "paper_id, source_id"),
                ("collection_papers", "collection, paper_id"),
                (
                    "chunks",
                    "id, paper_id, chunk_index, text, data_json, embedding, "
                    "embedding_model, embedding_version, embedding_dimension",
                ),
                ("chunks_fts", "rowid, text"),
                ("catalogue_sources", "id, data_json"),
                ("catalogue_aliases", "normalized_alias, source_id"),
                ("catalogue_links", "source_id, catalogue_source_id"),
            ):
                self._connection.execute(f"SELECT {columns} FROM {table} LIMIT 0")
        except (OSError, sqlite3.Error, TypeError, json.JSONDecodeError):
            self.close()
            raise ValueError(_DATASET_ERROR) from None
        except ValueError:
            self.close()
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _rows(self, query: str, parameters: tuple | list = ()) -> list[sqlite3.Row]:
        if self._connection is None:
            raise ValueError("Portable dataset reader must be opened with a context manager")
        try:
            return self._connection.execute(query, parameters).fetchall()
        except sqlite3.Error:
            raise ValueError(_DATASET_ERROR) from None

    @staticmethod
    def _data(row: sqlite3.Row) -> dict:
        try:
            value = json.loads(row["data_json"])
        except (TypeError, json.JSONDecodeError):
            raise ValueError(_DATASET_ERROR) from None
        if not isinstance(value, dict):
            raise ValueError(_DATASET_ERROR)
        return _public_data(value)

    def _registry_source(self, identifier: str) -> sqlite3.Row | None:
        rows = self._rows("SELECT id, data_json FROM sources WHERE id = ?", (identifier,))
        if rows:
            return rows[0]
        normalized = normalize_alias(identifier)
        rows = self._rows(
            "SELECT id, data_json FROM sources WHERE normalized_name = ?", (normalized,)
        )
        if rows:
            return rows[0]
        rows = self._rows(
            "SELECT s.id, s.data_json FROM sources s JOIN source_aliases a ON a.source_id = s.id "
            "WHERE a.normalized_alias = ?",
            (normalized,),
        )
        return rows[0] if rows else None

    def _catalogue_source(self, identifier: str) -> sqlite3.Row | None:
        rows = self._rows("SELECT id, data_json FROM catalogue_sources WHERE id = ?", (identifier,))
        if rows:
            return rows[0]
        normalized = normalize_alias(identifier)
        rows = self._rows(
            "SELECT s.id, s.data_json FROM catalogue_sources s JOIN catalogue_aliases a "
            "ON a.source_id = s.id WHERE a.normalized_alias = ? ORDER BY s.id",
            (normalized,),
        )
        if len(rows) > 1:
            raise ValueError("Ambiguous catalogue source alias; use a catalogue source ID")
        if rows:
            return rows[0]
        # Canonical names remain resolvable in a snapshot whose alias table does
        # not repeat them. Do not guess from coordinates or other scientific data.
        matches = {row["id"]: row for row in rows}
        for row in self._rows("SELECT id, data_json FROM catalogue_sources"):
            canonical = self._data(row).get("canonical_name")
            if isinstance(canonical, str) and canonical.strip():
                if normalize_alias(canonical) == normalized:
                    matches[row["id"]] = row
        if len(matches) > 1:
            raise ValueError("Ambiguous catalogue source alias; use a catalogue source ID")
        return next(iter(matches.values()), None)

    def source_object(self, identifier: str) -> dict:
        identifier = identifier.strip()
        source = self._registry_source(identifier)
        if source is not None:
            result = self._data(source)
            result.setdefault("id", source["id"])
            result["catalogue_matches"] = [
                self._data(row)
                for row in self._rows(
                    "SELECT c.id, c.data_json FROM catalogue_sources c JOIN catalogue_links l "
                    "ON l.catalogue_source_id = c.id WHERE l.source_id = ? ORDER BY c.id",
                    (source["id"],),
                )
            ]
            return result
        catalogue = self._catalogue_source(identifier)
        if catalogue is not None:
            result = self._data(catalogue)
            result.setdefault("id", catalogue["id"])
            result["identity_scope"] = "catalogue"
            return result
        raise UnknownSource("Source is not registered or present in the portable catalogue")

    def paper_object(self, identifier: str) -> dict:
        identifier = identifier.strip()
        if not identifier:
            raise ValueError("Paper identifier must not be empty")
        normalized = {}
        for field in ("doi", "arxiv_id"):
            try:
                normalized[field] = getattr(PaperMetadata(**{field: identifier}), field)
            except ValueError:
                pass
        matches = []
        for row in self._rows("SELECT id, data_json FROM papers"):
            data = self._data(row)
            if (
                row["id"] == identifier
                or str(data.get("title", "")).casefold() == identifier.casefold()
                or data.get("ads_bibcode") == identifier
                or any(data.get(field) == value for field, value in normalized.items())
            ):
                matches.append((row, data))
        if not matches:
            raise ValueError("Paper not found")
        if len(matches) > 1:
            raise ValueError(
                "Ambiguous paper title; use an internal ID or bibliographic identifier"
            )
        paper, result = matches[0]
        result.setdefault("id", paper["id"])
        chunks = [
            (row, self._data(row))
            for row in self._rows(
                "SELECT id, data_json FROM chunks WHERE paper_id = ? ORDER BY chunk_index",
                (paper["id"],),
            )
        ]
        result["sources"] = [
            {"id": row["id"], "canonical_name": self._data(row).get("canonical_name")}
            for row in self._rows(
                "SELECT s.id, s.data_json FROM sources s JOIN paper_sources ps "
                "ON ps.source_id = s.id "
                "WHERE ps.paper_id = ? ORDER BY s.id",
                (paper["id"],),
            )
        ]
        result["sections"] = [
            {
                "chunk_id": row["id"],
                "section": data.get("section"),
                "page_start": data.get("page_start"),
                "page_end": data.get("page_end"),
                "provenance_id": data.get("provenance", {}).get("id"),
            }
            for row, data in chunks
        ]
        result["wavelengths"] = sorted(
            {item for _, c in chunks for item in c.get("wavelengths", [])}
        )
        result["instruments"] = sorted(
            {item for _, c in chunks for item in c.get("instruments", [])}
        )
        result["page_numbering"] = "pdf_1_based"
        return result

    def dataset_info(self, include_catalogues: bool = False) -> dict:
        """Return the published manifest and counts without the host database path."""
        manifest = self._metadata.get("manifest", {})
        if not isinstance(manifest, dict):
            raise ValueError(_DATASET_ERROR)
        result = _public_data(manifest)
        result["format_version"] = SNAPSHOT_VERSION
        result["database_mode"] = "portable"
        result["read_only"] = True
        if include_catalogues:
            result["catalogues"] = _public_data(self._metadata.get("catalogues", []))
            result["collections"] = _public_data(self._metadata.get("collections", []))
            result["catalogue_registry_review"] = _public_data(
                self._metadata.get("catalogue_registry_review", [])
            )
        if "counts" not in result:
            result["counts"] = {
                table: self._rows(f"SELECT count(*) AS count FROM {table}")[0]["count"]
                for table in ("sources", "papers", "chunks", "catalogue_sources")
            }
        return result

    def _filter_sql(
        self, filters: LiteratureFilters, source_id: str | None
    ) -> tuple[list[str], list]:
        clauses = []
        parameters: list = []
        if source_id:
            clauses.append("c.paper_id IN (SELECT paper_id FROM paper_sources WHERE source_id = ?)")
            parameters.append(source_id)
        if filters.source_class:
            clauses.append(
                "c.paper_id IN (SELECT ps.paper_id FROM paper_sources ps JOIN sources s "
                "ON s.id = ps.source_id WHERE json_extract(s.data_json, '$.source_class') = ?)"
            )
            parameters.append(filters.source_class)
        for field in ("wavelengths", "instruments", "topics"):
            values = getattr(filters, field)
            if values:
                placeholders = ",".join("?" for _ in values)
                clauses.append(
                    f"EXISTS (SELECT 1 FROM json_each(c.data_json, '$.{field}') "
                    f"WHERE value IN ({placeholders}))"
                )
                parameters.extend(values)
        if filters.year_min is not None:
            clauses.append("json_extract(p.data_json, '$.publication_year') >= ?")
            parameters.append(filters.year_min)
        if filters.year_max is not None:
            clauses.append("json_extract(p.data_json, '$.publication_year') <= ?")
            parameters.append(filters.year_max)
        if filters.collection:
            clauses.append(
                "c.paper_id IN (SELECT paper_id FROM collection_papers WHERE collection = ?)"
            )
            parameters.append(filters.collection)
        return clauses, parameters

    def search_literature(
        self,
        query: str,
        filters: LiteratureFilters,
        backend: EmbeddingBackend | None = None,
    ) -> dict:
        """Search passages using SQLite BM25 and optional compatible cosine/RRF.

        Lexical tokenization and ranking differ from PostgreSQL. See the module's
        constrained web query grammar; source/tag/year/collection filters retain
        their PostgreSQL meaning and page/provenance references remain unchanged.
        """
        query = query.strip()
        if not query or len(query) > 10000:
            raise ValueError("Query must contain between 1 and 10000 characters")
        source_id = None
        warnings = []
        response = {
            "query": query,
            "mode": "hybrid" if backend else "lexical",
            "retrieval_backend": "sqlite_fts5",
            "filters": filters.model_dump(),
            "results": [],
            "warnings": warnings,
            "synthesis_generated": False,
        }
        if filters.source:
            source = self._registry_source(filters.source.strip())
            if source is not None:
                source_id = source["id"]
            elif self._catalogue_source(filters.source.strip()) is not None:
                warnings.append(
                    "This source exists only in the catalogue and has no registered literature "
                    "identity; no literature search was performed"
                )
                return response
            else:
                raise UnknownSource("Source is not registered or present in the portable catalogue")
        clauses, parameters = self._filter_sql(filters, source_id)
        where = " AND ".join(clauses) if clauses else "1"
        limit = max(50, filters.top_k * 5)
        expression = _compile_fts_query(query)
        lexical = []
        if expression:
            order = ""
            order_parameters = []
            if source_id:
                order = (
                    "EXISTS (SELECT 1 FROM json_each(c.data_json, '$.source_ids') "
                    "WHERE value = ?) DESC, "
                )
                order_parameters.append(source_id)
            lexical = [
                row["id"]
                for row in self._rows(
                    "SELECT c.id FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid "
                    "JOIN papers p ON p.id = c.paper_id WHERE chunks_fts MATCH ? AND "
                    f"{where} ORDER BY {order}bm25(chunks_fts), c.id LIMIT ?",
                    [expression, *parameters, *order_parameters, limit],
                )
            ]
        else:
            warnings.append("Lexical retrieval requires at least one positive searchable term")
        semantic = []
        if backend:
            query_vector = np.asarray(checked_embeddings(backend, [query])[0], dtype=float)
            query_vector /= np.linalg.norm(query_vector)
            ranked = []
            missing = 0
            for row in self._rows(
                "SELECT c.id, c.data_json, c.embedding, c.embedding_model, c.embedding_version, "
                "c.embedding_dimension FROM chunks c JOIN papers p ON p.id = c.paper_id "
                f"WHERE {where}",
                parameters,
            ):
                blob = row["embedding"]
                compatible = (
                    row["embedding_model"] == backend.model
                    and row["embedding_version"] == backend.version
                    and row["embedding_dimension"] == backend.dimension
                    and isinstance(blob, bytes)
                    and len(blob) == backend.dimension * 4
                )
                if not compatible:
                    missing += 1
                    continue
                vector = np.frombuffer(blob, dtype="<f4").astype(float)
                norm = np.linalg.norm(vector)
                if not np.isfinite(vector).all() or not np.isfinite(norm) or norm == 0:
                    missing += 1
                    continue
                mentions_source = source_id is not None and source_id in self._data(row).get(
                    "source_ids", []
                )
                cosine = float(np.dot(vector / norm, query_vector))
                ranked.append((not mentions_source, -cosine, row["id"]))
            semantic = [identifier for _, _, identifier in sorted(ranked)[:limit]]
            if missing:
                warnings.append(
                    f"{missing} filtered chunks lack compatible embeddings; export a snapshot "
                    "with embeddings for the configured model"
                )
        else:
            warnings.append("Semantic retrieval disabled; only SQLite full-text search was used")
        scores = reciprocal_rank_fusion(lexical, semantic)
        bundles = []
        identifiers = list(scores)
        for offset in range(0, len(identifiers), 400):
            batch = identifiers[offset : offset + 400]
            placeholders = ",".join("?" for _ in batch)
            for row in self._rows(
                "SELECT c.id, c.text, c.data_json, p.data_json AS paper_json "
                "FROM chunks c JOIN papers p ON p.id = c.paper_id "
                f"WHERE c.id IN ({placeholders})",
                batch,
            ):
                bundle = self._data(row)
                try:
                    paper = json.loads(row["paper_json"])
                except (TypeError, json.JSONDecodeError):
                    raise ValueError(_DATASET_ERROR) from None
                if not isinstance(paper, dict):
                    raise ValueError(_DATASET_ERROR)
                bundle.update(
                    chunk_id=row["id"],
                    text=row["text"],
                    paper=_public_data(paper),
                    score=scores[row["id"]],
                    retrieval_channels=[
                        name
                        for name, ranking in (("lexical", lexical), ("semantic", semantic))
                        if row["id"] in ranking
                    ],
                )
                bundles.append(bundle)
        bundles.sort(
            key=lambda bundle: (
                -(1 if source_id and source_id in bundle.get("source_ids", []) else 0),
                -bundle["score"],
                bundle["chunk_id"],
            )
        )
        response["results"] = bundles[: filters.top_k]
        return response
