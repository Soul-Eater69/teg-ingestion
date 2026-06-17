"""Historical IDMT search-index document builder (Generator C)."""

from __future__ import annotations

from teg.domain.condensed import CondensedTicket, SummaryFields
from teg.ingestion.documents.historical_index_documents import (
    build_historical_content,
    build_historical_index_document,
    build_retrieval_text,
)
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest
from teg.ingestion.ground_truth.theme_ground_truth import ThemeGroundTruth


def _condensed() -> CondensedTicket:
    return CondensedTicket(
        ticket_id="IDMT-19761",
        ticket_title="t",
        primary_source="idea_card",
        summary_fields=SummaryFields(
            generated_summary="Automate appeals handling",
            business_problem="Manual appeals are slow",
            business_capability="Faster resolution",
            key_terms=["appeals"],
        ),
        description="d",
        raw_text="r",
    )


def _er() -> ExtractedEngagementRequest:
    return ExtractedEngagementRequest(stable_id="3364549", key="IDMT-19761", title="t")


def _gt() -> list[ThemeGroundTruth]:
    return [
        ThemeGroundTruth(
            theme_stable_id="3966046",
            group_key="GROUP-23618",
            value_stream_id="VSR00074590",
            value_stream_name="Resolve Appeal",
        )
    ]


def test_content_matches_query_builder() -> None:
    # The historical content must be built the same way as the prediction query.
    content = build_historical_content(_condensed())
    assert content == build_retrieval_text(_condensed().summary_fields)
    assert "Automate appeals handling" in content and "Manual appeals are slow" in content


def test_historical_index_document_shape() -> None:
    doc = build_historical_index_document(
        er=_er(), condensed=_condensed(), theme_gt=_gt(), content_vector=[0.1, 0.2]
    )
    assert len(doc["id"]) == 36  # uuid doc id
    assert doc["key"] == "IDMT-19761"  # leave-one-out / match key
    assert doc["sourceId"] == "3364549"  # stable Jira id
    assert doc["entityType"] == "ENGAGEMENTREQUEST"  # all caps - matches the retrieval filter
    assert doc["source"] == "JIRA"
    assert doc["content_vector"] == [0.1, 0.2]
    assert doc["searchText"]  # was 'content'
    # Retrieval-only doc: no properties block at all - VS labels + content come from Cosmos by key.
    assert "properties" not in doc


def test_no_vector_when_not_embedded() -> None:
    doc = build_historical_index_document(er=_er(), condensed=_condensed(), theme_gt=[])
    assert doc["content_vector"] is None
    assert "properties" not in doc  # retrieval-only
