"""Rewrite where the business ``key`` lives in the locally-generated Cosmos docs.

Works on the per-ticket docs written by ``generate_docs_local.py`` - the ER doc (idmt.json) and the
Theme docs (theme_*.json). The index doc (index.json) is left untouched: it has no ``properties``
and keeps ``key`` at the top level by design.

Note: generate_docs_local.py now writes the business ``key`` at BOTH levels natively, so this
script is a migration/repair utility for docs generated before that change (or to switch shapes).

Two modes (the key value is read from wherever it currently is - properties.key or top-level key):
  --mode both   key at BOTH the top level AND inside properties (the shape the generator now emits)
  --mode props  key ONLY inside properties (older schema); removes the top-level key

Idempotent and safe to re-run. Use --dry-run to preview without writing.

    uv run python scripts/fixup_doc_key.py --mode both
    uv run python scripts/fixup_doc_key.py --mode props --dir out/local_docs
    uv run python scripts/fixup_doc_key.py --mode props --ticket IDMT-19761 --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _ticket_dirs(out: Path, ticket: str | None) -> list[Path]:
    if ticket:
        d = out / ticket
        return [d] if d.is_dir() else []
    return sorted(p for p in out.iterdir() if p.is_dir())


def _cosmos_files(d: Path) -> list[Path]:
    """The Cosmos docs in a ticket dir: the ER doc + every Theme doc (NOT index.json)."""
    files = []
    idmt = d / "idmt.json"
    if idmt.exists():
        files.append(idmt)
    files.extend(sorted(d.glob("theme_*.json")))
    return files


def _current_key(doc: dict) -> str | None:
    """The key value, wherever it currently sits (properties wins, then top level)."""
    props = doc.get("properties")
    if isinstance(props, dict) and props.get("key"):
        return props["key"]
    return doc.get("key")


def _props_key_first(props: dict, key) -> dict:
    """Return properties with ``key`` as the first field (matches the builder's order)."""
    rest = {k: v for k, v in props.items() if k != "key"}
    return {"key": key, **rest}


def rewrite_key(doc: dict, mode: str) -> dict:
    """Return a copy of ``doc`` with ``key`` placed per ``mode``. Top-level key kept right after id."""
    key = _current_key(doc)
    props = doc.get("properties")
    if not isinstance(props, dict):
        # No properties object (e.g. an index doc slipped in) - leave it as-is.
        return doc

    out = {k: v for k, v in doc.items() if k != "key"}  # drop top-level key; re-add below if needed
    out["properties"] = _props_key_first(props, key)

    if mode == "both":
        # Re-insert top-level key right after id so it reads like the original schema.
        ordered: dict = {}
        for k, v in out.items():
            ordered[k] = v
            if k == "id":
                ordered["key"] = key
        if "key" not in ordered:  # no id field - just put it first
            ordered = {"key": key, **out}
        return ordered
    return out  # mode == "props": top-level key already dropped


def main(out_dir: str, ticket: str | None, mode: str, dry_run: bool) -> None:
    out = Path(out_dir)
    if not out.is_dir():
        raise SystemExit(f"{out} not found - run generate_docs_local.py first")

    changed = scanned = 0
    for d in _ticket_dirs(out, ticket):
        for f in _cosmos_files(d):
            scanned += 1
            doc = json.loads(f.read_text(encoding="utf-8"))
            if _current_key(doc) is None:
                print(f"  WARN {f.relative_to(out)}: no key found, skipped")
                continue
            new_doc = rewrite_key(doc, mode)
            if new_doc == doc:
                continue
            changed += 1
            print(f"  {'(dry-run) ' if dry_run else ''}{f.relative_to(out)}: key -> {mode}")
            if not dry_run:
                f.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    verb = "would change" if dry_run else "changed"
    print(f"{verb} {changed}/{scanned} Cosmos doc(s) (mode={mode})")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Place the business key at both levels or properties-only.")
    p.add_argument("--mode", required=True, choices=("both", "props"),
                   help="both = top-level + properties; props = properties only (removes top-level)")
    p.add_argument("--dir", default="out/local_docs", help="directory holding the per-ticket doc folders")
    p.add_argument("--ticket", default="", help="only this ticket's docs")
    p.add_argument("--dry-run", action="store_true", help="preview changes without writing")
    args = p.parse_args()
    main(args.dir, args.ticket or None, args.mode, args.dry_run)
