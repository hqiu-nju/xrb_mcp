# X-ray Binary Multiwavelength MCP Research System — Project Plan

## 1. Project Summary

Build a continuously updateable scientific knowledge system for X-ray binary (XRB) research, exposed through a Model Context Protocol (MCP) server. The system is optimized for radio astronomy preparation while retaining full-spectrum context across radio, infrared, optical, ultraviolet, X-ray, and gamma-ray observations.

The system will combine structured astrophysical entities, literature retrieval, catalogue cross-matching, observation timelines, and provenance-aware scientific search. It is intended to function as a research assistant rather than a generic “chat with PDFs” system.

---

## 2. Primary Goals

1. Ingest and search a growing local database of XRB papers and catalogues.
2. Preserve source identity across canonical names and aliases.
3. Retrieve evidence using hybrid semantic, keyword, and metadata search.
4. Represent observations, source states, and astrophysical events as structured data rather than only free text.
5. Provide full-spectrum context for radio observing preparation.
6. Preserve traceable provenance for every paper-derived or catalogue-derived fact.
7. Support incremental updates without rebuilding the complete index.
8. Expose all important capabilities through MCP tools and resources.
9. Remain model-agnostic so the database can be used from multiple MCP-compatible AI clients.

---

## 3. Non-Goals for the Initial Version

The MVP will not attempt to:

- autonomously produce publication-grade scientific conclusions without source verification;
- replace ADS, SIMBAD, VizieR, HEASARC, or observatory archives;
- perform full raw-data calibration or imaging;
- automatically reproduce every table or figure from papers;
- create a universal ontology for all high-energy astrophysics;
- fully automate scientific judgement about state classification or physical interpretation.

These can be added later where useful.

---

## 4. Core Research Use Cases

### 4.1 Literature Search

Example queries:

- “Find radio observations of black-hole XRBs during hard-to-soft transitions.”
- “What evidence exists for jet quenching during the soft state?”
- “Find MeerKAT observations of MAXI J1820+070.”
- “What multiwavelength observations accompanied the 2018 radio ejecta?”

### 4.2 Source Research

- Resolve aliases such as ASASSN-18ey → MAXI J1820+070.
- Retrieve source properties and known measurements.
- Retrieve all papers, observations, and catalogue entries associated with a source.

### 4.3 Observation Timeline

- Construct a chronological timeline of an outburst.
- Align radio flares, X-ray states, optical changes, ejecta, and other events.
- Search within time windows around state transitions.

### 4.4 Radio Observation Preparation

For a target and observing setup, summarize:

- prior radio detections and upper limits;
- typical flux density range;
- radio spectral indices;
- polarization information;
- variability timescales;
- known jet behaviour;
- X-ray state dependence;
- multiwavelength triggers and diagnostics;
- previous comparable observations;
- relevant papers and uncertainties.

### 4.5 Catalogue Cross-Matching

- Search radio, optical, X-ray, and gamma-ray catalogues around a target position.
- Resolve source counterparts.
- Compare historical catalogue measurements.

### 4.6 Comparative Science

- Compare radio behaviour across XRB systems.
- Search for analogous outbursts.
- Compare black-hole and neutron-star systems under equivalent states.

---

## 5. Recommended Architecture

```text
MCP Client
(ChatGPT / Claude / IDE / Research Tool)
        |
        v
XRB MCP Server
        |
        +------------------------------+
        |                              |
        v                              v
Research API / Query Layer        Ingestion Layer
        |                              |
        v                              v
PostgreSQL + pgvector          Papers / Catalogues / Metadata
        |
        +-- Papers
        +-- Sources + Aliases
        +-- Observations
        +-- Events
        +-- Catalogue Entries
        +-- Chunks + Embeddings
        +-- Collections
        +-- Provenance
```

The MCP server should remain thin. Core scientific logic should live in reusable Python modules so the same backend can later support a web interface, notebooks, batch analysis, or API endpoints.

---

## 6. Recommended Technology Stack

### Language

