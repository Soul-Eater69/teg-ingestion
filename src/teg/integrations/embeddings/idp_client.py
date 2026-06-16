"""IDP embeddings client (async).

Embeddings go through the same IDP OpenAI-compatible gateway as the LLM
(POST {base}/api/v1/embeddings) with the same bearer auth. Returns one vector per
input text.
"""

from __future__ import annotations

import httpx

from teg.config.settings import Settings
from teg.integrations.http_retry import post_with_retry
from teg.integrations.llm.idp_auth import IDPCustomAuth


class EmbeddingsError(RuntimeError):
    pass


class IdpEmbeddingsClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        model: str,
        dimensions: int,
        path: str = "/api/v1/embeddings",
        api_version: str = "2024-06-01",
        max_retries: int = 5,
    ) -> None:
        self._http = http_client
        self._model = model
        self._dimensions = dimensions
        self._path = path
        self._api_version = api_version
        self._max_retries = max_retries

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        body = {
            "api_version": self._api_version,
            "input": list(texts),
            "model": self._model,
            "encoding_format": "float",
            "dimensions": self._dimensions,
        }
        response = await post_with_retry(self._http, self._path, body, max_retries=self._max_retries)
        data = response.json()
        try:
            return [entry["vector"] for entry in data["embeddings"]]
        except (KeyError, TypeError) as exc:
            raise EmbeddingsError(f"unexpected embeddings response: {exc}") from exc


def build_embeddings_client(settings: Settings) -> IdpEmbeddingsClient:
    auth = IDPCustomAuth(
        app_id=settings.llm_app_id,
        auth_url=settings.idp_auth_url,
        client_id=settings.idp_client_id,
        client_secret=settings.idp_client_secret,
        user=settings.idp_user,
        password=settings.idp_password,
        verify_ssl=settings.llm_verify_ssl,
    )
    http_client = httpx.AsyncClient(
        base_url=settings.llm_base_url,
        auth=auth,
        timeout=settings.llm_timeout_seconds,
        verify=settings.llm_verify_ssl,
    )
    return IdpEmbeddingsClient(
        http_client,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        path=settings.embedding_path,
        api_version=settings.embedding_api_version,
        max_retries=settings.llm_max_retries,
    )
