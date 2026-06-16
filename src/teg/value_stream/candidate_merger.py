"""Merge the two retrieval lanes into a bounded, ranked review pool.

build_candidates - aggregate the historical hits' VS labels into per-VS support,
  union with the catalogue (semantic) hits, and assign each a lane/bucket.
select_review_pool - gate weak candidates, rank, and fill the candidate window in
  lane priority order (semantic+historic, then historic-only, then semantic-only).

Ranking uses only semantic score and historical evidence - no per-stream special
casing. Shapes live in teg.value_stream.models; thresholds in CandidateMergePolicy.
"""

from __future__ import annotations

from teg.domain.value_stream import Lane
from teg.integrations.search import HistoricalHit, ValueStreamHit
from teg.value_stream.config import ValueStreamConfig
from teg.value_stream.models import CandidateMergePolicy, ValueStreamCandidate


def derive_runtime(
    requested_count: int,
    *,
    config: ValueStreamConfig = ValueStreamConfig(),
) -> tuple[int, int, CandidateMergePolicy]:
    """Derive (vs_top_k, historical_top_k, policy) for a requested count.

    Fetch is capped at the catalogue size and auto-bumped for large requests; the
    LLM window is floored at the requested count (so we can return what was asked)
    and capped at what retrieval can supply; the semantic-only lane stays small (it
    is the noisiest) while semantic+historic fills the window.
    """
    vs_top_k = min(config.semantic_fetch_cap, max(config.semantic_fetch_k, requested_count + 5))
    upper_bound = vs_top_k + config.historical_fetch_k
    default_window = min(upper_bound, requested_count + config.window_headroom)
    window = min(upper_bound, max(config.llm_candidate_window or default_window, requested_count))
    policy = CandidateMergePolicy(
        window=window,
        max_semantic_plus_historic=window,
        max_historic_only=config.historical_fetch_k,
        max_semantic_only=min(5, max(3, int(window * 0.20))),
        max_supporting_tickets=config.max_supporting_tickets,
        generic_penalty_scale=config.generic_penalty_scale,
        generic_earned_hits=config.generic_earned_hits,
    )
    return vs_top_k, config.historical_fetch_k, policy


def build_candidates(
    value_stream_hits: list[ValueStreamHit],
    historical_hits: list[HistoricalHit],
    *,
    max_supporting_tickets: int = 2,
    base_rates: dict[str, float] | None = None,
    vs_details: dict[str, dict] | None = None,
) -> list[ValueStreamCandidate]:
    """Merge the two lanes into candidates.

    A historic candidate is pure co-occurrence + frequency + similarity. The ingestion
    direct/implied classification and its reason/evidence snippets were removed (an ablation
    showed they added no relevance and slightly hurt), so the historic lane carries only the
    VS id/name plus the support scores derived from retrieval.
    """
    by_id: dict[str, ValueStreamCandidate] = {}

    details = vs_details or {}
    for rank, hit in enumerate(value_stream_hits, start=1):
        if not hit.value_stream_id:
            continue
        # Selection-prompt context (description/category/trigger/value) comes from the governed
        # catalogue when provided (the lean index carries only id+name); else from the hit.
        d = details.get(hit.value_stream_id, {})
        candidate = by_id.setdefault(
            hit.value_stream_id,
            ValueStreamCandidate(
                value_stream_id=hit.value_stream_id,
                value_stream_name=hit.value_stream_name,
                value_stream_description=d.get("description") or hit.value_stream_description,
            ),
        )
        candidate.from_semantic = True
        candidate.semantic_score = hit.score
        candidate.semantic_rank = rank
        candidate.category = d.get("category") or hit.category
        candidate.trigger = d.get("trigger") or hit.trigger
        candidate.value_proposition = d.get("valueProposition") or hit.value_proposition

    for vs_id, pairs in _group_historical_by_vs(historical_hits).items():
        first_label = pairs[0][1]
        candidate = by_id.setdefault(
            vs_id,
            ValueStreamCandidate(
                value_stream_id=vs_id,
                value_stream_name=first_label.value_stream_name,
            ),
        )
        ticket_ids = _unique(hit.ticket_id for hit, _ in pairs if hit.ticket_id)
        scores = [hit.score for hit, _ in pairs]
        candidate.from_historical = True
        candidate.supporting_ticket_count = len(ticket_ids)
        candidate.source_ticket_ids = ticket_ids[:max_supporting_tickets]
        candidate.best_support_score = max(scores, default=0.0)
        candidate.avg_support_score = (sum(scores) / len(scores)) if scores else 0.0
        candidate.weighted_support = round(
            _support_weight(candidate.best_support_score) * candidate.supporting_ticket_count, 4
        )

    rates = base_rates or {}
    for candidate in by_id.values():
        candidate.lane = _lane(candidate)
        candidate.base_rate = rates.get(candidate.value_stream_id, 0.0)
    return list(by_id.values())


