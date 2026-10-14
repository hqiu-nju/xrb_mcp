# Portable MCP dataset

The GitHub repository contains the MCP code, migrations, documentation, synthetic
tests, and a minimal dataset: `data/dataset/xrb.sqlite3` and `data/dataset/dataset.json`.
Original papers and catalogue files are provided through a separate link or drive.
The MCP can query a compact, read-only SQLite snapshot without PostgreSQL, Docker,
or access to the original PDFs. Paper passages retain identifiers, page citations,
source associations, collection memberships, and extraction provenance. Catalogue
entries retain original rows and input provenance. This provides a retrieval backend
for an agent; it does not distribute or train a language model.

## Minimal dataset and separate originals

```text
xrb_mcp/                         # clone the repository to try the MCP
  src/                          # MCP implementation
  examples/mcp/portable.json     # portable client configuration
  data/
    dataset/                    # these two files are included in Git
      dataset.json              # format, counts, SHA256 and asset inventory
      xrb.sqlite3               # compact searchable literature and catalogue snapshot
    originals/                  # optional separate drive/link bundle; ignored by Git
      papers/                   # original PDFs, named by SHA256
        <sha256>.pdf
      catalogues/               # original FITS/HTML catalogue files
```

`dataset.json` and `xrb.sqlite3` are sufficient to run the MCP. The original papers
and catalogue files are useful for inspection and rebuilding. They are not opened
by ordinary MCP queries. The snapshot includes extracted paper text and catalogue
rows even though the original files are omitted. Its relative `archive_path`
references identify files within the separate original bundle, and optional
`archive_url` values can link to hosted originals. Opening those source files
requires the separate bundle or URL; querying the snapshot does not.

The minimal folder can also be copied to a dedicated drive. An absolute
`XRB_DATASET_DIR` can point to either location. Git permits only the two named files
in `data/dataset/`; originals, other databases, SQL dumps, model weights, credentials,
and processing caches remain excluded. Research data is excluded from Docker build
context.

## Try the MCP on another machine

From a clone of this repository, install the Python package:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

The clone already includes the minimal dataset. Verify it:

```bash
xrb-validate-dataset data/dataset
```

Alternatively, download the index from the dataset provider's actual `dataset.json`
URL. The following URL is an example to replace, not a published dataset:

```bash
xrb-download-dataset https://example.org/xrb-dataset/dataset.json --output-dir data/downloaded-dataset
```

The manifest and `xrb.sqlite3` must be hosted together with their filenames unchanged.
The downloader verifies size, SHA256, schema, and database integrity before installing
the index into a new or empty folder. It does not download originals. For a private
drive or a provider's web download page, download/copy the two-file folder directly
instead. Set `XRB_DATASET_DIR` to the absolute path of the downloaded folder.
Use a fresh destination for a new dataset version so an existing dataset remains
available while the replacement is verified.

Set these environment variables in your MCP client's server configuration:

```text
XRB_DATABASE_MODE=portable
XRB_DATASET_DIR=/absolute/path/to/xrb_mcp/data/dataset
XRB_EMBEDDING_BACKEND=none
```

Launch `python -m xrb_mcp.server.main` using the environment where the package was
installed. The templates [portable.json](../examples/mcp/portable.json) and
[portable.toml](../examples/mcp/portable.toml) contain the same settings. Use absolute
paths because clients can launch from another working directory. The same three
tools (`search_literature`, `get_paper`, `get_source`) and paper/source/ontology
resources remain available.
The `xrb://dataset` resource provides the dataset inventory, full catalogue input
metadata (including units/headers), collection definitions, and identity-link review records.

For command-line examples, put these settings in the repository's local `.env`, or
export them in the terminal. The runnable client and Ollama bridge forward them to
the MCP subprocess:

```bash
XRB_DATABASE_MODE=portable XRB_DATASET_DIR="$PWD/data/dataset" XRB_EMBEDDING_BACKEND=none \
  python examples/mcp/client.py --source 'Vela X-1' --query wind --paper ''
```

`get_paper` and search evidence include `archive_path` and, when configured at export,
`archive_url`. Catalogue-only sources can be looked up by name/alias; registered
literature sources include linked `catalogue_matches`. These links require exact
normalized name/alias agreement and an unambiguous catalogue identity. Positions
alone do not create literature-to-catalogue links. A source with only catalogue data
returns no literature matches when used as a search filter.

## Create or refresh the distribution

On the ingestion workstation, keep adding papers and rebuilding catalogues using
the existing PostgreSQL workflows. Create a new portable snapshot after those
updates. Ingestion and validation of the research PostgreSQL database still use
`XRB_DATABASE_URL` and `XRB_READ_DATABASE_URL` even when the MCP is in portable mode.

```bash
# Shared minimal index, preserving existing passage embeddings:
xrb-export-dataset --output-dir data/dataset --include-embeddings

# Optional complete bundle for a separate drive/link; never put originals in the shared folder:
xrb-export-dataset --output-dir data/full-dataset \
  --include-embeddings --include-originals
```

The exporter reads PostgreSQL in a read-only snapshot, joins bibliographic records
and passage provenance, and imports the current standalone source catalogue from
`data/processed/source_catalogue/sources.db` when it exists. Use
`--catalogue-database PATH` to select another catalogue snapshot. Embeddings are
stored as compact float32 vectors; FTS indexes are optimized and the database is
vacuumed. No local PDF paths, database credentials, model weights, processing caches,
or historical dumps belong in the dataset.

`--include-originals` copies referenced PDFs and original catalogue inputs into the
chosen output folder. Keep that complete bundle separate from `data/dataset/`.
Existing source folders are retained for the ingestion workstation. A failed build
does not replace a working exported snapshot. Update the
portable folder whenever you want ingestion changes to become available to clients.
Validate a complete bundle with `xrb-validate-dataset data/full-dataset --verify-assets`.

To link originals hosted separately, set the actual base URLs when exporting:

```bash
xrb-export-dataset --output-dir data/dataset \
  --include-embeddings \
  --papers-url https://example.org/xrb-papers/ \
  --catalogues-url https://example.org/xrb-catalogues/
```

Replace those example URLs with your own download endpoints. PDFs are referenced by
their content-hash filenames; catalogue inputs keep their original filenames. A
shared folder download link may be more useful as a human-facing link alongside the
dataset, rather than as a base URL for individually accessible files.

For semantic retrieval, install `.[embeddings]`, export with `--include-embeddings`,
and set `XRB_EMBEDDING_BACKEND=sentence-transformers` with the same model/revision as
the exported vectors. The model weights are downloaded separately by that backend.
The manifest's `embedding_models` entries give the model name, pinned revision,
dimension, and number of exported vectors to use for that configuration.
The default portable examples use SQLite full-text retrieval without model downloads.
SQLite FTS ranking and query behavior can differ from PostgreSQL. Retrieval responses
identify the backend and flag missing or incompatible embeddings.

## Share the minimal dataset and originals

Push MCP code and the two files in `data/dataset/` through the normal Git workflow;
no force-add is needed. A committed refresh lets recipients obtain the updated
snapshot with the repository. Share originals separately through the dedicated drive
or a download link, using `data/originals/` locally or leaving them on the drive.
An externally shared minimal dataset is also supported: recipients can point
`XRB_DATASET_DIR` to that folder. Keep snapshots compatible with the format version
supported by their code; the reader rejects an unsupported version.
