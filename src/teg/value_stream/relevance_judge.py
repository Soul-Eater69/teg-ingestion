"""Eval-only LLM-as-judge: is a predicted value stream genuinely relevant to the ticket?

Exact-GT match is harsh - it scores a business-relevant pick as wrong whenever it isn't the
BA's exact choice (sibling/near-twin streams). This judge gives a second, GT-independent view:
for each value stream, does the ticket's workflow genuinely initiate, feed, or depend on it?
Used to compute judge-adjusted precision (are our 'false positives' actually relevant) and
judge-adjusted recall (are our 'misses' actually supported by the ticket, or GT label noise).

Caveat: a judge can be lenient and the attractors are attractors *because* they look plausible,
so this tends to read OPTIMISTIC vs the BA's intent. Report it alongside strict GT, not instead.
"""

from __future__ import annotations

from pydantic import Field

from teg.domain.base import CamelModel
from teg.integrations.llm import LLMClient

_SYSTEM = (
    "You are a Senior Healthcare Business Analyst auditing value-stream impact mapping. For each "
    "value stream listed, decide if the idea card's change genuinely impacts it: the ticket's "
    "workflow initiates, feeds, or depends on that value stream's end-to-end process. Mark "
    "relevant=true ONLY for genuine operational impact or an explicit naming in the card. Mark "
    "relevant=false for mere thematic or keyword adjacency, and for broad streams that merely "
    "relate loosely. Be strict - when impact is not concrete, it is not relevant."
)


class VSRelevance(CamelModel):
    entity_id: str
    relevant: bool = False
    reason: str = ""


class VSRelevanceList(CamelModel):
    judgements: list[VSRelevance] = Field(default_factory=list)


async def judge_value_streams(
    *,
    query: str,
    items: list[tuple[str, str, str]],  # (entity_id, name, description)
    llm_client: LLMClient,
) -> dict[str, bool]:
    """Return {entity_id: relevant} for each value stream judged against the ticket."""
    if not items:
        return {}
    blocks = "\n\n".join(
        f"entity_id: {i}\nname: {n}" + (f"\ndescription: {d}" if d else "") for i, n, d in items
    )
    user = (
        f"IDEA CARD:\n{query}\n\n"
        f"Judge each value stream's relevance to this ticket:\n\n{blocks}"
    )
    result = await llm_client.complete(system=_SYSTEM, user=user, schema=VSRelevanceList)
    return {j.entity_id: j.relevant for j in result.judgements}
