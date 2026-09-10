import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from xrb_mcp.astronomy.ontology import ONTOLOGY_VERSION
from xrb_mcp.astronomy.source_resolver import resolve_source
from xrb_mcp.database.models import (
    Collection,
    CollectionPaper,
    Paper,
    PaperChunk,
    PaperSource,
    Provenance,
    SourceAlias,
)
from xrb_mcp.ingestion.chunking import chunk_blocks
from xrb_mcp.ingestion.embeddings import EmbeddingBackend, checked_embeddings
from xrb_mcp.ingestion.incremental import content_hash
from xrb_mcp.ingestion.metadata import PaperMetadata
from xrb_mcp.ingestion.pdf_parser import PARSER_METHOD, parse_pdf
from xrb_mcp.ingestion.tagging import contains_term, tag_text

logger = logging.getLogger(__name__)


def ingest_paper(
    session: Session,
    path: Path,
    metadata: PaperMetadata,
    data_dir: Path,
    backend: EmbeddingBackend | None = None,
    max_words: int = 350,
) -> dict:
    """Call inside a transaction. Hash skips never parse PDFs or regenerate embeddings."""
    path = path.resolve(strict=True)
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise ValueError("Input must be a local PDF file")
    digest = content_hash(path)
    # Serialize initial single-worker ingestion to prevent conflicting identifier updates.
    session.execute(text("SELECT pg_advisory_xact_lock(827002)"))
    same = session.scalar(select(Paper).where(Paper.content_hash == digest))
    if same:
        return {"status": "skipped", "paper_id": str(same.id), "reason": "unchanged_sha256"}
    identifiers = [
        getattr(Paper, field) == getattr(metadata, field)
        for field in ("doi", "arxiv_id", "ads_bibcode")
        if getattr(metadata, field)
    ]
    matches = session.scalars(select(Paper).where(or_(*identifiers))).all() if identifiers else []
    if len(matches) > 1:
        raise ValueError("Paper identifiers point to different records; manual review is required")
    paper = matches[0] if matches else None
    if paper:
        for field in ("doi", "arxiv_id", "ads_bibcode"):
            old, new = getattr(paper, field), getattr(metadata, field)
            if old and new and old != new:
                raise ValueError(f"Conflicting {field}; review the paper identity manually")
    parsed = parse_pdf(path)
    chunks = chunk_blocks(parsed.blocks, max_words)
    vectors = checked_embeddings(backend, [c.text for c in chunks]) if backend else None
    explicit_sources = {resolve_source(session, name).id for name in metadata.sources}
    if paper and "sources" not in metadata.model_fields_set:
        explicit_sources.update(
            session.scalars(
                select(PaperSource.source_id).where(
                    PaperSource.paper_id == paper.id,
                    PaperSource.relationship_type == "manual",
                )
            ).all()
        )
    aliases = session.scalars(select(SourceAlias)).all()
    mentioned = [{a.source_id for a in aliases if contains_term(c.text, a.alias)} for c in chunks]
    all_sources = explicit_sources | set().union(*mentioned)
    archive = data_dir.resolve() / "papers" / f"{digest}.pdf"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        # Atomic publication inside the content-addressed directory. Failures may leave only
        # unreferenced originals, never partially updated database rows.
        temporary = archive.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with path.open("rb") as src, temporary.open("xb") as dst:
                import shutil

                shutil.copyfileobj(src, dst)
            if content_hash(temporary) != digest:
                raise ValueError("PDF changed while being ingested; retry with a stable file")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    elif content_hash(archive) != digest:
        raise ValueError("Archived PDF checksum mismatch")

    status = "updated" if paper else "ingested"
    values = metadata.model_dump(exclude={"sources", "collections"}, exclude_unset=True)
    if not values.get("title"):
        values["title"] = (
            (paper.title if paper else None) or parsed.metadata.get("title") or path.stem
        )
    if paper is None:
        paper = Paper(
            **values,
            pdf_path=str(archive),
            content_hash=digest,
            metadata_method="sidecar+pdf_metadata",
        )
        session.add(paper)
        session.flush()
    else:
        for field, value in values.items():
            if value is not None:
                setattr(paper, field, value)
        paper.content_hash, paper.pdf_path = digest, str(archive)
        paper.updated_at = datetime.now(UTC)
        session.execute(delete(PaperChunk).where(PaperChunk.paper_id == paper.id))
        session.execute(delete(PaperSource).where(PaperSource.paper_id == paper.id))
    for source_id in all_sources:
        session.add(
            PaperSource(
                paper_id=paper.id,
                source_id=source_id,
                relationship_type="manual" if source_id in explicit_sources else "name_mention",
                confidence=1.0 if source_id in explicit_sources else 0.8,
            )
        )
    for index, chunk in enumerate(chunks):
        row = PaperChunk(
            paper_id=paper.id,
            section=chunk.section,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            text=chunk.text,
            chunk_index=index,
            token_count=chunk.token_count,
            source_ids=sorted(mentioned[index], key=str),
            **tag_text(chunk.text),
        )
        if backend and vectors:
            row.embedding = vectors[index]
            row.embedding_model, row.embedding_version = backend.model, backend.version
            row.embedding_dimension, row.embedded_at = backend.dimension, datetime.now(UTC)
        session.add(row)
        session.flush()
        session.add(
            Provenance(
                paper_id=paper.id,
                chunk_id=row.id,
                page=chunk.page_start,
                section=chunk.section,
                extraction_method=PARSER_METHOD,
                verified_by_user=False,
                details={
                    "page_numbering": "pdf_1_based",
                    "ontology_version": ONTOLOGY_VERSION,
                    "token_count_method": "ceil_whitespace_words_times_1.34",
                    "content_hash": digest,
                    "tags_method": "keyword_heuristic",
                },
            )
        )
    for name in metadata.collections:
        if not name.strip():
            raise ValueError("Collection names must not be empty")
        if session.get(Collection, name) is None:
            session.add(Collection(name=name))
            session.flush()
        if session.get(CollectionPaper, (name, paper.id)) is None:
            session.add(CollectionPaper(collection=name, paper_id=paper.id))
    session.flush()
    logger.info("paper_%s paper_id=%s chunks=%d", status, paper.id, len(chunks))
    return {
        "status": status,
        "paper_id": str(paper.id),
        "chunks": len(chunks),
        "pages": parsed.page_count,
        "embedded": backend is not None,
        "warnings": []
        if metadata.title and metadata.authors and metadata.publication_year
        else ["Incomplete bibliographic metadata; supply a reviewed JSON sidecar"],
    }
