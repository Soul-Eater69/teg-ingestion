"""Ticket context resolution.

Resolves the idea-card source for a ticket and consolidates it into one
section-tagged blob for the condense LLM pass. Both source paths (idea card vs
description + top-4 attachments) converge on the same :class:`ResolvedContext`.
"""

from __future__ import annotations

import asyncio

from teg.condense.attachment_ranker import select_attachments
from teg.condense.config import CondenseConfig
from teg.condense.models import ResolvedContext
from teg.integrations.files import AttachmentTextExtractor
from teg.integrations.jira import JiraAttachment, JiraClient, JiraTicket


def _section(tag: str, body: str) -> str:
    return f"[{tag}]\n{body.strip()}"


def _consolidate(
    description: str,
    documents: list[tuple[str, str]],
    *,
    doc_char_budget: int | None = None,
) -> str:
    """Combine the description (always full - the one authoritative source) with docs.

    GREEDY budget packing: the description is taken first (counts against the budget), then each
    attachment (in ranked order) takes up to the REMAINING budget, until the budget is exhausted.
    So small attachments don't waste their share, big ones aren't over-truncated, and the 5th/6th
    attachment is included whenever it still fits - the token budget is the only cap, not a count.
    ``doc_char_budget=None`` -> every doc in full (idea-card path).
    """
    docs = [(name, text) for name, text in documents if text and text.strip()]

    blocks: list[str] = []
    desc = description.strip()
    if desc:
        blocks.append(_section("DESCRIPTION", desc))
    remaining = None if doc_char_budget is None else max(0, doc_char_budget - len(desc))
    for name, text in docs:
        body = text.strip()
        if remaining is not None:
            if remaining <= 0:
                break  # budget exhausted - drop the rest
            body = body[:remaining]
            remaining -= len(body)
        if body:
            blocks.append(_section(f"DOCUMENT: {name}", body))
    return "\n\n".join(blocks)


async def resolve_from_ticket(
    ticket: JiraTicket,
    jira_client: JiraClient,
    extractor: AttachmentTextExtractor,
    *,
    config: CondenseConfig = CondenseConfig(),
) -> ResolvedContext:
    """Idea-card-first resolution. Idea card -> sole attachment (used in full); else top-N."""
    selection = select_attachments(
        ticket.attachments,
        max_fallback=config.max_attachments,
    )

    chosen: list[JiraAttachment]
    if selection.idea_card is not None:
        chosen = [selection.idea_card]
        primary_source = "idea_card"
    else:
        chosen = selection.fallback
        primary_source = "attachments_fallback"

    async def _extract(attachment: JiraAttachment) -> tuple[str, str]:
        content = await jira_client.download_attachment(attachment)
        # Extraction is synchronous CPU work - run it off the event loop so it does
        # not block concurrent downloads (pypdfium2 also releases the GIL while parsing).
        text = await asyncio.to_thread(extractor.extract, attachment.filename, content)
        return attachment.filename, text

    documents = list(await asyncio.gather(*(_extract(a) for a in chosen)))

    if primary_source == "idea_card":
        consolidated = _consolidate(ticket.description, documents)  # idea card in full
    else:
        consolidated = _consolidate(
            ticket.description,
            documents,
            doc_char_budget=config.doc_char_budget,
        )

    return ResolvedContext(
        ticket_id=ticket.ticket_id,
        ticket_title=ticket.title,
        description=ticket.description,
        primary_source=primary_source,
        attachments_used=[a.filename for a in chosen],
        consolidated_text=consolidated,
    )
