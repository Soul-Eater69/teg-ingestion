"""Internal data shapes for the Value Stream layer (retrieval -> merge -> selection).

These are pipeline internals shared across the value_stream modules; the wire/output
records live in teg.domain.value_stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from teg.domain.value_stream import Lane
from teg.integrations.search import HistoricalHit, ValueStreamHit


@dataclass
class RetrievalResult:
    value_stream_hits: list[ValueStreamHit] = field(default_factory=list)
    historical_hits: list[HistoricalHit] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateMergePolicy:
    """Tuning knobs for the review pool. Defaults are the eval-winning config."""

    window: int = 18  # max candidates sent to the LLM
    max_semantic_plus_historic: int = 18
    max_historic_only: int = 6
    max_semantic_only: int = 3
    # historic-only gate: any one of these qualifies it
    historic_min_hits: int = 1
    historic_min_best: float = 0.55
    historic_min_weighted: float = 0.5
    # semantic-only gate floor
    semantic_min_score: float = 1.00
    # supporting tickets / evidence kept per candidate
    max_supporting_tickets: int = 2
    # data-driven generic/broad-stream penalty: subtract (scale * base_rate) from a
    # candidate's ranking score, UNLESS it is earned by historical evidence (hits >=
    # generic_earned_hits, or any direct hit). 0.0 scale disables it. Replaces the POC's
    # hardcoded generic/risky list with a corpus-frequency prior - no stream names in code.
    generic_penalty_scale: float = 0.0
    generic_earned_hits: int = 3


@dataclass
class ValueStreamCandidate:
    value_stream_id: str
    value_stream_name: str
    value_stream_description: str = ""
    category: str = ""
    trigger: str = ""
    value_proposition: str = ""
    from_semantic: bool = False
    from_historical: bool = False
    base_rate: float = 0.0  # corpus tag-frequency (0-1); high = broad/generic stream
    semantic_score: float = 0.0
    semantic_rank: int | None = None
    supporting_ticket_count: int = 0
    best_support_score: float = 0.0
    avg_support_score: float = 0.0
    weighted_support: float = 0.0
    source_ticket_ids: list[str] = field(default_factory=list)
    lane: Lane = "semantic_only"
