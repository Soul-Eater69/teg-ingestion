"""Internal data shapes for the condense layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResolvedContext:
    ticket_id: str
    ticket_title: str
    description: str
    primary_source: str  # "idea_card" | "attachments_fallback"
    attachments_used: list[str] = field(default_factory=list)
    consolidated_text: str = ""
