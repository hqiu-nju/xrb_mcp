from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from xrb_mcp.astronomy.source_resolver import resolve_source
from xrb_mcp.database.models import (
    CollectionPaper,
    Paper,
    PaperChunk,
    PaperSource,
    Provenance,
    Source,
)
from xrb_mcp.ingestion.embeddings import EmbeddingBackend, checked_embeddings
from xrb_mcp.provenance.citations import evidence_bundle
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.ranking import reciprocal_rank_fusion


def search_literature(
    session: Session,
    query: str,
    filters: LiteratureFilters,
    backend: EmbeddingBackend | None = None,
) -> dict:
    query = query.strip()
    if not query or len(query) > 10000:
        raise ValueError("Query must contain between 1 and 10000 characters")
    conditions = []
    source_id = None
    if filters.source:
        source_id = resolve_source(session, filters.source).id
        conditions.append(
            Paper.id.in_(select(PaperSource.paper_id).where(PaperSource.source_id == source_id))
        )
    if filters.source_class:
        conditions.append(
            Paper.id.in_(
                select(PaperSource.paper_id)
                .join(Source)
                .where(Source.source_class == filters.source_class)
            )
        )
    for field in ("wavelengths", "instruments", "topics"):
        values = getattr(filters, field)
        if values:
            conditions.append(getattr(PaperChunk, field).overlap(values))
    if filters.year_min:
        conditions.append(Paper.publication_year >= filters.year_min)
    if filters.year_max:
        conditions.append(Paper.publication_year <= filters.year_max)
    if filters.collection:
        conditions.append(
            Paper.id.in_(
                select(CollectionPaper.paper_id).where(
                    CollectionPaper.collection == filters.collection
                )
            )
        )
    base = select(PaperChunk.id).join(Paper).where(*conditions)
    tsquery = func.websearch_to_tsquery("english", query)
    source_order = (
        [case((PaperChunk.source_ids.contains([source_id]), 1), else_=0).desc()]
        if source_id
        else []
    )
    limit = max(50, filters.top_k * 5)
    lexical = session.scalars(
        base.where(PaperChunk.search_vector.op("@@")(tsquery))
        .order_by(
            *source_order,
            func.ts_rank_cd(PaperChunk.search_vector, tsquery).desc(),
            PaperChunk.id,
        )
        .limit(limit)
    ).all()
    semantic = []
    warnings = []
    if backend:
        vector = checked_embeddings(backend, [query])[0]
        compatible = (
            PaperChunk.embedding_model == backend.model,
            PaperChunk.embedding_version == backend.version,
            PaperChunk.embedding_dimension == backend.dimension,
        )
        # CASE guards the distance operation even if PostgreSQL reorders WHERE evaluation.
        embedding = case(
            (PaperChunk.embedding_dimension == backend.dimension, PaperChunk.embedding),
            else_=None,
        )
        semantic = session.scalars(
            base.where(
                *compatible,
                PaperChunk.embedding.is_not(None),
            )
            .order_by(
                *source_order,
                embedding.cosine_distance(vector),
                PaperChunk.id,
            )
            .limit(limit)
        ).all()
        missing = session.scalar(
            select(func.count())
            .select_from(PaperChunk)
            .join(Paper)
            .where(
                *conditions,
                (PaperChunk.embedding.is_(None))
                | (PaperChunk.embedding_model != backend.model)
                | (PaperChunk.embedding_version != backend.version)
                | (PaperChunk.embedding_dimension != backend.dimension),
            )
        )
        if missing:
            warnings.append(f"{missing} filtered chunks lack compatible embeddings; rebuild them")
    else:
        warnings.append("Semantic retrieval disabled; only PostgreSQL full-text search was used")
    scores = reciprocal_rank_fusion(lexical, semantic)
    rows = (
        session.execute(
            select(PaperChunk, Paper, Provenance)
            .select_from(PaperChunk)
            .join(Paper, Paper.id == PaperChunk.paper_id)
            .join(
                Provenance,
                Provenance.chunk_id == PaperChunk.id,
            )
            .where(PaperChunk.id.in_(scores))
        ).all()
        if scores
        else []
    )
    rows.sort(
        key=lambda row: (
            -(1 if source_id and source_id in row[0].source_ids else 0),
            -scores[row[0].id],
            str(row[0].id),
        )
    )
    results = []
    for chunk, paper, provenance in rows[: filters.top_k]:
        bundle = evidence_bundle(paper, chunk, provenance)
        bundle["score"] = scores[chunk.id]
        bundle["retrieval_channels"] = [
            name for name, ids in (("lexical", lexical), ("semantic", semantic)) if chunk.id in ids
        ]
        results.append(bundle)
    return {
        "query": query,
        "mode": "hybrid" if backend else "lexical",
        "filters": filters.model_dump(),
        "results": results,
        "warnings": warnings,
        "synthesis_generated": False,
    }
