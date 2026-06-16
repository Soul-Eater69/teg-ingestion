"""Search integration: protocol + records + Azure AI Search implementation."""

from teg.integrations.search.client import (
    HistoricalHit,
    HistoricalValueStreamLabel,
    SearchClient,
    ValueStreamHit,
)

__all__ = [
    "SearchClient",
    "ValueStreamHit",
    "HistoricalHit",
    "HistoricalValueStreamLabel",
    "AzureSearchClient",
    "build_search_client",
]


def __getattr__(name: str):
    # Lazy: only import the Azure-backed client (and its optional SDK) on demand.
    if name in ("AzureSearchClient", "build_search_client"):
        from teg.integrations.search import azure_client

        return getattr(azure_client, name)
    raise AttributeError(name)
