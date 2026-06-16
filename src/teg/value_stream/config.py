"""Retrieval and review-window tuning knobs for Value Stream prediction.

These were loose module constants in the merger; grouped here as one explicit,
env-overridable shape (built from Settings in bootstrap), mirroring CondenseConfig.
derive_runtime turns them into a per-request CandidateMergePolicy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValueStreamConfig:
    semantic_fetch_k: int = 50  # VS catalogue hits to fetch
    semantic_fetch_cap: int = 50  # hard cap - the catalogue has <=50 streams
    historical_fetch_k: int = 6  # similar past tickets shown as precedent (tuning: 8 was within
    # noise, 10 diluted - keep 6; see docs/vs_selection_tuning.md). Also the historic-only cap.
    llm_candidate_window: int = 18  # review-pool size for a ~10-stream request
    window_headroom: int = 8  # buffer over the requested count when the window is derived
    max_supporting_tickets: int = 2  # source tickets kept per candidate
    use_historic_lane: bool = True  # use the historic ER lane at all (ablation: False = semantic-only)
    generic_penalty_scale: float = 0.6  # broad-stream rank penalty = scale * attractor_signal (0 = off)
    generic_earned_hits: int = 3  # historical hits that exempt a broad stream from the penalty
    min_confidence: float = 0.0  # abstention floor (0-1); >0 keeps only confident picks, no padding
    # Candidate-pool construction. Production default is `evidence` (tuning winner - see
    # docs/vs_selection_tuning.md): the full 50-stream catalogue is the candidate pool and the
    # similar past tickets are shown as a separate EVIDENCE block. The others are experiment modes:
    #   merge         - VS + historic merged into the review pool
    #   all50         - all VS candidates, no historic (pool = full catalogue)
    #   topk          - top-K VS by semantic score only (K = llm_candidate_window)
    #   historic_only - candidates only from the historic lane's VS
    #   evidence      - all VS candidates + historic shown as a separate EVIDENCE block (no merge)
    selection_mode: str = "evidence"
    selection_prompt_override: str = ""  # prompt name to use instead of the mode default (A/B prompts)
    # How each historic ticket is rendered in the evidence block:
    #   snippet (search snippet) | summary (businessSummary) | description | raw
    # 'summary' is the winner (see docs/vs_representation_eda.md): same quality as raw/description,
    # cheapest prompt, keeps the LLM call ~3.7s. raw@7k historic was slow (132s) for no gain.
    historic_repr: str = "summary"
    historic_budget: int = 0  # truncate the historic 'raw' text to ~N tokens (0 = no cap)
    # Semantic scores in candidate blocks are off: the VS-lane ranking is weak (R@10 ~0.26) so the
    # score is a misleading hint; the eval showed it's a wash-to-slightly-better to drop it.
    show_candidate_scores: bool = False
    # Two-stage score-then-select (experiment): instead of one 'pick N' call, the LLM scores EVERY
    # candidate 0-1 independently, then we take the top-N by score deterministically. Tests whether
    # the model's independent scoring (which rated dropped GT >= a pick 81% of the time) recovers
    # the near-misses the single call drops. evidence mode only. See docs/vs_representation_eda.md.
    score_select: bool = False
