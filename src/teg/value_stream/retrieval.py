"""VS retrieval lanes.

Builds a retrieval query from the condensed summary and runs the two lanes in
parallel: the VS-catalogue lane and the historical-ER lane (top-6, shown to the SME).
The search client owns query vectorization. Returns the raw hits; bucketing and
ranking are the merger's job.
"""

from __future__ import annotations

import asyncio

from teg.domain.condensed import SummaryFields
from teg.integrations.search import SearchClient, ValueStreamHit
from teg.value_stream.models import RetrievalResult

# Winning retrieval knobs.
_VS_TOP_K = 50
_HISTORICAL_TOP_K = 6


def build_retrieval_text(summary: SummaryFields) -> str:
    """Curated retrieval text from the summary fields.

    Shared by prediction (the query) and ingestion (a historical doc's embedded
    ``content``) so a stored ticket and a live query land in the same vector space.
    """
    parts = [summary.generated_summary, summary.business_problem, summary.business_capability]
    parts += summary.key_terms + summary.stakeholders + summary.systems_and_products
    return "\n".join(part for part in parts if part and part.strip())


async def retrieve(
    summary: SummaryFields,
    search_client: SearchClient,
    *,
    vs_top_k: int = _VS_TOP_K,
    historical_top_k: int = _HISTORICAL_TOP_K,
    include_historical: bool = True,
    vs_candidates: list[ValueStreamHit] | None = None,
) -> RetrievalResult:
    """``vs_candidates`` (the governed catalogue's 50 VS) makes the VS lane come from the catalogue
    instead of the index - the index then holds only historic docs. When None, the VS lane is the
    index search (legacy / topk semantic ranking)."""
    query = build_retrieval_text(summary)

    async def _vs() -> list[ValueStreamHit]:
        return list(vs_candidates) if vs_candidates is not None \
            else list(await search_client.search_value_streams(query, top_k=vs_top_k))

    if not include_historical:  # semantic-only (eval ablation): skip the historic lane
        return RetrievalResult(value_stream_hits=await _vs())
    vs_hits, historical_hits = await asyncio.gather(
        _vs(), search_client.search_historical(query, top_k=historical_top_k),
    )
    return RetrievalResult(value_stream_hits=list(vs_hits), historical_hits=list(historical_hits))
