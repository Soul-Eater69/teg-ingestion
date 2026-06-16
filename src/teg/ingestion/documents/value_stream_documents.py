"""Build the Cosmos VS-catalogue document and the VS search-index document.

Single source of truth for these two shapes. The Cosmos doc is the governed system of
record: one nested document per VS -> stages -> capabilities (each capability an L3 leaf
carrying its L2/L1 ancestor, 1-1 L3->L2). The envelope carries the source's catalogue
audit (created/modified). The index doc carries only retrieval text + vector + display/
filter fields.
"""

from __future__ import annotations

from teg.ingestion.documents.idmt_documents import doc_id
from teg.ingestion.catalogues.models import (
    CatalogueCapability,
    CatalogueStage,
    CatalogueValueStream,
)

CATALOGUE_SOURCE = "Sightline"
ENTITY_TYPE = "ValueStream"  # PascalCase, consistent with EngagementRequest / Theme


def build_catalogue_document(vs: CatalogueValueStream) -> dict:
    """Cosmos governed-catalogue document (point-read by valueStreamId at stage gen)."""
    return {
        "id": vs.value_stream_id,
        "source": CATALOGUE_SOURCE,
        "entityType": ENTITY_TYPE,
        "createdDate": vs.created_date or None,
        "createdBy": vs.created_by or None,
        "modifiedDate": vs.modified_date or None,
        "modifiedBy": vs.modified_by or None,
        "properties": {
            "valueStreamId": vs.value_stream_id,
            "valueStreamName": vs.value_stream_name,
            "valueStreamDescription": vs.value_stream_description,
            "valueProposition": vs.value_proposition,
            "trigger": vs.trigger,
            "category": vs.category,
            "stakeholders": list(vs.stakeholders),
            "assumptions": vs.assumptions,
            "definedTerms": vs.defined_terms,
            "active": vs.active,
            "valueStages": [_stage_document(stage) for stage in vs.stages],
        },
    }


def _stage_document(stage: CatalogueStage) -> dict:
    return {
        "stageId": stage.stage_id,
        "stageName": stage.stage_name,
        "stageDescription": stage.stage_description,
        "stageSequence": stage.sequence,
        "stageEntranceCriteria": stage.entrance_criteria,
        "stageExitCriteria": stage.exit_criteria,
        "stageValueItems": stage.value_items,
        "stageStakeholders": list(stage.stakeholders),
        "active": stage.active,
        "createdDate": stage.created_date or None,
        "modifiedDate": stage.modified_date or None,
        "capabilities": [_capability_document(cap) for cap in stage.capabilities],
    }


def _capability_document(cap: CatalogueCapability) -> dict:
    return {
        "capabilityId": cap.capability_id,
        "capabilityName": cap.capability_name,
        "capabilityDescription": cap.capability_description,
        "level": cap.level,
        "tier": cap.tier,
        "active": cap.active,
        "levelOneId": cap.level_one_id,
        "levelOneName": cap.level_one_name,
        "levelTwoId": cap.level_two_id,
        "levelTwoName": cap.level_two_name,
    }


def build_catalogue_content(vs: CatalogueValueStream) -> str:
    """Retrieval text embedded for the VS index: the semantically meaningful VS fields."""
    parts = [
        vs.value_stream_name,
        vs.value_stream_description,
        vs.category,
        vs.trigger,
        vs.value_proposition,
    ]
    return "\n".join(part for part in parts if part and part.strip())


def build_index_document(
    vs: CatalogueValueStream, content_vector: list[float] | None = None
) -> dict:
    """VS search-index document: retrieval text + vector + display fields. Identity matches the
    historic doc: id=uuid (deterministic), key=VS name, sourceId=VS id. status is null (VS has none).
    The properties are read by the selection candidate blocks, so they stay."""
    return {
        "id": doc_id(ENTITY_TYPE, vs.value_stream_id),  # uuid (deterministic)
        "key": vs.value_stream_name,  # VS name (business key)
        "sourceId": vs.value_stream_id,  # VS id (e.g. VSR00074590)
        "source": CATALOGUE_SOURCE,
        "entityType": ENTITY_TYPE,
        "status": None,  # value streams have no ticket status
        "searchText": build_catalogue_content(vs),
        "content_vector": content_vector,
        "properties": {  # lean: only the VS identity; full data is in the governed catalogue
            "valueStreamId": vs.value_stream_id,
            "valueStreamName": vs.value_stream_name,
        },
    }
