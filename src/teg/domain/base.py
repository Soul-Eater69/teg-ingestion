"""Shared model base: snake_case attributes in Python, camelCase on the wire.

Records are defined once and used both internally and at the backend boundary.
Serialize with ``model_dump(by_alias=True)`` (or ``model_dump_json``) for camelCase.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
