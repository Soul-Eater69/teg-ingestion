"""Contract C - Theme generation. Backend -> us, after HITL approves the VS set.

Backend replays the stored condensed data + the approved VS set. Governed stage /
L2 / L3 catalogues are read by us from Cosmos and are never sent by the backend.
We return one theme package per approved Value Stream.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from teg.domain.condensed import GenerationSignals, SummaryFields


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CondensedContext(_Camel):
    summary_fields: SummaryFields
    generation_signals: GenerationSignals


class ApprovedValueStream(_Camel):
    value_stream_id: str
    value_stream_name: str


class ThemeGenerationRequest(_Camel):
    ticket_id: str
    ticket_title: str
    condensed: CondensedContext
    approved_value_streams: list[ApprovedValueStream]


class SelectedStage(_Camel):
    stage_id: str
    stage_name: str
    reason: str = ""


class Capability(_Camel):
    capability_id: str
    name: str
    reason: str = ""  # why it applies (L3); empty for L2 (derived as the L3's parent)


class StageCapabilities(_Camel):
    stage_id: str
    stage_name: str
    capabilities: list[Capability] = Field(default_factory=list)


class ThemePackage(_Camel):
    value_stream_id: str
    value_stream_name: str
    theme_title: str
    theme_description: str  # the final consolidated Jira theme-description text
    selected_stages: list[SelectedStage] = Field(default_factory=list)
    business_needs: str = ""  # the final consolidated Business Needs text (all selected stages)
    l2_capabilities: list[StageCapabilities] = Field(default_factory=list)
    l3_capabilities: list[StageCapabilities] = Field(default_factory=list)


class ThemeGenerationResponse(_Camel):
    ticket_id: str
    theme_packages: list[ThemePackage]
    model: str
    prompt_version: str
    latency_ms: int = 0
