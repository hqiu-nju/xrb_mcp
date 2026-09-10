# XRB MCP research framework

A local, provenance-aware literature backend for X-ray binary research. This is the
initial Phase 1 framework from [the system plan](XRB_MCP_SYSTEM_PLAN.md), not the
completed scientific knowledge base. No research papers or asserted astrophysical
measurements are bundled.

Implemented:

- PostgreSQL + pgvector, a frozen Alembic migration, full-text/metadata indexes,
  and a separate read-only MCP database role.
- PDF text extraction with 1-based PDF page references and section heuristics;
  paragraph-aware chunking and content-addressed PDF storage.
- Transactional ingestion, SHA256 skips, and changed-document replacement by
  normalized DOI, arXiv identifier or ADS bibcode.
- Reviewed source/alias registration; strict case/spacing normalization that
  preserves coordinate signs and rejects conflicting identities.
- PostgreSQL lexical search and optional real sentence-transformer embeddings,
  pgvector cosine search, reciprocal-rank fusion, and metadata filters.
- MCP tools `search_literature`, `get_paper`, `get_source`; paper, source and
  ontology resources. CLI ingestion and validation remain separate from MCP.
- Automated synthetic-PDF tests, including a real stdio MCP client workflow.

Python modules follow the plan’s functional layout under `src/xrb_mcp/` to avoid
collisions with unrelated installed packages. Deployment and migrations remain at
the repository root.

## Documentation

- [Updating the database](docs/DATABASE_UPDATES.md): ingestion, revisions, source
  registration, embeddings, backups, and the stored census-paper example.
- [Using MCP with agents](docs/MCP_AGENTS.md): Codex and generic client setup,
  tool reference, research workflows, and troubleshooting.
- [Runnable Python MCP client](examples/mcp/client.py),
  [Codex configuration](examples/mcp/codex.toml), and
  [generic stdio configuration](examples/mcp/stdio.json).

## Quick start

Requires Conda (Miniconda/Miniforge/Anaconda) and Docker Desktop/Engine with
Compose. `environment.yml` creates the `xrb-mcp` environment with Python 3.12
and installs the project plus development tools. Run commands from this repository root.

```bash
conda env create -f environment.yml
conda activate xrb-mcp
if [ ! -f .env ]; then cp .env.example .env; fi
docker compose up -d db
alembic upgrade head
xrb-validate
```

The default database port is bound to localhost. Example passwords are for local
development. Set credentials in `.env` before first startup. The database initializes
`xrb_reader` with SELECT permissions on tables created by the migration owner.
Changing passwords in `.env` does not change roles in an existing database volume.

To run the migration and MCP server entirely in containers:

```bash
docker compose build migrate mcp
docker compose run --rm migrate
docker compose run --rm --no-deps -T mcp
```

The final command speaks MCP over stdin/stdout and is intended for a client to
launch. Do not allocate a TTY. There is no unauthenticated HTTP endpoint.

For an existing environment, use `conda env update -f environment.yml`. After
changing project code, run `python -m pip install --no-deps .` inside the active
environment. Agent launch paths must point to this Conda environment; see
[agent setup](docs/MCP_AGENTS.md). Docker images install the same Python package
independently and do not require the host Conda environment.

## Add a source and paper

Register identities you have reviewed, recording the authority/reference. For
example, after verifying the alias relationship from your reference material:

```bash
xrb-source 'MAXI J1820+070' --alias 'ASASSN-18ey' \
  --authority 'user-reviewed reference: replace with your citation'
```

Put a lawfully accessible PDF in `data/inbox/`, together with an optional JSON
sidecar with the same basename, such as `paper.pdf` and `paper.json`:

```json
{
  "title": "Replace with the paper title",
  "authors": ["Replace with author names"],
  "publication_year": 2018,
  "sources": ["MAXI J1820+070"],
  "collections": ["MeerKAT_XRB"]
}
```

Optional metadata fields: `journal`, `doi`, `arxiv_id`, `ads_bibcode`, `abstract`,
`source_url`. Supply identifiers from the actual paper, not placeholders. Unknown
JSON fields are rejected. Sources in a sidecar must already be registered; mention
detection also associates registered names found in the paper.

```bash
xrb-ingest data/inbox/paper.pdf
xrb-ingest data/inbox/paper.pdf --metadata path/to/reviewed-metadata.json
xrb-update data/inbox
xrb-validate
```

PDF metadata and filenames provide only a title fallback. Authors, year, DOI and
abstract are not guessed; ingestion reports incomplete bibliography. Review the
sidecar before first ingestion. Identical bytes are skipped, including metadata
changes to their sidecars; metadata-only editing is a later workflow. For a changed
PDF, provide its existing bibliographic identifier to update that paper. Without a
matching identifier it becomes a new record.

Updates replace only that paper's chunks and passage provenance in one transaction.
Unchanged papers retain chunk IDs and embeddings. Old original PDFs remain archived
under their SHA256 names, but historical chunk revisions are not retained yet.
Omitted reviewed source links persist across updates; an explicit `sources` list
replaces manual links. Collections are additive. A failed transaction may leave an
unreferenced archived PDF, but cannot leave a partially updated paper in the database.

## Enable semantic retrieval

The default `XRB_EMBEDDING_BACKEND=none` is **lexical-only**. It needs neither an
API key nor a model download. The response includes this mode and a warning.

