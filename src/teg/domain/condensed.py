"""Condensed ticket records.

The condense step is a single LLM pass over the source material producing
``summary_fields`` (retrieval + routing + LLM context). This model is the single
source of truth - used internally and serialized at the backend boundary
(camelCase via CamelModel).
"""

from __future__ import annotations

from pydantic import Field

from teg.domain.base import CamelModel


class SummaryFields(CamelModel):
    """Retrieval + routing + LLM context. Used by every downstream call."""

    generated_summary: str
    business_problem: str
    business_capability: str
    key_terms: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    systems_and_products: list[str] = Field(default_factory=list)


class CondensedTicket(CamelModel):
    """Full condense output. The backend stores this and replays it downstream."""

    ticket_id: str
    ticket_title: str
    primary_source: str  # "idea_card" | "attachments_fallback"
    attachments_used: list[str] = Field(default_factory=list)
    summary_fields: SummaryFields
    description: str
    raw_text: str  # consolidated description + extracted attachment text
