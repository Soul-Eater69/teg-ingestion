# teg-ingestion

The **ingestion module** of the Theme & Epic Generation (TEG) system, packaged as a self-contained,
installable module with every dependency it needs bundled (prompts, LLM/embeddings/Jira/search clients,
shared models). Ingestion converts historical IDMT Engagement Request tickets into the trusted corpus —
**Cosmos** (system of record) + the **idp_teg_data** retrieval index — that the generation module reads.

Design reference: **`docs/ingestion_tdd.md`** (with flowcharts).

## Install & test

```bash
# install the module + its dependencies
pip install -e ".[extract,dev]"          # extract = pdf/pptx/docx parsing; dev = test deps
#   add  ,azure  for live Cosmos / AI-Search persistence

# run the tests (no live Jira / Azure / LLM calls — clients are faked)
pytest                                    # 55 tests, all passing
```

Entry point: `teg.ingestion.pipeline.idmt_ingestion.IdmtIngestion.ingest(ticket_id)` — inject a
`JiraIngestionSource`, a `CondenseService`, and (optionally) an `EmbeddingsClient`. Configuration is via
`teg.config.settings.Settings` (env-driven, `TEG_` prefix).

**Models used:** condense = `gpt-5-mini-idp`; embeddings = `text-embedding-3-small-idp` (1536-d).

## Run it end to end — locally, no persistence

First set up config: **copy `.env.example` → `.env`** and fill in the Jira + LLM-gateway values (and
`NEO4J_*` for Stage 0). Settings load from `.env` automatically (`TEG_` prefix).

Two scripts under `scripts/` let you (1) fetch the valid-ticket cohort, then (2) generate the Cosmos +
index documents to **local JSON** — **nothing is written to Cosmos or the search index.**

**Stage 0 — fetch the valid tickets** (Neo4j; set `NEO4J_URI / USER / PASSWORD`):

```bash
python scripts/fetch_idmt_vs_valid_tickets.py --output cohort.txt
# writes the usable IDMT ticket keys (one per line) to cohort.txt
```

**Stage 1 — generate the docs locally** (calls live Jira + the LLM gateway to fetch + condense; writes
JSON, no upload). Configure the `TEG_*` settings (Jira + LLM gateway) first:

```bash
# one ticket
python scripts/generate_docs_local.py IDMT-19761 --out out/local_docs

# the whole cohort from Stage 0
python scripts/generate_docs_local.py --from-file cohort.txt --out out/local_docs
```

For each ticket it writes under `out/local_docs/<ticket-id>/`:
- `idmt.json` — the Cosmos Engagement-Request document
- `theme_<KEY>.json` — one Cosmos Theme document per linked Theme
- `index.json` — the idp_teg_data search-index document (`content_vector` is null unless `--embed`)

Inspect the JSON to see exactly what *would* be ingested — no actual ingestion happens.

## Layout

```
src/teg/
  ingestion/        ← the module (the focus)
    pipeline/         per-ticket orchestrator (idmt_ingestion.py)
    extraction/       Jira fetch + Business Value Stream field parsing
    documents/        Cosmos IDMT/Theme + historical index builders
    ground_truth/     ground-truth records
    catalogues/       Value Stream catalogue loader/models
    upload/           AI-search index uploader
  condense/         attachment ranking, raw-text assembly, condense LLM pass
  integrations/     low-level clients: jira, files (pdf/pptx/docx), embeddings, search, cosmos, llm
  services/         condense service wrapper        ← shared dep
  value_stream/     retrieval-text helper           ← shared dep (one helper used by the index builder)
  contracts/ domain/ config/ prompts/  shared models, settings, prompt templates
tests/              55 ingestion tests (all passing)
data/               index schema + value-stream catalogue fixtures
docs/               ingestion_tdd (md + pdf) + flowcharts
```

> `services/` and `value_stream/` are included because the pipeline imports a couple of helpers from
> them (the condense service wrapper and a retrieval-text builder). They are not the generation module.

## What is implemented (and what is not)

**Implemented & tested** — the per-ticket pipeline:
- Fetch the Engagement Request + linked Themes; read each Theme's Value Stream directly from its
  **Business Value Stream** field (`<name> {id}`, taken as-is — no fuzzy match, no LLM).
- Extract attachments (`.pdf`/`.pptx`/`.docx`, priority PowerPoint → PDF → Word), assemble the raw text
  to a ~24k-token budget, and **condense** it into the business-context fields.
- Build the Cosmos **Engagement Request** doc, one Cosmos **Theme** doc per linked Theme, and the
  **historical search-index** doc (with embedding).
- 55 tests pass (Jira source, document builders, condense, extractor, index-schema conformance, …).

**Not in this module / not yet wired** (see the TDD for the target design):
- **Stage 0 — ticket identification.** The Neo4j 5-filter funnel that produces the eligible ticket list
  is a **separate production script**, not here. The pipeline takes one `ticket_id` and assumes
  identification already happened.
- **Batch runner** and **Cosmos persistence write.** The pipeline *builds* and returns the documents;
  the write to Cosmos and the batch loop over the cohort are the caller's responsibility.
- **Schema simplification.** The code still builds the legacy `themes[]` ground truth on the IDMT
  document and ships the stage/L2/L3 ground-truth module; the TDD's simplified design (store only the
  Theme's title, description, and Value Stream) is **not yet reflected in code.**

## Conventions
Code-quality standards are in **`CODE_QUALITY.md`** — please follow them. Unit tests must not make live
Jira / Azure / LLM calls; inject fakes.
