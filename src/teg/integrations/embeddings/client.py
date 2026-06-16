"""Embeddings client protocol.

Vectorizes the query for the vector search lanes (used inside the search client) and
embeds documents during ingestion. The real implementation wraps the IDP gateway's
embeddings endpoint.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsClient(Protocol):
    async def embed(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: list[str]) -> list[list[float]]: ...
