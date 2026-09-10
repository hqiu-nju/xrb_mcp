"""Initial literature schema; frozen DDL independent of future ORM changes."""

from alembic import op

revision = "0001_literature"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS vector
    """)
    op.execute("""
        CREATE TABLE collections (
            name TEXT NOT NULL,
            description TEXT,
            PRIMARY KEY (name)
        )
    """)
    op.execute("""
        CREATE TABLE papers (
            id UUID NOT NULL,
            title TEXT NOT NULL,
            authors TEXT[] NOT NULL,
            publication_year INTEGER,
            journal TEXT,
            doi TEXT,
            arxiv_id TEXT,
            ads_bibcode TEXT,
            abstract TEXT,
            pdf_path TEXT NOT NULL,
            source_url TEXT,
            content_hash VARCHAR(64) NOT NULL,
            metadata_method TEXT NOT NULL,
            ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (doi),
            UNIQUE (arxiv_id),
            UNIQUE (ads_bibcode),
            UNIQUE (content_hash)
        )
    """)
    op.execute("""
        CREATE INDEX ix_papers_publication_year ON papers (publication_year)
    """)
    op.execute("""
        CREATE TABLE sources (
            id UUID NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            source_class TEXT,
            compact_object_type TEXT,
            ra_deg FLOAT,
            dec_deg FLOAT,
            notes TEXT,
            authority TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            PRIMARY KEY (id),
            CHECK (ra_deg >= 0
                AND ra_deg < 360),
            CHECK (dec_deg >= -90
                AND dec_deg <= 90),
            CHECK ((ra_deg IS NULL) = (dec_deg IS NULL)),
            UNIQUE (canonical_name),
            UNIQUE (normalized_name)
        )
    """)
    op.execute("""
        CREATE TABLE collection_papers (
            collection TEXT NOT NULL,
            paper_id UUID NOT NULL,
            PRIMARY KEY (collection, paper_id),
            FOREIGN KEY(collection) REFERENCES collections (name) ON DELETE CASCADE,
            FOREIGN KEY(paper_id) REFERENCES papers (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE paper_chunks (
            id UUID NOT NULL,
            paper_id UUID NOT NULL,
            section TEXT NOT NULL,
            subsection TEXT,
            page_start INTEGER NOT NULL,
            page_end INTEGER NOT NULL,
            text TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            source_ids UUID[] NOT NULL,
            wavelengths TEXT[] NOT NULL,
            instruments TEXT[] NOT NULL,
            topics TEXT[] NOT NULL,
            embedding VECTOR,
            embedding_model TEXT,
            embedding_version TEXT,
            embedding_dimension INTEGER,
            embedded_at TIMESTAMP WITH TIME ZONE,
            search_vector TSVECTOR GENERATED ALWAYS AS
                (to_tsvector('english'::regconfig, text)) STORED,
            PRIMARY KEY (id),
            UNIQUE (paper_id, chunk_index),
            CHECK (page_start >= 1
                AND page_end >= page_start),
            CHECK (token_count > 0),
            CHECK ((embedding IS NULL
                AND embedding_model IS NULL
                AND embedding_version IS NULL
                AND embedding_dimension IS NULL
                AND embedded_at IS NULL) OR (embedding IS NOT NULL
                AND embedding_model IS NOT NULL
                AND embedding_version IS NOT NULL
                AND embedding_dimension > 0
                AND embedded_at IS NOT NULL
                AND vector_dims(embedding) = embedding_dimension)),
            FOREIGN KEY(paper_id) REFERENCES papers (id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX ix_chunks_fts ON paper_chunks USING gin (search_vector)
    """)
    op.execute("""
        CREATE INDEX ix_chunks_instruments ON paper_chunks USING gin (instruments)
    """)
    op.execute("""
        CREATE INDEX ix_chunks_sources ON paper_chunks USING gin (source_ids)
    """)
    op.execute("""
        CREATE INDEX ix_chunks_topics ON paper_chunks USING gin (topics)
    """)
    op.execute("""
        CREATE INDEX ix_chunks_wavelengths ON paper_chunks USING gin (wavelengths)
    """)
    op.execute("""
        CREATE TABLE paper_sources (
            paper_id UUID NOT NULL,
            source_id UUID NOT NULL,
            relationship_type TEXT NOT NULL,
            confidence FLOAT NOT NULL,
            PRIMARY KEY (paper_id, source_id),
            CHECK (confidence BETWEEN 0
                AND 1),
            FOREIGN KEY(paper_id) REFERENCES papers (id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES sources (id)
        )
    """)
    op.execute("""
        CREATE TABLE source_aliases (
            id UUID NOT NULL,
            source_id UUID NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            authority TEXT NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE CASCADE,
            UNIQUE (normalized_alias)
        )
    """)
    op.execute("""
        CREATE INDEX ix_alias_source ON source_aliases (source_id)
    """)
    op.execute("""
        CREATE TABLE provenance (
            id UUID NOT NULL,
            paper_id UUID NOT NULL,
            chunk_id UUID NOT NULL,
            page INTEGER NOT NULL,
            section TEXT NOT NULL,
            extraction_method TEXT NOT NULL,
            confidence FLOAT,
            verified_by_user BOOLEAN NOT NULL,
            details JSONB NOT NULL,
            PRIMARY KEY (id),
            CHECK (confidence IS NULL OR confidence BETWEEN 0
                AND 1),
            FOREIGN KEY(paper_id) REFERENCES papers (id) ON DELETE CASCADE,
            UNIQUE (chunk_id),
            FOREIGN KEY(chunk_id) REFERENCES paper_chunks (id) ON DELETE CASCADE
        )
    """)


def downgrade():
    op.execute("""
        DROP TABLE provenance
    """)
    op.execute("""
        DROP TABLE source_aliases
    """)
    op.execute("""
        DROP TABLE paper_sources
    """)
    op.execute("""
        DROP TABLE paper_chunks
    """)
    op.execute("""
        DROP TABLE collection_papers
    """)
    op.execute("""
        DROP TABLE sources
    """)
    op.execute("""
        DROP TABLE papers
    """)
    op.execute("""
        DROP TABLE collections
    """)
