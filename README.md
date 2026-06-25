# teg-ingestion

The **ingestion module** of the Theme & Epic Generation (TEG) system. It converts historical IDMT
Engagement Request tickets into the trusted corpus — **Cosmos** (system of record) + the
**`idp_teg_data`** Azure AI Search retrieval index — that the generation module reads.

Design reference: **`docs/ingestion_tdd.md`** (with flowcharts).

---

## Setup

This is a **uv package** (`pyproject.toml`). The runtime features are optional extras:

| Extra | Pulls in | Needed for |
| --- | --- | --- |
| `extract` | pypdfium2, python-pptx, python-docx | reading PDF / PPTX / DOCX attachments (Stage 1) |
| `neo4j` | neo4j driver | the cohort fetcher (Stage 0) |
| `azure` | azure-cosmos, azure-search-documents, azure-identity | Cosmos + AI Search persistence (Stage 2) |

**1. Configure** — copy the example env and fill it in:

```bash
cp .env.example .env
# then edit .env — Settings load automatically (TEG_ prefix; Stage 0 uses NEO4J_* with no prefix)
```

**2. Install the extras** — simplest is to sync everything once:

```bash
uv sync --all-extras
```

> ⚠️ **uv gotcha:** a plain `uv run python …` re-syncs the env to the default and *drops* extras. Either
> `uv sync --all-extras` once (recommended), or pass the extras on every run, e.g.
> `uv run --extra extract --extra azure python scripts/…`.

---

## Pipeline — end to end

```
Stage 0  fetch cohort (Neo4j)         →  cohort.txt
Stage 1  generate docs (Jira + LLM)   →  out/local_docs/<ticket>/{idmt,theme_*,index}.json
Stage 2  provision + persist (Azure)  →  idp_teg_data index + Cosmos
```

### Stage 0 — fetch the valid-ticket cohort (Neo4j)

Applies the L2→L6 funnel (ER not Cancelled/Blocked/New Request → `implemented by` a non-Cancelled
Theme with a `{VSR…}` value stream) and writes the ticket keys.

```bash
uv run python scripts/fetch_idmt_vs_valid_tickets.py --output cohort.txt
# options: --since 2023-01-01 (start date) · --stdout (also print) · --no-file
```

### Stage 1 — generate the docs locally (Jira + LLM gateway)

Fetches each ticket, extracts attachments, condenses to a ~24k-token budget, and writes the Cosmos +
index JSON to disk. **Nothing is persisted** in this stage.

```bash
# one ticket
uv run python scripts/generate_docs_local.py IDMT-19761 --out out/local_docs --embed

# the whole cohort, 4 at a time
uv run python scripts/generate_docs_local.py --from-file cohort.txt --out out/local_docs --embed --concurrency 4
```

Per ticket it writes `out/local_docs/<ticket>/`:
- `idmt.json` — the Cosmos Engagement-Request document
- `theme_<KEY>.json` — one Cosmos Theme document per linked Theme
- `index.json` — the `idp_teg_data` search-index document (`content_vector` is null **unless `--embed`**)

Flags: `--embed` (compute embeddings — **required** before upload) · `--concurrency N` · `--limit N`
(smoke test) · `--from-file <cohort.txt>`.

### Stage 2 — provision the index, then persist (Azure)

Writes to the live services. Both ingest steps are **idempotent** (upsert by deterministic id — re-running
overwrites, never duplicates). The Cosmos doc and the index doc for a ticket share the **same `id`**.

```bash
# 2a. create-or-update the index from its JSON schema (idempotent; one-time / on schema change)
uv run python scripts/create_index.py
#     --recreate  →  DROP then create (loses all docs; only for incompatible schema changes)

# 2b. upsert the Cosmos docs (idmt.json + theme_*.json)
uv run python scripts/cosmos_ingest.py --dir out/local_docs

# 2c. upsert the index docs (index.json) — refuses docs whose content_vector is null
uv run python scripts/upload_index.py --dir out/local_docs
```

`cosmos_ingest.py` / `upload_index.py` also take `--ticket IDMT-####` (one ticket) and `--limit N`
(smoke test). `data/idp_teg_data_index.json` is the **single source of truth** for the index schema.

---

## Utility scripts

```bash
# audit local docs for the lastModifiedyBy / lastModifiedyAt key typo (exit 1 if any found)
uv run python scripts/check_typo_keys.py --dir out/local_docs
```

---

## Environment variables

Copy `.env.example` → `.env`. Grouped by stage:

- **Stage 0 (Neo4j, no prefix):** `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (`NEO4J_DATABASE` optional)
- **Stage 1 (Jira + LLM):** `TEG_JIRA_BASE_URL`, `TEG_JIRA_TOKEN`, `TEG_LLM_BASE_URL`, `TEG_LLM_MODEL`,
  `TEG_LLM_APP_ID`, `TEG_IDP_AUTH_URL`, `TEG_IDP_CLIENT_ID`, `TEG_IDP_CLIENT_SECRET`, `TEG_IDP_USER`,
  `TEG_IDP_PASSWORD`, `TEG_EMBEDDING_MODEL` (for `--embed`)
- **Stage 2 (Cosmos + Search):** `TEG_COSMOS_ENDPOINT`, `TEG_COSMOS_DATABASE`, `TEG_COSMOS_CONTAINER`,
  `TEG_SEARCH_ENDPOINT`, `TEG_SEARCH_INDEX`. **Auth:** the Azure service principal
  (`TEG_AZURE_TENANT_ID` / `TEG_AZURE_CLIENT_ID` / `TEG_AZURE_CLIENT_SECRET`, or the org's `AZURE_*_DEV`
  names) — needs the **"Cosmos DB Built-in Data Contributor"** role — **or** fall back to
  `TEG_COSMOS_KEY` / `TEG_SEARCH_API_KEY`.

Models: condense = `gpt-5-mini-idp`; embeddings = `text-embedding-3-small-idp` (1536-d). The condense
budget is `TEG_CONDENSE_DOC_CHAR_BUDGET` (default 96k chars ≈ 24k tokens) over
`TEG_CONDENSE_MAX_ATTACHMENTS` (default 5) downloaded attachments.

---

## Layout

```
src/teg/
  ingestion/        the module (the focus)
    pipeline/         per-ticket orchestrator (idmt_ingestion.py)
    extraction/       Jira fetch + Business Value Stream field parsing
    documents/        Cosmos IDMT/Theme + historical index builders
    ground_truth/     Theme (Value Stream) ground-truth records
    upload/           AI-search index uploader
  condense/         attachment ranking, raw-text assembly, the single condense LLM pass
  integrations/     low-level clients: jira, files (pdf/pptx/docx), embeddings, search, cosmos, llm
  services/         condense service wrapper
  contracts/ domain/ config/ prompts/   shared models, settings, the condense prompt
data/               idp_teg_data index schema (source of truth)
docs/               ingestion_tdd (md + pdf) + flowcharts
scripts/            the runnable pipeline (fetch / generate / create_index / cosmos_ingest / upload_index)
```

The **VS/Stage catalogue is not built here** (it is the org's gold data in Azure SQL, consumed as-is),
so the catalogue loader / VS-catalogue index builder / stage ground-truth modules are intentionally
absent. Condense is a **single LLM pass** (generated summary + business context fields), per
`docs/ingestion_tdd.md` §4.3–4.4.
