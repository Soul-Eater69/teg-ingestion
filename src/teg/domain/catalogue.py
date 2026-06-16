"""Governed catalogue records.

Catalogues come from Sightline into Cosmos. We read them; the backend never sends
them. They govern what VS / stage / L2 / L3 values predictions may resolve to.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValueStreamCatalogueEntry:
    value_stream_id: str
    value_stream_name: str
    value_stream_description: str


@dataclass
class StageCatalogueEntry:
    stage_id: str
    stage_name: str
    stage_description: str
    value_stream_id: str  # the VS this stage belongs to


@dataclass
class CapabilityCatalogueEntry:
    """An L2 or L3 capability mapped to a stage."""

    capability_id: str
    name: str
    description: str
    stage_id: str
    level: str  # "L2" | "L3"


@dataclass
class StageCatalogue:
    """All governed stages + capability mappings for one Value Stream."""

    value_stream_id: str
    stages: list[StageCatalogueEntry] = field(default_factory=list)
    l2_by_stage: dict[str, list[CapabilityCatalogueEntry]] = field(default_factory=dict)
    l3_by_stage: dict[str, list[CapabilityCatalogueEntry]] = field(default_factory=dict)
