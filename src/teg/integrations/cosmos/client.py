"""Cosmos writer: upsert ingestion docs into one container, partition key /sourceId.

The container holds every TEG doc type in one collection, told apart by the ``entityType`` field
(EngagementRequest / Theme / ValueStream), partitioned by ``sourceId`` - mirroring the org's
worklet containers. Upsert is idempotent: the deterministic uuid5 ``id`` means re-ingesting a
ticket overwrites its docs rather than duplicating them.

Auth follows the search client: Azure AD service principal when the ``azure_*`` settings are
present, else the Cosmos account key. The azure-cosmos SDK is the optional ``cosmos`` extra, so the
import is guarded and the module always loads (tests use a fake, no live calls).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from teg.config.settings import Settings

try:  # azure-cosmos is the optional 'cosmos' extra
    from azure.cosmos.aio import CosmosClient as _CosmosClient
    from azure.identity.aio import ClientSecretCredential as _AsyncClientSecretCredential
except Exception:  # pragma: no cover - import guarded so the module always loads
    _CosmosClient = None  # type: ignore[assignment]
    _AsyncClientSecretCredential = None  # type: ignore[assignment]

# Hierarchical partition key (matches the org's Items containers): /domain + /entityType. The
# azure-cosmos SDK reads both values straight from the document body on upsert.
_PARTITION_PATHS = ("domain", "entityType")
_UPSERT_CONCURRENCY = 8  # modest fan-out so autoscale RU/s isn't hammered into 429s


@runtime_checkable
class CosmosWriter(Protocol):
    async def upsert(self, docs: Iterable[dict]) -> int:
        """Upsert each doc (idempotent on its id); return how many were written."""

    async def close(self) -> None:
        ...


class AzureCosmosWriter:
    """Upserts into a single Cosmos container. The azure client is injected for testability."""

    def __init__(self, client, database: str, container: str, *, credential=None) -> None:
        self._client = client
        self._database = database
        self._container = container
        self._credential = credential  # held so we can close it (AAD holds an aiohttp session)

    async def upsert(self, docs: Iterable[dict]) -> int:
        container = self._client.get_database_client(self._database).get_container_client(self._container)
        docs = [_validate(d) for d in docs]
        sem = asyncio.Semaphore(_UPSERT_CONCURRENCY)

        async def _one(doc: dict) -> None:
            async with sem:
                await container.upsert_item(doc)

        await asyncio.gather(*(_one(d) for d in docs))
        return len(docs)

    async def close(self) -> None:
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()


def _validate(doc: dict) -> dict:
    # Cosmos needs an id; both partition-key paths must be present or the upsert is rejected.
    if not doc.get("id"):
        raise ValueError(f"cosmos doc missing 'id': {doc.get('key') or doc}")
    for path in _PARTITION_PATHS:
        if not doc.get(path):
            raise ValueError(f"cosmos doc missing partition key '{path}': {doc.get('id')}")
    return doc


def build_cosmos_writer(settings: Settings) -> AzureCosmosWriter:
    """Build the live writer from Settings (service principal preferred, else account key)."""
    if _CosmosClient is None:
        raise RuntimeError("azure-cosmos not installed - run: uv sync --extra cosmos")
    if not (settings.cosmos_endpoint and settings.cosmos_database and settings.cosmos_container):
        raise ValueError("cosmos_endpoint, cosmos_database and cosmos_container must be set")

    credential = None
    if settings.azure_tenant_id and settings.azure_client_id and settings.azure_client_secret:
        credential = _AsyncClientSecretCredential(
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
        )
        client = _CosmosClient(settings.cosmos_endpoint, credential=credential)
    elif settings.cosmos_key:
        client = _CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
    else:
        raise ValueError("no Cosmos credential: set the azure_* service principal or cosmos_key")

    return AzureCosmosWriter(client, settings.cosmos_database, settings.cosmos_container,
                             credential=credential)
