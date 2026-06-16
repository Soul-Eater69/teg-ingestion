"""Parse a requested-count intent from a free-text custom instruction.

The custom instruction may ONLY influence how many value streams to return - nothing else.
The guardrail is structural: we deterministically extract an integer here, and the raw
instruction text NEVER reaches any LLM prompt. So prompt-injection, role-play, task changes,
or any non-count content cannot affect the system - anything that isn't a clean count is
ignored and the explicit requested_count stands.
"""

from __future__ import annotations

import re

# A bare integer, or one introduced by a count phrase ("give me 6", "top 8", "4 value
# streams", "limit to 5"). Word numbers one-twenty are also accepted.
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
_DIGITS = re.compile(r"\b(\d{1,3})\b")
_WORDS = re.compile(r"\b(" + "|".join(_WORD_NUMBERS) + r")\b", re.IGNORECASE)


def parse_requested_count(instruction: str | None, *, lo: int = 1, hi: int = 50) -> int | None:
    """Return the count requested in the instruction, clamped to [lo, hi], or None.

    Only a number is ever extracted; the rest of the text is discarded. Returns None when no
    number is present, so the caller keeps its explicit requested_count.
    """
    if not instruction:
        return None
    match = _DIGITS.search(instruction)
    value = int(match.group(1)) if match else _WORD_NUMBERS.get(_first_word(instruction))
    if value is None:
        return None
    return max(lo, min(hi, value))


def _first_word(instruction: str) -> str:
    match = _WORDS.search(instruction)
    return match.group(1).lower() if match else ""
