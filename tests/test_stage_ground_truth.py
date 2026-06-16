"""Stage ground-truth extraction from Jira Themes/Epics (offline; fake Jira client)."""

from __future__ import annotations

import asyncio

from teg.ingestion.catalogues.models import CatalogueStage, CatalogueValueStream
from teg.ingestion.ground_truth.stage_ground_truth import (
    build_ticket_stage_ground_truth,
    canonicalize_stage,
    parse_capabilities,
)


def _stage(stage_id: str, name: str) -> CatalogueStage:
    return CatalogueStage(
        stage_id=stage_id, stage_name=name, stage_description="", sequence=0,
        entrance_criteria="", exit_criteria="", value_items="", active=True,
        created_date="", modified_date="",
    )


def _catalogue() -> list[CatalogueValueStream]:
    return [
        CatalogueValueStream(
            value_stream_id="VSR001", value_stream_name="Resolve Appeal",
            value_stream_description="", value_proposition="", trigger="", category="",
            assumptions="", defined_terms="", active=True, created_date="", created_by="",
            modified_date="", modified_by="",
            stages=[_stage("ST1", "Intake & Triage"), _stage("ST2", "Resolve Appeal Decision")],
        )
    ]


class FakeJira:
    """Serves canned issues by key and canned JQL searches by exact query string."""

    def __init__(self, issues: dict[str, dict], searches: dict[str, list[dict]]) -> None:
        self._issues = issues
        self._searches = searches

    async def get_issue(self, key: str, *, fields) -> dict:
        return self._issues[key]

    async def search(self, jql: str, *, fields) -> list[dict]:
        return self._searches.get(jql, [])


def _stage_select(vs: str, stage: str) -> dict:
    """The Value Stream Stage field's cascading-select shape: parent = VS, child = stage."""
    return {"value": vs, "child": {"value": stage}}


def _epic(key: str, summary: str, *, stage_field: object = None, status: str = "In Progress") -> dict:
    return {"key": key, "fields": {
        "summary": summary, "issuetype": {"name": "Epic"}, "status": {"name": status},
        "customfield_18700": stage_field,  # Value Stream Stage (cascading select)
    }}


def _fixture() -> FakeJira:
    ticket = {"key": "IDMT-1", "fields": {
        "summary": "Appeals automation", "description": "Automate appeals",
        "issuelinks": [
            {"type": {"name": "Relates"}, "outwardIssue": {"key": "GROUP-9"}},
            {"type": {"name": "Relates"}, "outwardIssue": {"key": "REL-5"}},  # not a VS theme
        ],
    }}
    theme = {"key": "GROUP-9", "fields": {
        "summary": "Appeals theme", "description": "Theme description text",
        "customfield_20900": "Members can appeal decisions quickly",
        "customfield_18602": [{"value": "Capability Mgmt"}],  # L2 on the Theme
        "customfield_18603": "Case Intake; Triage Routing",  # L3 on the Theme
        "Business Value Stream": "Resolve Appeal {VSR001}",
        "issuelinks": [  # an Epic reached only via an implement link (not via parent search)
            {"type": {"name": "Implements", "outward": "implements"},
             "outwardIssue": {"key": "EPIC-3", "fields": {"issuetype": {"name": "Epic"}}}},
        ],
    }}
    rel = {"key": "REL-5", "fields": {"summary": "unrelated", "Business Value Stream": None}}
    stage_select = _stage_select("Resolve Appeal {VSR001}", "Intake & Triage {ST1}")
    # EPIC-2: stage read straight from the Value Stream Stage cascading field (authoritative).
    epic2 = _epic("EPIC-2", "Some unrelated epic title", stage_field=stage_select)
    # EPIC-3: field empty -> falls back to canonicalizing the summary against the catalogue.
    epic3 = _epic("EPIC-3", "Resolve Appeal Decision")
    # EPIC-X cancelled -> skipped. EPIC-T is To Do -> KEPT (a planned stage is still valid GT).
    epic_x = _epic("EPIC-X", "x", stage_field=stage_select, status="Cancelled")
    epic_t = _epic("EPIC-T", "t", stage_field=stage_select, status="To Do")
    # EPIC-OLD: a field stage whose id is NOT in the catalogue (retired) -> dropped from GT.
    epic_old = _epic("EPIC-OLD", "old",
                     stage_field=_stage_select("Resolve Appeal {VSR001}", "Retired Stage {ST_OLD}"))
    return FakeJira(
        issues={"IDMT-1": ticket, "GROUP-9": theme, "REL-5": rel, "EPIC-3": epic3},
        searches={'"Parent Link" = GROUP-9 AND issuetype = Epic': [epic2, epic_x, epic_t, epic_old]},
    )


