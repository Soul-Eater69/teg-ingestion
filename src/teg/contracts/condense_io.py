"""Contract A - Condense. Backend -> us; backend stores the response.

The backend sends only a ticket id. We fetch from Jira, locate the idea card
(idea_card.ppt/pptx), and fall back to the top-4 attachments when it is absent.
The condensed records live in ``teg.domain.condensed`` (single source of truth) and
serialize to camelCase JSON. JSON Schema for the backend:
``CondenseResponse.model_json_schema(by_alias=True)``.
"""

from __future__ import annotations

from teg.domain.base import CamelModel
from teg.domain.condensed import CondensedTicket  # re-exported for the boundary


class CondenseRequest(CamelModel):
    ticket_id: str  # the only input; we resolve the idea card / attachments from Jira


class CondenseResponse(CamelModel):
    condensed: CondensedTicket
    model: str
    prompt_version: str
    # Per-phase wall-clock (diagnostics; like ThemeGenerationResponse.latency_ms). Extraction =
    # attachment download + text extract + consolidate; summarization = the condense LLM pass.
    extraction_seconds: float = 0.0
    summarization_seconds: float = 0.0


__all__ = ["CondenseRequest", "CondenseResponse", "CondensedTicket"]
