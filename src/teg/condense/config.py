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
    # greedy packing). 8 lets the 5th-8th be included when they fit the budget (corpus max is 12);
    # the token budget, not this count, is the real cap.
    max_attachments: int = 8
