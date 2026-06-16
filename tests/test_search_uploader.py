"""Search uploader batching + upsert (fake index client; no SDK needed)."""

from __future__ import annotations

from teg.ingestion.upload.search_uploader import SearchUploader, _chunk


def test_chunk_splits_at_batch_size() -> None:
    docs = [{"id": str(i)} for i in range(2500)]
    batches = list(_chunk(docs, size=1000))
    assert [len(b) for b in batches] == [1000, 1000, 500]


def test_chunk_empty() -> None:
    assert list(_chunk([])) == []


class _Result:
    def __init__(self, key, succeeded, status_code=None, error_message=""):
        self.key = key
        self.succeeded = succeeded
        self.status_code = status_code
        self.error_message = error_message


class FakeIndex:
    def __init__(self, fail_keys: set[str] | None = None) -> None:
        self.calls: list[int] = []
        self.closed = False
        self._fail = fail_keys or set()

    async def merge_or_upload_documents(self, *, documents):
        self.calls.append(len(documents))
        return [
            _Result(d["id"], d["id"] not in self._fail, 400 if d["id"] in self._fail else 200, "rejected")
            for d in documents
        ]

    async def close(self):
        self.closed = True


async def test_upload_batches_and_reports_success() -> None:
    fake = FakeIndex()
    uploader = SearchUploader(fake)
    report = await uploader.upload([{"id": str(i)} for i in range(1500)])
    assert report.succeeded == 1500 and report.ok is True
    assert fake.calls == [1000, 500]  # batched
    await uploader.close()
    assert fake.closed is True


async def test_upload_surfaces_per_doc_failures() -> None:
    fake = FakeIndex(fail_keys={"2", "5"})
    report = await SearchUploader(fake).upload([{"id": str(i)} for i in range(6)])
    assert report.succeeded == 4 and report.ok is False
    failed_ids = sorted(f.document_id for f in report.failures)
    assert failed_ids == ["2", "5"]
    assert report.failures[0].status_code == 400