- Python 3.11+

### MCP

- Official Python MCP SDK

### Database

- PostgreSQL
- pgvector

### Astronomy

- Astropy
- astroquery
- pandas
- numpy

### PDF / Literature Processing

Initial:

- PyMuPDF
- structured section heuristics

Optional later:

- GROBID for higher-quality scholarly parsing

### Retrieval

- PostgreSQL metadata filters
- PostgreSQL full-text search
- pgvector semantic similarity
- optional reranking layer

### Embeddings

Pluggable embedding backend. Keep embedding provider isolated behind an interface so the system can switch between:

- local sentence-transformer models;
- hosted embedding APIs;
- astronomy-specific embedding models if useful later.

### Infrastructure

Initial deployment:

- Docker Compose
- PostgreSQL container
- Python MCP server
- local data directory

Later:

- managed PostgreSQL
- object storage
- hosted Streamable HTTP MCP server

---

## 7. Repository Structure

```text
xrb-mcp/
|
+-- README.md
+-- pyproject.toml
+-- docker-compose.yml
+-- .env.example
|
+-- server/
|   +-- main.py
|   +-- tools/
|   |   +-- literature.py
|   |   +-- sources.py
|   |   +-- observations.py
|   |   +-- timelines.py
|   |   +-- catalogues.py
|   |   +-- observing.py
|   +-- resources/
|
+-- database/
|   +-- models.py
|   +-- connection.py
|   +-- migrations/
|   +-- queries/
|
+-- ingestion/
|   +-- papers.py
|   +-- pdf_parser.py
|   +-- metadata.py
|   +-- chunking.py
|   +-- tagging.py
|   +-- entity_extraction.py
|   +-- embeddings.py
|   +-- catalogues.py
|   +-- incremental.py
|
+-- astronomy/
|   +-- source_resolver.py
|   +-- aliases.py
|   +-- wavelengths.py
|   +-- instruments.py
|   +-- source_states.py
|   +-- coordinates.py
|   +-- crossmatch.py
|
+-- retrieval/
|   +-- hybrid_search.py
|   +-- ranking.py
|   +-- filters.py
|
+-- provenance/
|   +-- citations.py
|   +-- evidence.py
|
+-- data/
|   +-- inbox/
|   +-- papers/
|   +-- catalogues/
|   +-- processed/
|
+-- tests/
|   +-- unit/
|   +-- integration/
|   +-- scientific/
|
+-- scripts/
    +-- ingest.py
    +-- update.py
    +-- rebuild_embeddings.py
    +-- validate_database.py
```

---

## 8. Data Model

### 8.1 `sources`

Core object record.

Fields:

- `id`
- `canonical_name`
- `source_class`
- `compact_object_type`
- `ra_deg`
- `dec_deg`
- `distance_kpc`
- `distance_error`
- `orbital_period`
- `inclination`
- `mass_compact_object`
- `discovery_date`
- `notes`
- `created_at`
- `updated_at`

### 8.2 `source_aliases`

Fields:

- `id`
- `source_id`
- `alias`
- `alias_type`
- `authority`

Aliases must be indexed case-insensitively.

### 8.3 `papers`

Fields:

- `id`
- `title`
- `authors`
- `publication_year`
- `journal`
- `doi`
- `arxiv_id`
- `ads_bibcode`
- `abstract`
- `pdf_path`
- `source_url`
- `content_hash`
- `ingested_at`
- `updated_at`

### 8.4 `paper_sources`

Many-to-many association between papers and astrophysical sources.

Fields:

- `paper_id`
- `source_id`
- `relationship_type`
- `confidence`

### 8.5 `paper_chunks`

Fields:

- `id`
- `paper_id`
- `section`
- `subsection`
- `page_start`
- `page_end`
- `text`
- `embedding`
- `token_count`
- `chunk_index`

Additional tags:

- source IDs
- wavelengths
- instruments
- science topics

### 8.6 `observations`

Fields:

