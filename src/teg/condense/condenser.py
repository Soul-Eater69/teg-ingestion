"""Condense step.

A single structured LLM pass over the resolved ticket context:
  - SUMMARY  -> summaryFields (retrieval-ready digest)
The output shape is a pydantic schema. Ingestion stores ``summary_fields`` plus the
raw description and consolidated text; it does not derive generation signals.
"""

from __future__ import annotations

from teg.condense.models import ResolvedContext
from teg.domain.condensed import CondensedTicket, SummaryFields
from teg.integrations.llm import LLMClient
from teg.prompts.loader import load_prompt


class CondenseError(RuntimeError):
    pass


async def condense(context: ResolvedContext, llm_client: LLMClient) -> CondensedTicket:
    # The char budget is applied during consolidation (ticket_context); the
    # consolidated text is already within budget here.
    if not context.consolidated_text.strip():
        raise CondenseError(f"No source text to condense for {context.ticket_id}")

    values = {"ticket_id": context.ticket_id, "consolidated_text": context.consolidated_text}
    summary_system, summary_user = load_prompt("condense/summary").render(**values)

    summary_fields = await llm_client.complete(
        system=summary_system, user=summary_user, schema=SummaryFields
    )

    return CondensedTicket(
        ticket_id=context.ticket_id,
        ticket_title=context.ticket_title,
        primary_source=context.primary_source,
        attachments_used=list(context.attachments_used),
        summary_fields=summary_fields,
        description=context.description,
        raw_text=context.consolidated_text,
    )
