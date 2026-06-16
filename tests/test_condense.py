"""Condense unit tests. All clients are fakes - no live Jira/LLM calls."""

from __future__ import annotations

import pytest

from teg.condense.attachment_ranker import select_attachments
from teg.condense.condenser import condense
from teg.condense.config import CondenseConfig
from teg.condense.ticket_context import resolve_from_ticket
from teg.contracts.condense_io import CondenseRequest
from teg.domain.condensed import GenerationSignals, SummaryFields
from teg.integrations.jira import JiraAttachment, JiraTicket
from teg.services.condense_service import CondenseService


# ---- fakes ---------------------------------------------------------------

class FakeJira:
    def __init__(self, ticket: JiraTicket) -> None:
        self._ticket = ticket

    async def fetch_ticket(self, ticket_id: str) -> JiraTicket:
        return self._ticket

    async def download_attachment(self, attachment: JiraAttachment) -> bytes:
        return f"bytes::{attachment.filename}".encode()


class FakeExtractor:
    def extract(self, filename: str, content: bytes) -> str:
        return f"extracted text of {filename}"


_LLM_JSON = {
    "summaryFields": {
        "generatedSummary": "A proposed change to claims intake.",
        "businessProblem": "Manual intake is slow.",
        "businessCapability": "Automated claims intake.",
        "keyTerms": ["claims", "intake"],
        "stakeholders": ["Claims Ops"],
        "systemsAndProducts": ["ClaimsHub"],
    },
    "generationSignals": {
        "marketSegments": ["Medicare members"],
        "dependencies": [],
        # other 16 keys intentionally absent -> must become empty lists
    },
}


class FakeLLM:
    """Returns the canned slice for the requested schema (summary | signals call)."""

    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload if payload is not None else _LLM_JSON

    async def complete(self, *, system: str, user: str, schema):
        if schema is SummaryFields:
            return schema.model_validate(self._payload["summaryFields"])
        if schema is GenerationSignals:
            return schema.model_validate(self._payload["generationSignals"])
        return schema.model_validate(self._payload)


def _ticket(attachments: list[JiraAttachment]) -> JiraTicket:
    return JiraTicket(
        ticket_id="IDMT-1",
        title="Claims Intake Modernization",
        description="Automate manual claims intake.",
        attachments=attachments,
    )


# ---- attachment ranker ---------------------------------------------------

def test_idea_card_is_sole_source_when_present() -> None:
    selection = select_attachments(
        [JiraAttachment("deck.pdf"), JiraAttachment("idea_card.pptx"), JiraAttachment("notes.docx")]
    )
    assert selection.idea_card is not None
    assert selection.idea_card.filename == "idea_card.pptx"
    assert selection.fallback == []


def test_idea_card_requires_exact_name() -> None:
    # near-miss names are NOT treated as the idea card
    selection = select_attachments(
        [JiraAttachment("the_idea_card.pptx"), JiraAttachment("idea_card_v2.pptx")]
    )
    assert selection.idea_card is None


def test_fallback_takes_top_four_ppt_pdf_doc() -> None:
    selection = select_attachments(
        [
            JiraAttachment("a.docx"),
            JiraAttachment("b.pdf"),
            JiraAttachment("c.pptx"),
            JiraAttachment("d.pptx"),
            JiraAttachment("e.pdf"),
            JiraAttachment("ignore.txt"),
        ]
    )
    assert selection.idea_card is None
    assert [a.filename for a in selection.fallback] == ["c.pptx", "d.pptx", "b.pdf", "e.pdf"]


# ---- ticket context ------------------------------------------------------

async def test_resolve_prefers_idea_card() -> None:
    ticket = _ticket([JiraAttachment("brief.pdf"), JiraAttachment("idea_card.pptx")])
    ctx = await resolve_from_ticket(ticket, FakeJira(ticket), FakeExtractor())
    assert ctx.primary_source == "idea_card"
    assert ctx.attachments_used == ["idea_card.pptx"]
    assert "[DESCRIPTION]" in ctx.consolidated_text
    assert "[DOCUMENT: idea_card.pptx]" in ctx.consolidated_text


async def test_resolve_falls_back_to_top_attachments() -> None:
    ticket = _ticket([JiraAttachment("a.docx"), JiraAttachment("b.pdf")])
    ctx = await resolve_from_ticket(ticket, FakeJira(ticket), FakeExtractor())
    assert ctx.primary_source == "attachments_fallback"
    assert ctx.attachments_used == ["b.pdf", "a.docx"]


