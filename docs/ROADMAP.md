# Initial framework boundary

The root system plan defines a multi-phase research service. This implementation
delivers a usable Phase 1 vertical slice, with the original plan left unchanged.

## Implemented foundation

- Python packaging, Docker Compose, typed settings, writer/reader separation.
- Migrated sources, aliases, papers, paper-source links, chunks, provenance and collections.
- PDF extraction, section/paragraph chunks, metadata sidecars, hash-based updates.
- Optional embedding provider with model/version/dimension tracking and an explicit rebuild command.
- Full-text and vector queries with shared filters, rank fusion and cited evidence bundles.
- Three core tools and source/paper/ontology resources over local MCP stdio.
- Unit and PostgreSQL integration tests, including the MCP wire protocol.

## Remaining Phase 1 acceptance work

- Review and ingest a licensed 20–50 paper scientific corpus, then evaluate at 100+ papers.
- Verify real alias authorities and establish query relevance/citation benchmarks.
- Evaluate embeddings on astronomy language; tune chunking, tags and ranking using evidence.
- Add metadata-only corrections and durable document/chunk revision history.
- Add metadata discovery and richer parsing only after measuring extraction errors.
- Evaluate ANN indexing, batch throughput and restore procedures at corpus scale.
- Consider database-enforced provenance consistency and stricter operator grants as
  additional writers are introduced. Today the ingestion service and validator enforce
  passage/paper/page consistency; all MCP transactions are read-only.

## Phase 2 extension points

Add observations and events through migrations, with separate measurement errors,
extraction confidence, units, time scales, original values and mandatory evidence.
Implement reusable services before registering `search_observations`, `source_timeline`
or catalogue tools. Never return fabricated placeholder records from unimplemented tools.

Extend `src/xrb_mcp/astronomy/` for coordinate-aware candidate matching and external authorities.
Ambiguous candidates must not be automatically merged. Catalogue records need version,
row identifier, licensing and provenance before they can become research evidence.

## Phase 3 extension points

Comparisons and radio observing preparation should consume structured, cited
measurements. Model expectations and generated synthesis must remain distinguishable
from measured values. Remote HTTP requires authentication and a separate deployment review.
