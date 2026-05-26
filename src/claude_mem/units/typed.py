from __future__ import annotations

import json
from typing import Any
from dataclasses import replace

from .model import Unit


KIND_VALID_FOR_LAYER: dict[str, set[str]] = {
    "memory": {"fact", "decision", "preference", "convention"},
    "task": {"task", "task_snapshot"},
    "docs": {"section", "frontmatter"},
    "code": {"function", "method", "class", "route", "interface", "module", "struct", "trait"},
}


def metadata_json(unit: Unit) -> dict[str, Any]:
    """Parse metadata as JSON. Returns {} for None, missing, or invalid."""
    if not unit.metadata:
        return {}
    try:
        v = json.loads(unit.metadata)
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def with_metadata(unit: Unit, data: dict[str, Any]) -> Unit:
    return replace(unit, metadata=json.dumps(data))
