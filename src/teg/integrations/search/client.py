"""Search protocols + records for the two VS retrieval lanes.

VS retrieval depends on these protocols, not a concrete Azure client, so it is
unit-tested with fakes. The client owns query vectorization (integrated server-side
on the index, or internally), so the retrieval layer just passes query text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class HistoricalValueStreamLabel:
    """A Value Stream the historical ER was linked to (its ground truth: id + name)."""

    value_stream_id: str
    value_stream_name: str


@dataclass
class ValueStreamHit:
    """A VS-catalogue lane hit."""

    value_stream_id: str
    value_stream_name: str
    value_stream_description: str = ""
    category: str = ""
    trigger: str = ""
    value_proposition: str = ""
    score: float = 0.0


@dataclass
class HistoricalHit:
    """A historical Engagement Request lane hit, with the VS labels it carries."""

    ticket_id: str
    title: str
    score: float = 0.0
    snippet: str = ""
    value_streams: list[HistoricalValueStreamLabel] = field(default_factory=list)


@runtime_checkable
class SearchClient(Protocol):
    async def search_value_streams(self, query: str, *, top_k: int = 50) -> list[ValueStreamHit]:
        """VS-catalogue lane over the valueStream documents."""
        ...

    async def search_historical(self, query: str, *, top_k: int = 6) -> list[HistoricalHit]:
        """Historical-ER lane over the EngagementRequest documents."""
        ...
