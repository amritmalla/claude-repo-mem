from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

from ..units.model import Unit


TaskStatus = Literal["pending", "active", "done", "blocked"]
VALID_STATUSES = {"pending", "active", "done", "blocked"}


@dataclass
class TaskView:
    handle: str
    title: str
    intent: str
    status: str = "pending"
    scope: str = "root"
    acceptance: list[str] = field(default_factory=list)
    context_handles: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    parent: Optional[str] = None
    session_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid task status: {self.status!r}")


def task_to_unit_metadata(t: TaskView) -> dict:
    return {
        "title": t.title,
        "intent": t.intent,
        "status": t.status,
        "acceptance": list(t.acceptance),
        "context_handles": list(t.context_handles),
        "open_questions": list(t.open_questions),
        "decisions_made": list(t.decisions_made),
        "session_id": t.session_id,
    }


def unit_metadata_to_task(unit: Unit) -> TaskView:
    meta = json.loads(unit.metadata) if unit.metadata else {}
    return TaskView(
        handle=unit.id,
        title=meta.get("title", ""),
        intent=meta.get("intent", ""),
        status=meta.get("status", "pending"),
        scope=unit.scope,
        acceptance=list(meta.get("acceptance", [])),
        context_handles=list(meta.get("context_handles", [])),
        open_questions=list(meta.get("open_questions", [])),
        decisions_made=list(meta.get("decisions_made", [])),
        parent=unit.parent_id,
        session_id=meta.get("session_id"),
    )
