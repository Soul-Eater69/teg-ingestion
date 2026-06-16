"""Condensed ticket records.

The condense step is two parallel LLM passes over the idea-card source material:
``summary_fields`` (retrieval + routing + LLM context) and ``generation_signals``
(evidence strings for Theme Description and Business Needs). These models are the
single source of truth - used internally and serialized at the backend boundary
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


class GenerationSignals(CamelModel):
    """Evidence strings for Theme Description + Business Needs. Empty when absent.

    Each field is a list of short source-grounded snippets (no provenance metadata -
    the UI does not surface citations, and generation only needs the text).
    """

    market_segments: list[str] = Field(default_factory=list)
    funding_model_signals: list[str] = Field(default_factory=list)
    market_opportunity: list[str] = Field(default_factory=list)
    business_solution_objectives: list[str] = Field(default_factory=list)
    value_proposition: list[str] = Field(default_factory=list)
    estimated_benefits: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    resources_needed: list[str] = Field(default_factory=list)
    digital_experience_signals: list[str] = Field(default_factory=list)
    product_availability_signals: list[str] = Field(default_factory=list)
    plan_signals: list[str] = Field(default_factory=list)
    network_signals: list[str] = Field(default_factory=list)
    product_pairing_signals: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    operational_signals: list[str] = Field(default_factory=list)
    reporting_signals: list[str] = Field(default_factory=list)
    training_signals: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CondensedTicket(CamelModel):
    """Full condense output. The backend stores this and replays it downstream."""

    ticket_id: str
    ticket_title: str
    primary_source: str  # "idea_card" | "attachments_fallback"
    attachments_used: list[str] = Field(default_factory=list)
    summary_fields: SummaryFields
    generation_signals: GenerationSignals
    description: str
    raw_text: str  # consolidated description + extracted attachment text
