# teg-ingestion

The **ingestion module** of the Theme & Epic Generation (TEG) system, packaged as a self-contained,
installable module with every dependency it needs bundled (prompts, LLM/embeddings/Jira/search clients,
shared models). Ingestion converts historical IDMT Engagement Request tickets into the trusted corpus —
**Cosmos** (system of record) + the **idp_teg_data** retrieval index — that the generation module reads.

Design reference: **`docs/ingestion_tdd.md`** (with flowcharts).

## Install & test

This is a **uv package** (`pyproject.toml` + `uv.lock`). Test tooling is in the `dev`
dependency-group (installed by default); the runtime features are optional extras.

```bash
# create the env + install the module, the dev group, and the feature extras
uv sync --extra extract --extra neo4j     # extract = pdf/pptx/docx · neo4j = Stage 0
#   add  --extra azure  for live Cosmos / AI-Search persistence

# run the tests (no live Jira / Azure / LLM calls — clients are faked)
uv run pytest                             # 48 tests, all passing
```

> Prefer pip? `pip install -e ".[extract,neo4j]"` then `pip install pytest pytest-asyncio` works too —
> the `dev` group is uv-native, so under pip install the test deps explicitly.

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
uv run python scripts/fetch_idmt_vs_valid_tickets.py --output cohort.txt
# writes the usable IDMT ticket keys (one per line) to cohort.txt
```

**Stage 1 — generate the docs locally** (calls live Jira + the LLM gateway to fetch + condense; writes
JSON, no upload). Configure the `TEG_*` settings (Jira + LLM gateway) first:

```bash
# one ticket
uv run python scripts/generate_docs_local.py IDMT-19761 --out out/local_docs

# the whole cohort from Stage 0
uv run python scripts/generate_docs_local.py --from-file cohort.txt --out out/local_docs
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
    ground_truth/     Theme (Value Stream) ground-truth records
    upload/           AI-search index uploader
  condense/         attachment ranking, raw-text assembly, the single condense LLM pass
  integrations/     low-level clients: jira, files (pdf/pptx/docx), embeddings, search, cosmos, llm
  services/         condense service wrapper only    ← shared dep
  contracts/ domain/ config/ prompts/  shared models, settings, the condense prompt
tests/              48 ingestion tests (all passing)
data/               index schema fixture
docs/               ingestion_tdd (md + pdf) + flowcharts
```

> This is the **ingestion subset only** — exactly the modules the runnable pipeline + scripts use, plus
> the low-level integration clients. No generation code (theme / value-stream / stage selection, their
> prompts and judges) and no `value_stream/` package — the one retrieval-text helper the index builder
> needed is inlined into `historical_index_documents.py`. Per the TDD, the **VS/Stage catalogue is not
> built here** (it is the org's gold data in Azure SQL), so the catalogue loader / VS-catalogue index
> builder / stage ground-truth modules are not included either.
>
> **Condense is a single LLM pass** (`SummaryFields` — generated summary, business problem/capability,
> key terms, stakeholders, systems & products), matching `docs/ingestion_tdd.md` §4.3-4.4. The old
> second "generation signals" pass is removed; ingestion never stored it.

## What is implemented (and what is not)

**Implemented & tested** — the per-ticket pipeline:
- Fetch the Engagement Request + linked Themes; read each Theme's Value Stream directly from its
  **Business Value Stream** field (`<name> {id}`, taken as-is — no fuzzy match, no LLM).
- Extract attachments (`.pdf`/`.pptx`/`.docx`, priority PowerPoint → PDF → Word), assemble the raw text
  to a ~24k-token budget, and **condense** it into the business-context fields.
- Build the Cosmos **Engagement Request** doc, one Cosmos **Theme** doc per linked Theme, and the
  **historical search-index** doc (with embedding).
- 48 tests pass (Jira source, document builders, condense, extractor, index-schema conformance, …).

**Not in this module / not yet wired** (see the TDD for the target design):
- **Stage 0 — ticket identification.** The Neo4j 5-filter funnel that produces the eligible ticket list
  is a **separate production script** (`scripts/fetch_idmt_vs_valid_tickets.py`). The pipeline takes one
  `ticket_id` and assumes identification already happened.
- **Batch runner** and **Cosmos persistence write.** The pipeline *builds* and returns the documents;
  the write to Cosmos and the batch loop over the cohort are the caller's responsibility (the Cosmos /
  AI-Search clients under `integrations/` are provided for that).
- **VS/Stage catalogue + stage ground truth.** Per the TDD these are the org's gold data in Azure SQL,
  consumed as-is — ingestion does not build them, so that code is intentionally absent.

## Conventions
Code-quality standards are in **`CODE_QUALITY.md`** — please follow them. Unit tests must not make live
Jira / Azure / LLM calls; inject fakes.
