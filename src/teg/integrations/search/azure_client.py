"""Azure AI Search implementation of SearchClient.

One unified index (idp_teg_data) holds both doc types our ingestion produces; the
``entityType`` field is the lane discriminator: 'ValueStream' for the catalogue lane
(hybrid text+vector+semantic), 'EngagementRequest' for the historical lane (pure
vector). The query is embedded via the embeddings client. Result mapping reads our
generated nested ``properties`` shape; the pure mappers are unit-tested, the SDK search
calls need live creds (gated smoke test).
"""

from __future__ import annotations

from teg.config.settings import Settings
from teg.integrations.embeddings import EmbeddingsClient, build_embeddings_client
from teg.integrations.search.client import (
    HistoricalHit,
    HistoricalValueStreamLabel,
    ValueStreamHit,
)
from teg.integrations.search.credential import build_search_credential

try:  # azure SDK is the optional 'search' extra
    from azure.search.documents.aio import SearchClient as _AzureSearchClient
    from azure.search.documents.models import VectorizedQuery
except Exception:  # pragma: no cover - import guarded so the module always loads
    _AzureSearchClient = None  # type: ignore[assignment]
    VectorizedQuery = None  # type: ignore[assignment]

_VS_FILTER = "entityType eq 'ValueStream'"
_HISTORICAL_FILTER = "entityType eq 'EngagementRequest'"
_RERANKER_SCALE = 4.0  # Azure semantic reranker scores are 0-4
# The BM25 keyword query is capped: a long query (e.g. raw ticket text) has thousands of terms,
# and terms x searchable-fields must stay under Azure's 3000-clause limit. The vector query still
# uses the full-text embedding, so semantics aren't lost - only the keyword half is trimmed.
_KEYWORD_CHAR_CAP = 8_000
_EMBED_CHAR_CAP = 30_000  # ~8k tokens; keep under the embedding model's input limit
_CONTENT_FIELD = "searchText"  # the single searchable text field (BM25 clause count = terms x 1)
_VS_SELECT = [
    "key",
    "properties/valueStreamId",
    "properties/valueStreamName",
]  # lean index: description/category/trigger/value come from the catalogue at selection time
# key (IDMT-####) is the leave-one-out / display id; searchText is the hit snippet.
_HISTORICAL_SELECT = ["key", "sourceId", "searchText"]  # VS labels come from Cosmos by key, not the index


class AzureSearchClient:
    def __init__(
        self,
        *,
        index_client,
        embeddings: EmbeddingsClient,
        vector_field: str = "content_vector",
        semantic_config: str = "teg-semantic",
        credential=None,
    ) -> None:
        self._index = index_client
        self._embeddings = embeddings
        self._vector_field = vector_field
        self._semantic_config = semantic_config
        self._credential = credential  # closed alongside the index client

    async def close(self) -> None:
        """Close the aio index client and credential (both hold aiohttp sessions)."""
        await self._index.close()
        if self._credential is not None and hasattr(self._credential, "close"):
            await self._credential.close()

    async def search_value_streams(self, query: str, *, top_k: int = 50) -> list[ValueStreamHit]:
        vector = await self._embeddings.embed(query[:_EMBED_CHAR_CAP])
        results = await self._index.search(
            search_text=query[:_KEYWORD_CHAR_CAP],
            search_fields=[_CONTENT_FIELD],  # keep terms x fields under the 3000-clause limit
            vector_queries=[self._vector_query(vector, top_k)],
            filter=_VS_FILTER,
            select=_VS_SELECT,
            top=top_k,
            query_type="semantic",
            semantic_configuration_name=self._semantic_config,
        )
        return [_to_value_stream_hit(doc) async for doc in results]

    async def search_historical(self, query: str, *, top_k: int = 6) -> list[HistoricalHit]:
        vector = await self._embeddings.embed(query[:_EMBED_CHAR_CAP])
        results = await self._index.search(
            search_text=query[:_KEYWORD_CHAR_CAP],  # hybrid (BM25 + vector) + semantic rerank
            search_fields=[_CONTENT_FIELD],
            vector_queries=[self._vector_query(vector, top_k)],
            filter=_HISTORICAL_FILTER,
            select=_HISTORICAL_SELECT,
            top=top_k,
            query_type="semantic",
            semantic_configuration_name=self._semantic_config,
        )
        return [_to_historical_hit(doc) async for doc in results]

    def _vector_query(self, vector: list[float], top_k: int):
        return VectorizedQuery(
            vector=vector, k_nearest_neighbors=top_k, fields=self._vector_field
        )


def _props(doc) -> dict:
    props = doc.get("properties")
    return props if isinstance(props, dict) else {}


def _to_value_stream_hit(doc) -> ValueStreamHit:
    props = _props(doc)
    # Lean index: only id + name + score. description/category/trigger/value are enriched from
    # the governed catalogue by VS id during candidate building.
    return ValueStreamHit(
        value_stream_id=str(props.get("valueStreamId") or ""),
        value_stream_name=str(props.get("valueStreamName") or ""),
        score=float(doc.get("@search.reranker_score") or doc.get("@search.score") or 0.0),
    )


def _to_historical_hit(doc) -> HistoricalHit:
    # Retrieval-only doc: key + searchText. The VS labels are enriched downstream from Cosmos by key.
    ticket_id = str(doc.get("key") or doc.get("sourceId") or doc.get("id") or "")
    return HistoricalHit(
        ticket_id=ticket_id,
        title=ticket_id,
        score=_historical_score(doc),
        snippet=str(doc.get("searchText") or "")[:200],
        value_streams=[],  # filled by the service from the historic lookup (Cosmos / eval-local)
    )


def _historical_score(doc) -> float:
    """Historical relevance on a 0-1 scale for the merger's support bands.

    The lane is hybrid+semantic, so prefer the semantic reranker score - but normalize it
    from its 0-4 range down to 0-1, the scale the merger's support-weight bands and historic
    gates are tuned to. Falls back to the raw search score (already ~0-1) if no reranker.
    """
    reranker = doc.get("@search.reranker_score")
    if reranker is not None:
        return min(1.0, float(reranker) / _RERANKER_SCALE)
    return float(doc.get("@search.score") or 0.0)


def _parse_value_streams(raw) -> list[HistoricalValueStreamLabel]:
    """Map the native valueStreams collection (our generated shape) to labels."""
    if not isinstance(raw, list):
        return []
    labels: list[HistoricalValueStreamLabel] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        vs_id = str(item.get("valueStreamId") or "")
        if not vs_id:
            continue
        labels.append(
            HistoricalValueStreamLabel(
                value_stream_id=vs_id,
                value_stream_name=str(item.get("valueStreamName") or ""),
            )
        )
    return labels


def build_search_client(settings: Settings) -> AzureSearchClient:
    if _AzureSearchClient is None:
        raise ImportError("azure-search-documents is required: install the 'search' extra")
    credential = build_search_credential(settings)
    index_client = _AzureSearchClient(
        endpoint=settings.search_endpoint,
        index_name=settings.search_index,
        credential=credential,
    )
    return AzureSearchClient(
        index_client=index_client,
        embeddings=build_embeddings_client(settings),
        vector_field=settings.search_vector_field,
        semantic_config=settings.search_semantic_config,
        credential=credential,
    )
