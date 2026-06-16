"""Jira ingestion parsing: ER + linked-issue extraction, VS from the Business Value Stream field.

Links of ANY type are followed (not only implement-links); the Value Stream is read straight
from the linked issue's Business Value Stream field ("<name> {<id>}").
"""

from __future__ import annotations

from teg.ingestion.extraction.jira_source import parse_engagement_request, parse_theme

_BVS = "customfield_10100"  # stand-in Business Value Stream field id

ER_ISSUE = {
    "id": "3364549",
    "key": "IDMT-19761",
    "fields": {
        "summary": "CP 2026 Women's and Family Health",
        "description": "Gate 0 link and idea card",
        "created": "2024-05-31T08:12:12.023-0500",
        "updated": "2025-12-31T09:47:10.733-0600",
        "reporter": {"name": "U133178", "displayName": "Lisa Yancey"},
        "issuelinks": [
            {  # implement link to a Theme
                "type": {"name": "Implement", "inward": "is implemented by", "outward": "implements"},
                "inwardIssue": {"id": "3966046", "key": "GROUP-23618",
                                "fields": {"summary": "... : Appeal Decision", "issuetype": {"name": "Theme"}}},
            },
            {  # a DIFFERENT link type (Relates) is now also followed
                "type": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
                "outwardIssue": {"id": "4001", "key": "GROUP-30000",
                                 "fields": {"summary": "... : Enrollment", "issuetype": {"name": "Theme"}}},
            },
            {  # duplicate key -> deduped
                "type": {"name": "Estimate", "inward": "is estimated by", "outward": "estimates"},
                "inwardIssue": {"id": "3966046", "key": "GROUP-23618", "fields": {"summary": "dup"}},
            },
        ],
    },
}

THEME_ISSUE = {
    "id": "3966046",
    "key": "GROUP-23618",
    "fields": {
        "summary": "CP 2027 Guided Health Plans : Appeal Decision",
        "description": "This theme describes the processed appeal",
        "created": "2025-07-09T12:55:24.147-0500",
        "updated": "2025-11-10T11:49:11.773-0600",
        "reporter": {"name": "U447949"},
        _BVS: "Resolve Appeal {VSR00074590}",
    },
}

THEME_NO_VS = {
    "id": "9999", "key": "GROUP-22287",
    "fields": {"summary": "... - BO", _BVS: None},  # no Business Value Stream value
}


def test_parse_engagement_request_follows_all_link_types_deduped() -> None:
    er, linked_keys = parse_engagement_request(ER_ISSUE)
    assert er.stable_id == "3364549" and er.key == "IDMT-19761"
    assert er.created_by == "U133178"
    # any link type is followed; the duplicate key is deduped
    assert linked_keys == ["GROUP-23618", "GROUP-30000"]


def test_parse_theme_reads_value_stream_from_field() -> None:
    theme = parse_theme(THEME_ISSUE, value_stream_field=_BVS)
    assert theme.stable_id == "3966046" and theme.group_key == "GROUP-23618"
    assert theme.value_stream_id == "VSR00074590"
    assert theme.value_stream_name == "Resolve Appeal"
    assert theme.created_by == "U447949"
    assert theme.modified_date.startswith("2025-11-10")


def test_parse_theme_without_value_stream_field_is_blank() -> None:
    theme = parse_theme(THEME_NO_VS, value_stream_field=_BVS)
    assert theme.value_stream_id == "" and theme.value_stream_name == ""
