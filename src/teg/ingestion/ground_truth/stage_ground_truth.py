"""Stage ground-truth extraction from Jira Themes and their Epics.

For one IDMT ticket this resolves, per linked Theme/GROUP (a Value Stream):

    Theme description   -> theme_description
    Business Needs field-> business_needs
    each child Epic     -> one stage (Epic summary canonicalized to the stage catalogue)
    L2 / L3 fields      -> theme_l2_capabilities / theme_l3_capabilities

Stages are the eval answer key for stage selection; theme_description / business_needs /
L2 / L3 are the answer key for the rest of the theme package (see ``ThemePackage``). Epics
under a Theme are found three ways and unioned (deduped by key): the "Parent Link" custom
field, the standard ``parent`` relation, and implement/Epic issue-links on the Theme.

Business Needs and the L2/L3 Business Capability Model fields all live on the Theme (verified
on a live GROUP issue), so L2/L3 GT is per-theme, not per-stage. Field ids are overridable
(see :class:`StageGtFields`); a field empty across all themes is reported in ``warnings``.

Pure logic + a small injected Jira protocol so it unit-tests with a fake (no live calls).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol, Sequence

from teg.ingestion.catalogues.models import CatalogueStage, CatalogueValueStream
from teg.ingestion.extraction.value_stream_field import (
    parse_value_stream,
    parse_value_stream_stage,
)

# Jira field ids (override via StageGtFields). All three live on the Theme (verified on a
# live GROUP issue); Parent Link finds the child Epics.
BUSINESS_NEEDS_FIELD = "customfield_20900"  # "Business Needs" on the Theme
L2_CAPABILITY_FIELD = "customfield_18602"  # "L2 Business Capability Model" on the Theme
L3_CAPABILITY_FIELD = "customfield_18603"  # "L3 Business Capability Model" on the Theme
PARENT_LINK_FIELD = "customfield_11401"
# "Value Stream Stage" on each Epic: "<vs> {vs_id} - <stage> {stage_id}" - the stage id+name come
# straight from this field (authoritative); the Epic summary is only a fallback when it's empty.
STAGE_FIELD = "customfield_18700"

_FUZZY_THRESHOLD = 0.86  # min ratio to accept a fuzzy stage-name match (summary fallback only)
# Themes/epics in these states are NOT real GT: cancelled = the BA dropped it. To Do is KEPT
# (a planned-but-not-started stage is still a valid GT selection).
_SKIP_STATUSES = {"cancelled", "canceled"}


@dataclass(frozen=True)
class StageGtFields:
    """Overridable Jira field ids for the stage GT extraction."""

    business_needs: str = BUSINESS_NEEDS_FIELD
    l2_capability: str = L2_CAPABILITY_FIELD
    l3_capability: str = L3_CAPABILITY_FIELD
    parent_link: str = PARENT_LINK_FIELD
    stage: str = STAGE_FIELD  # the Epic's Value Stream Stage field


@dataclass(frozen=True)
class StageGroundTruth:
    """One Epic resolved to a catalogue stage."""

    epic_key: str
    raw_summary: str  # the Epic title (kept for traceability / the summary fallback)
    stage_id: str  # stage id ("" when unresolved)
    stage_name: str  # stage name ("" when unresolved)
    match_method: str  # field | exact | fuzzy | unresolved  ('field' = from Value Stream Stage)
    confidence: float


@dataclass(frozen=True)
class ThemeStageGroundTruth:
    """One linked Theme (a Value Stream): its stages, description, needs, and L2/L3 caps."""

    theme_key: str
    group_key: str
    value_stream_id: str
    value_stream_name: str
    theme_description: str
    business_needs: str
    l2_capabilities: list[str] = field(default_factory=list)
    l3_capabilities: list[str] = field(default_factory=list)
    stages: list[StageGroundTruth] = field(default_factory=list)


@dataclass(frozen=True)
class TicketStageGroundTruth:
    """All linked-theme stage GT for one IDMT ticket."""

    ticket_id: str
    summary: str
    description: str
    themes: list[ThemeStageGroundTruth] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StageJiraClient(Protocol):
    """Minimal Jira surface the extraction needs (injected; faked in tests)."""

    async def get_issue(self, key: str, *, fields: Sequence[str]) -> dict: ...

    async def search(self, jql: str, *, fields: Sequence[str]) -> list[dict]: ...


# ---------------------------------------------------------------------------- #
# Orchestration (needs Jira I/O via the injected client)
# ---------------------------------------------------------------------------- #


async def build_ticket_stage_ground_truth(
    ticket_id: str,
    *,
    jira: StageJiraClient,
    catalogue: list[CatalogueValueStream],
    value_stream_field: str,
    fields: StageGtFields = StageGtFields(),
) -> TicketStageGroundTruth:
    """Build the stage GT for one IDMT ticket: ticket -> linked Themes -> Epics."""
    stages_by_vs = {vs.value_stream_id: vs.stages for vs in catalogue}
    warnings: list[str] = []

    issue = await jira.get_issue(ticket_id, fields=["summary", "description", "issuelinks"])
    f = issue.get("fields") or {}
    summary = _clean(f.get("summary"))
    description = _coerce_text(f.get("description"))

    themes: list[ThemeStageGroundTruth] = []
    for target in _link_targets(f.get("issuelinks")):
        theme = await _build_theme(
            target["key"], jira=jira, value_stream_field=value_stream_field,
            stages_by_vs=stages_by_vs, fields=fields, warnings=warnings,
        )
        if theme is not None:
            themes.append(theme)

    return TicketStageGroundTruth(
        ticket_id=ticket_id, summary=summary, description=description,
        themes=themes, warnings=warnings,
    )


async def _build_theme(
    theme_key: str,
    *,
    jira: StageJiraClient,
    value_stream_field: str,
    stages_by_vs: dict[str, list[CatalogueStage]],
    fields: StageGtFields,
    warnings: list[str],
) -> ThemeStageGroundTruth | None:
    theme = await jira.get_issue(
        theme_key,
        fields=["summary", "description", "status", "issuelinks", value_stream_field,
                fields.business_needs, fields.l2_capability, fields.l3_capability],
    )
    tf = theme.get("fields") or {}
    vs = parse_value_stream(tf.get(value_stream_field))
    if not vs:
        return None  # not a Value Stream theme - skip (e.g. a plain related issue)
    if _skip_status(theme):
        warnings.append(f"{theme_key}: skipped - theme status is {_status(theme)!r}")
        return None
    vs_name, vs_id = vs

    catalogue_stages = stages_by_vs.get(vs_id) or []
    if not catalogue_stages:
        warnings.append(f"{theme_key}: no stage catalogue entry for value stream {vs_id}")

    epics = await _fetch_child_epics(theme, jira=jira, fields=fields)
    stages = [
        _stage_from_epic(epic, catalogue_stages=catalogue_stages, vs_name=vs_name, fields=fields)
        for epic in epics
    ]
    # Drop GT stages whose id is not in the approved catalogue for this VS - they are retired /
    # out-of-catalogue stages the model could never pick, so they are not fair GT. Unresolved
    # (no id) stages are also dropped. This keeps coverage at 100% by construction.
    allowed = {s.stage_id for s in catalogue_stages}
    kept = [s for s in stages if s.stage_id and s.stage_id in allowed]
    dropped = len(stages) - len(kept)
    if dropped:
        warnings.append(f"{theme_key}: dropped {dropped} GT stage(s) not in the approved catalogue")
    return ThemeStageGroundTruth(
        theme_key=theme_key,
        group_key=theme_key,  # the Theme is the GROUP-#### issue
        value_stream_id=vs_id,
        value_stream_name=vs_name,
        theme_description=_coerce_text(tf.get("description")),
        business_needs=_coerce_text(tf.get(fields.business_needs)),
        l2_capabilities=parse_capabilities(tf.get(fields.l2_capability)),
        l3_capabilities=parse_capabilities(tf.get(fields.l3_capability)),
        stages=kept,
    )


async def _fetch_child_epics(
    theme: dict, *, jira: StageJiraClient, fields: StageGtFields
) -> list[dict]:
    """Union the three Epic-discovery paths, deduped by key (first seen wins)."""
    theme_key = _clean(theme.get("key")).upper()
    epic_fields = ["summary", "status", "issuetype", "parent", fields.parent_link, fields.stage]
    by_key: dict[str, dict] = {}

    for jql in (
        f'"Parent Link" = {theme_key} AND issuetype = Epic',
        f"parent = {theme_key} AND issuetype = Epic",
    ):
        for epic in await _safe_search(jira, jql, epic_fields):
            key = _clean(epic.get("key")).upper()
            if key and key not in by_key and _issue_type(epic).lower() == "epic" and not _skip_status(epic):
                by_key[key] = epic

    # Issue-link Epics on the Theme (implement links + plain Epic links). These come back
    # without the capability fields, so re-fetch each so L2/L3 are populated.
    for link in _epic_link_keys(theme):
        if link not in by_key:
            epic = await _safe_get(jira, link, epic_fields)
            if epic and _issue_type(epic).lower() == "epic" and not _skip_status(epic):
                by_key[link] = epic

    return sorted(by_key.values(), key=lambda e: _clean(e.get("key")))


# ---------------------------------------------------------------------------- #
# Pure stage resolution
# ---------------------------------------------------------------------------- #


def _stage_from_epic(
    epic: dict, *, catalogue_stages: list[CatalogueStage], vs_name: str, fields: StageGtFields
) -> StageGroundTruth:
    ef = epic.get("fields") or {}
    raw_summary = _clean(ef.get("summary"))

    # Authoritative: read the stage id+name straight from the Epic's Value Stream Stage field.
    parsed = parse_value_stream_stage(ef.get(fields.stage))
    if parsed:
        stage_name, stage_id = parsed
        return StageGroundTruth(
            epic_key=_clean(epic.get("key")).upper(), raw_summary=raw_summary,
            stage_id=stage_id, stage_name=stage_name, match_method="field", confidence=1.0,
        )

    # Fallback: the field is empty - canonicalize the Epic summary against the catalogue.
    stage_id, stage_name, method, confidence = canonicalize_stage(
        raw_summary, catalogue_stages, value_stream_name=vs_name
    )
    return StageGroundTruth(
        epic_key=_clean(epic.get("key")).upper(),
        raw_summary=raw_summary,
        stage_id=stage_id,
        stage_name=stage_name,
        match_method=method,
        confidence=confidence,
    )


def canonicalize_stage(
    summary: str, stages: list[CatalogueStage], *, value_stream_name: str = ""
) -> tuple[str, str, str, float]:
    """Map an Epic summary to a catalogue (stage_id, stage_name, method, confidence).

    Tries the prefix-stripped suffix first (Epic titles are often "<VS> - <Stage>"), then
    the full summary. An exact normalized name match wins (1.0); otherwise the best fuzzy
    ratio above the threshold. Returns ("", "", "unresolved", 0.0) if nothing matches.
    """
    if not stages:
        return "", "", "unresolved", 0.0
    by_norm = {_norm(s.stage_name): s for s in stages if s.stage_name}

    best: tuple[CatalogueStage, float] | None = None
    for candidate in _stage_candidates(summary, value_stream_name):
        norm = _norm(candidate)
        if not norm:
            continue
        exact = by_norm.get(norm)
        if exact is not None:
            return exact.stage_id, exact.stage_name, "exact", 1.0
        for stage in stages:
            ratio = SequenceMatcher(None, norm, _norm(stage.stage_name)).ratio()
            if best is None or ratio > best[1]:
                best = (stage, ratio)

    if best is not None and best[1] >= _FUZZY_THRESHOLD:
        return best[0].stage_id, best[0].stage_name, "fuzzy", round(best[1], 4)
    return "", "", "unresolved", 0.0


def parse_capabilities(raw: object) -> list[str]:
    """Capability names from a Jira field: option object(s), a list, or delimited text."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [v] if (v := _option_text(raw)) else []
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            out.extend(parse_capabilities(item))
        return _dedupe(out)
    # Split on the raw string (before whitespace is collapsed) so newline-delimited
    # capability lists survive, then clean each part.
    parts = [_clean(p) for p in re.split(r"[;\n]", str(raw)) if _clean(p)]
    return _dedupe(parts)


