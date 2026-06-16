"""Value Stream selection: the review-pool LLM call that picks the final streams.

Runs the (eval-winning) selection prompt over the rendered candidate blocks, then
resolves each pick back to its catalogue candidate, scales confidence to 0-100,
dedupes, and enforces the requested count.
"""

from __future__ import annotations

from pydantic import Field

from teg.domain.base import CamelModel
from teg.domain.value_stream import SupportType, ValueStreamRecommendation
from teg.integrations.llm import LLMClient
from teg.prompts.loader import load_prompt
from teg.value_stream.candidate_blocks import render_candidate_blocks
from teg.value_stream.models import ValueStreamCandidate

_FILL_CONFIDENCE = 30.0  # the 0.30 floor (as a percent) for count-fill picks


class ValueStreamPick(CamelModel):
    """One LLM pick. confidence is 0-1 as emitted by the model."""

    entity_id: str
    confidence: float = 0.0
    support_type: SupportType = "implied"
    reason: str = ""


class ValueStreamSelection(CamelModel):
    """The selection LLM's structured output."""

    picks: list[ValueStreamPick] = Field(default_factory=list)


async def select_value_streams(
    *,
    query: str,
    candidates: list[ValueStreamCandidate],
    requested_count: int,
    llm_client: LLMClient,
    min_confidence: float = 0.0,
    historic_evidence: str = "",
    prompt_name: str = "value_stream/selection",
    show_scores: bool = True,
    trace: dict | None = None,
) -> list[ValueStreamRecommendation]:
    # In evidence mode the historic tickets are shown as a separate context block (not merged
    # into candidates); empty string keeps the section out of the prompt.
    evidence_block = (
        f"\nSIMILAR PAST TICKETS (evidence - the value streams these were tagged with):\n"
        f"{historic_evidence}\n" if historic_evidence else ""
    )
    prompt = load_prompt(prompt_name)
    system, user = prompt.render(
        max_select=requested_count,
        requested_final_output_count=requested_count,
        query_for_prompt=query,
        historic_evidence=evidence_block,
        candidate_blocks=render_candidate_blocks(candidates, show_scores=show_scores),
    )
    selection = await llm_client.complete(system=system, user=user, schema=ValueStreamSelection)
    recommendations = _resolve(selection, candidates)
    if trace is not None:
        # The LLM's OWN pick count (deduped, valid ids), before any count enforcement/padding -
        # so eval can see whether the model followed the requested count or we forced it.
        trace["llm_pick_count"] = len(recommendations)
        trace["requested_count"] = requested_count
    if min_confidence > 0.0:
        # Abstention: honor the prompt's "skip non-matches" - keep only confident picks, cap at
        # the count, never pad. requested_count is an upper bound, not a quota.
        floor = min_confidence * 100
        return [r for r in recommendations if r.confidence >= floor][:requested_count]
    return _enforce_count(recommendations, candidates, requested_count)


class ScoredCandidate(CamelModel):
    """One candidate's independent relevance score (score-then-select)."""

    entity_id: str
    score: float = 0.0
    support_type: SupportType = "implied"
    reason: str = ""


class CandidateScoring(CamelModel):
    scores: list[ScoredCandidate] = Field(default_factory=list)


