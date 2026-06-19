"""Upsert the locally-generated Cosmos docs into Cosmos.

Reads the per-ticket docs written by ``generate_docs_local.py`` (``<out>/<ticket>/idmt.json`` and
``theme_*.json``), restamps their lifecycle timestamps to NOW (the ingestion-run time, not the
extraction time), adapts them to the org Cosmos schema, and upserts them into the one container.
Idempotent - re-running overwrites by the deterministic id, never duplicates. Themes/index docs are
handled by ``upload_index.py`` (index) and are skipped here except the Cosmos Theme docs.

    uv sync --extra azure
    uv run python scripts/cosmos_ingest.py --dir out/local_docs --limit 2   # smoke test: 2 docs
    uv run python scripts/cosmos_ingest.py --dir out/local_docs             # full ingest
    uv run python scripts/cosmos_ingest.py --ticket IDMT-19761              # one ticket's docs

Needs the Cosmos env (TEG_COSMOS_* / AZURE_COSMOS_* + the service principal with the
"Cosmos DB Built-in Data Contributor" data role).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from teg.config.settings import load_settings
from teg.ingestion.documents.idmt_documents import _now, restamp
from teg.integrations.cosmos import build_cosmos_writer, to_cosmos_doc


def _ticket_dirs(out: Path, ticket: str | None) -> list[Path]:
    if ticket:
        d = out / ticket
        return [d] if d.is_dir() else []
    return sorted(p for p in out.iterdir() if p.is_dir())


def _load(out: Path, ticket: str | None, limit: int | None) -> list[dict]:
    """Collect the Cosmos docs (idmt.json + theme_*.json) across the per-ticket directories."""
    docs: list[dict] = []
    for d in _ticket_dirs(out, ticket):
        idmt = d / "idmt.json"
        if idmt.exists():
            docs.append(json.loads(idmt.read_text(encoding="utf-8")))
        themes = sorted(d.glob("theme_*.json"))
        docs.extend(json.loads(p.read_text(encoding="utf-8")) for p in themes)
        print(f"{d.name}: idmt + {len(themes)} theme doc(s)")
    return docs[:limit] if limit else docs


async def main(out_dir: str, ticket: str | None, limit: int | None) -> None:
    out = Path(out_dir)
    if not out.is_dir():
        raise SystemExit(f"{out} not found - run generate_docs_local.py first")

    docs = _load(out, ticket, limit)
    if not docs:
        print("nothing to ingest")
        return

    when = _now()  # one timestamp for the whole run
    for doc in docs:
        restamp(doc, when)
    # Adapt to the org Cosmos schema (domain=WORKITEM, uppercase discriminators, drop themes).
    docs = [to_cosmos_doc(doc) for doc in docs]

    writer = build_cosmos_writer(load_settings())
    try:
        written = await writer.upsert(docs)
    finally:
        await writer.close()
    print(f"upserted {written} docs into Cosmos (lifecycle stamped {when})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="out/local_docs", help="directory holding the per-ticket doc folders")
    parser.add_argument("--ticket", default="", help="upsert only this ticket's docs")
    parser.add_argument("--limit", type=int, default=0, help="upsert only the first N docs (smoke test)")
    args = parser.parse_args()
    asyncio.run(main(args.dir, args.ticket or None, args.limit or None))
