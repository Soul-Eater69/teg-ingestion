"""Fetch an Engagement Request and its linked Themes from Jira (ingestion).

Parsing (pure, from raw issue JSON) is separated from fetching (httpx) so the mapping is
unit-testable. Linked themes are taken from ANY issue-link type (a theme may be linked any
way), not only implement-links. Each linked issue is fetched once for its stable id, content,
dates, and its Business Value Stream field; the Value Stream is read straight from that field
("<name> {<id>}") - no catalogue match, no LLM. Links whose issue has no Business Value Stream
value are not themes for our purpose and are dropped.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from teg.config.settings import Settings
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest, ExtractedTheme
from teg.ingestion.extraction.value_stream_field import parse_value_stream

# Jira issue fields we request (the REST `fields` param is a comma-joined list).
_COMMON_FIELDS = ("summary", "description", "created", "updated", "reporter", "status")
_ER_FIELDS = (*_COMMON_FIELDS, "issuelinks")  # the ER also needs its linked issues


def _text(value: object) -> str:
    return str(value or "").strip()


def _actor(fields: dict) -> str:
    reporter = fields.get("reporter")
    if isinstance(reporter, dict):
        return _text(reporter.get("name") or reporter.get("key") or reporter.get("displayName"))
    return ""


def _status(fields: dict) -> str:
    status = fields.get("status")
    return _text(status.get("name")) if isinstance(status, dict) else ""


def _linked_issue_keys(fields: dict) -> list[str]:
    """Keys of ALL linked issues, any link type, deduped.

    Each issuelink carries only one end (inwardIssue or outwardIssue - the other side is the
    ER itself), so we take whichever is present. We do not filter by link type or issue type
    here; whether a linked issue is a real theme is decided downstream by whether it carries a
    Business Value Stream value.
    """
    keys: list[str] = []
    for link in fields.get("issuelinks") or []:
        issue = link.get("inwardIssue") or link.get("outwardIssue")
        if isinstance(issue, dict):
            key = _text(issue.get("key"))
            if key and key not in keys:
                keys.append(key)
    return keys


def parse_engagement_request(issue: dict) -> tuple[ExtractedEngagementRequest, list[str]]:
    """Return the ER (without theme bodies) plus the linked issue keys to fetch."""
    fields = issue.get("fields") or {}
    er = ExtractedEngagementRequest(
        stable_id=_text(issue.get("id")),
        key=_text(issue.get("key")),
        title=_text(fields.get("summary")),
        description=_text(fields.get("description")),
        status=_status(fields),
        created_date=_text(fields.get("created")),
        modified_date=_text(fields.get("updated")),
        created_by=_actor(fields),
    )
    return er, _linked_issue_keys(fields)


def parse_theme(issue: dict, *, value_stream_field: str) -> ExtractedTheme:
    """Build a Theme, reading its Value Stream from the Business Value Stream field."""
    fields = issue.get("fields") or {}
    vs = parse_value_stream(fields.get(value_stream_field))
    return ExtractedTheme(
        stable_id=_text(issue.get("id")),
        group_key=_text(issue.get("key")),
        summary=_text(fields.get("summary")),
        value_stream_id=vs[1] if vs else "",
        value_stream_name=vs[0] if vs else "",
        description=_text(fields.get("description")),
        created_date=_text(fields.get("created")),
        modified_date=_text(fields.get("updated")),
        created_by=_actor(fields),
    )


class JiraIngestionSource:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        api_version: str = "2",
        value_stream_field_id: str = "",
        value_stream_field_name: str = "Business Value Stream",
    ) -> None:
        self._http = http_client
        self._api_version = api_version
        self._vs_field_id = value_stream_field_id  # customfield_#####; discovered if empty
        self._vs_field_name = value_stream_field_name

    async def fetch_engagement_request(self, ticket_id: str) -> ExtractedEngagementRequest:
        vs_field = await self._value_stream_field_id()
        er, linked_keys = parse_engagement_request(await self._issue(ticket_id, _ER_FIELDS))
        theme_fields = (*_COMMON_FIELDS, vs_field)
        # Linked issues are independent fetches - run them concurrently.
        issues = await asyncio.gather(*(self._issue(key, theme_fields) for key in linked_keys))
        themes = [parse_theme(issue, value_stream_field=vs_field) for issue in issues]
        # Keep only linked issues that actually carry a Value Stream (real themes).
        return replace(er, themes=[t for t in themes if t.value_stream_id])

    async def _value_stream_field_id(self) -> str:
        """The Business Value Stream custom-field id, discovered by name once and cached."""
        if self._vs_field_id:
            return self._vs_field_id
        response = await self._http.get(f"/rest/api/{self._api_version}/field")
        response.raise_for_status()
        wanted = self._vs_field_name.strip().lower()
        for field in response.json() or []:
            if _text(field.get("name")).lower() == wanted:
                self._vs_field_id = _text(field.get("id"))
                return self._vs_field_id
        raise RuntimeError(
            f"Jira field '{self._vs_field_name}' not found; set jira_value_stream_field "
            "to its customfield_##### id"
        )

    async def _issue(self, issue_id: str, fields: tuple[str, ...]) -> dict:
        response = await self._http.get(
            f"/rest/api/{self._api_version}/issue/{issue_id}",
            params={"fields": ",".join(fields)},
        )
        response.raise_for_status()
        return response.json() or {}


def build_jira_ingestion_source(settings: Settings) -> JiraIngestionSource:
    http_client = httpx.AsyncClient(
        base_url=settings.jira_base_url,
        headers={"Authorization": f"Bearer {settings.jira_token}"},
        timeout=settings.jira_timeout_seconds,
        verify=settings.jira_verify_ssl,
    )
    return JiraIngestionSource(
        http_client,
        api_version=settings.jira_api_version,
        value_stream_field_id=settings.jira_value_stream_field,
        value_stream_field_name=settings.jira_value_stream_field_name,
    )
