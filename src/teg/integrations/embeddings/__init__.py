"""Embeddings integration: protocol + IDP gateway client."""

from teg.integrations.embeddings.client import EmbeddingsClient
from teg.integrations.embeddings.idp_client import (
    EmbeddingsError,
    IdpEmbeddingsClient,
    build_embeddings_client,
)

__all__ = [
    "EmbeddingsClient",
    "IdpEmbeddingsClient",
    "EmbeddingsError",
    "build_embeddings_client",
]
