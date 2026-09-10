import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xrb_mcp.database.connection import session_scope
from xrb_mcp.database.models import Paper, PaperChunk, Provenance
from xrb_mcp.ingestion.incremental import content_hash


def validate_database(session: Session) -> dict:
    errors = []
    papers = session.scalars(select(Paper)).all()
    for paper in papers:
        path = Path(paper.pdf_path)
        if not path.is_file() or content_hash(path) != paper.content_hash:
            errors.append({"paper_id": str(paper.id), "error": "missing_or_corrupt_pdf"})
        count = session.scalar(
            select(func.count())
            .select_from(PaperChunk)
            .where(
                PaperChunk.paper_id == paper.id,
            )
        )
        if not count:
            errors.append({"paper_id": str(paper.id), "error": "no_chunks"})
    missing = session.scalars(
        select(PaperChunk.id)
        .outerjoin(
            Provenance,
            Provenance.chunk_id == PaperChunk.id,
        )
        .where(Provenance.id.is_(None))
    ).all()
    errors.extend(
        {"chunk_id": str(chunk_id), "error": "missing_provenance"} for chunk_id in missing
    )
    inconsistent = session.scalars(
        select(PaperChunk.id)
        .join(
            Provenance,
            Provenance.chunk_id == PaperChunk.id,
        )
        .where(
            (Provenance.paper_id != PaperChunk.paper_id)
            | (Provenance.page != PaperChunk.page_start)
            | (Provenance.section != PaperChunk.section),
        )
    ).all()
    errors.extend({"chunk_id": str(c), "error": "inconsistent_provenance"} for c in inconsistent)
    return {"valid": not errors, "papers": len(papers), "errors": errors}


def main() -> None:
    with session_scope(read_only=True) as session:
        report = validate_database(session)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