# ---------------------------------------------------------------------------- #
# Link / field helpers
# ---------------------------------------------------------------------------- #


def _link_targets(issuelinks: object) -> list[dict]:
    """Flatten issuelinks to {key} for each linked issue (any link type/direction)."""
    out: list[dict] = []
    for link in issuelinks if isinstance(issuelinks, list) else []:
        if not isinstance(link, dict):
            continue
        issue = link.get("inwardIssue") or link.get("outwardIssue")
        if isinstance(issue, dict) and issue.get("key"):
            out.append({"key": str(issue["key"])})
    return out


_NON_STAGE_LINK_TOKENS = ("relate", "duplicate", "clone", "block", "depend", "caused",
                          "split", "supersede")


def _epic_link_keys(theme: dict) -> list[str]:
    """Keys of Epics linked from the Theme: implement links, then other non-relationship links."""
    links = [l for l in ((theme.get("fields") or {}).get("issuelinks") or []) if isinstance(l, dict)]
    keys: list[str] = []
    seen: set[str] = set()

    def _add(issue: object) -> None:
        if isinstance(issue, dict) and _issue_type(issue).lower() == "epic":
            key = _clean(issue.get("key")).upper()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)

    for implement_only in (True, False):
        for link in links:
            type_text = _link_type_text(link.get("type") or {})
            is_implement = "implement" in type_text.lower()
            if is_implement != implement_only:
                continue
            if not is_implement and any(t in type_text.lower() for t in _NON_STAGE_LINK_TOKENS):
                continue
            _add(link.get("inwardIssue"))
            _add(link.get("outwardIssue"))
    return keys


