"""Extracted Jira records for ingestion (ER + its linked Themes).

The doc `id` is the STABLE Jira internal issue id; the mutable Jira key (IDMT-####,
GROUP-####) is kept separately. A linked Theme's stable id + content come from fetching
the linked issue (the issuelink only gives the key). The Value Stream is read straight from
the linked issue's Business Value Stream field (no catalogue match), so the Theme carries its
resolved value_stream_id + name.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExtractedTheme:
    """A linked Theme issue and the Value Stream read from its Business Value Stream field."""

    stable_id: str  # Jira internal issue id (e.g. 3966046)
    group_key: str  # linked issue key, e.g. GROUP-#### (mutable)
    summary: str  # linked-issue summary - the Theme title
    value_stream_id: str = ""  # from the Business Value Stream field "<name> {<id>}"
    value_stream_name: str = ""
    description: str = ""
    created_date: str = ""
    modified_date: str = ""
    created_by: str = ""


@dataclass(frozen=True)
class ExtractedEngagementRequest:
    """An IDMT Engagement Request and its linked themes."""

    stable_id: str  # Jira internal issue id (e.g. 3364549)
    key: str  # IDMT-#### (mutable)
    title: str  # Jira summary
    description: str = ""
    status: str = ""  # Jira issue status (e.g. To Do / In Progress / Cancelled)
    created_date: str = ""
    modified_date: str = ""
    created_by: str = ""
    themes: list[ExtractedTheme] = field(default_factory=list)
