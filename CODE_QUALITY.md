# Code quality — TEG ingestion

Standards for working in this codebase. The existing ingestion code follows these; keep it that way.

## Style

Write clean, production Python:

- **Clear names** — use domain names directly (`value_stream_ground_truth`, `idmt_document_builder`,
  `stage_support`). Avoid vague `Manager` / `Service` / `Processor` / `handler` / `engine` / `util`.
- **Small, meaningful functions** with a single real responsibility; linear, readable flow; minimal
  nesting.
- **Explicit data shapes** — simple dataclasses / pydantic models for core records; one source of truth
  for each important shape/schema.
- **Helpers only when they earn it** — no one-line wrappers, no generic utility dumping grounds.
- **Status logs for long-running jobs**, not scattered debug prints.

Avoid: useless wrappers, over-engineered abstractions, deep nesting, duplicated business logic, random
CLI flags, and large functions doing several unrelated things.

```python
# Bad
def process(data):
    return Manager().execute(data)

# Good
def build_stage_pairs(gt_by_value_stream: dict[str, list[str]]) -> list[str]:
    pairs: list[str] = []
    for value_stream, stages in gt_by_value_stream.items():
        for stage in stages:
            pairs.append(f"{value_stream}::{stage}")
    return dedupe_text(pairs)
```

## Architecture rules

- **Package boundaries are intentional.** `ingestion` = offline extraction + transformation +
  persistence (no runtime generation logic). `integrations` = low-level external clients only (no
  business logic). `domain` / `contracts` = shared models. Keep these separate; don't mix runtime
  generation into `ingestion`.
- **Configuration via `Settings`, never `os.environ` directly** in business code — inject settings.
- **Dependency injection for clients** (Jira, Azure Search, embeddings, LLM) so tests inject fakes.
- **Single source of truth for the indexed/stored document shape** — the document builders under
  `ingestion/documents/` own it; don't re-derive the shape elsewhere.
- **LLM output is a pydantic model** passed as the structured-output schema — never a JSON schema block
  pasted into the prompt text.

## Testing

- **Unit tests must not make live Jira / Azure / LLM calls.** Inject fakes/stubs.
- New public contracts include model / `to_dict` (serialization) tests.
- Keep tests fast and deterministic.

## Before committing

```bash
python -m compileall src
python -m pytest tests/ -q
```

Keep summaries honest: if tests fail, say so with the output; don't claim done until it's verified.
