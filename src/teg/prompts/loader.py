"""Load prompt templates from this package.

One loader for every prompt. Templates are YAML with ``system`` / ``user`` keys
(and an optional ``version``). Rendering replaces only the named ``{placeholders}``
we pass in, so literal JSON braces in a prompt body are left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

import yaml


@dataclass(frozen=True)
class Prompt:
    name: str
    system: str
    user: str
    version: str = ""

    def render(self, **values: object) -> tuple[str, str]:
        """Return (system, user) with ``{key}`` placeholders filled."""
        return self._fill(self.system, values), self._fill(self.user, values)

    @staticmethod
    def _fill(text: str, values: dict[str, object]) -> str:
        for key, value in values.items():
            text = text.replace("{" + key + "}", str(value))
        return text


@lru_cache(maxsize=None)
def load_prompt(name: str) -> Prompt:
    """Load a prompt by path under ``src/teg/prompts/`` (cached).

    ``name`` is a slash path without extension, e.g. ``"condense/condense"`` or
    ``"theme/stage_prediction"``.
    """
    resource = resources.files(__package__)
    for part in f"{name}.yaml".split("/"):
        resource = resource.joinpath(part)
    raw = resource.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return Prompt(
        name=name,
        system=data["system"],
        user=data.get("user", ""),
        version=str(data.get("version", "")),
    )
