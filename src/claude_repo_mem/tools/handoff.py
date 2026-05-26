from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..handoff.snapshot import handoff


def tool_schema() -> Tool:
    return Tool(
        name="handoff",
        description=(
            "Render the current state of a task to a markdown snapshot under "
            ".claude-repo-mem/handoffs/ and write a task_snapshot unit. Use at the end "
            "of a working session or before a context-budget reset. Returns the "
            "snapshot handle and the markdown path."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Handle of the task to snapshot"},
            },
            "required": ["task_id"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    try:
        result = handoff(settings, task_id=args["task_id"])
    except (KeyError, ValueError) as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(type="text", text=json.dumps({
        "task_id": result.task_id,
        "snapshot_handle": result.snapshot_handle,
        "markdown_path": str(result.markdown_path),
    }))]