async def score_and_select(
    *,
    query: str,
    candidates: list[ValueStreamCandidate],
    requested_count: int,
    llm_client: LLMClient,
    historic_evidence: str = "",
    prompt_name: str = "value_stream/score_all_recall",
    show_scores: bool = True,
    trace: dict | None = None,
) -> list[ValueStreamRecommendation]:
    """Two-stage: the LLM scores EVERY candidate independently, then take the top-N by score.

    Replaces the single 'pick N' call. The scoring is done with no count pressure (each candidate on
    its own), then the cut is deterministic - so a relevant candidate the single call would drop is
    kept whenever it out-scores a weaker one. Falls back to the candidate order for any unscored id.
    """
    evidence_block = (
        f"\nSIMILAR PAST TICKETS (evidence - the value streams these were tagged with):\n"
        f"{historic_evidence}\n" if historic_evidence else ""
    )
    prompt = load_prompt(prompt_name)
    system, user = prompt.render(
        query_for_prompt=query,
        historic_evidence=evidence_block,
        candidate_blocks=render_candidate_blocks(candidates, show_scores=show_scores),
    )
    result = await llm_client.complete(system=system, user=user, schema=CandidateScoring)

    by_id = {c.value_stream_id: c for c in candidates}
    scored: dict[str, ScoredCandidate] = {}
    for s in result.scores:
        if s.entity_id in by_id and s.entity_id not in scored:  # catalogue ids only, deduped
            scored[s.entity_id] = s
    # Rank by score desc; unscored candidates sink to the bottom in their original order.
    ranked = sorted(
        candidates,
        key=lambda c: scored[c.value_stream_id].score if c.value_stream_id in scored else -1.0,
        reverse=True,
    )
    top = ranked[:requested_count]
    if trace is not None:
        # 'picked' by the LLM = candidates it scored at/above the cut's score (its own judgement),
        # before the deterministic top-N. Lets eval compare to requested_count like the single call.
        cut_score = scored[top[-1].value_stream_id].score if top and top[-1].value_stream_id in scored else 0.0
        trace["llm_pick_count"] = sum(1 for s in scored.values() if s.score >= cut_score and s.score > 0)
        trace["requested_count"] = requested_count

    out: list[ValueStreamRecommendation] = []
    for c in top:
        s = scored.get(c.value_stream_id)
        confidence = (s.score if s else _FILL_CONFIDENCE / 100) * 100
        out.append(_recommend(c, confidence, s.support_type if s else "implied", s.reason if s else ""))
    return out


def _resolve(
    selection: ValueStreamSelection, candidates: list[ValueStreamCandidate]
) -> list[ValueStreamRecommendation]:
    by_id = {c.value_stream_id: c for c in candidates}
    out: list[ValueStreamRecommendation] = []
    seen: set[str] = set()
    for pick in selection.picks:
        candidate = by_id.get(pick.entity_id)
        if candidate is None or candidate.value_stream_id in seen:
            continue  # only catalogue entity_ids, deduped
        seen.add(candidate.value_stream_id)
        confidence = min(max(pick.confidence, 0.0), 1.0) * 100
        out.append(_recommend(candidate, confidence, pick.support_type, pick.reason))
    return out


def _enforce_count(
    recommendations: list[ValueStreamRecommendation],
    candidates: list[ValueStreamCandidate],
    requested_count: int,
) -> list[ValueStreamRecommendation]:
    # Exact count: trim extras, or fill from the ranked pool at the confidence floor.
    if len(recommendations) >= requested_count:
        return recommendations[:requested_count]
    chosen = {r.value_stream_id for r in recommendations}
    for candidate in candidates:
        if len(recommendations) >= requested_count:
            break
        if candidate.value_stream_id in chosen:
            continue
        recommendations.append(_recommend(candidate, _FILL_CONFIDENCE, "implied", ""))
        chosen.add(candidate.value_stream_id)
    return recommendations


def _recommend(
    candidate: ValueStreamCandidate,
    confidence: float,
    support_type: SupportType,
    reason: str,
) -> ValueStreamRecommendation:
    return ValueStreamRecommendation(
        value_stream_id=candidate.value_stream_id,
        value_stream_name=candidate.value_stream_name,
        confidence=round(confidence, 1),
        support_type=support_type,
        reason=reason,
        # Source tickets are the historic analogs that justify an INFERRED pick, so they
        # are surfaced only for implied picks. A direct pick is explicitly named by the
        # idea card and needs no historic backing. (semantic_only picks have none anyway.)
        source_tickets=candidate.source_ticket_ids if support_type == "implied" else [],
    )
