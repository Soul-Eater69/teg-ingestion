"""Upsert documents into the unified Azure Search index (idp_teg_data).

merge_or_upload = upsert by key (id), so re-ingesting a ticket overwrites its doc -
safe to re-run. Batched to the Azure per-request cap. Each document's IndexingResult is
inspected so a partial-batch failure (e.g. a schema-rejected doc) is surfaced rather than
silently swallowed - it matters for an unattended nightly run. Gated on the optional
'search' extra; the pure helpers are unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from teg.config.settings import Settings
from teg.integrations.search.credential import build_search_credential

try:  # azure SDK is the optional 'search' extra
    from azure.search.documents.aio import SearchClient as _AzureSearchClient
except Exception:  # pragma: no cover - import guarded so the module always loads
    _AzureSearchClient = None  # type: ignore[assignment]

_BATCH_SIZE = 1000  # Azure caps a request at 1000 documents / 16 MB


def _chunk(documents: list[dict], size: int = _BATCH_SIZE) -> Iterator[list[dict]]:
    for start in range(0, len(documents), size):
        yield documents[start : start + size]


@dataclass(frozen=True)
class UploadFailure:
    document_id: str
    status_code: int | None
    error_message: str


@dataclass(frozen=True)
class UploadReport:
    succeeded: int = 0
    failures: list[UploadFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _failures(results) -> list[UploadFailure]:
    """Pull the failed IndexingResults from one batch response."""
    out: list[UploadFailure] = []
    for result in results or []:
        if getattr(result, "succeeded", True):
            continue
        out.append(
            UploadFailure(
                document_id=str(getattr(result, "key", "") or ""),
                status_code=getattr(result, "status_code", None),
                error_message=str(getattr(result, "error_message", "") or ""),
            )
        )
    return out


class SearchUploader:
    def __init__(self, index_client, credential=None) -> None:
        self._index = index_client
        self._credential = credential

    async def upload(self, documents: list[dict]) -> UploadReport:
        failures: list[UploadFailure] = []
        for batch in _chunk(documents):
            results = await self._index.merge_or_upload_documents(documents=batch)
            failures.extend(_failures(results))
        return UploadReport(succeeded=len(documents) - len(failures), failures=failures)

    async def close(self) -> None:
        await self._index.close()
        if self._credential is not None and hasattr(self._credential, "close"):
            await self._credential.close()


def build_search_uploader(settings: Settings) -> SearchUploader:
    if _AzureSearchClient is None:
        raise ImportError("azure-search-documents is required: install the 'search' extra")
    credential = build_search_credential(settings)
    index_client = _AzureSearchClient(
        endpoint=settings.search_endpoint,
        index_name=settings.search_index,
        credential=credential,
    )
    return SearchUploader(index_client, credential)