class _LongExtractor:
    def extract(self, filename: str, content: bytes) -> str:
        return "X" * 5000


async def test_description_full_and_attachments_greedily_packed_to_budget() -> None:
    ticket = _ticket([JiraAttachment("a.pdf"), JiraAttachment("b.pdf")])
    ctx = await resolve_from_ticket(
        ticket, FakeJira(ticket), _LongExtractor(), config=CondenseConfig(doc_char_budget=400)
    )
    assert ticket.description in ctx.consolidated_text  # authoritative, never truncated
    # GREEDY: description (counts against the 400 budget); the FIRST doc takes the whole remaining
    # budget, the second is dropped (budget exhausted) - not an even 200/200 split.
    assert ctx.consolidated_text.count("X") == 400 - len(ticket.description)
    assert ctx.consolidated_text.count("[DOCUMENT:") == 1  # second doc dropped


async def test_idea_card_used_in_full_ignoring_budget() -> None:
    ticket = _ticket([JiraAttachment("idea_card.pptx")])
    ctx = await resolve_from_ticket(
        ticket, FakeJira(ticket), _LongExtractor(), config=CondenseConfig(doc_char_budget=400)
    )
    assert ctx.consolidated_text.count("X") == 5000  # idea card is used complete, not capped


async def test_fallback_drops_near_empty_docs() -> None:
    ticket = _ticket([JiraAttachment("a.pdf")])  # FakeExtractor yields < min_doc_chars
    ctx = await resolve_from_ticket(ticket, FakeJira(ticket), FakeExtractor())
    assert "[DESCRIPTION]" in ctx.consolidated_text
    assert "[DOCUMENT:" not in ctx.consolidated_text  # near-empty extraction dropped


def test_select_attachments_respects_max_fallback() -> None:
    selection = select_attachments(
        [JiraAttachment("a.pdf"), JiraAttachment("b.pdf"), JiraAttachment("c.pdf")],
        max_fallback=2,
    )
    assert selection.idea_card is None
    assert [a.filename for a in selection.fallback] == ["a.pdf", "b.pdf"]


def test_select_attachments_skips_oversized_fallback() -> None:
    selection = select_attachments(
        [
            JiraAttachment("big.pdf", size_bytes=50_000_000),
            JiraAttachment("small.pdf", size_bytes=1_000),
            JiraAttachment("unknown.pdf", size_bytes=0),
        ],
        max_bytes=10_000_000,
    )
    names = [a.filename for a in selection.fallback]
    assert "big.pdf" not in names  # oversized skipped pre-download
    assert names == ["small.pdf", "unknown.pdf"]  # small kept; unknown size kept


# ---- condenser -----------------------------------------------------------

async def test_condense_maps_fields_and_keeps_absent_signals_empty() -> None:
    ticket = _ticket([JiraAttachment("idea_card.pptx")])
    ctx = await resolve_from_ticket(ticket, FakeJira(ticket), FakeExtractor())
    condensed = await condense(ctx, FakeLLM())

    assert condensed.summary_fields.generated_summary == "A proposed change to claims intake."
    assert condensed.summary_fields.key_terms == ["claims", "intake"]
    assert condensed.generation_signals.market_segments == ["Medicare members"]
    # absent categories never invented:
    assert condensed.generation_signals.notes == []
    assert condensed.generation_signals.reporting_signals == []


# ---- service (Contract A) ------------------------------------------------

async def test_service_condenses_from_ticket_id_and_serializes_camel_case() -> None:
    ticket = _ticket([JiraAttachment("idea_card.pptx")])
    service = CondenseService(FakeJira(ticket), FakeLLM(), FakeExtractor(), model_name="test-model")
    response = await service.condense(CondenseRequest(ticket_id="IDMT-1"))

    data = response.model_dump(by_alias=True)
    assert data["condensed"]["ticketId"] == "IDMT-1"
    assert data["condensed"]["primarySource"] == "idea_card"
    assert data["condensed"]["summaryFields"]["businessProblem"] == "Manual intake is slow."
    assert data["condensed"]["generationSignals"]["marketSegments"] == ["Medicare members"]
    assert data["model"] == "test-model"


def test_request_requires_ticket_id() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CondenseRequest()
