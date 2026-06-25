"""Scan locally-generated docs for the lastModified key typo.

Old ingestion wrote the Cosmos key names as ``lastModifiedyBy`` / ``lastModifiedyAt`` (an extra "y");
the correct names are ``lastModifiedBy`` / ``lastModifiedAt``. APIs fail on the typo'd records, so
this walks a directory of generated JSON docs and reports every file that still carries a typo'd key
(recursing nested objects/arrays) - the set of files that would need a re-ingest.

    uv run python scripts/check_typo_keys.py
    uv run python scripts/check_typo_keys.py --dir out/local_docs

Exit code is 1 when any typo is found (0 when clean), so it doubles as a CI/guard check.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# typo (wrong key) -> correct key
TYPO_KEYS = {
    "lastModifiedyBy": "lastModifiedBy",
    "lastModifiedyAt": "lastModifiedAt",
}


def typo_keys_in(obj: object) -> set[str]:
    """Every typo key name present anywhere in a JSON value (recurses dicts and lists)."""
    found: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in TYPO_KEYS:
                found.add(key)
            found |= typo_keys_in(value)
    elif isinstance(obj, list):
        for item in obj:
            found |= typo_keys_in(item)
    return found


def main(directory: str) -> None:
    root = Path(directory)
    if not root.exists():
        raise SystemExit(f"directory not found: {root}")

    files = sorted(root.rglob("*.json"))
    bad: list[tuple[Path, set[str]]] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"skip {path} ({exc})")
            continue
        keys = typo_keys_in(data)
        if keys:
            bad.append((path, keys))

    print(f"scanned {len(files)} json file(s) under {root}")
    for path, keys in bad:
        fixes = ", ".join(f"{key} -> {TYPO_KEYS[key]}" for key in sorted(keys))
        print(f"  TYPO  {path}: {fixes}")
    print(f"{len(bad)} file(s) with the lastModified typo")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dir", default="out/local_docs", help="directory of generated JSON docs to scan"
    )
    args = parser.parse_args()
    main(args.dir)
