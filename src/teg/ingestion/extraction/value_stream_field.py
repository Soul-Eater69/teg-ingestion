"""Parse a Theme's "Business Value Stream" field into (value stream name, id).

The linked Theme carries its Value Stream directly in a Jira field formatted
``<name> {<id>}`` (e.g. ``Configure Price {VS1024}``). We read it as-is - no catalogue
fuzzy match, no LLM verification. Tolerates a plain string, a Jira select object
(``{"value": ...}`` / ``{"name": ...}``), or a list of those (first that parses wins).
"""

from __future__ import annotations

import re

# "<name> {<id>}" - name is everything before the last {...}; id is inside the braces.
_VS_PATTERN = re.compile(r"^\s*(?P<name>.*?)\s*\{\s*(?P<id>[^{}]+?)\s*\}\s*$")
# One "<name> {<id>}" segment, used to split the Value Stream Stage field which carries two.
_SEGMENT = re.compile(r"(?P<name>[^{}]+?)\s*\{\s*(?P<id>[^{}]+?)\s*\}")


def parse_value_stream(raw: object) -> tuple[str, str] | None:
    """Return (name, id) from a Business Value Stream field value, or None if absent/unparseable."""
    if raw is None:
        return None
    if isinstance(raw, list):
        for item in raw:
            parsed = parse_value_stream(item)
            if parsed:
                return parsed
        return None
    if isinstance(raw, dict):
        raw = raw.get("value") or raw.get("name") or ""
    match = _VS_PATTERN.match(str(raw))
    if not match:
        return None
    return match.group("name").strip(), match.group("id").strip()


def parse_value_stream_stage(raw: object) -> tuple[str, str] | None:
    """Return (stage name, stage id) from an Epic's "Value Stream Stage" field, or None.

    The field is a Jira CASCADING SELECT: the parent option is the value stream and the child
    option is the stage, so the value comes back as
    ``{"value": "<vs> {vs_id}", "child": {"value": "<stage> {stage_id}"}}`` - the stage is the
    CHILD. It also tolerates the flat string form ``<vs> {vs_id} - <stage> {stage_id}`` (stage =
    the last segment) and a list (first that parses). Returns None when no stage is present.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        for item in raw:
            parsed = parse_value_stream_stage(item)
            if parsed:
                return parsed
        return None
    if isinstance(raw, dict):
        child = raw.get("child")
        if isinstance(child, dict):  # cascading select: the stage is the child option
            return _parse_segment(child.get("value") or child.get("name") or "")
        # No child -> only the value stream is selected (no stage), unless the flat string carries both.
        raw = raw.get("value") or raw.get("name") or ""
    segments = list(_SEGMENT.finditer(str(raw)))
    if len(segments) < 2:  # one segment = VS only, no stage
        return None
    last = segments[-1]
    name = re.sub(r"^\s*[-–—]\s*", "", last.group("name").strip())  # drop the " - " lead
    return name.strip(), last.group("id").strip()


def _parse_segment(text: object) -> tuple[str, str] | None:
    """Parse a single "<name> {<id>}" (e.g. a cascading child option) into (name, id)."""
    match = _SEGMENT.search(str(text or ""))
    if not match:
        return None
    return match.group("name").strip(), match.group("id").strip()
