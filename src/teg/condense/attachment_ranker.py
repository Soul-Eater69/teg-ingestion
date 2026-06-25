"""Attachment selection for the idea-card source.

Rules:
  - Prefer the idea card: an attachment explicitly named ``idea_card.<format>`` (exact
    stem, any supported format) is the sole primary source when present.
  - Otherwise take the top four *supported* attachments in priority order:
    PowerPoint, then PDF, then Word. Original order is preserved within a format.
Unsupported formats are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from teg.integrations.jira import JiraAttachment

# Lower number = higher priority. PPT first: SMEs confirmed it is the common idea-card format.
_FORMAT_PRIORITY: dict[str, int] = {
    ".ppt": 0,
    ".pptx": 0,
    ".pdf": 1,
    ".doc": 2,
    ".docx": 2,
}

_MAX_FALLBACK_ATTACHMENTS = 4
_IDEA_CARD_STEM = "idea_card"


def _extension(filename: str) -> str:
    name = filename.lower().strip()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def _stem(filename: str) -> str:
    name = filename.lower().strip()
    dot = name.rfind(".")
    return name[:dot] if dot != -1 else name


def is_supported(filename: str) -> bool:
    return _extension(filename) in _FORMAT_PRIORITY


def is_idea_card(filename: str) -> bool:
    """True only when explicitly named idea_card.<format> with a supported format."""
    return is_supported(filename) and _stem(filename) == _IDEA_CARD_STEM


@dataclass
class SelectedAttachments:
    """What the condense source resolver should extract.

    When ``idea_card`` is set it is the sole primary source. Otherwise ``fallback``
    holds up to four supported attachments in priority order.
    """

    idea_card: JiraAttachment | None
    fallback: list[JiraAttachment]


def select_attachments(
    attachments: list[JiraAttachment],
    *,
    max_fallback: int = _MAX_FALLBACK_ATTACHMENTS,
) -> SelectedAttachments:
    # Idea card wins outright - trusted, used in full.
    for attachment in attachments:
        if is_idea_card(attachment.filename):
            return SelectedAttachments(idea_card=attachment, fallback=[])

    supported = [a for a in attachments if is_supported(a.filename)]
    ranked = sorted(
        enumerate(supported),
        key=lambda pair: (_FORMAT_PRIORITY[_extension(pair[1].filename)], pair[0]),
    )
    fallback = [attachment for _, attachment in ranked[:max_fallback]]
    return SelectedAttachments(idea_card=None, fallback=fallback)
