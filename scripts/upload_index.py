"""Upsert the locally-generated index docs into the search index.

Reads the per-ticket ``index.json`` files written by ``generate_docs_local.py`` and merge-or-uploads
them into the ``idp_teg_data`` index. Upsert by key (id), so re-ingesting a ticket overwrites its
doc. Decoupled from generation: inspect the local docs, then upload (and re-upload cheaply) without
re-fetching Jira or re-running the LLM.

    uv sync --extra azure
    uv run python scripts/upload_index.py --dir out/local_docs
    uv run python scripts/upload_index.py --ticket IDMT-19761

The docs must carry ``content_vector`` - regenerate with ``generate_docs_local.py --embed`` first,
else the upload is refused (an index doc without its vector is useless for retrieval).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from teg.config.settings import load_settings
from teg.ingestion.upload.search_uploader import build_search_uploader


def _ticket_dirs(out: Path, ticket: str | None) -> list[Path]:
    if ticket:
        d = out / ticket
        return [d] if d.is_dir() else []
    return sorted(p for p in out.iterdir() if p.is_dir())


def _load(out: Path, ticket: str | None, limit: int | None) -> list[dict]:
    """Collect the index docs (index.json) across the per-ticket directories."""
    docs: list[dict] = []
    for d in _ticket_dirs(out, ticket):
        index = d / "index.json"
        if not index.exists():
            print(f"skip {d.name} (no index.json)")
            continue
        docs.append(json.loads(index.read_text(encoding="utf-8")))
        print(f"{d.name}: index doc")
    return docs[:limit] if limit else docs


async def main(out_dir: str, ticket: str | None, limit: int | None) -> None:
    out = Path(out_dir)
    if not out.is_dir():
        raise SystemExit(f"{out} not found - run generate_docs_local.py first")

    documents = _load(out, ticket, limit)
    if not documents:
        print("nothing to upload")
        return

    missing_vectors = sum(1 for d in documents if not d.get("content_vector"))
    if missing_vectors:
        raise SystemExit(
            f"{missing_vectors} doc(s) have no content_vector - "
            "regenerate with generate_docs_local.py --embed before uploading"
        )

    settings = load_settings()
    uploader = build_search_uploader(settings)
    try:
        report = await uploader.upload(documents)
    finally:
        await uploader.close()

    print(f"upserted {report.succeeded}/{len(documents)} docs -> {settings.search_index}")
    for failure in report.failures:
        print(f"  FAILED {failure.document_id}: [{failure.status_code}] {failure.error_message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="out/local_docs", help="directory holding the per-ticket doc folders")
    parser.add_argument("--ticket", default="", help="upload only this ticket's index doc")
    parser.add_argument("--limit", type=int, default=0, help="upload only the first N docs")
    args = parser.parse_args()
    asyncio.run(main(args.dir, args.ticket or None, args.limit or None))
