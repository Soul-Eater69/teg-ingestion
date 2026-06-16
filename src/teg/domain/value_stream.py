"""Value Stream prediction output records.

Single source of truth for the VS output shapes - used internally and serialized at
the backend boundary (camelCase via CamelModel). The internal retrieval/merge
candidate shape lives with the retrieval/merger code, not here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from teg.domain.base import CamelModel

Lane = Literal["semantic_plus_historic", "historic_only", "semantic_only"]
SupportType = Literal["direct", "implied"]


class HistoricalTicket(CamelModel):
    """A matched historical Engagement Request, shown for SME selection."""

    ticket_id: str
    title: str
    score: float
    snippet: str = ""


class ValueStreamRecommendation(CamelModel):
    """A recommended Value Stream, resolved to the approved catalogue.

    ``confidence`` is a 0-100 percentage (the model emits 0-1; selection scales it).
    ``reason`` is prompt-guided to a short phrase; not hard-enforced so a slightly
    longer model value never fails validation. ``source_tickets`` is populated only
    for historically-backed picks (the retrieval lane gates this internally but is
    not surfaced in the output).
    """

    value_stream_id: str
    value_stream_name: str
    confidence: float = Field(ge=0.0, le=100.0)
    support_type: SupportType
    reason: str
    source_tickets: list[str] = Field(default_factory=list)
