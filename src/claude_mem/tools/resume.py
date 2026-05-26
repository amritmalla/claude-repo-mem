from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..handoff.resume import resume


def tool_schema() -> Tool:
    return Tool(
        name="resume",
        description=(
            "Pick up a task from its most recent handoff snapshot. Returns the "
            "snapshot markdown and a budgeted bundle of the task's context handles. "
            "Use at the start of a fresh session when continuing work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "budget": {"type": "integer", "default": 4000, "minimum": 200},
            },
            "required": ["task_id"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    try:
        r = resume(settings, task_id=args["task_id"], budget=args.get("budget", 4000))
    except KeyError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(type="text", text=json.dumps({
        "task_id": r.task_id,
        "snapshot_markdown": r.snapshot_markdown,
        "hydrated_items": r.hydrated_items,
        "overflow_handles": r.overflow_handles,
    }))]
