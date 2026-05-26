from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool, TextContent

from ..config import Settings
from ..embeddings.base import Embedder
from ..retrieval.recall import recall, DEFAULT_BUDGET


def tool_schema() -> Tool:
    return Tool(
        name="recall",
        description=(
            "Hybrid retrieve from claude-repo-mem. Returns ranked, budget-filled results "
            "(T0 full content for top hits, T2 summary for mid-tier, T1 header for tail). "
            "Use this BEFORE native Read/Grep when looking for code or docs in this repo."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language query"},
                "budget": {"type": "integer", "default": DEFAULT_BUDGET,
                           "description": "Max tokens to return (default 3000)"},
                "scopes": {"type": "array", "items": {"type": "string"},
                           "description": "Scope filter (e.g. ['backend/auth'])"},
                "layers": {"type": "array", "items": {"type": "string", "enum": ["memory", "docs", "code"]}},
                "include_superseded": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    )


async def handle(settings: Settings, embedder: Embedder, args: dict[str, Any]) -> list[TextContent]:
    from ..observability.counters import get_counters
    try:
        get_counters().recall_calls += 1
    except Exception:
        pass
    result = recall(
        settings,
        query=args["query"],
        embedder=embedder,
        budget=args.get("budget", DEFAULT_BUDGET),
        scopes=args.get("scopes"),
        layers=args.get("layers"),
        include_superseded=args.get("include_superseded", False),
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
