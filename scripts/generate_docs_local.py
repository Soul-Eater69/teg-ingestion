"""Generate the Cosmos + index documents for IDMT tickets LOCALLY — no persistence.

This runs the ingestion pipeline per ticket and writes the produced documents to local JSON files
instead of uploading them. **Nothing is written to Cosmos or the AI-search index** — you just see the
documents that *would* be ingested.

It still calls **live Jira** (to fetch the ticket + its linked Themes) and the **LLM gateway** (to
condense), so the relevant `TEG_*` settings must be configured. Embedding is off by default
(`content_vector` is null) so it runs without Azure embeddings; pass --embed to populate it.

Per ticket it writes, under <out>/<ticket-id>/:
  idmt.json            the Cosmos Engagement-Request document
  theme_<KEY>.json     one Cosmos Theme document per linked Theme
  index.json           the idp_teg_data search-index document

Usage:
  uv run python scripts/generate_docs_local.py IDMT-19761
  uv run python scripts/generate_docs_local.py IDMT-19761 IDMT-12857 --out out/local_docs
  uv run python scripts/generate_docs_local.py --from-file output_prod/idmt_vs_valid_ticket_keys.txt
  uv run python scripts/generate_docs_local.py IDMT-19761 --embed
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from teg.condense.config import CondenseConfig
from teg.config.settings import Settings, load_settings
from teg.integrations.embeddings import build_embeddings_client
from teg.integrations.files import build_attachment_extractor
from teg.integrations.jira import build_jira_client
from teg.integrations.llm import build_llm_client
from teg.ingestion.extraction.jira_source import build_jira_ingestion_source
from teg.ingestion.pipeline.idmt_ingestion import IdmtIngestion
from teg.services.condense_service import CondenseService


def _build_ingestion(settings: Settings, *, embed: bool) -> IdmtIngestion:
    """Wire the ingestion pipeline directly (no generation deps)."""
    config = CondenseConfig(
        doc_char_budget=settings.condense_doc_char_budget,
        max_attachments=settings.condense_max_attachments,
        max_attachment_bytes=settings.condense_max_attachment_bytes,
        min_doc_chars=settings.condense_min_doc_chars,
    )
    condense_service = CondenseService(
        build_jira_client(settings),
        build_llm_client(settings),
        build_attachment_extractor(),
        model_name=settings.llm_model,
        config=config,
    )
    return IdmtIngestion(
        jira_source=build_jira_ingestion_source(settings),
        condense_service=condense_service,
        embeddings_client=build_embeddings_client(settings) if embed else None,
    )


def _ticket_ids(args: argparse.Namespace) -> list[str]:
    ids = list(args.tickets)
    if args.from_file:
        ids += [line.strip() for line in Path(args.from_file).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    if args.limit:
        ids = ids[:args.limit]
    # de-dupe, preserve order
    seen: set[str] = set()
    return [t for t in ids if not (t in seen or seen.add(t))]


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


async def main(args: argparse.Namespace) -> None:
    tickets = _ticket_ids(args)
    if not tickets:
        raise SystemExit("no ticket ids (pass ids, or --from-file <cohort.txt>)")

    settings = load_settings()
    ingestion = _build_ingestion(settings, embed=args.embed)
    out_root = Path(args.out)
    print(f"generating docs for {len(tickets)} ticket(s) -> {out_root}/  "
          f"(embed={args.embed}; NO Cosmos/index write)\n")

    for tid in tickets:
        try:
            result = await ingestion.ingest(tid)
        except Exception as exc:
            print(f"  {tid}: ERROR {type(exc).__name__}: {exc}")
            continue
        d = out_root / tid
        d.mkdir(parents=True, exist_ok=True)
        _write(d / "idmt.json", result.idmt_document)
        _write(d / "index.json", result.historical_index_document)
        for theme in result.theme_documents:
            key = (theme.get("key") or theme.get("sourceId") or "theme")
            _write(d / f"theme_{key}.json", theme)
        print(f"  {tid}: idmt.json + index.json + {len(result.theme_documents)} theme doc(s) -> {d}/")

    print(f"\ndone. inspect the JSON under {out_root}/ — nothing was persisted.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generate Cosmos + index docs locally (no persistence).")
    p.add_argument("tickets", nargs="*", help="IDMT ticket id(s)")
    p.add_argument("--from-file", default="",
                   help="read ticket ids from a file (e.g. the Stage 0 cohort output), one per line")
    p.add_argument("--out", default="out/local_docs", help="output directory (default out/local_docs)")
    p.add_argument("--embed", action="store_true",
                   help="populate content_vector via the embeddings model (needs Azure embeddings)")
    p.add_argument("--limit", type=int, default=0, help="cap the number of tickets")
    asyncio.run(main(p.parse_args()))
