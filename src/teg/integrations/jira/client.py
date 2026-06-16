"""Jira source protocol + records.

The live idea-card path fetches a ticket and its attachments from Jira. The
condense step depends on these protocols (not a concrete HTTP client) so it can be
unit-tested with fakes. Real implementations live alongside this module and are
configured from :class:`teg.config.settings.Settings`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class JiraAttachment:
    """Attachment metadata from Jira. ``content_url`` is the absolute download URL."""

    filename: str
    content_url: str = ""
    mime_type: str = ""
    size_bytes: int = 0


@dataclass
class JiraTicket:
    ticket_id: str
    title: str
    description: str
    attachments: list[JiraAttachment] = field(default_factory=list)


@runtime_checkable
class JiraClient(Protocol):
    async def fetch_ticket(self, ticket_id: str) -> JiraTicket: ...

    async def download_attachment(self, attachment: JiraAttachment) -> bytes: ...
