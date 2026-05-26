from __future__ import annotations

import json
from typing import Any, Optional
from mcp.types import Tool, TextContent

from ..config import Settings
from ..llm.base import LLMClient
from ..tasks.planner import plan_task as _plan_task


def tool_schema() -> Tool:
    return Tool(
        name="plan_task",
        description=(
            "Decompose a high-level intent into 2-6 INDEPENDENT child tasks via "
            "the LLM. Persists the task tree and returns it. Use at the start of "
            "any multi-step engineering task before writing code."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "parent_id": {"type": "string"},
                "scope": {"type": "string", "default": "root"},
                "context_handles": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["intent"],
        },
    )


async def handle(
    settings: Settings,
    llm: LLMClient,
    args: dict[str, Any],
) -> list[TextContent]:
    from ..observability.counters import get_counters
    try:
        get_counters().plan_task_calls += 1
    except Exception:
        pass
    result = await _plan_task(
        settings,
        intent=args["intent"],
        llm=llm,
        parent_id=args.get("parent_id"),
        scope=args.get("scope", "root"),
        context_handles=args.get("context_handles"),
    )
    payload = {
        "root": {
            "handle": result.root.handle,
            "title": result.root.title,
            "intent": result.root.intent,
        },
        "children": [
            {
                "handle": c.handle,
                "title": c.title,
                "intent": c.intent,
                "acceptance": c.acceptance,
                "context_handles": c.context_handles,
            }
            for c in result.children
        ],
    }
    return [TextContent(type="text", text=json.dumps(payload))]