def _stage_candidates(summary: str, value_stream_name: str) -> list[str]:
    """Candidate stage strings from an Epic summary: prefix-stripped suffix, then full."""
    summary = _clean(summary)
    candidates: list[str] = []
    suffix = _suffix_after_prefix(summary, value_stream_name)
    if suffix and suffix != summary:
        candidates.append(suffix)
    candidates.append(summary)
    return _dedupe(candidates)


def _suffix_after_prefix(summary: str, value_stream_name: str) -> str:
    name = _clean(value_stream_name)
    if name:
        idx = summary.lower().find(name.lower())
        if idx != -1:
            return _strip_separators(summary[idx + len(name):])
    for sep in (" : ", ":", " - ", " – ", " — "):
        if sep in summary:
            return _strip_separators(summary.rsplit(sep, 1)[-1])
    return summary


def _strip_separators(value: str) -> str:
    return re.sub(r"^\s*[:\-–—]+\s*", "", str(value or "")).strip()


def _link_type_text(link_type: dict) -> str:
    return " | ".join(
        _clean(link_type.get(k)) for k in ("name", "outward", "inward") if _clean(link_type.get(k))
    )


def _issue_type(issue: dict) -> str:
    it = (issue.get("fields") or {}).get("issuetype") or issue.get("issuetype") or {}
    return _clean(it.get("name")) if isinstance(it, dict) else _clean(it)


