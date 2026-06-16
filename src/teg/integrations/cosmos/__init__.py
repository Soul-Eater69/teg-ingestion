"""Cosmos DB persistence for ingestion (one container, partition key /sourceId)."""

from teg.integrations.cosmos.client import (
    CosmosWriter,
    build_cosmos_writer,
)
from teg.integrations.cosmos.documents import DOMAIN, to_cosmos_doc

__all__ = ["CosmosWriter", "build_cosmos_writer", "to_cosmos_doc", "DOMAIN"]
