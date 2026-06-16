"""File text extraction: protocol + per-format implementation."""

from teg.integrations.files.document_extractor import (
    DocumentExtractor,
    build_attachment_extractor,
)
from teg.integrations.files.extractor import AttachmentTextExtractor

__all__ = ["AttachmentTextExtractor", "DocumentExtractor", "build_attachment_extractor"]
