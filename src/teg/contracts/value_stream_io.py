"""Contract B - Value Stream prediction. Backend -> us.

Backend replays the stored summaryFields. We return ranked recommendations plus the
top-6 historical analogs for the backend's HITL selection step. The records live in
``teg.domain.value_stream`` (single source of truth); this module adds the request /
response envelope.
"""

from __future__ import annotations

from pydantic import Field

from teg.domain.base import CamelModel
from teg.domain.condensed import SummaryFields
from teg.domain.value_stream import HistoricalTicket, ValueStreamRecommendation


class ValueStreamRequest(CamelModel):
    ticket_id: str
    summary_fields: SummaryFields  # ALWAYS used for retrieval (embedding); summary stays the matcher
    # Optional raw ticket text for the SELECTION prompt only (not retrieval). When set, the LLM that
    # picks the VS reads this instead of the summary - "summary to find, raw to decide". Empty -> the
    # prompt falls back to the summary. This is what keeps retrieval on the (embeddable) summary while
    # the prompt gets full raw context.
    prompt_text: str = ""
    requested_count: int = 10  # exact number of value streams to return (the only VS knob)
    # Optional free-text steer. May ONLY set the count (e.g. "give me 6"); a count parsed from
    # it overrides requested_count. Everything else is ignored - the raw text never reaches an
    # LLM prompt (structural guardrail against injection / off-task instructions).
    custom_instruction: str | None = None
    # Only the SME-selected analogs; omit to auto-use the retrieved set.
    selected_historical_ticket_ids: list[str] = Field(default_factory=list)
    # Historic tickets to drop from the analog lane (eval leave-one-out: a ticket must not
    # see itself as its own evidence; also a sensible guard if the ticket is already indexed).
    exclude_ticket_ids: list[str] = Field(default_factory=list)


class ValueStreamResponse(CamelModel):
    ticket_id: str
    recommendations: list[ValueStreamRecommendation]
    historical_tickets: list[HistoricalTicket] = Field(default_factory=list)
    model: str
    latency_ms: int = 0


__all__ = [
    "ValueStreamRequest",
    "ValueStreamResponse",
    "HistoricalTicket",
    "ValueStreamRecommendation",
]