```bash
python -m pip install '.[dev,embeddings]'
# Set XRB_EMBEDDING_BACKEND=sentence-transformers in .env, then:
xrb-rebuild-embeddings
```

The default model is `sentence-transformers/all-MiniLM-L6-v2`. Its first use downloads
weights. Set `XRB_EMBEDDING_REVISION` to a reviewed model commit for reproducibility;
the adapter records the resolved commit when available. Ingestion and search must
use the same model, revision and dimension. Mismatches are excluded from vector
retrieval and reported. Rebuilding embeddings preserves chunk IDs and citations.
Long passages use multiple model-sized windows and average their embeddings.

For container use, set `INSTALL_EMBEDDINGS=true` in `.env` and rebuild `mcp`.
The `EmbeddingBackend` protocol in `src/xrb_mcp/ingestion/embeddings.py` is the extension point
for other local or hosted providers. There is no fake embedding production mode.

Vector search is exact, suitable for the initial local corpus. Variable-dimension
vectors permit provider changes without a schema rewrite; add model-specific HNSW
indexes through a migration when corpus scale warrants it.

## Connect an MCP client

Use this generic stdio configuration, replacing the absolute repository path:

```json
{
  "mcpServers": {
    "xrb": {
      "command": "/absolute/path/to/conda/envs/xrb-mcp/bin/python",
      "args": ["-m", "xrb_mcp.server.main"],
      "cwd": "/absolute/path/xrb_mcp",
      "env": {
        "XRB_READ_DATABASE_URL": "postgresql+psycopg://xrb_reader:xrb_reader_dev_only@localhost:5432/xrb",
        "XRB_EMBEDDING_BACKEND": "none"
      }
    }
  }
}
```

For clients without `cwd`, the installed module still runs; provide configuration
via environment variables because `.env` is loaded relative to the working directory.
Use `docker compose -f /absolute/path/xrb_mcp/docker-compose.yml run --rm --no-deps -T mcp`
as the alternative client command after building the images and applying migrations.

Example tool arguments:

```json
{
  "query": "quenching",
  "source": "4U 1702-429",
  "wavelengths": ["radio"],
  "year_min": 2021,
  "year_max": 2021,
  "top_k": 3
}
```

Tag values use the canonical spelling in `xrb://ontology/wavelengths`,
`xrb://ontology/instruments` and `xrb://ontology/topics`. Lists use OR within a
field and AND between fields. Unknown sources raise an error instead of broadening
the search. A source filter selects associated papers and prioritizes passages
that explicitly mention that source; not every passage independently names it.
Scores are ranks, not calibrated scientific confidence. Semantic matches can be
weak; inspect the returned passage before treating it as supporting evidence.

Stable objects are exposed at `xrb://papers/{paper_id}` and
`xrb://sources/{source_id}`. Tools return metadata and evidence excerpts, never the
original PDF bytes or internal PDF paths. Extracted text is untrusted content.

For development, reinstall after changing code (`python -m pip install --no-deps .`).
Editable installs are also supported, but Python 3.14 ignores `.pth` files marked
hidden by macOS; a regular install avoids that launch issue.

## Verification

```bash
python -m pytest tests/unit -q
ruff check .
ruff format --check .
docker compose exec -T db createdb -U xrb xrb_test
XRB_TEST_DATABASE_URL=postgresql+psycopg://xrb:xrb_dev_only@localhost:5432/xrb_test \
  python -m pytest -q
```

Integration tests require a disposable database whose name ends in `_test`.
They migrate it automatically and clear test records; never point them at research
data. Without the variable those tests are explicitly skipped. Synthetic fixtures
test system behavior, not astrophysical validity or embedding quality. The optional
ML backend needs separate model-download and scientific retrieval evaluation.

## Backups and migrations

```bash
docker compose exec -T db pg_dump -U xrb -Fc xrb > xrb.dump
docker compose exec -T db createdb -U xrb xrb_restore
docker compose exec -T db pg_restore -U xrb --no-owner -d xrb_restore < xrb.dump
```

Back up `data/papers/`, sidecars, configuration and future annotations separately.
Stored PDF paths are absolute: preserve the data location on restore or perform a
reviewed path migration. Dumps may contain locally accessible paper text. Keep
them private. The reader role is initialized for database `xrb`; configure grants
explicitly when restoring under another database name.

Schema evolution uses `alembic revision --autogenerate -m 'description'`, review of
the generated migration, then `alembic upgrade head`. Never replace migrations with
runtime `create_all`. The initial migration is frozen independently of ORM code.

## Scope and next steps

PDF section detection is heuristic; multi-column layouts, equations, tables and
scans need review. OCR and GROBID are not implemented. Tags are descriptive mentions,
not detections or verified source-state classifications. The approximate token
count is recorded with its method. No measurements, predictions or synthesis are
automatically generated.

Observations/events, units and upper-limit validation, timelines, catalogue
ingestion/cross-matching, external authority lookup, automatic discovery and radio
preparation belong to subsequent phases. Collections currently support ingestion
membership and search filtering, not standalone MCP resources. See
[the implementation roadmap](docs/ROADMAP.md).

The implementation uses the official
[MCP Python SDK v1 interface](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x),
[pgvector SQLAlchemy integration](https://github.com/pgvector/pgvector-python), and
[PostgreSQL full-text support in SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#full-text-search).
The SDK dependency is bounded below v2 to keep that API consistent.
