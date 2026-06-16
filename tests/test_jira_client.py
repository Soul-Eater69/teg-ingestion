"""JiraRestClient tests using a mocked HTTP transport - no live Jira calls."""

from __future__ import annotations

import httpx
import pytest

from teg.integrations.jira import JiraAttachment, JiraRestClient

_ISSUE = {
    "fields": {
        "summary": "Claims Intake Modernization",
        "description": "Automate manual claims intake.",
        "attachment": [
            {
                "filename": "idea_card.pptx",
                "content": "https://jira.test/secure/attachment/1/idea_card.pptx",
                "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "size": 2048,
            }
        ],
    }
}


def _client(handler) -> JiraRestClient:
    http = httpx.AsyncClient(base_url="https://jira.test", transport=httpx.MockTransport(handler))
    return JiraRestClient(http, api_version="2")


async def test_fetch_ticket_parses_fields_and_attachments() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["fields"] = request.url.params.get("fields")
        return httpx.Response(200, json=_ISSUE)

    ticket = await _client(handler).fetch_ticket("IDMT-1")

    assert captured["path"] == "/rest/api/2/issue/IDMT-1"
    assert captured["fields"] == "summary,description,attachment"
    assert ticket.title == "Claims Intake Modernization"
    assert ticket.description == "Automate manual claims intake."
    assert len(ticket.attachments) == 1
    assert ticket.attachments[0].filename == "idea_card.pptx"
    assert ticket.attachments[0].content_url == "https://jira.test/secure/attachment/1/idea_card.pptx"
    assert ticket.attachments[0].size_bytes == 2048


async def test_fetch_ticket_handles_missing_attachments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"fields": {"summary": "T", "description": "D"}})

    ticket = await _client(handler).fetch_ticket("IDMT-2")
    assert ticket.attachments == []


async def test_download_attachment_returns_bytes_from_content_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/secure/attachment/1/idea_card.pptx"
        return httpx.Response(200, content=b"PPTX-BYTES")

    attachment = JiraAttachment(
        filename="idea_card.pptx",
        content_url="https://jira.test/secure/attachment/1/idea_card.pptx",
    )
    content = await _client(handler).download_attachment(attachment)
    assert content == b"PPTX-BYTES"


async def test_fetch_ticket_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errorMessages": ["not found"]})

    with pytest.raises(httpx.HTTPStatusError):
        await _client(handler).fetch_ticket("IDMT-404")
