"""Eval-only probe: why did the selector drop a candidate it actually saw?

Given the exact review-pool blocks the selection LLM read, the picks it made, and a set
of dropped candidate ids (the GT misses bucketed as ``llm_dropped``), ask the model to
classify each drop into a small fixed taxonomy. This runs AFTER scoring - it never feeds
back into the prediction or the metrics, so it can safely look at the dropped ids. It is a
post-hoc reason classifier over the same context, not the original call's chain of thought.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from teg.domain.base import CamelModel
from teg.integrations.llm import LLMClient
from teg.value_stream.candidate_blocks import render_candidate_blocks
from teg.value_stream.models import ValueStreamCandidate

DropReason = Literal[
    "off_topic",  # genuinely not relevant to this ticket
    "lower_priority",  # relevant, but less central than the picks (count-limited it out)
    "near_duplicate_of_pick",  # a sibling / near-twin was picked instead
    "thin_context",  # relevant, but this candidate's own block was too sparse to justify
    "other",
]

_SYSTEM = (
    "You are auditing a value-stream selection. A model was shown the candidate blocks below "
    "for a ticket and picked some of them. For each candidate id you are asked about (all of "
    "which were NOT picked), state the single most likely reason it was left out, using only "
    "these codes: off_topic (not relevant to the ticket), lower_priority (relevant but less "
    "central than the picks), near_duplicate_of_pick (a near-twin was picked instead), "
    "thin_context (relevant but its block was too sparse to justify), other. Add a short note. "
    "Judge only from the ticket and the blocks shown."
)


class DropExplanation(CamelModel):
    entity_id: str
    reason_code: DropReason = "other"
    note: str = ""


class DropExplanations(CamelModel):
    explanations: list[DropExplanation] = Field(default_factory=list)


async def explain_drops(
    *,
    query: str,
    review_pool: list[ValueStreamCandidate],
    picked_ids: list[str],
    dropped_ids: list[str],
    llm_client: LLMClient,
) -> dict[str, DropExplanation]:
    """Return {entity_id: explanation} for each dropped id the model can account for."""
    if not dropped_ids:
        return {}
    by_id = {c.value_stream_id: c for c in review_pool}
    picked = [by_id[i].value_stream_name for i in picked_ids if i in by_id]
    asked = [f"{i} ({by_id[i].value_stream_name})" for i in dropped_ids if i in by_id]
    if not asked:
        return {}

    user = (
        f"TICKET:\n{query}\n\n"
        f"PICKED: {', '.join(picked) or '(none)'}\n\n"
        f"CANDIDATE BLOCKS (what the selector saw):\n{render_candidate_blocks(review_pool)}\n\n"
        f"Explain why each of these was NOT picked:\n" + "\n".join(asked)
    )
    result = await llm_client.complete(system=_SYSTEM, user=user, schema=DropExplanations)
    return {e.entity_id: e for e in result.explanations}


# --------------------------------------------------------------------------- #
# Level B: score EVERY candidate, so we can see how close a dropped GT was to the cut
# --------------------------------------------------------------------------- #

_SCORE_SYSTEM = (
    "You are scoring how relevant each value-stream candidate is to a ticket, independently. "
    "For EVERY candidate id below, give a relevance score from 0.0 (irrelevant) to 1.0 (clearly "
    "central to this ticket's work). Score each on its own merits - do NOT limit how many are "
    "high. Judge only from the ticket and the candidate blocks shown."
)


class CandidateScore(CamelModel):
    entity_id: str
    score: float = 0.0


class CandidateScores(CamelModel):
    scores: list[CandidateScore] = Field(default_factory=list)


async def score_candidates(
    *,
    query: str,
    review_pool: list[ValueStreamCandidate],
    llm_client: LLMClient,
) -> dict[str, float]:
    """Return {entity_id: 0..1 relevance} for every pool candidate (independent scoring).

    Lets eval compute a dropped GT's MARGIN to the cut: if a dropped GT scores >= a candidate the
    model actually picked, the selection contradicted its own relevance judgement (a near-miss the
    prompt can likely recover); if it scores far below, the drop is a genuine low-relevance call.
    """
    if not review_pool:
        return {}
    user = (
        f"TICKET:\n{query}\n\n"
        f"CANDIDATE BLOCKS:\n{render_candidate_blocks(review_pool)}\n\n"
        f"Score every candidate id (0.0-1.0)."
    )
    result = await llm_client.complete(system=_SCORE_SYSTEM, user=user, schema=CandidateScores)
    return {s.entity_id: max(0.0, min(1.0, s.score)) for s in result.scores}


# --------------------------------------------------------------------------- #
# Level C: comparative probe - why these picks over THIS dropped GT, specifically
# --------------------------------------------------------------------------- #

SwapReason = Literal[
    "picks_more_specific",  # the picks match the ticket more precisely than the dropped GT
    "dropped_too_broad",  # the dropped GT is broad/downstream, only loosely implied
    "no_evidence_for_dropped",  # nothing in the ticket points to the dropped GT
    "picks_more_prominent",  # the ticket emphasises the picks' area, the dropped GT is secondary
    "dropped_is_valid_should_have_picked",  # on reflection the dropped GT is as applicable as a pick
    "other",
]

_SWAP_SYSTEM = (
    "You are auditing one value-stream selection. The model picked some value streams for a ticket "
    "and left out one that was actually correct (ground truth). Explain, grounded in THIS ticket's "
    "evidence, why the picks won out over the left-out one. Choose the single best code: "
    "picks_more_specific (picks match the ticket more precisely), dropped_too_broad (the left-out "
    "one is broad/downstream, only loosely implied), no_evidence_for_dropped (nothing in the ticket "
    "points to it), picks_more_prominent (the ticket emphasises the picks' area), "
    "dropped_is_valid_should_have_picked (it is genuinely as applicable as a pick - a real miss), "
    "other. Add a one-line note citing the ticket."
)


class SwapExplanation(CamelModel):
    dropped_id: str
    reason_code: SwapReason = "other"
    note: str = ""


class SwapExplanations(CamelModel):
    explanations: list[SwapExplanation] = Field(default_factory=list)


async def explain_swaps(
    *,
    query: str,
    review_pool: list[ValueStreamCandidate],
    picked_ids: list[str],
    dropped_ids: list[str],
    llm_client: LLMClient,
) -> dict[str, SwapExplanation]:
    """Comparative: for each dropped GT, why the picks beat IT (richer than the post-hoc bucket)."""
    if not dropped_ids:
        return {}
    by_id = {c.value_stream_id: c for c in review_pool}
    picked = [by_id[i].value_stream_name for i in picked_ids if i in by_id]
    asked = [f"{i} ({by_id[i].value_stream_name})" for i in dropped_ids if i in by_id]
    if not asked or not picked:
        return {}
    user = (
        f"TICKET:\n{query}\n\n"
        f"PICKED value streams: {', '.join(picked)}\n\n"
        f"CANDIDATE BLOCKS (what the model saw):\n{render_candidate_blocks(review_pool)}\n\n"
        f"For each of these CORRECT-but-left-out value streams, explain why the picks beat it:\n"
        + "\n".join(asked)
    )
    result = await llm_client.complete(system=_SWAP_SYSTEM, user=user, schema=SwapExplanations)
    return {e.dropped_id: e for e in result.explanations}


# --------------------------------------------------------------------------- #
# Grounding: was the evidence for the dropped GT actually present? (the actionable split)
# --------------------------------------------------------------------------- #

GroundingBucket = Literal[
    # The ticket has NO evidence for this GT - dropping it was justified (GT is likely a broad /
    # downstream BA choice or label noise; not a model error, not prompt-fixable).
    "no_context_for_gt",
    # The ticket clearly supports this GT and the candidate block showed enough - it SHOULD have
    # been picked. This is the real, prompt-fixable miss (the F1 headroom).
    "context_present_but_dropped",
    # Only indirect / downstream / broad evidence - borderline, reasonably deprioritised.
    "weak_broad_context",
    "other",
]

_GROUND_SYSTEM = (
    "You audit value-stream selection. For each CORRECT-but-left-out value stream, judge ONLY the "
    "EVIDENCE: does this ticket contain support for it, and was that support visible in the "
    "candidate block shown? Choose one code: "
    "no_context_for_gt (the ticket has no evidence for it - leaving it out was justified), "
    "context_present_but_dropped (the ticket clearly supports it and the block showed enough - it "
    "should have been picked), "
    "weak_broad_context (only indirect/downstream/broad evidence - borderline), other. "
    "Add a one-line note quoting the ticket evidence, or noting its absence. Be strict: only call "
    "it context_present_but_dropped when the ticket genuinely supports it."
)


class GroundingExplanation(CamelModel):
    dropped_id: str
    grounding: GroundingBucket = "other"
    note: str = ""


class GroundingExplanations(CamelModel):
    explanations: list[GroundingExplanation] = Field(default_factory=list)


async def classify_drop_grounding(
    *,
    query: str,
    review_pool: list[ValueStreamCandidate],
    dropped_ids: list[str],
    llm_client: LLMClient,
) -> dict[str, GroundingExplanation]:
    """Per dropped GT: was the supporting evidence present (fixable) or absent (justified)?"""
    if not dropped_ids:
        return {}
    by_id = {c.value_stream_id: c for c in review_pool}
    asked = [f"{i} ({by_id[i].value_stream_name})" for i in dropped_ids if i in by_id]
    if not asked:
        return {}
    user = (
        f"TICKET:\n{query}\n\n"
        f"CANDIDATE BLOCKS (what the model saw):\n{render_candidate_blocks(review_pool)}\n\n"
        f"For each left-out CORRECT value stream, classify the evidence situation:\n"
        + "\n".join(asked)
    )
    result = await llm_client.complete(system=_GROUND_SYSTEM, user=user, schema=GroundingExplanations)
    return {e.dropped_id: e for e in result.explanations}
