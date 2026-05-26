from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..tasks.model import unit_metadata_to_task
from ..units.model import Unit
from .render import HandoffPayload, render_handoff_markdown


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_handle: str
    markdown_path: Path
    task_id: str


RECENT_MEMORY_LIMIT = 10


def handoff(settings: Settings, *, task_id: str) -> SnapshotResult:
    """Render the task to .claude-repo-mem/handoffs/<short>.md and write a task_snapshot unit."""
    conn = connect(settings.db_path)
    repo = Repository(conn)

    task_unit = repo.get_unit(task_id)
    if task_unit is None:
        raise KeyError(task_id)
    if task_unit.layer != "task" or task_unit.kind != "task":
        raise ValueError(
            f"handoff() requires a task unit (kind='task'); got "
            f"layer={task_unit.layer!r} kind={task_unit.kind!r}"
        )

    task = unit_metadata_to_task(task_unit)

    rows = conn.execute(
        "SELECT id, metadata FROM unit WHERE layer='memory' AND superseded_by IS NULL "
        "ORDER BY last_seen_at DESC LIMIT ?",
        (RECENT_MEMORY_LIMIT,),
    ).fetchall()
    recent_memories: list[tuple[str, str]] = []
    for r in rows:
        meta = json.loads(r["metadata"]) if r["metadata"] else {}
        body = meta.get("body", "")
        recent_memories.append((r["id"], body))

    payload = HandoffPayload(task=task, recent_memories=recent_memories)
    md = render_handoff_markdown(payload)

    handoffs_dir = settings.handoffs_dir
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    short = task_id.rsplit("/", 1)[-1]
    path = handoffs_dir / f"{short}.md"
    path.write_text(md, encoding="utf-8")

    now = int(time.time())
    content_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()
    snap_id = f"task://task_snapshot/{content_hash[:12]}"
    snap = Unit(
        id=snap_id,
        layer="task",
        kind="task_snapshot",
        scope=task.scope,
        source_ref=str(path),
        content_hash=content_hash,
        t1_header=f"[task_snapshot] {task.title[:80]}",
        created_at=now,
        last_seen_at=now,
        parent_id=task_id,
        metadata=json.dumps({"task_id": task_id, "rendered_at": now}),
    )
    repo.upsert_unit(snap)
    return SnapshotResult(snapshot_handle=snap_id, markdown_path=path, task_id=task_id)