def test_build_ticket_stage_ground_truth_end_to_end() -> None:
    gt = asyncio.run(build_ticket_stage_ground_truth(
        "IDMT-1", jira=_fixture(), catalogue=_catalogue(), value_stream_field="Business Value Stream",
    ))

    assert gt.ticket_id == "IDMT-1"
    assert gt.description == "Automate appeals"
    assert len(gt.themes) == 1  # REL-5 (no VS field) is skipped

    theme = gt.themes[0]
    assert (theme.value_stream_id, theme.value_stream_name) == ("VSR001", "Resolve Appeal")
    assert theme.theme_description == "Theme description text"
    assert theme.business_needs == "Members can appeal decisions quickly"
    # L2/L3 are theme-level (verified on a live GROUP issue).
    assert theme.l2_capabilities == ["Capability Mgmt"]
    assert theme.l3_capabilities == ["Case Intake", "Triage Routing"]

    by_key = {s.epic_key: s for s in theme.stages}
    # parent-link + issue-link Epics + EPIC-T (To Do, kept); EPIC-X (cancelled) skipped; deduped.
    assert set(by_key) == {"EPIC-2", "EPIC-3", "EPIC-T"}
    assert by_key["EPIC-T"].stage_id == "ST1" and by_key["EPIC-T"].match_method == "field"

    # EPIC-2: stage from the Value Stream Stage field (authoritative) - id+name direct, no fuzzy.
    s2 = by_key["EPIC-2"]
    assert (s2.stage_id, s2.stage_name, s2.match_method) == ("ST1", "Intake & Triage", "field")
    assert s2.confidence == 1.0

    # EPIC-3: field empty -> summary canonicalized against the catalogue; via the implement link.
    s3 = by_key["EPIC-3"]
    assert s3.stage_id == "ST2" and s3.match_method == "exact"


def test_canonicalize_stage_exact_fuzzy_and_unresolved() -> None:
    stages = _catalogue()[0].stages
    # exact via prefix-stripped suffix
    assert canonicalize_stage("Resolve Appeal - Intake & Triage", stages,
                              value_stream_name="Resolve Appeal")[:3] == ("ST1", "Intake & Triage", "exact")
    # fuzzy: a near miss still resolves above threshold
    sid, _, method, conf = canonicalize_stage("Resolve Appeal Decisions", stages)
    assert sid == "ST2" and method == "fuzzy" and conf >= 0.86
    # unresolved: nothing close
    assert canonicalize_stage("Completely unrelated work", stages)[2] == "unresolved"
    # no catalogue stages -> unresolved
    assert canonicalize_stage("Anything", [])[2] == "unresolved"


def test_parse_capabilities_shapes() -> None:
    assert parse_capabilities(None) == []
    assert parse_capabilities({"value": "A"}) == ["A"]
    assert parse_capabilities([{"value": "A"}, {"name": "B"}, {"value": "A"}]) == ["A", "B"]
    assert parse_capabilities("X; Y\nZ") == ["X", "Y", "Z"]
    assert parse_capabilities("Single") == ["Single"]
