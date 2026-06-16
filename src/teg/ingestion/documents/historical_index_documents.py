"""Build the historical IDMT search-index document (idp_teg_data).

Turns an ingested ticket into the retrieval doc that powers the historic-evidence lane of VS
prediction: searchText (embedded) + content_vector + properties.valueStreams. searchText is built
the SAME way as the prediction query (build_retrieval_text) so a stored ticket and a live query
share the vector space. valueStreams carries the resolved VS GT (id + name) so a historical hit
brings its labels without a Cosmos lookup. Identity: id=uuid (deterministic), key=IDMT-#### (the
match/leave-one-out key), sourceId=stable Jira id. status = the ticket's Jira status.
"""

from __future__ import annotations

from teg.domain.condensed import CondensedTicket, SummaryFields
from teg.ingestion.documents.idmt_documents import ER_ENTITY_TYPE, doc_id
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest
from teg.ingestion.ground_truth.theme_ground_truth import ThemeGroundTruth

SOURCE = "Jira"
ENTITY_TYPE = ER_ENTITY_TYPE


def build_retrieval_text(summary: SummaryFields) -> str:
    """Curated retrieval text from the summary fields. The stored historical doc's embedded
    content and the live prediction query are built the same way, so a stored ticket and a
    live query land in the same vector space."""
    parts = [summary.generated_summary, summary.business_problem, summary.business_capability]
    parts += summary.key_terms + summary.stakeholders + summary.systems_and_products
    return "\n".join(part for part in parts if part and part.strip())


def build_historical_content(condensed: CondensedTicket) -> str:
    """Retrieval text embedded for the historical index (matches the prediction query)."""
    return build_retrieval_text(condensed.summary_fields)


def build_historical_index_document(
    *,
    er: ExtractedEngagementRequest,
    condensed: CondensedTicket,
    theme_gt: list[ThemeGroundTruth],
    content_vector: list[float] | None = None,
) -> dict:
    # Retrieval-only doc: searchText (embedded) + the match key. The VS labels (GT) and full content
    # are NOT stored here - they live in Cosmos and are fetched by key when a hit is used (one
    # point-read returns both). theme_gt is accepted for signature stability but no longer stored.
    _ = theme_gt
    return {
        "id": doc_id(ENTITY_TYPE, er.stable_id),  # uuid (deterministic)
        "key": er.key or None,  # IDMT-#### (the retrieval match / leave-one-out key)
        "sourceId": er.stable_id,  # stable Jira internal id
        "source": SOURCE,
        "entityType": ENTITY_TYPE,
        "status": er.status or None,  # Jira status (filter out Cancelled at retrieval)
        "searchText": build_historical_content(condensed),
        "content_vector": content_vector,
    }
