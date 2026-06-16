"""Condense step.

Two structured LLM passes run in parallel over the resolved ticket context:
  - SUMMARY  -> summaryFields (retrieval-ready digest)
  - SIGNALS  -> generationSignals (evidence for description + business needs)
Splitting along this seam parallelizes the work (wall time ~ the slower pass) and
lets each prompt stay focused. Both output shapes are pydantic schemas; absent
signal categories default to empty lists.
"""

from __future__ import annotations

import asyncio

from teg.condense.models import ResolvedContext
from teg.domain.condensed import CondensedTicket, GenerationSignals, SummaryFields
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
    signals_system, signals_user = load_prompt("condense/signals").render(**values)

    summary_fields, generation_signals = await asyncio.gather(
        llm_client.complete(system=summary_system, user=summary_user, schema=SummaryFields),
        llm_client.complete(system=signals_system, user=signals_user, schema=GenerationSignals),
    )

    return CondensedTicket(
        ticket_id=context.ticket_id,
        ticket_title=context.ticket_title,
        primary_source=context.primary_source,
        attachments_used=list(context.attachments_used),
        summary_fields=summary_fields,
        generation_signals=generation_signals,
        description=context.description,
        raw_text=context.consolidated_text,
    )
