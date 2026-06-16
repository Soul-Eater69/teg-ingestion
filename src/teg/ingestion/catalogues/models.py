"""Parsed Sightline catalogue records (value_stream_capability_map.json + capability_tree.json).

VS -> stages -> capabilities. Each catalogue capability is an L3 leaf that carries its
L2 (and L1) ancestor inline; L3 maps 1-1 to its L2 via level_two_*. The capability tree
is the standalone full L1/L2/L3 hierarchy (parent_id links). Semicolon-delimited source
strings (stakeholders) are normalised to lists here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogueCapability:
    """An L3 capability leaf with its L2/L1 ancestors inline (1-1 L3->L2)."""

    capability_id: str
    capability_name: str
    capability_description: str
    level: int  # 3 for catalogue capabilities (the L3 leaf)
    tier: str
    active: bool | None
    level_one_id: str
    level_one_name: str
    level_two_id: str
    level_two_name: str


@dataclass(frozen=True)
class CatalogueStage:
    stage_id: str
    stage_name: str
    stage_description: str
    sequence: int
    entrance_criteria: str
    exit_criteria: str
    value_items: str
    active: bool | None
    created_date: str
    modified_date: str
    stakeholders: list[str] = field(default_factory=list)
    capabilities: list[CatalogueCapability] = field(default_factory=list)


@dataclass(frozen=True)
class CatalogueValueStream:
    value_stream_id: str
    value_stream_name: str
    value_stream_description: str
    value_proposition: str
    trigger: str
    category: str
    assumptions: str
    defined_terms: str
    active: bool | None
    created_date: str
    created_by: str
    modified_date: str
    modified_by: str
    stakeholders: list[str] = field(default_factory=list)
    stages: list[CatalogueStage] = field(default_factory=list)