def _status(issue: dict) -> str:
    st = (issue.get("fields") or {}).get("status") or issue.get("status") or {}
    return _clean(st.get("name")) if isinstance(st, dict) else _clean(st)


def _skip_status(issue: dict) -> bool:
    """True if the issue's status means it isn't real GT (cancelled or not-yet-committed To Do)."""
    return _status(issue).lower() in _SKIP_STATUSES


def _option_text(value: dict) -> str:
    for key in ("value", "name", "displayName", "text"):
        if value.get(key):
            return _clean(value.get(key))
    return ""


async def _safe_search(jira: StageJiraClient, jql: str, fields: Sequence[str]) -> list[dict]:
    try:
        return await jira.search(jql, fields=fields)
    except Exception:
        return []  # one lookup path failing must not stop the others


async def _safe_get(jira: StageJiraClient, key: str, fields: Sequence[str]) -> dict | None:
    try:
        return await jira.get_issue(key, fields=fields)
    except Exception:
        return None


def _norm(text: str) -> str:
    text = re.sub(r"\s*\([^)]*\)\s*$", "", str(text or ""))  # drop trailing "(...)"
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _coerce_text(value: object) -> str:
    """Plain text from a Jira field: string, ADF/dict, or list (recursively)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        if "content" in value:
            return _clean(" ".join(_adf_text(value)))
        for key in ("value", "text", "name"):
            if value.get(key):
                return _clean(value.get(key))
        return _clean(" ".join(_coerce_text(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return _clean(" ".join(_coerce_text(item) for item in value))
    return _clean(value)


def _adf_text(node: object) -> list[str]:
    if isinstance(node, dict):
        out = [str(node["text"])] if node.get("type") == "text" and node.get("text") else []
        for child in node.get("content") or []:
            out.extend(_adf_text(child))
        return out
    if isinstance(node, list):
        out = []
        for item in node:
            out.extend(_adf_text(item))
        return out
    return []


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())