- `id`
- `source_id`
- `paper_id`
- `facility`
- `instrument`
- `start_time`
- `end_time`
- `mjd_start`
- `mjd_end`
- `wavelength_domain`
- `frequency_min_hz`
- `frequency_max_hz`
- `energy_min_kev`
- `energy_max_kev`
- `measurement_type`
- `flux_value`
- `flux_error`
- `flux_unit`
- `spectral_index`
- `spectral_index_error`
- `polarization_fraction`
- `detection_status`
- `source_state`
- `notes`

Each extracted measurement must retain provenance.

### 8.7 `events`

Fields:

- `id`
- `source_id`
- `paper_id`
- `event_time`
- `event_time_uncertainty`
- `event_type`
- `source_state_before`
- `source_state_after`
- `description`
- `confidence`

Initial event vocabulary:

- outburst_start
- outburst_peak
- hard_state
- hard_intermediate_state
- soft_intermediate_state
- soft_state
- hard_state_return
- radio_flare
- jet_ejection
- jet_quenching
- xray_flare
- optical_flare

### 8.8 `catalogues`

Fields:

- `id`
- `name`
- `version`
- `description`
- `reference`
- `download_date`
- `content_hash`

### 8.9 `catalogue_entries`

Use a general schema plus catalogue-specific JSON metadata.

Fields:

- `id`
- `catalogue_id`
- `external_id`
- `ra_deg`
- `dec_deg`
- `position_error_arcsec`
- `source_id` nullable
- `measurements_json`
- `metadata_json`

### 8.10 `collections`

Examples:

- BHXRB_core
- NSXRB_core
- radio_xray_correlation
- jet_physics
- state_transitions
- transient_ejecta
- polarization
- MeerKAT_XRB
- SKA_XRB

### 8.11 `provenance`

Every extracted scientific value should point to evidence.

Fields:

- `id`
- `entity_type`
- `entity_id`
- `paper_id`
- `chunk_id`
- `page`
- `section`
- `quote_start`
- `quote_end`
- `extraction_method`
- `confidence`
- `verified_by_user`

---

## 9. Astronomy Ontology

### 9.1 Wavelength Domain

```text
radio
  low_frequency
  L_band
  S_band
  C_band
  X_band
  Ku_band
  K_band
  mm
  submm

infrared
  NIR
  MIR
  FIR

optical
ultraviolet
xray
  soft_xray
  hard_xray
gamma_ray
```

Numerical frequency/energy ranges should be stored whenever possible. Tags are descriptive, not substitutes for physical values.

### 9.2 Measurement Type

- continuum
- spectral_line
- imaging
- spectroscopy
- photometry
- timing
- polarimetry
- astrometry

### 9.3 Physical Component

- compact_jet
- transient_ejecta
- accretion_disk
- corona
- companion_star
- accretion_stream
- disk_wind
- stellar_wind
- jet_shock
- nebula

### 9.4 Science Topics

Initial controlled vocabulary:

- accretion_state
- state_transition
- jet_launching
- jet_quenching
- radio_xray_correlation
- transient_ejecta
- synchrotron_emission
- jet_spectral_break
- polarization
- variability
- orbital_modulation
- timing
- quasi_periodic_oscillation
- disk_jet_coupling
- mass_transfer
- winds
- distance
- proper_motion

Vocabulary must remain extensible.

---

## 10. Source Identity Resolution

Source resolution is a core subsystem.

Resolution order:

1. exact canonical name match;
2. exact alias match;
3. normalized alias match;
4. external authority identifier match;
5. coordinate match within configurable tolerance;
6. fuzzy text match only as a candidate generator;
7. unresolved cases flagged for review.

Never automatically merge two astrophysical sources based only on semantic similarity.

The resolver should eventually integrate trusted external identifiers from services such as SIMBAD, where legally and operationally appropriate.

---

## 11. Paper Ingestion Pipeline

