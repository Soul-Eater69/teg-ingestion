"""to_cosmos_doc: adapt an ingestion doc to the org Cosmos container schema."""

from __future__ import annotations

from teg.integrations.cosmos.documents import to_cosmos_doc


def _er_doc() -> dict:
    return {
        "id": "uuid-1",
        "key": "IDMT-31170",
        "sourceId": "3364549",
        "source": "Jira",
        "entityType": "EngagementRequest",
        "createdBy": "teg-ingestion",
        "lastModifiedBy": "teg-ingestion",
        "properties": {
            "summary": "CareWay+",
            "rawText": "clean text",
            "themes": [{"valueStreamId": "VS1", "valueStreamName": "Adjudicate Claim"}],
        },
    }


def test_adds_domain_and_uppercases_discriminators() -> None:
    out = to_cosmos_doc(_er_doc())
    assert out["domain"] == "WORKITEM"
    assert out["entityType"] == "ENGAGEMENTREQUEST"
    assert out["source"] == "JIRA"
    assert out["createdBy"] == "TEG-INGESTION"
    assert out["lastModifiedBy"] == "TEG-INGESTION"


def test_drops_themes_but_keeps_other_properties() -> None:
    out = to_cosmos_doc(_er_doc())
    assert "themes" not in out["properties"]
    assert out["properties"]["summary"] == "CareWay+"
    assert out["properties"]["rawText"] == "clean text"


def test_does_not_mutate_input() -> None:
    doc = _er_doc()
    to_cosmos_doc(doc)
    assert doc["entityType"] == "EngagementRequest"  # original untouched
    assert "themes" in doc["properties"]
    assert "domain" not in doc


def test_theme_doc_without_themes_property_is_fine() -> None:
    theme = {"id": "u2", "entityType": "Theme", "source": "Jira", "createdBy": "teg-ingestion",
             "lastModifiedBy": "teg-ingestion", "properties": {"summary": "t"}}
    out = to_cosmos_doc(theme)
    assert out["domain"] == "WORKITEM"
    assert out["entityType"] == "THEME"
    assert out["properties"] == {"summary": "t"}
