import argparse
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from xrb_mcp.database.connection import session_scope
from xrb_mcp.database.models import Paper, PaperChunk
from xrb_mcp.ingestion.embeddings import EmbeddingBackend, checked_embeddings, get_embedding_backend


def rebuild_paper(session: Session, paper_id: uuid.UUID, backend: EmbeddingBackend) -> int:
    session.execute(text("SELECT pg_advisory_xact_lock(827002)"))
    chunks = session.scalars(
        select(PaperChunk)
        .where(
            PaperChunk.paper_id == paper_id,
        )
        .order_by(PaperChunk.chunk_index)
    ).all()
    if not chunks:
        return 0
    vectors = checked_embeddings(backend, [chunk.text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model, chunk.embedding_version = backend.model, backend.version
        chunk.embedding_dimension, chunk.embedded_at = backend.dimension, datetime.now(UTC)
    session.flush()
    logging.info("embeddings_rebuilt paper_id=%s chunks=%d", paper_id, len(chunks))
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly rebuild embeddings, preserving chunk IDs"
    )
    parser.add_argument("--paper-id", type=uuid.UUID)
    args = parser.parse_args()
    backend = get_embedding_backend()
    if backend is None:
        parser.error("Configure XRB_EMBEDDING_BACKEND before rebuilding embeddings")
    logging.basicConfig(level=logging.INFO)
    with session_scope() as session:
        ids = session.scalars(select(Paper.id)).all() if args.paper_id is None else [args.paper_id]
        if args.paper_id and session.get(Paper, args.paper_id) is None:
            parser.error("Paper not found")
    count = 0
    for paper_id in ids:
        with session_scope() as session:
            count += rebuild_paper(session, paper_id, backend)
    print(
        json.dumps(
            {
                "papers": len(ids),
                "chunks_embedded": count,
                "model": backend.model,
                "version": backend.version,
            }
        )
    )


if __name__ == "__main__":
    main()
