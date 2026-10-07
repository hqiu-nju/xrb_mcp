# Updating the XRB database

Use the operator CLI to add or update literature. Agents query the same database
through read-only MCP tools; ingestion is not an MCP tool.

This guide describes the implemented Phase 1 behavior. For agent setup, see
[MCP and agents](MCP_AGENTS.md). Commands below use the existing workstation path;
replace it if you move the repository.

## Start an operator session

```bash
cd /Users/h.qiu/Documents/xrb_mcp
conda activate xrb-mcp
docker compose up -d db
docker compose ps
alembic upgrade head
xrb-validate
```

Docker must be running. `alembic upgrade head` applies pending schema migrations;
it does not ingest papers. Repeating it at the current revision is harmless.
`xrb-validate` checks archived PDF hashes, chunks and passage provenance, not the
scientific correctness of extracted text.

On a fresh installation, run `conda env create -f environment.yml` from the
repository root, then activate `xrb-mcp`. See [README setup](../README.md#quick-start).
Create `.env` from `.env.example` only if you do not already have one. Preserve
existing credentials when updating an established database. Settings are read from
the current directory's `.env`, with environment variables taking precedence.

| Setting | Purpose |
| --- | --- |
| `XRB_DATABASE_URL` | Writer connection for ingestion, embeddings and migrations |
| `XRB_READ_DATABASE_URL` | Reader connection for MCP queries and validation |
| `XRB_DATA_DIR` | Archive/inbox root; defaults to `./data` |
| `XRB_EMBEDDING_BACKEND` | `none` or `sentence-transformers` |
| `XRB_EMBEDDING_MODEL`, `XRB_EMBEDDING_REVISION` | Model identity used by ingestion and search |
| `XRB_CHUNK_MAX_WORDS` | Paragraph packing limit; defaults to 350 words |

Default example credentials are for the local development instance. Changing a
password in `.env` does not change the password of an existing PostgreSQL role.
In a connection URL, percent-encode reserved characters in passwords.

## Add a new paper

### 1. Place the PDF and metadata together

Use the same basename:

```text
data/inbox/my_paper.pdf
data/inbox/my_paper.json
```

Example sidecar structure; replace the bibliographic values with the actual paper:

```json
{
  "title": "Actual paper title",
  "authors": ["A. Author", "B. Author"],
  "publication_year": 2021,
  "journal": "Actual journal name",
  "sources": ["Vela X-1"],
  "collections": ["my_research_collection"]
}
```

Add the real `doi`, `arxiv_id`, `ads_bibcode`, `abstract`, and `source_url` when
available. Omit unknown fields rather than supplying invented identifiers. DOI URL
prefixes/case and arXiv version suffixes are normalized for identity matching.
The source URL can still identify the particular arXiv version of your PDF.

The JSON sidecar is optional, but recommended: the parser only supplies a title
fallback from PDF metadata or filename. It does not infer authors, year or DOI.
Only the documented fields are accepted; extra JSON keys fail validation.

### 2. Register any new source names

Every name in the sidecar's `sources` list must already be registered. Use an
actual reference as the authority. For example, this identity is supported by the
census paper's Table 2, PDF page 10:

```bash
xrb-source 'Vela X-1' \
  --authority 'van den Eijnden et al. (2021), DOI 10.1093/mnras/stab1995, Table 2, PDF page 10'
```

For another source, substitute its reviewed name and reference. Add aliases with
repeated `--alias 'name'` arguments only when the relationship is established.
The command adds missing aliases to an existing source; it does not overwrite an
existing source's class or compact-object type. Conflicting aliases are rejected.

Case and whitespace variants resolve automatically. Other punctuation and source
name variations may need an explicit alias. Mention detection also associates
registered names found in the PDF, but manual sidecar links are useful when text
extraction breaks a name across lines. Registering names later does not backfill
already-ingested paper links or chunk tags.

### 3. Ingest and validate

```bash
xrb-ingest data/inbox/my_paper.pdf
xrb-validate
```

For a PDF outside the inbox, pass its sidecar explicitly:

```bash
xrb-ingest '/absolute/path/to/my_paper.pdf' \
  --metadata data/inbox/my_paper.json
```

The original input is unchanged. A byte-identical copy is archived at
`data/papers/<sha256>.pdf`; the database stores metadata, source links, chunks,
tags and provenance. Page numbers refer to PDF pages starting at 1.

Ingestion prints JSON with `status`, `paper_id`, chunk/page counts, embedding status
and warnings. A complete metadata sidecar avoids missing-bibliography warnings;
it does not establish that the extracted passages were manually verified.

## Update a directory incrementally

```bash
xrb-update data/inbox
```

With no argument, `xrb-update` uses `XRB_DATA_DIR/inbox`. It scans that directory
once, non-recursively, and processes:

- PDFs with either lowercase or uppercase suffixes, using same-basename `.json` sidecars.
- Catalogue files in FITS (`.fits`, `.fit`, `.fts`) and ASCII/CSV (`.csv`, `.tsv`, `.txt`,
  `.dat`, `.ascii`, `.ecsv`, `.tab`) formats.

Files remain in the inbox.

One JSON record is printed per processed file. Each paper has its own transaction,
so an invalid file does not discard its successfully ingested neighbours. Catalogue
records are parse-only summaries (`status: catalogue_read`) with format, row count,
and column count; they are not written into database catalogue tables in Phase 1.
The command returns exit code 1 if any file fails; failure records include the
exception type. Run `xrb-ingest` on a failed PDF for a more detailed local diagnostic.

There is no background watcher or automatic literature discovery. Run the command
again after adding files, or invoke it from a scheduler you manage. Start with one
ingestion worker; database writes are serialized by the current implementation.

## What an update does

| Input/change | Current behavior | Operator action |
| --- | --- | --- |
| Same PDF bytes | `skipped`, reason `unchanged_sha256` | Nothing is re-parsed or re-embedded |
| Different PDF, matching DOI/arXiv/bibcode | `updated`; same paper ID, replacement chunks | Supply the existing identifier in the sidecar |
| Different PDF, no matching identifier | New paper | Review metadata to avoid accidental duplicates |
| Identifiers point to different records | Rejected | Review the bibliography; records are not merged |
| Sidecar edits only, same PDF | Skipped; edits are not applied | Metadata-only correction needs a separate reviewed implementation |
| Parser, tags or chunk size changed, same PDF | Skipped | Full-text reprocessing/force-ingest is not implemented |
| Embedding backend/model changed | Old vectors are incompatible or absent | Use the explicit embedding rebuild command |

When replacing a changed PDF, use its current title/authors/year along with its
existing identifier. Omitted bibliographic fields retain old values; null values
do not clear them. An omitted `sources` field preserves prior manual links. An
explicit list replaces manual links, while current detected mentions are still
associated. Collections are additive, not replaced or removed.

Changed-document updates replace that paper's chunks and passage provenance
atomically. Other papers are unaffected. Old PDFs remain in the archive, but old
chunk IDs are no longer valid: retrieve evidence again after a document revision.
Embedding-only rebuilds preserve chunk IDs. There is currently no delete, merge,
metadata-edit or `--force` operator command. Do not modify PDF bytes just to defeat
duplicate detection.

## Reuse the stored example

The local example is *A new radio census of neutron star X-ray binaries*:

| Identifier | Value |
| --- | --- |
| DOI | `10.1093/mnras/stab1995` |
| arXiv ID | `2107.05286` |
| Local paper ID | `22f8e308-5011-44bd-9bf4-b8a15e459e89` |
| Verified import | 31 pages, 116 chunks, 36 source links |
| Retrieval mode at import | Lexical-only |

The counts and internal ID describe this database's recorded import, not a fixed
result for every future parser version. The local files are:

- [Metadata sidecar](../data/inbox/van_den_eijnden_2021_radio_census.json)
- [Source-name manifest](../data/processed/van_den_eijnden_2021_source_manifest.json)
- [Ingestion and query report](../data/processed/van_den_eijnden_2021_ingestion_report.json)

These private data files are ignored by Git and will not exist in a clean checkout.
The original PDF is outside the inbox, so the directory update command does not
automatically revisit it. To verify an unchanged-file skip on this workstation:

```bash
xrb-ingest '/Users/h.qiu/Documents/papers/vastxrbs/radio census van den eijnden 2021.pdf' \
  --metadata data/inbox/van_den_eijnden_2021_radio_census.json
```

Expected result: `status: skipped` with the paper ID above. Its 36 linked names
were transcribed from Tables 1–2; source classes, physical properties and external
counterparts were not inferred. Table text has not been converted into verified
structured measurements.

## Enable or rebuild embeddings

```bash
python -m pip install '.[dev,embeddings]'
```

Set `XRB_EMBEDDING_BACKEND=sentence-transformers` in `.env`. Choose the same
`XRB_EMBEDDING_MODEL` and `XRB_EMBEDDING_REVISION` for the operator and every MCP
client. A pinned model commit is preferable for reproducibility. Downloading model
weights happens on first use; no hosted embedding API is configured.

```bash
# Only the stored census paper:
xrb-rebuild-embeddings --paper-id 22f8e308-5011-44bd-9bf4-b8a15e459e89

# Or every paper in the database:
xrb-rebuild-embeddings
xrb-validate
```

Rebuild is explicit and recomputes the selected papers even if their embeddings
already match. Updates are atomic per paper. It does not re-extract PDF text,
repair metadata, or change citations. An unchanged PDF remains skipped by normal
ingestion even after enabling embeddings.

Update agent environment settings too, then restart their MCP processes. Existing
processes cache settings and the embedding backend. A client environment entry
setting the backend to `none` overrides `.env`. Check the search response's `mode`,
`warnings` and per-result `retrieval_channels`; `mode: hybrid` alone does not prove
every chunk has a compatible vector. Initial example verification used lexical
search; scientific embedding quality remains to be evaluated.

## Update application code or schema

If the Conda specification changed, run `conda env update -f environment.yml`
from the repository root. Activate `xrb-mcp` before installing the current code:

```bash
conda activate xrb-mcp
python -m pip install --no-deps .
alembic upgrade head
xrb-validate
```

Use `python -m pip install '.[dev]'` instead if dependency requirements changed. Restart
agent MCP processes to load new Python code. If agents use the Docker launch
option, rebuild `mcp`; restart those clients after the build. Container migrations
can be run with `docker compose build migrate` and `docker compose run --rm migrate`.
Schema changes require reviewed Alembic migrations; installing code alone does not
alter the schema or reprocess existing papers.

## Back up and restore

Pause ingestion/rebuild jobs while taking a coordinated backup of database and
files. MCP reads can continue. From the repository root:

```bash
backup_dir="backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
docker compose exec -T db pg_dump -U xrb -Fc xrb > "$backup_dir/xrb.dump"
tar -czf "$backup_dir/data.tar.gz" data
```

Keep configuration/credentials in a separate protected backup. `data` includes
archived PDFs, available metadata sidecars and import reports. Check both commands'
exit status and retain the matching code/schema version. Copy the backup to your
normal backup destination; a copy on the same disk does not cover disk loss.

To test a dump, restore into a new database name that does not already exist:

```bash
docker compose exec -T db createdb -U xrb xrb_restore
docker compose exec -T db pg_restore -U xrb --no-owner -d xrb_restore \
  < backups/YOUR_BACKUP_DIRECTORY/xrb.dump
```

This does not switch any agent to the restored database. To validate that copy,
use a matching reader connection and data files. The original reader role is
configured for `xrb`; provision its grants for the restored database as needed.
Stored PDF paths are absolute, so preserve their original host location or perform
a reviewed path migration. A Docker query server can read paper metadata/passages
without the host path, but PDF hash validation must run where those paths exist.

`docker compose stop db` stops PostgreSQL while preserving its volume. Avoid
`docker compose down -v` on the research instance: it removes the database volume.

## Troubleshooting

| Symptom | Check/action |
| --- | --- |
| Connection refused | Start Docker, then `docker compose up -d db`; inspect `docker compose ps` |
| Authentication failure | Check URL credentials against the existing database roles |
| Schema not ready | Run `alembic upgrade head` using the writer connection |
| Unknown source | Register the reviewed identity or correct the sidecar name |
| Unexpected skip after editing JSON | Same-byte PDFs are skipped before metadata updates |
| Empty batch output | Directory has no immediate PDF children; sidecars alone are not inputs |
| No extractable text | OCR is not implemented; use a reviewed text-bearing PDF |
| Incorrect sections/equations/table text | Inspect the original pages; do not treat heuristics as verified measurements |
| Embeddings unavailable | Install the optional dependency, select a backend, and rebuild |
| `conda activate` is unavailable | Initialize Conda for your shell, or use `conda run --no-capture-output -n xrb-mcp` before a command |
| Installed CLI cannot import the project | Use a regular install; Python 3.14 may skip a macOS-hidden editable `.pth` file |
| Archived PDF missing/corrupt | Restore the matching archive and verify its SHA256; do not alter database hashes to hide damage |

For retrieval-specific problems and citation handling, continue with
[MCP and agents](MCP_AGENTS.md).