```text
PDF enters data/inbox
    |
    v
Calculate SHA256
    |
    +-- already ingested -> skip
    |
    v
Extract metadata
    |
    v
Extract structured text
    |
    v
Detect sections/subsections/pages
    |
    v
Resolve source names and aliases
    |
    v
Tag wavelengths / instruments / science topics
    |
    v
Create structure-aware chunks
    |
    v
Generate embeddings
    |
    v
Store chunks + metadata + provenance
    |
    v
Optional extraction of observations/events
    |
    v
Validation report
```

### Chunking Rules

Avoid fixed-length chunking alone.

Prefer:

1. section boundaries;
2. subsection boundaries;
3. paragraph boundaries;
4. maximum token size only as final constraint.

Each chunk must retain:

- paper ID;
- title;
- section;
- page range;
- source IDs;
- instruments;
- wavelength tags;
- science-topic tags.

---

## 12. Incremental Update Strategy

### Papers

Use content hashes and identifiers.

On ingestion:

- same hash → skip;
- same DOI/arXiv/bibcode but changed file → update document and affected chunks;
- new paper → full ingestion.

Do not rebuild embeddings for unchanged papers.

### Catalogues

Store catalogue version and file hash.

Support:

- replace catalogue version;
- compare versions;
- append new rows where appropriate;
- preserve previous catalogue provenance where required.

### Automated Discovery Later

Possible scheduled sources:

- ADS query feeds;
- arXiv searches;
- observatory publication feeds;
- catalogue releases.

Automatic discovery should initially ingest metadata only. Full-text ingestion must respect publication access rights.

---

## 13. Retrieval Architecture

Use hybrid search rather than pure vector retrieval.

### Query Pipeline

```text
User query
   |
   v
Query interpretation
   |
   +-- source resolution
   +-- wavelength filters
   +-- instrument filters
   +-- date filters
   +-- source-class filters
   +-- topic filters
   |
   v
Parallel retrieval
   |
   +-- PostgreSQL full-text search
   +-- pgvector similarity search
   +-- structured metadata query
   |
   v
Score fusion
   |
   v
Optional reranker
   |
   v
Evidence bundle with provenance
```

Ranking should prioritize:

1. exact source matches;
2. exact metadata matches;
3. scientifically relevant sections;
4. lexical relevance;
5. semantic relevance;
6. recency only where scientifically appropriate.

---

## 14. MCP Interface

### MVP Tools

#### `search_literature`

Inputs:

- query
- source optional
- source_class optional
- wavelengths optional
- instruments optional
- topics optional
- year_min optional
- year_max optional
- collection optional
- top_k

Returns ranked evidence passages plus paper metadata and citations.

#### `get_paper`

Inputs:

- DOI, ADS bibcode, arXiv ID, internal paper ID, or title

Returns:

- metadata;
- abstract;
- sections;
- associated sources;
- instruments;
- wavelength tags;
- evidence references.

#### `get_source`

Inputs:

- source name or alias

Returns canonical source information and aliases.

#### `source_literature`

Inputs:

- source
- optional filters

Returns all relevant papers ranked by relevance.

#### `search_observations`

Inputs:

- source
- wavelength
- instrument
- frequency/energy range
- MJD/date range
- source state
- detection status

Returns structured observations with provenance.

#### `source_timeline`

Inputs:

- source
- date range or outburst year
- event types optional

Returns chronological multiwavelength events and observations.

#### `catalogue_search`

Inputs:

- catalogue
- sky position or source
- search radius
- filters

Returns catalogue matches.

#### `crossmatch_source`

Inputs:

- source
- catalogues
- radius

Returns likely counterparts with separations and catalogue metadata.

### Phase 2 Tool

#### `compare_sources`

Compare selected properties, states, observations, and literature across multiple XRBs.

### Phase 3 Tool

#### `prepare_radio_observation`

Inputs:

- source
- telescope
- observing frequency/band
- current or expected source state
- requested observing date/window optional

Returns:

- historical radio behaviour;
- likely flux range;
- spectral behaviour;
- polarization history;
- variability timescale;
- relevant state-dependent behaviour;
- multiwavelength indicators;
- comparable previous epochs;
- uncertainties;
- citations.

