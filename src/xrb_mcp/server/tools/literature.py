from xrb_mcp.database.connection import session_scope
from xrb_mcp.ingestion.embeddings import get_embedding_backend
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.hybrid_search import search_literature as research_search
from xrb_mcp.retrieval.objects import paper_object


def search_literature(
    query: str,
    source: str | None = None,
    source_class: str | None = None,
    wavelengths: list[str] | None = None,
    instruments: list[str] | None = None,
    topics: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    collection: str | None = None,
    top_k: int = 10,
) -> dict:
    """Search local literature. Return extracted passages, citations and explicit retrieval mode.

    Tags are heuristic mentions, not verified observations. Unknown sources raise an error.
    Filter lists use OR within each list and AND between fields. No synthesis is generated.
    """
    filters = LiteratureFilters(
        source=source,
        source_class=source_class,
        wavelengths=wavelengths or [],
        instruments=instruments or [],
        topics=topics or [],
        year_min=year_min,
        year_max=year_max,
        collection=collection,
        top_k=top_k,
    )
    with session_scope(read_only=True) as session:
        return research_search(session, query, filters, get_embedding_backend())


def get_paper(identifier: str) -> dict:
    """Get paper metadata and evidence references by ID, DOI, arXiv, bibcode or title."""
    with session_scope(read_only=True) as session:
        return paper_object(session, identifier)
