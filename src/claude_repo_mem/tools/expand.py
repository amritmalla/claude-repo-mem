from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool, TextContent

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository


def tool_schema() -> Tool:
    return Tool(
        name="expand",
        description=(
            "Return one unit at a specific tier (T0 full source, T2 LLM summary, "
            "or T1 header). Use this for long-tail drill-down — the common case "
            "of 'top result + full code' is already handled by recall and trace."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Opaque handle from recall/trace"},
                "tier": {"type": "string", "enum": ["T0", "T2", "T1"], "default": "T0"},
            },
            "required": ["handle"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    from ..observability.counters import get_counters
    try:
        get_counters().expand_calls += 1
    except Exception:
        pass
    repo = Repository(connect(settings.db_path))
    unit = repo.get_unit(args["handle"])
    if unit is None:
        return [TextContent(type="text", text=json.dumps({"error": "handle not found"}))]
    tier = args.get("tier", "T0")
    if tier == "T1":
        content = unit.t1_header
    elif tier == "T2":
        content = unit.t2_summary or unit.t1_header
    else:
        content = unit.metadata or unit.t2_summary or unit.t1_header
    payload = {
        "handle": unit.id,
        "tier": tier,
        "content": content,
        "scope": unit.scope,
        "layer": unit.layer,
        "kind": unit.kind,
        "source_ref": unit.source_ref,
    }
    return [TextContent(type="text", text=json.dumps(payload))]
