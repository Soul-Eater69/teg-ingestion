"""Resolved theme ground-truth record.

One per linked Theme after VS resolution (theme summary -> approved catalogue VS). This is
what becomes an entry in the ER's ``properties.themes[]`` (and links to the Theme doc via
``theme_stable_id``). Historic direct/implied support classification was removed: an ablation
showed it added no relevance and slightly hurt, so the historic lane carries only the VS id+name.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeGroundTruth:
    theme_stable_id: str  # -> Theme doc id (themes[].key)
    group_key: str  # GROUP-#### (themes[].groupId)
    value_stream_id: str  # resolved approved VS id
    value_stream_name: str  # resolved canonical VS name
