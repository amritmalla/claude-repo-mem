from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..llm.base import LLMClient, LLMError
from ..units.headers import t1_header
from ..units.model import Unit, Relation
from .model import TaskView, task_to_unit_metadata
from .prompts import DECOMPOSE_SYSTEM, USER_TEMPLATE


@dataclass
class PlanResult:
    root: TaskView
    children: list[TaskView]


async def plan_task(
    settings: Settings,
    *,
    intent: str,
    llm: LLMClient,
    parent_id: Optional[str] = None,
    recall_bundle: str = "",
    scope: str = "root",
    context_handles: Optional[list[str]] = None,
) -> PlanResult:
    """Decompose `intent` into child tasks; persist the tree."""
    user = USER_TEMPLATE.format(recall_bundle=recall_bundle, intent=intent)
    try:
        raw = await llm.complete(
            system=DECOMPOSE_SYSTEM, user=user, max_tokens=2000, temperature=0.0
        )
    except LLMError as e:
        raw = ""

    subtasks_data = _parse_subtasks(raw, intent)

    repo = Repository(connect(settings.db_path))
    now = int(time.time())

    root_view = TaskView(
        handle=_make_task_handle(intent, parent_id or ""),
        title=intent.strip().splitlines()[0][:80] if intent.strip() else "task",
        intent=intent,
        status="pending",
        scope=scope,
        context_handles=list(context_handles or []),
        parent=parent_id,
    )
    _persist_task(repo, root_view, now)
    if parent_id:
        repo.add_relation(Relation(src_id=parent_id, dst_id=root_view.handle, kind="child_task"))

    children: list[TaskView] = []
    for i, sub in enumerate(subtasks_data):
        child = TaskView(
            handle=_make_task_handle(sub.get("intent") or sub.get("title", ""), root_view.handle + f":{i}"),
            title=sub.get("title", f"Subtask {i+1}"),
            intent=sub.get("intent", ""),
            status="pending",
            scope=scope,
            acceptance=list(sub.get("acceptance", [])),
            context_handles=list(context_handles or []),
            parent=root_view.handle,
        )
        _persist_task(repo, child, now)
        repo.add_relation(Relation(src_id=root_view.handle, dst_id=child.handle, kind="child_task"))
        children.append(child)

    return PlanResult(root=root_view, children=children)


def _parse_subtasks(raw: str, fallback_intent: str) -> list[dict]:
    if not raw:
        return [{"title": "Could not decompose", "intent": fallback_intent, "acceptance": []}]
    try:
        data = json.loads(raw)
        subs = data.get("subtasks") or []
        if not isinstance(subs, list) or not subs:
            raise ValueError("no subtasks")
        return subs
    except (json.JSONDecodeError, ValueError, TypeError):
        return [{"title": "Could not decompose", "intent": fallback_intent, "acceptance": []}]


def _make_task_handle(seed: str, salt: str) -> str:
    h = hashlib.sha256(f"{seed}\0{salt}\0{time.time_ns()}".encode("utf-8")).hexdigest()[:12]
    return f"task://task/{h}"


def _persist_task(repo: Repository, t: TaskView, now: int) -> None:
    meta = task_to_unit_metadata(t)
    unit = Unit(
        id=t.handle,
        layer="task",
        kind="task",
        scope=t.scope,
        source_ref=None,
        content_hash=hashlib.sha256((t.title + t.intent).encode("utf-8")).hexdigest(),
        t1_header=t1_header(layer="task", kind="task", text=f"{t.title}: {t.intent}"),
        created_at=now,
        last_seen_at=now,
        parent_id=t.parent,
        metadata=json.dumps(meta),
    )
    repo.upsert_unit(unit)
