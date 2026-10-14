"""Versioned, read-only distribution format; PostgreSQL remains the ingestion store."""

SNAPSHOT_VERSION = 1
DATABASE_FILENAME = "xrb.sqlite3"
MANIFEST_FILENAME = "dataset.json"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE snapshot_metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE sources (
    id TEXT PRIMARY KEY, normalized_name TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL
);
CREATE TABLE source_aliases (
    normalized_alias TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id)
);
CREATE TABLE papers (id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
CREATE TABLE paper_sources (
    paper_id TEXT NOT NULL REFERENCES papers(id), source_id TEXT NOT NULL REFERENCES sources(id),
    PRIMARY KEY (paper_id, source_id)
);
CREATE INDEX ix_paper_sources_source ON paper_sources(source_id);
CREATE TABLE collection_papers (
    collection TEXT NOT NULL, paper_id TEXT NOT NULL REFERENCES papers(id),
    PRIMARY KEY (collection, paper_id)
);
CREATE TABLE chunks (
    id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id),
    chunk_index INTEGER NOT NULL, text TEXT NOT NULL, data_json TEXT NOT NULL,
    embedding BLOB, embedding_model TEXT, embedding_version TEXT, embedding_dimension INTEGER,
    UNIQUE (paper_id, chunk_index)
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TABLE catalogue_sources (id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
CREATE TABLE catalogue_aliases (
    normalized_alias TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES catalogue_sources(id),
    PRIMARY KEY (normalized_alias, source_id)
);
CREATE TABLE catalogue_links (
    source_id TEXT NOT NULL REFERENCES sources(id),
    catalogue_source_id TEXT NOT NULL REFERENCES catalogue_sources(id),
    PRIMARY KEY (source_id, catalogue_source_id)
);
"""
