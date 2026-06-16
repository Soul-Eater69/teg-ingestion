"""Catalogue loader + Cosmos/index/capability document builders (Generator A)."""

from __future__ import annotations

import json

from teg.ingestion.catalogues.loader import load_value_stream_catalogue
from teg.ingestion.documents.value_stream_documents import (
    build_catalogue_content,
    build_catalogue_document,
    build_index_document,
)

SAMPLE = {
    "source_file": "value_streams.xlsx",
    "value_stream_count": 1,
    "value_streams": [
        {
            "value_stream_id": "VSR00074583",
            "value_stream_name": "Acquire Asset",
            "value_stream_description": "End-to-end request to delivery",
            "value_proposition": "Faster asset turnaround",
            "trigger": "Asset Requester",
            "category": "Finance",
            "stakeholders": "Supplier; Procurement; Asset Requestor",
            "assumptions": "Budget approved",
            "defined_terms": "BOM = bill of materials",
            "active": True,
            "created_date": "2021-03-14",
            "created_by": "U447949",
            "modified_date": "2025-01-02",
            "modified_by": "U999999",
            "stages": [
                {
                    "stage_id": "VSS00074680",
                    "stage_name": "Request Asset",
                    "stage_description": "Submit a request for a new asset",
                    "sequence": 1,
                    "entrance_criteria": "Asset order initiated",
                    "exit_criteria": "Asset order acknowledged",
                    "value_items": "Asset order requested",
                    "stakeholders": "Asset Requestor; Procurement",
                    "active": True,
                    "created_date": "2021-03-14",
                    "modified_date": "2024-06-01",
                    "capabilities": [
                        {
                            "capability_id": "CAP-L3-1",
                            "capability_name": "Capture Asset Request",
                            "capability_description": "Record the request details",
                            "level": 3,
                            "tier": "core",
                            "active": True,
                            "level_1_id": "CAP-L1-1",
                            "level_1_name": "Manage Assets",
                            "level_2_id": "CAP-L2-1",
                            "level_2_name": "Asset Intake",
                        }
                    ],
                }
            ],
        }
    ],
}

def _load(tmp_path):
    path = tmp_path / "map.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    return load_value_stream_catalogue(path)


def test_loader_parses_vs_stage_capability(tmp_path) -> None:
    vs = _load(tmp_path)[0]
    assert vs.value_stream_id == "VSR00074583"
    assert vs.value_proposition == "Faster asset turnaround"
    assert vs.stakeholders == ["Supplier", "Procurement", "Asset Requestor"]
    assert vs.active is True
    stage = vs.stages[0]
    assert stage.sequence == 1
    assert stage.stakeholders == ["Asset Requestor", "Procurement"]
    cap = stage.capabilities[0]
    assert cap.level == 3
    assert cap.level_two_id == "CAP-L2-1" and cap.level_two_name == "Asset Intake"


def test_catalogue_document_shape(tmp_path) -> None:
    vs = _load(tmp_path)[0]
    doc = build_catalogue_document(vs)
    assert doc["id"] == "VSR00074583"
    assert doc["entityType"] == "ValueStream"  # PascalCase, like EngagementRequest/Theme
    assert "ingestedAt" not in doc  # no ingested date; source audit at the envelope
    assert doc["createdDate"] == "2021-03-14"
    assert doc["createdBy"] == "U447949"
    assert doc["modifiedBy"] == "U999999"
    props = doc["properties"]
    assert props["category"] == "Finance"
    assert props["valueProposition"] == "Faster asset turnaround"
    assert "createdBy" not in props  # source audit lives on the envelope now
    stage = props["valueStages"][0]
    assert stage["stageSequence"] == 1
    cap = stage["capabilities"][0]
    assert cap["level"] == 3
    assert cap["levelTwoId"] == "CAP-L2-1"  # L3 -> L2 inline (1-1)


def test_index_document_content_and_props(tmp_path) -> None:
    vs = _load(tmp_path)[0]
    content = build_catalogue_content(vs)
    assert "Acquire Asset" in content and "Finance" in content and "Faster asset turnaround" in content

    doc = build_index_document(vs, content_vector=[0.1, 0.2])
    assert len(doc["id"]) == 36  # uuid doc id
    assert doc["sourceId"] == "VSR00074583"  # VS id
    assert doc["key"] == vs.value_stream_name  # VS name (business key)
    assert doc["status"] is None  # VS has no ticket status
    assert doc["searchText"] == content  # was 'content'
    assert doc["content_vector"] == [0.1, 0.2]
    props = doc["properties"]
    # lean index: only the VS identity; description/category/trigger/value come from the catalogue
    assert set(props) == {"valueStreamId", "valueStreamName"}
    assert props["valueStreamId"] == "VSR00074583"
