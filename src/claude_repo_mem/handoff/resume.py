from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..tasks.model import unit_metadata_to_task


@dataclass
class ResumeResult:
    task_id: str
    snapshot_markdown: str
    hydrated_items: List[dict] = field(default_factory=list)
    overflow_handles: List[str] = field(default_factory=list)


def resume(settings: Settings, *, task_id: str, budget: int = 4000) -> ResumeResult:
    conn = connect(settings.db_path)
    repo = Repository(conn)

    task_unit = repo.get_unit(task_id)
    if task_unit is None:
        raise KeyError(f"unknown task: {task_id}")

    snap_row = conn.execute(
        "SELECT * FROM unit WHERE layer='task' AND kind='task_snapshot' AND parent_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if snap_row is None:
        raise KeyError(f"no snapshot exists for {task_id}")

    md_path = Path(snap_row["source_ref"])
    snapshot_markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

    task = unit_metadata_to_task(task_unit)
    handles = list(task.context_handles)

    hydrated: list[dict] = []
    overflow: list[str] = []
    used = 0
    for h in handles:
        u = repo.get_unit(h)
        if u is None:
            overflow.append(h)
            continue
        body = u.t2_summary or u.t1_header
        cost = _approx_tokens(body) + _approx_tokens(u.t1_header)
        if used + cost > budget:
            overflow.append(h)
            continue
        used += cost
        hydrated.append({
            "handle": h,
            "header": u.t1_header,
            "tier_2": u.t2_summary or "",
            "layer": u.layer,
            "kind": u.kind,
        })

    return ResumeResult(
        task_id=task_id,
        snapshot_markdown=snapshot_markdown,
        hydrated_items=hydrated,
        overflow_handles=overflow,
    )


def _approx_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)
