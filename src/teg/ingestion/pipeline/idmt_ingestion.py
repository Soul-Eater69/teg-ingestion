"""IDMT ingestion pipeline: live Jira -> Cosmos IDMT/ER + Theme + historical index docs.

Per ticket: fetch the ER + its linked themes, condense the source material, read each theme's
Value Stream straight from its Business Value Stream field, then build the ER doc, one Theme doc
per linked theme (Themes are separate docs via parentRef - not embedded on the ER), and the
historical search-index doc (embedded when an embeddings client is provided). The Theme Value
Streams are carried into the historical index doc as retrieval labels.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from teg.contracts.condense_io import CondenseRequest
from teg.ingestion.documents.historical_index_documents import (
    build_historical_content,
    build_historical_index_document,
)
from teg.ingestion.documents.idmt_documents import build_idmt_document, build_theme_document
from teg.ingestion.extraction.jira_source import JiraIngestionSource
from teg.ingestion.ground_truth.theme_ground_truth import ThemeGroundTruth
from teg.integrations.embeddings import EmbeddingsClient
from teg.services.condense_service import CondenseService


@dataclass(frozen=True)
class IngestedTicket:
    """All documents produced for one ingested IDMT ticket."""

    idmt_document: dict  # Cosmos IDMT/ER doc
    theme_documents: list[dict]  # Cosmos Theme docs
    historical_index_document: dict  # idp_teg_data search doc
    extraction_seconds: float = 0.0  # condense phase timings (diagnostics)
    summarization_seconds: float = 0.0


class IdmtIngestion:
    def __init__(
        self,
        *,
        jira_source: JiraIngestionSource,
        condense_service: CondenseService,
        embeddings_client: EmbeddingsClient | None = None,
    ) -> None:
        self._jira = jira_source
        self._condense = condense_service
        self._embeddings = embeddings_client

    async def ingest(self, ticket_id: str) -> IngestedTicket:
        """Build the Cosmos IDMT/Theme docs + the historical index doc for one ticket."""
        def log(msg: str) -> None:
            print(f"[ingest {ticket_id}] {msg}", file=sys.stderr, flush=True)

        # The ER fetch (+ linked themes) and condense are independent - run concurrently.
        log("fetching ER from Jira + condensing (LLM gateway) …")
        er, condense_response = await asyncio.gather(
            self._jira.fetch_engagement_request(ticket_id),
            self._condense.condense(CondenseRequest(ticket_id=ticket_id)),
        )
        condensed = condense_response.condensed
        log(f"Jira + condense done ({len(er.themes)} theme(s); "
            f"condense {condense_response.summarization_seconds:.1f}s)")

        # The Value Stream is read straight from each theme's Business Value Stream field
        # (no catalogue match); themes without one were already dropped by the source. Each
        # kept theme becomes a Theme doc; its VS is also carried into the historical index doc.
        theme_gt: list[ThemeGroundTruth] = []
        theme_docs: list[dict] = []
        for theme in er.themes:
            theme_gt.append(
                ThemeGroundTruth(
                    theme_stable_id=theme.stable_id,
                    group_key=theme.group_key,
                    value_stream_id=theme.value_stream_id,
                    value_stream_name=theme.value_stream_name,
                )
            )
            theme_docs.append(build_theme_document(theme, parent_er_id=er.stable_id))

        idmt_doc = build_idmt_document(er=er, condensed=condensed)

        content_vector = None
        if self._embeddings is not None:
            log("embedding retrieval text (embeddings gateway) …")
            content_vector = await self._embeddings.embed(build_historical_content(condensed))
            log("embedding done")
        historical_doc = build_historical_index_document(
            er=er, condensed=condensed, theme_gt=theme_gt, content_vector=content_vector
        )
        return IngestedTicket(
            idmt_document=idmt_doc,
            theme_documents=theme_docs,
            historical_index_document=historical_doc,
            extraction_seconds=condense_response.extraction_seconds,
            summarization_seconds=condense_response.summarization_seconds,
        )