This tool must explicitly distinguish measured values from model-based expectations or LLM synthesis.

---

## 15. MCP Resources

Useful read-only MCP resources may include:

- `xrb://sources/{source_id}`
- `xrb://papers/{paper_id}`
- `xrb://collections/{collection}`
- `xrb://catalogues/{catalogue}`
- `xrb://ontology/wavelengths`
- `xrb://ontology/instruments`
- `xrb://ontology/topics`

Tools should be used for search, filtering, calculations, or cross-matching. Resources should expose stable objects.

---

## 16. Provenance and Citation Requirements

No scientific claim should be returned as database-derived evidence without source metadata.

Minimum literature provenance:

- paper title;
- authors/year;
- DOI, bibcode, or arXiv ID where available;
- section;
- page where available;
- internal chunk ID.

Minimum catalogue provenance:

- catalogue name;
- catalogue version;
- catalogue source identifier;
- ingestion date;
- relevant row identifier.

Structured measurements must additionally identify whether they were:

- directly parsed;
- manually entered;
- model-extracted;
- transformed/calculated.

Confidence should be stored separately from measurement uncertainty.

---

## 17. Scientific Reliability Rules

The system should enforce the following principles:

1. Separate published measurements from inferred interpretations.
2. Preserve upper limits distinctly from detections.
3. Preserve units explicitly.
4. Store original reported values where possible.
5. Keep measurement errors separate from extraction confidence.
6. Do not merge inconsistent literature values automatically.
7. Prefer presenting multiple measurements and their references over silently selecting one.
8. Distinguish source-state classifications from direct observables.
9. Make temporal reference frames explicit, preferably using MJD plus UTC where available.
10. Flag ambiguous source identifications for manual review.

---

## 18. Testing Strategy

### Unit Tests

Test:

- alias normalization;
- source resolution;
- wavelength classification;
- coordinate calculations;
- chunk generation;
- hash-based incremental ingestion;
- database filters;
- citation construction.

### Integration Tests

Test complete workflows:

- ingest paper → query paper;
- ingest source aliases → resolve alternate name;
- ingest observations → create timeline;
- ingest catalogue → crossmatch source;
- update paper → only affected chunks regenerated.

### Scientific Validation Set

Create a small manually verified reference corpus containing approximately 20–50 well-known XRB papers and several representative sources.

Suggested initial targets:

- GX 339-4
- MAXI J1820+070
- V404 Cyg
- GRS 1915+105
- Cygnus X-1
- XTE J1550-564
- Aql X-1
- Sco X-1

Create benchmark questions with known answers and references.

Examples:

- Does an alias resolve correctly?
- Are all radio observations retrieved?
- Does state-transition timing match the reference literature?
- Are upper limits handled correctly?
- Are citations attached to every extracted measurement?

### Retrieval Evaluation

Measure:

- recall@k;
- precision@k;
- mean reciprocal rank;
- source-resolution accuracy;
- citation correctness;
- observation-extraction accuracy.

---

## 19. Deployment Plan

### Stage 1 — Local Research Workstation

Docker Compose:

- PostgreSQL + pgvector
- MCP server
- mounted local data directory

Transport:

- stdio for local clients;
- Streamable HTTP optionally enabled.

### Stage 2 — Private Hosted Instance

Components:

- managed PostgreSQL;
- private object storage;
- authenticated MCP endpoint;
- scheduled ingestion worker;
- automated backups.

### Stage 3 — Collaborative Research Service

Potential additions:

- user accounts;
- role-based access;
- shared collections;
- manual verification workflow;
- annotations;
- paper-reading interface;
- team-specific private datasets.

---

## 20. Security and Data Rights

### Security

- never expose database credentials through MCP responses;
- keep secrets in environment variables;
- use read-only DB roles for normal MCP queries;
- isolate ingestion permissions;
- authenticate remote MCP endpoints;
- log database mutations;
- sanitize file paths and uploaded filenames.

### Copyright / Licensing

