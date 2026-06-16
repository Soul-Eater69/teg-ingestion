"""Guard: the index docs we upload must conform to the deployed index schema.

data/idp_teg_data_index.json is the single source of truth for the Azure Search index. If a
builder emits a field the index does not define, Azure rejects the doc (or silently drops it on
a recreate). This builds a sample of each index doc and asserts every key it emits exists in the
index definition - so removing/adding a field in one place without the other fails here, not in a
live ingest.
"""

from __future__ import annotations

import json
from pathlib import Path

from teg.domain.condensed import CondensedTicket, SummaryFields
from teg.ingestion.documents.historical_index_documents import build_historical_index_document
from teg.ingestion.documents.value_stream_documents import build_index_document
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest
from teg.ingestion.catalogues.models import CatalogueValueStream
from teg.ingestion.ground_truth.theme_ground_truth import ThemeGroundTruth

_INDEX = json.loads(Path("data/idp_teg_data_index.json").read_text(encoding="utf-8"))


def _names(field_list: list[dict]) -> dict[str, dict]:
    return {f["name"]: f for f in field_list}


def _check(doc: dict, schema_fields: dict[str, dict], path: str = "") -> None:
    for key, value in doc.items():
        assert key in schema_fields, f"{path}{key} not in index schema"
        sub = schema_fields[key].get("fields")
        if sub is None:
            continue
        sub_fields = _names(sub)
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, dict):
                _check(item, sub_fields, path=f"{path}{key}.")


def _historical_doc() -> dict:
    condensed = CondensedTicket(
        ticket_id="IDMT-1", ticket_title="t", primary_source="idea_card",
        summary_fields=SummaryFields(generated_summary="s", business_problem="p", business_capability="c"),
        description="d", raw_text="r",
    )
    gt = [ThemeGroundTruth(theme_stable_id="T1", group_key="GROUP-1",
                           value_stream_id="VSR1", value_stream_name="Adjudicate Claim")]
    er = ExtractedEngagementRequest(stable_id="3364549", key="IDMT-1", title="t")
    return build_historical_index_document(er=er, condensed=condensed, theme_gt=gt, content_vector=[0.1])


def _value_stream_doc() -> dict:
    vs = CatalogueValueStream(
        value_stream_id="VSR1", value_stream_name="Adjudicate Claim",
        value_stream_description="d", value_proposition="v", trigger="t", category="c",
        assumptions="", defined_terms="", active=True, created_date="", created_by="",
        modified_date="", modified_by="",
    )
    return build_index_document(vs, [0.1])


def test_historical_index_doc_conforms_to_schema() -> None:
    _check(_historical_doc(), _names(_INDEX["fields"]))


def test_value_stream_index_doc_conforms_to_schema() -> None:
    _check(_value_stream_doc(), _names(_INDEX["fields"]))
