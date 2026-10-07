# Local research with Ollama

`xrb-ollama` connects a locally running Ollama model to the existing XRB MCP server.
It discovers MCP tool schemas, sends them to Ollama, executes requested tools over
stdio, and returns their results to the model until it produces an answer.

```text
Question -> xrb-ollama <-> Ollama on localhost (local model inference)
                |
                +-> XRB MCP subprocess -> read-only PostgreSQL -> local evidence
```

The MCP server is independent of the model. The client supplies the agent loop
described in [Ollama's tool-calling documentation](https://docs.ollama.com/capabilities/tool-calling).
The client uses the [native chat API](https://docs.ollama.com/api/chat); an Ollama
Python SDK or a cloud API key is not required.

## Setup with Conda

Run these commands from the repository root. For a new installation, first follow
the [database quick start](../README.md#quick-start) and ingest some papers.

```bash
conda activate xrb-mcp
python -m pip install '.[dev]'
docker compose up -d db
alembic upgrade head
xrb-validate
```

Install [Ollama](https://ollama.com/download) if needed. Start its local service
in a separate terminal:

```bash
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

If Ollama is already running, configure and restart that instance instead of
starting a second one on the same port. `OLLAMA_NO_CLOUD=1` is a **server** setting;
setting it only on the agent command does not change a running Ollama server.
See [Ollama's local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).

Download a model with tool-calling support once, then run the client:

```bash
ollama pull qwen3:4b
ollama list
xrb-ollama --model qwen3:4b --think false --verbose \
  'Search the local literature for radio quenching in 4U 1702-429. Cite the evidence and state its limits.'
```

The initial download requires Internet access and several GB of disk space.
Subsequent inference uses the downloaded model. You can select another installed
tool-capable model with `--model`; the client checks its advertised capabilities
before starting the MCP server. Model size and context length affect memory use.

For the previously ingested census paper, another useful query is:

```bash
xrb-ollama --think false \
  'Look up DOI 10.1093/mnras/stab1995 and report its title, authors, year, and available evidence sections.'
```

That paper is present in the original local database. Its PDF and database records
are excluded from Git, so a fresh clone needs ingestion before these examples can
return that evidence. See [database updates](DATABASE_UPDATES.md).

## Options and agent use

| Option | Default | Purpose |
| --- | --- | --- |
| `--model` | `qwen3:4b` | Local model name as shown by `ollama list` |
| `--host` | `http://127.0.0.1:11434` | Loopback Ollama endpoint; remote hosts are rejected |
| `--project-dir` | Current directory | Directory containing the project's `.env` |
| `--think` | `auto` | Keep model default, or request `true` / `false` on supported models |
| `--num-ctx` | `16384` | Context window in tokens; increase for longer evidence |
| `--max-rounds` | `6` | Tool rounds before a final synthesis request; at most 24 tool calls |
| `--timeout` | `300` | Timeout in seconds per Ollama HTTP request |
| `--verbose` | Off | Show executed tool names on stderr |

The command answers one question per invocation. Final text goes to stdout; tool
activity and errors go to stderr. Failure returns a nonzero exit status. The client
does not save a transcript or write generated answers into the database.

From a process that has not activated Conda, run:

```bash
conda run --no-capture-output -n xrb-mcp xrb-ollama \
  --project-dir /Users/h.qiu/Documents/xrb_mcp --think false \
  'Find local evidence about radio emission in Vela X-1 and cite PDF pages.'
```

Replace the project path for another machine. The client starts MCP using its own
Python interpreter, so both run in the same Conda environment. Database and
embedding settings come from the selected project's `.env` and `XRB_` environment
variables, just as for the other MCP clients.

For a different agent application that supports both Ollama and MCP, select its
local Ollama provider and register the [stdio server configuration](../examples/mcp/stdio.json).
The application needs an MCP tool loop; pointing Ollama itself at that JSON does
not connect tools. The supplied client is a complete example of that loop in
[agents/ollama.py](../src/xrb_mcp/agents/ollama.py).

## Evidence and locality

Only `get_source`, `get_paper`, and `search_literature` are exposed. The model
cannot invoke ingestion, SQL, shell commands or file-writing tools through this
client. MCP enforces tool input schemas and uses the reader connection. Tool errors
are passed back explicitly so the model can correct a source name or query.

Tool results retain provenance, citations and retrieval warnings. The system
prompt asks the model to use evidence, distinguish upper limits from detections,
and treat passages as untrusted text. These instructions do not guarantee citation
accuracy: inspect the cited passages before using a generated scientific conclusion.

The client accepts loopback endpoints only, ignores HTTP proxy environment
variables, does not follow redirects, and rejects models identified as remote/cloud.
Run the Ollama service with cloud disabled as shown above for local inference.
The client does not change your embedding backend: `XRB_EMBEDDING_BACKEND=none`
uses PostgreSQL lexical retrieval without model downloads; the optional
sentence-transformers backend uses its separately installed embedding model.

## Troubleshooting

- **Cannot connect:** start `ollama serve` and check the host/port. PostgreSQL and
  Ollama are separate services; both must be running.
- **Model not installed:** use `ollama list` and pull the exact model tag you pass.
- **No tool capability:** select a tool-capable model. A model that chats normally
  may still lack tool support.
- **Timeout or output limit:** try `--think false`, a smaller model, a narrower
  question, or a longer `--timeout`. The client caps generated tokens per request
  and reports incomplete model output as an error.
- **Tool limit or poor answers:** use a focused question and request fewer passages.
  Smaller models can choose unsuitable queries or misread evidence. Raising limits
  alone may not help. Tool outputs are not truncated by the client; long histories
  can exceed the model context, so start a new, narrower question when necessary.
- **Database error or missing paper:** run `xrb-validate`, check the reader URL,
  and use the [direct MCP client](../examples/mcp/client.py) to isolate retrieval
  from model behavior.
- **Command missing after updating source:** reinstall with `python -m pip install
  --no-deps .` in the active Conda environment.