Paper metadata and user-owned PDFs should be treated separately.

The system should:

- store PDFs only where the user has lawful access;
- avoid automatically redistributing full copyrighted PDFs;
- preserve source URLs and identifiers;
- distinguish open-access from locally accessible documents;
- verify catalogue licensing before redistribution.

---

## 21. Backup and Migration Strategy

Back up independently:

1. PostgreSQL database;
2. original PDFs;
3. catalogue source files;
4. user-entered annotations;
5. configuration and ontology files.

Embeddings do not necessarily require permanent backup if they can be regenerated, but embedding model/version must be recorded.

Schema changes must use migrations.

Every embedding row should store:

- embedding model name;
- model version where available;
- embedding dimension;
- generation timestamp.

---

## 22. Main Risks and Mitigations

### Risk: Poor PDF extraction

Mitigation:

- preserve page boundaries;
- introduce GROBID later;
- retain original PDFs;
- allow manual correction.

### Risk: Wrong source alias resolution

Mitigation:

- strict canonical resolver;
- coordinate confirmation;
- confidence score;
- manual review queue.

### Risk: Hallucinated structured measurements

Mitigation:

- every extracted measurement requires provenance;
- preserve source passage;
- separate extraction confidence from scientific uncertainty;
- allow user verification.

### Risk: Vector retrieval misses exact scientific terms

Mitigation:

- hybrid lexical + semantic + structured search.

### Risk: Database becomes schema-heavy too early

Mitigation:

- keep MVP schema focused;
- use JSONB for catalogue-specific metadata;
- migrate frequently used fields to typed columns later.

### Risk: Ontology becomes inconsistent

Mitigation:

- controlled vocabularies stored centrally;
- normalization during ingestion;
- version ontology definitions.

### Risk: Automated updates import low-quality material

Mitigation:

- separate discovered, ingested, reviewed, and trusted statuses.

---

## 23. Development Roadmap

# Phase 1 — Literature Knowledge Base / MVP

Goal: reliable paper ingestion and evidence retrieval.

Deliverables:

- repository scaffold;
- PostgreSQL + pgvector;
- `sources` and `source_aliases` tables;
- `papers` and `paper_chunks` tables;
- PDF ingestion;
- metadata extraction;
- section-aware chunking;
- embeddings;
- full-text search;
- hybrid search;
- MCP server;
- `search_literature`;
- `get_paper`;
- `get_source`;
- citations;
- incremental re-ingestion.

Acceptance test:

A user can add a new XRB paper, ingest it, and query its scientific contents with a result that points back to the correct paper section/page.

---

# Phase 2 — Astronomy Intelligence

Goal: understand astrophysical entities and observation history.

Deliverables:

- robust alias resolver;
- wavelength ontology;
- instrument ontology;
- topic tagging;
- structured observations;
- events;
- source state representation;
- timelines;
- catalogue ingestion;
- coordinate cross-matching;
- `search_observations`;
- `source_literature`;
- `source_timeline`;
- `catalogue_search`;
- `crossmatch_source`.

Acceptance test:

A user can ask for all radio observations near a state transition for a known XRB and receive structured measurements, dates, states, and citations.

---

# Phase 3 — Advanced Research Assistant

Goal: support observation planning and comparative astrophysics.

Deliverables:

- `compare_sources`;
- `prepare_radio_observation`;
- automatic literature discovery;
- richer catalogue integrations;
- observation-window context;
- comparison-object retrieval;
- extracted flux histories;
- radio/X-ray relation tools;
- SED-oriented retrieval;
- manual validation interface or workflow.

Acceptance test:

Given a target and radio observing setup, the system produces a provenance-aware observing context that synthesizes historical radio and multiwavelength evidence without presenting unsupported predictions as measurements.

---

## 24. First Two-Week Implementation Sprint

### Priority 0 — Environment

- [ ] Create Git repository.
- [ ] Create Python project with `pyproject.toml`.
- [ ] Add Docker Compose.
- [ ] Launch PostgreSQL with pgvector.
- [ ] Create `.env.example`.
- [ ] Add migration framework.

