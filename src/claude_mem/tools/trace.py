from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool, TextContent

from ..config import Settings
from ..retrieval.trace import trace, DEFAULT_BUDGET, DEFAULT_DEPTH


def tool_schema() -> Tool:
    return Tool(
        name="trace",
        description=(
            "Traverse from one or more seed handles to connected units (callers, "
            "handlers, hooks, routes, imports) and return full source code inline "
            "for top hits in one round-trip. Use this INSTEAD of repeated expand "
            "calls when you need to follow code flow."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "seed_handles": {"type": "array", "items": {"type": "string"},
                                  "description": "Handles from a prior recall result"},
                "depth": {"type": "integer", "default": DEFAULT_DEPTH,
                          "description": "Max BFS hops (capped at 3)"},
                "budget": {"type": "integer", "default": DEFAULT_BUDGET,
                           "description": "Max tokens to return (default 8000)"},
                "relations": {"type": "array", "items": {"type": "string"},
                              "description": "Filter on relation kinds (e.g. ['route_to','imports'])"},
            },
            "required": ["seed_handles"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    result = trace(
        settings,
        seeds=args["seed_handles"],
        depth=args.get("depth", DEFAULT_DEPTH),
        budget=args.get("budget", DEFAULT_BUDGET),
        relations=args.get("relations"),
    )
    payload = {
        "items": [
            {
                "handle": it.handle,
                "tier": it.tier,
                "content": it.content,
                "rank": it.rank,
                "scope": it.scope,
                "layer": it.layer,
            }
            for it in result.items
        ],
        "overflow_handles": result.overflow_handles,
        "budget_used": result.budget_used,
        "budget_total": result.budget_total,
        "tier_histogram": result.tier_histogram,
    }
    return [TextContent(type="text", text=json.dumps(payload))]
