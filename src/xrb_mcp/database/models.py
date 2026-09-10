"""Phase 1 schema. Uncertain astrophysical measurements belong in later evidence tables."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(Text, unique=True)
    normalized_name: Mapped[str] = mapped_column(Text, unique=True)
    source_class: Mapped[str | None] = mapped_column(Text)
    compact_object_type: Mapped[str | None] = mapped_column(Text)
    ra_deg: Mapped[float | None] = mapped_column(Float)
    dec_deg: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    authority: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("ra_deg >= 0 AND ra_deg < 360"),
        CheckConstraint("dec_deg >= -90 AND dec_deg <= 90"),
        CheckConstraint("(ra_deg IS NULL) = (dec_deg IS NULL)"),
    )


class SourceAlias(Base):
    __tablename__ = "source_aliases"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(Text)
    normalized_alias: Mapped[str] = mapped_column(Text, unique=True)
    alias_type: Mapped[str] = mapped_column(Text, default="alternate")
    authority: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_alias_source", "source_id"),)


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    publication_year: Mapped[int | None] = mapped_column(Integer, index=True)
    journal: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text, unique=True)
    arxiv_id: Mapped[str | None] = mapped_column(Text, unique=True)
    ads_bibcode: Mapped[str | None] = mapped_column(Text, unique=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    pdf_path: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    metadata_method: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperSource(Base):
    __tablename__ = "paper_sources"
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    relationship_type: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1"),)


class PaperChunk(Base):
    __tablename__ = "paper_chunks"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(Text)
    subsection: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID), default=list)
    wavelengths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    instruments: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    embedding = mapped_column(Vector(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_version: Mapped[str | None] = mapped_column(Text)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector = mapped_column(
        TSVECTOR, Computed("to_tsvector('english'::regconfig, text)", persisted=True)
    )
    __table_args__ = (
        UniqueConstraint("paper_id", "chunk_index"),
        CheckConstraint("page_start >= 1 AND page_end >= page_start"),
        CheckConstraint("token_count > 0"),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL AND embedding_version IS NULL "
            "AND embedding_dimension IS NULL AND embedded_at IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL "
            "AND embedding_version IS NOT NULL AND embedding_dimension > 0 "
            "AND embedded_at IS NOT NULL AND vector_dims(embedding) = embedding_dimension)"
        ),
        Index("ix_chunks_fts", "search_vector", postgresql_using="gin"),
        Index("ix_chunks_sources", "source_ids", postgresql_using="gin"),
        Index("ix_chunks_wavelengths", "wavelengths", postgresql_using="gin"),
        Index("ix_chunks_instruments", "instruments", postgresql_using="gin"),
        Index("ix_chunks_topics", "topics", postgresql_using="gin"),
    )


class Provenance(Base):
    __tablename__ = "provenance"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_chunks.id", ondelete="CASCADE"), unique=True
    )
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    verified_by_user: Mapped[bool] = mapped_column(default=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1"),)


class Collection(Base):
    __tablename__ = "collections"
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)


class CollectionPaper(Base):
    __tablename__ = "collection_papers"
    collection: Mapped[str] = mapped_column(
        ForeignKey("collections.name", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
