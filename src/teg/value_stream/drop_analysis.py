"""Why does the LLM drop GT it saw? Deterministic displacement / bias analysis (Level A).

At `count=gt` every dropped GT (a false negative) is paired with a wrong pick (a false positive) -
the model swapped a correct value stream for an incorrect one. This reconstructs those swaps from
the per-ticket gt/predicted sets (no LLM) and surfaces the SYSTEMATIC pattern the coarse
'lower_priority' bucket hides:

  - per-VS drop rate   : when a value stream IS ground truth, how often the LLM fails to pick it
  - per-VS over-pick   : value streams the LLM picks when they are NOT ground truth
  - confusion pairs    : 'GT-X dropped -> Y picked instead', the most common substitutions
  - popularity bias    : does the model swap low-base-rate GT for high-base-rate (generic) picks?

These point straight at prompt levers (e.g. a chronically over-picked generic VS, or specific GT
losing to a popular sibling). Pure + unit-tested; the script feeds it parsed CSV rows.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class VsDropStat:
    vs_id: str
    gt_count: int = 0  # tickets where this VS is ground truth
    fn_count: int = 0  # of those, how many the LLM dropped (false negative)
    pred_count: int = 0  # tickets where the LLM picked this VS
    fp_count: int = 0  # of those, how many were wrong (false positive)

    @property
    def drop_rate(self) -> float:
        return self.fn_count / self.gt_count if self.gt_count else 0.0

    @property
    def over_rate(self) -> float:
        return self.fp_count / self.pred_count if self.pred_count else 0.0


@dataclass
class DropAnalysis:
    per_vs: dict[str, VsDropStat] = field(default_factory=dict)
    confusion: Counter = field(default_factory=Counter)  # (dropped_gt, picked_instead) -> count
    n_tickets: int = 0
    total_fn: int = 0
    total_fp: int = 0
    # Popularity bias: mean corpus base-rate of the wrong picks vs the dropped GT. picks >> drops
    # means the model defaults to common/generic value streams over the specific correct ones.
    mean_base_rate_dropped: float = 0.0
    mean_base_rate_overpicked: float = 0.0

    def most_dropped(self, top: int = 15) -> list[VsDropStat]:
        """VS most often dropped when they are GT (min 3 GT appearances, ranked by drop rate)."""
        eligible = [s for s in self.per_vs.values() if s.gt_count >= 3]
        return sorted(eligible, key=lambda s: (s.drop_rate, s.fn_count), reverse=True)[:top]

    def most_overpicked(self, top: int = 15) -> list[VsDropStat]:
        """VS most often picked when NOT GT (ranked by false-positive count)."""
        return sorted(self.per_vs.values(), key=lambda s: s.fp_count, reverse=True)[:top]

    def top_confusions(self, top: int = 20) -> list[tuple[tuple[str, str], int]]:
        return self.confusion.most_common(top)


def analyze_drops(
    tickets: list[tuple[set[str], list[str]]],
    *,
    base_rates: dict[str, float] | None = None,
) -> DropAnalysis:
    """Build the displacement analysis from (gt_set, predicted_list) per ticket.

    ``base_rates`` = corpus popularity per VS (fraction of tickets it's GT), used for the bias check.
    """
    base_rates = base_rates or {}
    out = DropAnalysis(n_tickets=len(tickets))
    drop_br: list[float] = []
    pick_br: list[float] = []

    for gt, predicted in tickets:
        pred_set = set(predicted)
        fn = gt - pred_set  # dropped GT
        fp = pred_set - gt  # wrong picks
        out.total_fn += len(fn)
        out.total_fp += len(fp)

        for vs in gt:
            out.per_vs.setdefault(vs, VsDropStat(vs)).gt_count += 1
        for vs in pred_set:
            out.per_vs.setdefault(vs, VsDropStat(vs)).pred_count += 1
        for vs in fn:
            out.per_vs[vs].fn_count += 1
            drop_br.append(base_rates.get(vs, 0.0))
        for vs in fp:
            out.per_vs[vs].fp_count += 1
            pick_br.append(base_rates.get(vs, 0.0))
        # Each dropped GT was swapped for one of the wrong picks - count every pairing.
        for dropped in fn:
            for picked in fp:
                out.confusion[(dropped, picked)] += 1

    out.mean_base_rate_dropped = sum(drop_br) / len(drop_br) if drop_br else 0.0
    out.mean_base_rate_overpicked = sum(pick_br) / len(pick_br) if pick_br else 0.0
    return out