def select_review_pool(
    candidates: list[ValueStreamCandidate],
    *,
    policy: CandidateMergePolicy = CandidateMergePolicy(),
) -> list[ValueStreamCandidate]:
    """Fill the review window in lane-priority order.

    Preferred fill: gated candidates within each lane's cap (the high-precision mix,
    semantic+historic -> historic-only -> semantic-only). If that underfills the
    window - e.g. a thin or empty historic lane, or semantic scores below the floor -
    backfill greedily from the remaining candidates, relaxing caps and gates, so the
    pool is never starved. Gates/caps therefore shape preference under surplus, not
    hard exclusion. The LLM still does the final selection.
    """
    semantic_plus = sorted(
        (c for c in candidates if c.lane == "semantic_plus_historic"),
        key=lambda c: _sort_semantic_plus_historic(c, policy),
    )
    historic_only = sorted(
        (c for c in candidates if c.lane == "historic_only"), key=_sort_historic_only
    )
    semantic_only = sorted(
        (c for c in candidates if c.lane == "semantic_only"),
        key=lambda c: _sort_semantic_only(c, policy),
    )

    pool: list[ValueStreamCandidate] = []
    pool += semantic_plus[: policy.max_semantic_plus_historic]
    room = max(0, policy.window - len(pool))
    pool += [c for c in historic_only if _is_good_historic_only(c, policy)][
        : min(policy.max_historic_only, room)
    ]
    room = max(0, policy.window - len(pool))
    pool += [c for c in semantic_only if _is_strong_semantic_only(c, policy)][
        : min(policy.max_semantic_only, room)
    ]

    # Backfill: top up from whatever is left (lane priority preserved) so a missing
    # or weak lane never starves the pool. Caps/gates above were the preferred shape.
    if len(pool) < policy.window:
        chosen = {c.value_stream_id for c in pool}
        remaining = [
            c
            for c in (*semantic_plus, *historic_only, *semantic_only)
            if c.value_stream_id not in chosen
        ]
        pool += remaining[: policy.window - len(pool)]

    return pool[: policy.window]


def _group_historical_by_vs(historical_hits):
    grouped: dict[str, list] = {}
    for hit in historical_hits:
        for label in hit.value_streams:
            if label.value_stream_id:
                grouped.setdefault(label.value_stream_id, []).append((hit, label))
    return grouped


def _lane(candidate: ValueStreamCandidate) -> Lane:
    if candidate.from_semantic and candidate.from_historical:
        return "semantic_plus_historic"
    if candidate.from_semantic:
        return "semantic_only"
    return "historic_only"


def _is_good_historic_only(c: ValueStreamCandidate, policy: CandidateMergePolicy) -> bool:
    return (
        c.supporting_ticket_count >= policy.historic_min_hits
        or c.best_support_score >= policy.historic_min_best
        or c.weighted_support >= policy.historic_min_weighted
    )


def _is_strong_semantic_only(c: ValueStreamCandidate, policy: CandidateMergePolicy) -> bool:
    # A broad stream (high base_rate) needs a stronger semantic match to qualify on name
    # alone, unless earned by history - the penalty raises its effective floor.
    return (c.semantic_score - _generic_penalty(c, policy)) >= policy.semantic_min_score


def _generic_penalty(c: ValueStreamCandidate, policy: CandidateMergePolicy) -> float:
    """Rank penalty for a broad/generic stream that history hasn't earned.

    scale * base_rate, applied only when the stream lacks real historical backing (fewer
    than generic_earned_hits supporting tickets and no direct hit). Continuous in base_rate,
    so broader streams are demoted more - no hardcoded list, no hard threshold.
    """
    if policy.generic_penalty_scale <= 0.0:
        return 0.0
    if c.supporting_ticket_count >= policy.generic_earned_hits:
        return 0.0
    return policy.generic_penalty_scale * c.base_rate


def _sort_semantic_plus_historic(c: ValueStreamCandidate, policy: CandidateMergePolicy) -> tuple:
    # Blend semantic with historical signal so strong historical evidence isn't buried
    # under a marginally-better-semantic candidate with only one hit.
    boost = min(1.0, c.supporting_ticket_count / 10.0) * 0.20 + c.best_support_score * 0.15
    blended = c.semantic_score + boost - _generic_penalty(c, policy)
    return (
        -blended,
        -c.semantic_score,
        -c.best_support_score,
        -c.weighted_support,
        -c.supporting_ticket_count,
        c.value_stream_name.lower(),
    )


def _sort_semantic_only(c: ValueStreamCandidate, policy: CandidateMergePolicy) -> tuple:
    return (-(c.semantic_score - _generic_penalty(c, policy)), c.value_stream_name.lower())


def _sort_historic_only(c: ValueStreamCandidate) -> tuple:
    return (
        -c.best_support_score,
        -c.weighted_support,
        -c.supporting_ticket_count,
        -c.avg_support_score,
        c.value_stream_name.lower(),
    )


def _support_weight(score: float) -> float:
    if score >= 0.80:
        return 1.0
    if score >= 0.70:
        return 0.6
    if score >= 0.60:
        return 0.3
    return 0.0


def _unique(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out
