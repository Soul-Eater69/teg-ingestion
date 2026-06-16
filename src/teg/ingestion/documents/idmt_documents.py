"""Build the Cosmos IDMT/ER document and the Cosmos Theme documents.

Single source of truth for these two shapes. The ER is a root (no parent); each Theme points
at its ER via parentId. Level-1 fields are the Cosmos document's own lifecycle (id, ingestedDate);
the SOURCE ticket's audit (created/modified by/date) lives inside properties alongside the rest of
the business data. id is the stable Jira internal issue id (deterministic -> idempotent upsert);
ticketId is the mutable business key (IDMT-####).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from teg.domain.condensed import CondensedTicket
from teg.ingestion.documents.text_cleaning import clean_text
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest, ExtractedTheme
from teg.ingestion.ground_truth.theme_ground_truth import ThemeGroundTruth

ER_SOURCE = "Jira"
ER_ENTITY_TYPE = "EngagementRequest"  # PascalCase (consistent with ValueStream)
THEME_ENTITY_TYPE = "Theme"
INGEST_ACTOR = "teg-ingestion"  # the Cosmos createdBy/lastModifiedBy actor
# Fixed namespace so doc_id is a UUID that is DETERMINISTIC from the stable source id - the
# same ticket always gets the same id, so re-ingest upserts (no duplicates), unlike a random uuid4.
_DOC_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def restamp(doc: dict, when: str | None = None) -> dict:
    """Set the Cosmos lifecycle timestamps to the ingestion-run time (not the extraction time).

    Docs built on disk carry createdAt/lastModifiedAt from when they were EXTRACTED. When they are
    later loaded from the local file and written to Cosmos, we want the time they are USED. Pass the
    same ``when`` for a whole run so every doc shares one timestamp. The source ticket's own dates
    (properties.creationDate / insightsTime) are left untouched - those are real Jira facts.
    """
    when = when or _now()
    doc["createdAt"] = when
    doc["lastModifiedAt"] = when
    return doc


def doc_id(entity_type: str, source_id: str) -> str:
    """A UUID doc id, deterministic from entity + stable source id (idempotent upsert key)."""
    return str(uuid.uuid5(_DOC_NS, f"{entity_type}:{source_id}"))


def build_idmt_document(
    *,
    er: ExtractedEngagementRequest,
    condensed: CondensedTicket,
    theme_gt: list[ThemeGroundTruth],
) -> dict:
    """Cosmos IDMT/ER document (TDD 4.1.1). Level-1 = Cosmos lifecycle; the source ticket's own
    dates live in properties as creationDate/insightsTime."""
    fields = condensed.summary_fields
    now = _now()
    return {
        "id": doc_id(ER_ENTITY_TYPE, er.stable_id),  # uuid doc id (deterministic from sourceId)
        "key": er.key or None,  # IDMT-#### (business key)
        "sourceId": er.stable_id,  # stable Jira internal id (e.g. 3364549)
        "source": ER_SOURCE,
        "entityType": ER_ENTITY_TYPE,
        "createdAt": now,  # Cosmos lifecycle
        "createdBy": INGEST_ACTOR,
        "lastModifiedAt": now,
        "lastModifiedBy": INGEST_ACTOR,
        "parentRef": None,  # ER is a root - no parent
        "properties": {
            "description": clean_text(condensed.description),
            "summary": condensed.ticket_title or er.title,  # the ticket TITLE
            "creationDate": er.created_date or None,  # source ticket created
            "insightsTime": er.modified_date or None,  # source ticket last updated
            "businessSummary": fields.generated_summary,  # LLM-generated summary
            "keyTerms": list(fields.key_terms),
            "businessProblem": fields.business_problem,
            "businessCapability": fields.business_capability,
            "stakeholders": list(fields.stakeholders),
            "systemsAndProducts": list(fields.systems_and_products),
            "rawText": clean_text(condensed.raw_text),  # cleaned for storage (LLM input untouched)
            # Value Stream ground truth (one entry per linked theme).
            "themes": [_theme_gt(gt) for gt in theme_gt],
        },
    }


def _theme_gt(gt: ThemeGroundTruth) -> dict:
    return {
        "key": gt.group_key,  # GROUP-#### (business key)
        "sourceId": gt.theme_stable_id,  # stable Jira theme id -> Theme doc id
        "valueStreamId": gt.value_stream_id,
        "valueStreamName": gt.value_stream_name,
    }


def build_theme_document(theme: ExtractedTheme, *, parent_er_id: str) -> dict:
    """Cosmos Theme document (TDD 4.1.2): the Jira GROUP artifact, linked to its ER via parentRef."""
    now = _now()
    return {
        "id": doc_id(THEME_ENTITY_TYPE, theme.stable_id),  # uuid doc id (deterministic)
        "key": theme.group_key or None,  # GROUP-#### (business key)
        "sourceId": theme.stable_id,  # stable Jira internal id
        "source": ER_SOURCE,
        "entityType": THEME_ENTITY_TYPE,
        "createdAt": now,  # Cosmos lifecycle
        "createdBy": INGEST_ACTOR,
        "lastModifiedAt": now,
        "lastModifiedBy": INGEST_ACTOR,
        "parentRef": parent_er_id,  # the parent ER's sourceId (stable Jira id)
        "properties": {
            "summary": theme.summary,  # ISSUE title
            "description": clean_text(theme.description),
            "valueStream": {
                "valueStreamId": theme.value_stream_id,
                "valueStreamName": theme.value_stream_name,
            },
            "creationDate": theme.created_date or None,  # source created
            "insightsTime": theme.modified_date or None,  # source last updated
        },
    }
