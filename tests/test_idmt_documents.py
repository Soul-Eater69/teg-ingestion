"""IDMT/ER + Theme Cosmos document builders (Generator B doc shapes)."""

from __future__ import annotations

from teg.domain.condensed import CondensedTicket, SummaryFields
from teg.ingestion.documents.idmt_documents import build_idmt_document, build_theme_document
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest, ExtractedTheme


def _condensed() -> CondensedTicket:
    return CondensedTicket(
        ticket_id="IDMT-19761",
        ticket_title="CP 2026 Women's and Family Health",
        primary_source="idea_card",
        summary_fields=SummaryFields(
            generated_summary="Automate appeals handling",
            business_problem="Manual appeals are slow",
            business_capability="Faster appeal resolution",
            key_terms=["appeals", "Medicare"],
            stakeholders=["Claims Ops"],
            systems_and_products=["Salesforce"],
        ),
        description="Gate 0 link and idea card",
        raw_text="full consolidated text",
    )


def _er() -> ExtractedEngagementRequest:
    return ExtractedEngagementRequest(
        stable_id="3364549",
        key="IDMT-19761",
        title="CP 2026 Women's and Family Health",
        created_date="2024-05-31T08:12:12-05:00",
        modified_date="2025-12-31T09:47:10-06:00",
        created_by="U133178",
        themes=[],
    )


def test_idmt_document_shape() -> None:
    doc = build_idmt_document(er=_er(), condensed=_condensed())
    assert len(doc["id"]) == 36 and doc["id"].count("-") == 4  # uuid doc id
    assert doc["key"] == "IDMT-19761"  # business key
    assert doc["sourceId"] == "3364549"  # stable Jira id
    # deterministic: same source id -> same uuid (idempotent upsert)
    assert doc["id"] == build_idmt_document(er=_er(), condensed=_condensed())["id"]
    assert doc["source"] == "JIRA"  # all caps
    assert doc["domain"] == "WORKITEM"
    assert doc["entityType"] == "ENGAGEMENTREQUEST"  # all caps
    assert doc["createdAt"] and doc["createdBy"] == "TEG-INGESTION"  # Cosmos lifecycle, level 1
    assert doc["lastModifiedAt"] and doc["lastModifiedBy"] == "TEG-INGESTION"
    assert doc["parentRef"] == "3364549"  # an ER has no parent -> its own sourceId
    props = doc["properties"]
    assert props["summary"] == "CP 2026 Women's and Family Health"  # the ticket TITLE
    assert props["businessSummary"] == "Automate appeals handling"  # LLM summary
    assert props["creationDate"].startswith("2024-05-31")  # source created
    assert props["insightsTime"].startswith("2025-12-31")  # source last updated
    assert "generationSignals" not in props  # signals no longer stored
    assert "themes" not in props  # Themes are separate docs (via parentRef), not embedded here
    assert props["businessProblem"] == "Manual appeals are slow"
    assert props["keyTerms"] == ["appeals", "Medicare"]


def test_theme_document_shape() -> None:
    theme = ExtractedTheme(
        stable_id="3966046",
        group_key="GROUP-23618",
        summary="CP 2027 Guided Health Plans : Appeal Decision",
        description="This theme describes the processed appeal",
        created_date="2025-07-09T12:55:24-05:00",
        modified_date="2025-11-10T11:49:11-06:00",
        created_by="U447949",
    )
    doc = build_theme_document(theme, parent_er_id="3364549")
    assert len(doc["id"]) == 36  # uuid doc id
    assert doc["key"] == "GROUP-23618"  # business key
    assert doc["sourceId"] == "3966046"  # stable Jira id
    assert doc["source"] == "JIRA"  # all caps
    assert doc["domain"] == "WORKITEM"
    assert doc["entityType"] == "THEME"  # all caps
    assert doc["parentRef"] == "3364549"  # parent ER's sourceId
    assert doc["createdAt"] and doc["createdBy"] == "TEG-INGESTION"  # Cosmos lifecycle
    props = doc["properties"]
    assert props["summary"] == "CP 2027 Guided Health Plans : Appeal Decision"  # ISSUE title
    assert props["description"].startswith("This theme")
    assert props["valueStream"] == {"valueStreamId": "", "valueStreamName": ""}  # from the field
    assert props["creationDate"].startswith("2025-07-09")  # source created


def test_restamp_sets_lifecycle_to_use_time_not_extraction() -> None:
    from teg.ingestion.documents.idmt_documents import restamp

    doc = {
        "createdAt": "2025-11-01T00:00:00+00:00",       # extraction time
        "lastModifiedAt": "2025-11-01T00:00:00+00:00",
        "properties": {"creationDate": "2025-07-09T00:00:00+00:00"},  # source Jira fact - untouched
    }
    restamp(doc, when="2026-06-12T10:00:00+00:00")

    assert doc["createdAt"] == "2026-06-12T10:00:00+00:00"
    assert doc["lastModifiedAt"] == "2026-06-12T10:00:00+00:00"
    assert doc["properties"]["creationDate"] == "2025-07-09T00:00:00+00:00"  # source date preserved
