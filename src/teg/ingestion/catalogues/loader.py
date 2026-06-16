"""Load and parse the Sightline VS catalogue (value_stream_capability_map.json).

VS -> stages -> capabilities (each an L3 leaf carrying its L2/L1 ancestor inline).
Stakeholder fields are semicolon-delimited strings in the source; split to lists.
"""

from __future__ import annotations

import json
from pathlib import Path

from teg.ingestion.catalogues.models import (
    CatalogueCapability,
    CatalogueStage,
    CatalogueValueStream,
)


def load_value_stream_catalogue(path: str | Path) -> list[CatalogueValueStream]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_value_stream(raw) for raw in data.get("value_streams") or []]


def _value_stream(raw: dict) -> CatalogueValueStream:
    return CatalogueValueStream(
        value_stream_id=_text(raw.get("value_stream_id")),
        value_stream_name=_text(raw.get("value_stream_name")),
        value_stream_description=_text(raw.get("value_stream_description")),
        value_proposition=_text(raw.get("value_proposition")),
        trigger=_text(raw.get("trigger")),
        category=_text(raw.get("category")),
        assumptions=_text(raw.get("assumptions")),
        defined_terms=_text(raw.get("defined_terms")),
        active=_bool(raw.get("active")),
        created_date=_text(raw.get("created_date")),
        created_by=_text(raw.get("created_by")),
        modified_date=_text(raw.get("modified_date")),
        modified_by=_text(raw.get("modified_by")),
        stakeholders=_split(raw.get("stakeholders")),
        stages=[_stage(s) for s in raw.get("stages") or []],
    )


def _stage(raw: dict) -> CatalogueStage:
    return CatalogueStage(
        stage_id=_text(raw.get("stage_id")),
        stage_name=_text(raw.get("stage_name")),
        stage_description=_text(raw.get("stage_description")),
        sequence=_int(raw.get("sequence")),
        entrance_criteria=_text(raw.get("entrance_criteria")),
        exit_criteria=_text(raw.get("exit_criteria")),
        value_items=_text(raw.get("value_items")),
        active=_bool(raw.get("active")),
        created_date=_text(raw.get("created_date")),
        modified_date=_text(raw.get("modified_date")),
        stakeholders=_split(raw.get("stakeholders")),
        capabilities=[_capability(c) for c in raw.get("capabilities") or []],
    )


def _capability(raw: dict) -> CatalogueCapability:
    return CatalogueCapability(
        capability_id=_text(raw.get("capability_id")),
        capability_name=_text(raw.get("capability_name")),
        capability_description=_text(raw.get("capability_description")),
        level=_int(raw.get("level")),
        tier=_text(raw.get("tier")),
        active=_bool(raw.get("active")),
        level_one_id=_text(raw.get("level_1_id")),
        level_one_name=_text(raw.get("level_1_name")),
        level_two_id=_text(raw.get("level_2_id")),
        level_two_name=_text(raw.get("level_2_name")),
    )


def _text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _split(raw: object) -> list[str]:
    """Split a semicolon-delimited source string (or pass a list through), trimmed."""
    if not raw:
        return []
    items = raw if isinstance(raw, list) else str(raw).split(";")
    return [text for text in (" ".join(str(item).split()) for item in items) if text]
