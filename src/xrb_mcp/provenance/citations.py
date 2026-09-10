from urllib.parse import quote

from xrb_mcp.database.models import Paper, PaperChunk, Provenance


def paper_metadata(paper: Paper) -> dict:
    """Deliberately omit internal filesystem paths and connection configuration."""
    url = None
    if paper.doi:
        url = "https://doi.org/" + quote(paper.doi, safe="/")
    elif paper.arxiv_id:
        url = "https://arxiv.org/abs/" + quote(paper.arxiv_id, safe="/")
    elif paper.ads_bibcode:
        url = "https://ui.adsabs.harvard.edu/abs/" + quote(paper.ads_bibcode, safe="")
    return {
        "id": str(paper.id),
        "title": paper.title,
        "authors": paper.authors,
        "publication_year": paper.publication_year,
        "journal": paper.journal,
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id,
        "ads_bibcode": paper.ads_bibcode,
        "source_url": paper.source_url,
        "citation_url": url,
        "abstract": paper.abstract,
        "metadata_method": paper.metadata_method,
    }


def evidence_bundle(paper: Paper, chunk: PaperChunk, provenance: Provenance) -> dict:
    return {
        "chunk_id": str(chunk.id),
        "text": chunk.text,
        "paper": paper_metadata(paper),
        "section": chunk.section,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "page_numbering": "pdf_1_based",
        "source_ids": [str(s) for s in chunk.source_ids],
        "wavelengths": chunk.wavelengths,
        "instruments": chunk.instruments,
        "topics": chunk.topics,
        "provenance": {
            "id": str(provenance.id),
            "extraction_method": provenance.extraction_method,
            "confidence": provenance.confidence,
            "verified_by_user": provenance.verified_by_user,
            "details": provenance.details,
        },
        "evidence_kind": "extracted_passage",
    }