### Priority 1 — Core Schema

- [ ] Create `sources`.
- [ ] Create `source_aliases`.
- [ ] Create `papers`.
- [ ] Create `paper_sources`.
- [ ] Create `paper_chunks`.
- [ ] Create provenance fields.
- [ ] Add indexes.

### Priority 2 — Ingestion

- [ ] Implement SHA256 duplicate detection.
- [ ] Implement PDF text extraction.
- [ ] Preserve page numbers.
- [ ] Detect section headings.
- [ ] Create section-aware chunks.
- [ ] Generate embeddings.
- [ ] Write all entities to PostgreSQL.

### Priority 3 — Retrieval

- [ ] Implement PostgreSQL full-text search.
- [ ] Implement pgvector semantic search.
- [ ] Implement score fusion.
- [ ] Add source and year filters.
- [ ] Return structured evidence with citations.

### Priority 4 — Source Resolver

- [ ] Exact canonical match.
- [ ] Alias match.
- [ ] normalized alias match.
- [ ] unit tests for selected XRB aliases.

### Priority 5 — MCP

- [ ] Start MCP server.
- [ ] Implement `search_literature`.
- [ ] Implement `get_paper`.
- [ ] Implement `get_source`.
- [ ] Test from MCP Inspector/client.

### Priority 6 — Reference Corpus

Load an initial test collection of approximately 20 papers covering:

- MAXI J1820+070;
- GX 339-4;
- V404 Cyg;
- at least one neutron-star XRB;
- hard/soft state behaviour;
- compact jets;
- transient ejecta;
- radio/X-ray correlation.

### End-of-Sprint Demonstration

The following query should work end-to-end:

> “What radio behaviour was observed from MAXI J1820+070 around its 2018 state transition? Give me the supporting papers and evidence.”

The system should:

1. resolve the source name;
2. search the local corpus;
3. combine lexical and semantic retrieval;
4. return relevant passages;
5. identify paper metadata;
6. provide section/page provenance;
7. distinguish published evidence from generated synthesis.

---

## 25. MVP Acceptance Criteria

The MVP is complete when all of the following are true:

- [ ] At least 100 papers can be ingested without manual database editing.
- [ ] Duplicate PDFs are detected automatically.
- [ ] Re-ingestion does not rebuild unchanged documents.
- [ ] Source aliases resolve reliably for the benchmark set.
- [ ] Hybrid retrieval works with source, year, and wavelength filters.
- [ ] Search results include paper-level and passage-level provenance.
- [ ] MCP client can call the three core tools successfully.
- [ ] New PDFs can be added without code changes.
- [ ] The database can be backed up and restored.
- [ ] Scientific benchmark queries return expected papers in the top results.

---

## 26. Recommended Build Order

Do not start by implementing automatic measurement extraction or a large catalogue ecosystem.

Build in this order:

1. database;
2. paper ingestion;
3. citation-preserving chunking;
4. hybrid search;
5. MCP interface;
6. source aliases;
7. observations and events;
8. catalogues;
9. automated updates;
10. observation-planning synthesis.

This order keeps the first usable system small and scientifically auditable.

---

## 27. Definition of Long-Term Success

The mature system should allow a researcher to ask:

> “I am proposing a 1.3 GHz radio observation of an X-ray binary currently entering the hard-intermediate state. What behaviour should I consider, what comparable systems and outbursts exist, what radio flux and spectral behaviour have been reported historically, what multiwavelength indicators should I monitor, and which measurements support those conclusions?”

The system should answer by combining:

- source identity;
- structured observations;
- source-state timelines;
- paper passages;
- catalogue measurements;
- comparable systems;
- multiwavelength evidence;
- explicit source citations;
- uncertainty and disagreement.

The core success criterion is not simply that the model can answer questions. It is that a researcher can inspect where every important scientific statement came from and update the underlying knowledge base continuously as new literature and catalogues appear.
