"""Build the Cosmos IDMT/ER document and the Cosmos Theme documents.

Single source of truth for these two shapes (TDD §5.1, §5.2). Each Theme points at its ER via
``parentRef`` = the ER's stable ``sourceId``; an ER has no parent, so its ``parentRef`` is its own
``sourceId``. Level-1 fields are the Cosmos document's own lifecycle (id, timestamps, actor); the
SOURCE ticket's audit (created/modified date) lives inside ``properties``. ``id`` is a UUID
deterministic from the stable Jira internal id (idempotent upsert); ``key`` is the mutable business
key (IDMT-#### / GROUP-####).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from teg.domain.condensed import CondensedTicket
from teg.ingestion.documents.text_cleaning import clean_text
from teg.ingestion.extraction.jira_records import ExtractedEngagementRequest, ExtractedTheme

ER_SOURCE = "JIRA"
ER_ENTITY_TYPE = "ENGAGEMENTREQUEST"
THEME_ENTITY_TYPE = "THEME"
DOMAIN = "WORKITEM"  # both the ER and the Theme are work items
INGEST_ACTOR = "TEG-INGESTION"  # the Cosmos createdBy / lastModifiedBy actor
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


def value_stream_label(name: str, vs_id: str) -> str:
    """The Theme's Value Stream as the raw ``<name> {id}`` string (TDD §4.4), e.g.
    ``Resolve Appeal {VSR00074590}``. Empty string when neither is present."""
    if not (name or vs_id):
        return ""
    return f"{name} {{{vs_id}}}"


def build_idmt_document(
    *,
    er: ExtractedEngagementRequest,
    condensed: CondensedTicket,
) -> dict:
    """Cosmos Engagement-Request document (TDD §5.1). Level-1 = Cosmos lifecycle; the source ticket's
    own dates live in properties as creationDate/insightsTime. Linked Themes are SEPARATE documents
    (found via parentRef) - they are NOT embedded here."""
    fields = condensed.summary_fields
    now = _now()
    return {
        "id": doc_id(ER_ENTITY_TYPE, er.stable_id),  # uuid doc id (deterministic from sourceId)
        "key": er.key or None,  # IDMT-#### (business key)
        "sourceId": er.stable_id,  # stable Jira internal id (e.g. 3364549)
        "source": ER_SOURCE,
        "domain": DOMAIN,
        "entityType": ER_ENTITY_TYPE,
        "createdAt": now,  # Cosmos lifecycle
        "createdBy": INGEST_ACTOR,
        "lastModifiedAt": now,
        "lastModifiedBy": INGEST_ACTOR,
        "parentRef": er.stable_id,  # an ER has no parent -> its own sourceId
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
        },
    }


def build_theme_document(theme: ExtractedTheme, *, parent_er_id: str) -> dict:
    """Cosmos Theme document (TDD §5.2): the Jira GROUP artifact, linked to its ER via parentRef."""
    now = _now()
    return {
        "id": doc_id(THEME_ENTITY_TYPE, theme.stable_id),  # uuid doc id (deterministic)
        "key": theme.group_key or None,  # GROUP-#### (business key)
        "sourceId": theme.stable_id,  # stable Jira internal id
        "source": ER_SOURCE,
        "domain": DOMAIN,
        "entityType": THEME_ENTITY_TYPE,
        "createdAt": now,  # Cosmos lifecycle
        "createdBy": INGEST_ACTOR,
        "lastModifiedAt": now,
        "lastModifiedBy": INGEST_ACTOR,
        "parentRef": parent_er_id,  # the parent ER's sourceId (stable Jira id)
        "properties": {
            "summary": theme.summary,  # ISSUE title
            "description": clean_text(theme.description),
            # The Value Stream as the raw "<name> {id}" string (TDD §4.4), not a nested object.
            "valueStream": value_stream_label(theme.value_stream_name, theme.value_stream_id),
            "creationDate": theme.created_date or None,  # source created
            "insightsTime": theme.modified_date or None,  # source last updated
        },
    }
