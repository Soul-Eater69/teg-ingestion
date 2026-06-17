"""Adapt a doc to the org Cosmos container schema, at the write boundary.

The ingestion builders already emit this shape directly, so here ``to_cosmos_doc`` is an
**idempotent** safety pass (re-applying it is a no-op). The org schema (from the existing
``Items`` containers):

- hierarchical partition key ``/domain`` + ``/entityType``; every doc carries ``domain``,
- ``domain`` = ``WORKITEM``,
- ``entityType`` / ``source`` / ``createdBy`` / ``lastModifiedBy`` are UPPERCASE,
- no ``properties.themes`` - the VS ground truth lives in the separate Theme docs (parentRef).
"""

from __future__ import annotations

DOMAIN = "WORKITEM"
_UPPER_FIELDS = ("entityType", "source", "createdBy", "lastModifiedBy")


def to_cosmos_doc(doc: dict) -> dict:
    """Return a copy of ``doc`` in the Cosmos container schema (does not mutate the input)."""
    out = dict(doc)
    out["domain"] = DOMAIN
    for field in _UPPER_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value:
            out[field] = value.upper()
    props = out.get("properties")
    if isinstance(props, dict) and "themes" in props:
        props = dict(props)
        props.pop("themes")  # GT is in the Theme docs (entityType THEME, parentRef = this id)
        out["properties"] = props
    return out
