from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import List, Tuple

from ..tasks.model import TaskView


@dataclass
class HandoffPayload:
    task: TaskView
    recent_memories: List[Tuple[str, str]] = field(default_factory=list)


def render_handoff_markdown(payload: HandoffPayload) -> str:
    t = payload.task
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[str] = []

    out.append("---")
    out.append(f"task_id: {t.handle}")
    if t.parent:
        out.append(f"parent_id: {t.parent}")
    out.append(f"status: {t.status}")
    out.append(f"created_at: {now}")
    out.append(f"scope: {t.scope}")
    out.append("---")
    out.append("")

    out.append(f"# Handoff: {t.title}")
    out.append("")
    out.append("## Intent")
    out.append(t.intent.strip() or "(no intent set)")
    out.append("")

    if t.acceptance:
        out.append("## Acceptance")
        for a in t.acceptance:
            out.append(f"- [ ] {a}")
        out.append("")

    if t.decisions_made:
        out.append("## Decisions made this session")
        for d in t.decisions_made:
            out.append(f"- {d}")
        out.append("")

    if t.open_questions:
        out.append("## Open questions")
        for q in t.open_questions:
            out.append(f"- {q}")
        out.append("")

    if t.context_handles:
        out.append("## Context handles")
        for h in t.context_handles:
            out.append(f"- {h}")
        out.append("")

    if payload.recent_memories:
        out.append("## Recent memory writes")
        for handle, text in payload.recent_memories:
            short = text.strip().splitlines()[0][:100] if text.strip() else ""
            out.append(f"- {handle}  \"{short}\"")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
