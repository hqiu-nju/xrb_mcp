import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from xrb_mcp.astronomy.source_resolver import resolve_source
from xrb_mcp.database.models import Paper, PaperChunk, PaperSource, Provenance, Source, SourceAlias
from xrb_mcp.ingestion.metadata import PaperMetadata
from xrb_mcp.provenance.citations import paper_metadata


def source_object(session: Session, name: str) -> dict:
    try:
        identifier = uuid.UUID(name)
    except ValueError:
        source = resolve_source(session, name)
    else:
        source = session.get(Source, identifier)
        if source is None:
            raise ValueError("Source not found")
    aliases = session.scalars(
        select(SourceAlias)
        .where(
            SourceAlias.source_id == source.id,
        )
        .order_by(SourceAlias.alias)
    ).all()
    return {
        "id": str(source.id),
        "canonical_name": source.canonical_name,
        "source_class": source.source_class,
        "compact_object_type": source.compact_object_type,
        "ra_deg": source.ra_deg,
        "dec_deg": source.dec_deg,
        "authority": source.authority,
        "notes": source.notes,
        "aliases": [
            {"alias": a.alias, "type": a.alias_type, "authority": a.authority} for a in aliases
        ],
    }


def paper_object(session: Session, identifier: str) -> dict:
    identifier = identifier.strip()
    conditions = [func.lower(Paper.title) == identifier.lower(), Paper.ads_bibcode == identifier]
    try:
        conditions.append(Paper.id == uuid.UUID(identifier))
    except ValueError:
        pass
    for field in ("doi", "arxiv_id"):
        try:
            normalized = getattr(PaperMetadata(**{field: identifier}), field)
            conditions.append(getattr(Paper, field) == normalized)
        except ValueError:
            pass
    papers = session.scalars(select(Paper).where(or_(*conditions))).all()
    if not papers:
        raise ValueError("Paper not found")
    if len(papers) > 1:
        raise ValueError("Ambiguous paper title; use an internal ID or bibliographic identifier")
    paper = papers[0]
    chunks = session.scalars(
        select(PaperChunk)
        .where(
            PaperChunk.paper_id == paper.id,
        )
        .order_by(PaperChunk.chunk_index)
    ).all()
    sources = session.scalars(
        select(Source)
        .join(PaperSource)
        .where(
            PaperSource.paper_id == paper.id,
        )
    ).all()
    evidence = dict(
        session.execute(
            select(Provenance.chunk_id, Provenance.id).where(
                Provenance.paper_id == paper.id,
            )
        ).all()
    )
    return {
        **paper_metadata(paper),
        "sources": [{"id": str(s.id), "canonical_name": s.canonical_name} for s in sources],
        "sections": [
            {
                "chunk_id": str(c.id),
                "section": c.section,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "provenance_id": str(evidence[c.id]) if c.id in evidence else None,
            }
            for c in chunks
        ],
        "wavelengths": sorted({w for c in chunks for w in c.wavelengths}),
        "instruments": sorted({i for c in chunks for i in c.instruments}),
        "page_numbering": "pdf_1_based",
    }
