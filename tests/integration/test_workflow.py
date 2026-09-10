import uuid

import pytest
from sqlalchemy import func, select

from xrb_mcp.astronomy.source_resolver import UnknownSource, register_source, resolve_source
from xrb_mcp.database.models import Paper, PaperChunk, Provenance
from xrb_mcp.ingestion.metadata import PaperMetadata
from xrb_mcp.ingestion.papers import ingest_paper
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.hybrid_search import search_literature
from xrb_mcp.retrieval.objects import paper_object
from xrb_mcp.scripts.rebuild_embeddings import rebuild_paper
from xrb_mcp.scripts.validate_database import validate_database

pytestmark = pytest.mark.integration


def metadata(**kwargs):
    return PaperMetadata(
        title="Synthetic radio paper",
        authors=["Test Author"],
        publication_year=2018,
        doi="10.1234/test",
        **kwargs,
    )


def test_ingest_search_duplicate_update(session, pdf_factory, tmp_path, backend):
    source = register_source(session, "MAXI J1820+070", ["ASASSN-18ey"], "test fixture")
    assert resolve_source(session, "asassn-18ey").id == source.id
    path = pdf_factory()
    first = ingest_paper(session, path, metadata(sources=["ASASSN-18ey"]), tmp_path, backend)
    paper_id = uuid.UUID(first["paper_id"])
    old_ids = set(session.scalars(select(PaperChunk.id)).all())
    calls = backend.calls
    assert ingest_paper(session, path, metadata(), tmp_path, backend)["status"] == "skipped"
    assert backend.calls == calls
    assert set(session.scalars(select(PaperChunk.id)).all()) == old_ids
    result = search_literature(
        session,
        "radio ejecta",
        LiteratureFilters(
            source="ASASSN-18ey",
            year_min=2018,
            year_max=2018,
            wavelengths=["radio"],
        ),
        backend,
    )
    assert result["mode"] == "hybrid"
    passage = result["results"][0]
    assert passage["page_start"] == 2
    assert passage["section"] == "2 Results"
    assert passage["paper"]["doi"] == "10.1234/test"
    assert passage["retrieval_channels"] == ["lexical", "semantic"]
    assert passage["provenance"]["verified_by_user"] is False
    assert "pdf_path" not in passage["paper"]
    assert (
        search_literature(session, "radio", LiteratureFilters(year_min=2020), backend)["results"]
        == []
    )
    assert paper_object(session, "https://doi.org/10.1234/TEST")["id"] == str(paper_id)
    # An unrelated paper must keep its chunk IDs during the update.
    other = ingest_paper(
        session,
        pdf_factory("other.pdf", [["Abstract", "Unrelated optical paper"]]),
        PaperMetadata(title="Other", doi="10.1234/other"),
        tmp_path,
        backend,
    )
    other_ids = set(
        session.scalars(
            select(PaperChunk.id).where(
                PaperChunk.paper_id == uuid.UUID(other["paper_id"]),
            )
        ).all()
    )
    changed = pdf_factory("revised.pdf", [["2 Results", "Revised radio ejecta measurement"]])
    update = ingest_paper(session, changed, metadata(), tmp_path, backend)
    assert update["status"] == "updated" and update["paper_id"] == first["paper_id"]
    assert not old_ids.intersection(session.scalars(select(PaperChunk.id)).all())
    assert other_ids.issubset(session.scalars(select(PaperChunk.id)).all())
    assert session.scalar(select(func.count()).select_from(Provenance)) == 2
    assert validate_database(session)["valid"]


def test_conflicts_unknown_sources_and_transaction_rollback(session, pdf_factory, tmp_path):
    register_source(session, "Source A", ["shared"], "test")
    with pytest.raises(ValueError, match="another source"):
        register_source(session, "Source B", ["SHARED"], "test")
    with pytest.raises(UnknownSource):
        resolve_source(session, "nonexistent")
    with pytest.raises(UnknownSource):
        search_literature(session, "radio", LiteratureFilters(source="nonexistent"))
    with pytest.raises(UnknownSource), session.begin_nested():
        ingest_paper(session, pdf_factory(), metadata(sources=["unknown"]), tmp_path)
    assert session.scalar(select(func.count()).select_from(Paper)) == 0


def test_lexical_mode_and_rebuild_preserves_citations(session, pdf_factory, tmp_path, backend):
    first = ingest_paper(session, pdf_factory(), metadata(), tmp_path)
    result = search_literature(session, "radio", LiteratureFilters())
    assert result["mode"] == "lexical" and result["warnings"]
    chunk_id = result["results"][0]["chunk_id"]
    rebuild_paper(session, uuid.UUID(first["paper_id"]), backend)
    assert search_literature(session, "radio", LiteratureFilters(), backend)["mode"] == "hybrid"
    assert session.get(PaperChunk, uuid.UUID(chunk_id)) is not None
    # Even a backend with a different dimension must safely exclude old vectors.
    backend.dimension = 4
    backend.version = "2"
    backend.embed = lambda texts: [[1, 0, 0, 0] for _ in texts]
    mixed = search_literature(session, "radio", LiteratureFilters(), backend)
    assert mixed["warnings"]
    assert mixed["results"][0]["retrieval_channels"] == ["lexical"]


def test_embedding_failure_leaves_existing_paper_intact(session, pdf_factory, tmp_path, backend):
    first = ingest_paper(session, pdf_factory(), metadata(), tmp_path, backend)
    original = session.get(Paper, uuid.UUID(first["paper_id"])).content_hash
    backend.embed = lambda texts: [[0, 0, 0] for _ in texts]
    with pytest.raises(ValueError, match="nonzero"), session.begin_nested():
        ingest_paper(
            session, pdf_factory("bad.pdf", [["Changed text"]]), metadata(), tmp_path, backend
        )
    assert session.get(Paper, uuid.UUID(first["paper_id"])).content_hash == original
