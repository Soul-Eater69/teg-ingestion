"""Clean consolidated raw text before it's persisted to Cosmos.

Attachment/Jira extraction leaves control characters, carriage returns, non-breaking and
zero-width spaces, and long runs of blank lines in the text. This normalises that junk while
keeping readable paragraph structure (single newlines between lines, at most one blank line). It is
applied only to the stored ``rawText`` field - the LLM's consolidated text is left untouched so the
locked-in eval is unaffected.
"""

from __future__ import annotations

import re
import unicodedata

# control chars except tab (09), newline (0a), carriage return (0d) - those are handled explicitly
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RUN = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalise extracted text: drop control chars, collapse whitespace, keep paragraph breaks."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)  # fold compatibility forms (e.g. fancy quotes)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("​", "").replace("﻿", "")  # nbsp, zero-width, BOM
    text = _CONTROL.sub("", text)
    text = _SPACE_RUN.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))  # trim each line
    text = _BLANK_LINES.sub("\n\n", text)  # at most one blank line between paragraphs
    return text.strip()
