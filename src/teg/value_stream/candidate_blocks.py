"""Render review-pool candidates into the compact blocks the selection prompt reads.

Each block exposes what the prompt's "how to read candidates" section expects: the
entity id to return, the lane, semantic score, and (when present) historical support.
"""

from __future__ import annotations

from teg.value_stream.models import ValueStreamCandidate


def render_candidate_blocks(candidates: list[ValueStreamCandidate], *, show_scores: bool = True) -> str:
    return "\n\n".join(_block(c, show_scores=show_scores) for c in candidates)


def _block(c: ValueStreamCandidate, *, show_scores: bool = True) -> str:
    lines = [
        f"Candidate: {c.value_stream_name}",
        f"entity_id: {c.value_stream_id}",
    ]
    # The lane + semantic score are weak/misleading signals when the semantic ranking is poor;
    # show_scores=False drops them so the model judges on business fit + (any) historical evidence.
    if show_scores:
        lines.append(f"lane: {c.lane}")
    if c.value_stream_description:
        lines.append(f"description: {c.value_stream_description}")
    if c.category:
        lines.append(f"category: {c.category}")
    if c.trigger:
        lines.append(f"trigger: {c.trigger}")
    if c.value_proposition:
        lines.append(f"value: {c.value_proposition}")

    if show_scores:
        semantic = f"semantic: score={c.semantic_score:.2f}"
        if c.semantic_rank is not None:
            semantic += f", rank={c.semantic_rank}"
        lines.append(semantic)

    if show_scores and c.from_historical:
        lines.append(
            f"historical: tickets={c.supporting_ticket_count}, "
            f"best={c.best_support_score:.2f}, avg={c.avg_support_score:.2f}, "
            f"weighted={c.weighted_support:.2f}, ids={c.source_ticket_ids}"
        )
    return "\n".join(lines)
