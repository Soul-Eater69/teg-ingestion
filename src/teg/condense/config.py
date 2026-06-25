"""Condense tuning knobs.

Grouped so the service / resolution signatures stay small. The idea-card path
ignores all of these (the idea card is trusted and used in full); they govern only
the heuristic fallback (no idea card -> top-N attachments).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CondenseConfig:
    # Total chars across fallback docs (split per doc). ~96k chars ≈ 24k tokens - the raw-text budget
    # from docs/token_analysis_findings.md (keep 4 attachments + ~24k tokens fits 95% of tickets
    # untouched; the rest are the huge decks, truncated here rather than dropping a whole attachment).
    doc_char_budget: int = 96_000
    # How many attachments to DOWNLOAD + extract (the budget above caps the actual content kept, via
    # greedy packing). EDA: keeping 4 retains 99% of content (the knee), and only ~10% of tickets
    # have 5+; 5 keeps that knee plus one for the content-heavy tickets. The token budget, not this
    # count, is the real cap.
    max_attachments: int = 5
