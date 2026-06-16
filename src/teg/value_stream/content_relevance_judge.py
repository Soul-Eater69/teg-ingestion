"""Eval-only LLM-as-judge: is a retrieved past ticket TOPICALLY similar to the query ticket?

The retrieval eval's primary relevance signal is VS-label overlap (free, end-task). That can't tell
a genuinely-similar ticket from a coincidental label match (e.g. a shared broad stream). This judge
is the diagnostic: independent of labels, it asks whether each retrieved past ticket is about the
SAME KIND of business change as the query. Comparing it to label-relevance separates real retrieval
hits from lucky label matches. Batched: one call per query judges all its retrieved tickets.
"""

from __future__ import annotations

from pydantic import Field

from teg.domain.base import CamelModel
from teg.integrations.llm import LLMClient

_SYSTEM = (
    "You audit a retrieval system for healthcare business tickets. Given a QUERY ticket and several "
    "RETRIEVED past tickets, decide for EACH retrieved ticket whether it is about the SAME KIND of "
    "business change or problem as the query - the same workflow, product area, or operational "
    "concern. Judge on substance, not shared generic words. Mark relevant=true only when a business "
    "analyst would consider it a genuine precedent for the query; mark false for tickets that merely "
    "share a domain or a keyword but address a different change. Return a judgement for every ticket."
)


class TicketRelevance(CamelModel):
    ticket_id: str
    relevant: bool = False


class TicketRelevanceList(CamelModel):
    judgements: list[TicketRelevance] = Field(default_factory=list)


async def judge_ticket_relevance(
    *,
    query: str,
    tickets: list[tuple[str, str]],  # (ticket_id, content)
    llm_client: LLMClient,
) -> dict[str, bool]:
    """Return {ticket_id: relevant} for each retrieved ticket judged against the query."""
    if not tickets:
        return {}
    blocks = "\n\n".join(f"ticket_id: {tid}\ncontent: {content}" for tid, content in tickets)
    user = (
        f"QUERY TICKET:\n{query}\n\n"
        f"Judge whether each retrieved ticket is a genuine precedent (same kind of change):\n\n{blocks}"
    )
    result = await llm_client.complete(system=_SYSTEM, user=user, schema=TicketRelevanceList)
    return {j.ticket_id: j.relevant for j in result.judgements}
