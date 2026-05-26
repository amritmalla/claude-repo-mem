from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..memory.writer import forget


def tool_schema() -> Tool:
    return Tool(
        name="forget",
        description=(
            "Tombstone a memory unit by handle. Marks the unit as superseded; "
            "appends `tombstoned: true` to the markdown frontmatter (file is NOT "
            "deleted). Use when a memory has become wrong or obsolete."
        ),
        inputSchema={
            "type": "object",
            "properties": {"handle": {"type": "string"}},
            "required": ["handle"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    from ..observability.counters import get_counters
    try:
        get_counters().forget_calls += 1
    except Exception:
        pass
    try:
        forget(settings, handle=args["handle"])
        return [TextContent(type="text", text=json.dumps({"ok": True}))]
    except (KeyError, ValueError) as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
