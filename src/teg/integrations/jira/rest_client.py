"""Jira REST implementation of JiraClient (async).

Fetches an issue's summary/description/attachments and downloads attachment bytes
via the attachment's absolute content URL. Auth is a Bearer PAT set on the injected
httpx client. Only what condense needs - no JQL/create/link/writeback.
"""

from __future__ import annotations

import httpx

from teg.config.settings import Settings
from teg.integrations.jira.client import JiraAttachment, JiraTicket

_ISSUE_FIELDS = "summary,description,attachment"


class JiraRestClient:
    def __init__(self, http_client: httpx.AsyncClient, *, api_version: str = "2") -> None:
        self._http = http_client
        self._api_version = api_version

    async def fetch_ticket(self, ticket_id: str) -> JiraTicket:
        response = await self._http.get(
            f"/rest/api/{self._api_version}/issue/{ticket_id}",
            params={"fields": _ISSUE_FIELDS},
        )
        response.raise_for_status()
        fields = (response.json() or {}).get("fields") or {}
        attachments = [
            JiraAttachment(
                filename=str(item.get("filename") or ""),
                content_url=str(item.get("content") or ""),
                mime_type=str(item.get("mimeType") or ""),
                size_bytes=int(item.get("size") or 0),
            )
            for item in (fields.get("attachment") or [])
        ]
        return JiraTicket(
            ticket_id=ticket_id,
            title=str(fields.get("summary") or ""),
            description=str(fields.get("description") or ""),
            attachments=attachments,
        )

    async def download_attachment(self, attachment: JiraAttachment) -> bytes:
        response = await self._http.get(attachment.content_url)
        response.raise_for_status()
        return response.content


def build_jira_client(settings: Settings) -> JiraRestClient:
    http_client = httpx.AsyncClient(
        base_url=settings.jira_base_url,
        headers={"Authorization": f"Bearer {settings.jira_token}"},
        timeout=settings.jira_timeout_seconds,
        verify=settings.jira_verify_ssl,
    )
    return JiraRestClient(http_client, api_version=settings.jira_api_version)
