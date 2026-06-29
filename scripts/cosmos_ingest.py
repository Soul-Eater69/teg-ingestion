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
    uv run python scripts/cosmos_ingest.py --skip IDMT-19761,IDMT-12857     # ingest all except these
    uv run python scripts/cosmos_ingest.py --skip-file skip.txt             # exclude keys listed in a file
    uv run python scripts/cosmos_ingest.py --er-only                        # only the ER docs (no Theme docs)

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


def _skip_keys(skip: str, skip_file: str) -> set[str]:
    """Ticket keys to exclude from ingestion (uppercased), from --skip and/or --skip-file."""
    keys: set[str] = set()
    if skip:
        keys |= {k.strip().upper() for k in skip.split(",") if k.strip()}
    if skip_file:
        keys |= {line.strip().upper()
                 for line in Path(skip_file).read_text(encoding="utf-8").splitlines() if line.strip()}
    return keys


def _ticket_dirs(out: Path, ticket: str | None, skip: set[str]) -> list[Path]:
    if ticket:
        d = out / ticket
        return [d] if d.is_dir() and d.name.upper() not in skip else []
    return sorted(p for p in out.iterdir() if p.is_dir() and p.name.upper() not in skip)


def _load(out: Path, ticket: str | None, limit: int | None, *, skip: set[str], er_only: bool) -> list[dict]:
    """Collect the Cosmos docs across the per-ticket directories.

    Always the ER doc (idmt.json); the Theme docs (theme_*.json) too unless ``er_only``. Ticket
    folders whose name is in ``skip`` are excluded entirely.
    """
    docs: list[dict] = []
    for d in _ticket_dirs(out, ticket, skip):
        idmt = d / "idmt.json"
        if idmt.exists():
            docs.append(json.loads(idmt.read_text(encoding="utf-8")))
        if er_only:
            print(f"{d.name}: idmt (ER only, Theme docs skipped)")
            continue
        themes = sorted(d.glob("theme_*.json"))
        docs.extend(json.loads(p.read_text(encoding="utf-8")) for p in themes)
        print(f"{d.name}: idmt + {len(themes)} theme doc(s)")
    return docs[:limit] if limit else docs


async def main(out_dir: str, ticket: str | None, limit: int | None, *,
               skip: set[str], er_only: bool) -> None:
    out = Path(out_dir)
    if not out.is_dir():
        raise SystemExit(f"{out} not found - run generate_docs_local.py first")

    if skip:
        print(f"skipping {len(skip)} ticket(s): {', '.join(sorted(skip))}")
    docs = _load(out, ticket, limit, skip=skip, er_only=er_only)
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
    parser.add_argument("--skip", default="", help="comma-separated ticket keys to exclude from ingestion")
    parser.add_argument("--skip-file", default="", help="file of ticket keys to exclude (one per line)")
    parser.add_argument("--er-only", action="store_true",
                        help="upsert only the ER docs (idmt.json); skip the Theme docs")
    args = parser.parse_args()
    asyncio.run(main(args.dir, args.ticket or None, args.limit or None,
                     skip=_skip_keys(args.skip, args.skip_file), er_only=args.er_only))
