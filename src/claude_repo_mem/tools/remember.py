from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..memory.writer import remember


def tool_schema() -> Tool:
    return Tool(
        name="remember",
        description=(
            "Write a durable memory entry. Use when you learn something the user "
            "will care about across sessions: a decision, convention, preference, "
            "or fact about this repo. Returns an opaque handle and the markdown "
            "file path. Memory files live at .claude-repo-mem/memory/<scope>/<slug>.md "
            "and are git-trackable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The text to remember"},
                "scope": {"type": "string", "description": "Scope, e.g. 'backend/auth'"},
                "kind": {
                    "type": "string",
                    "enum": ["fact", "decision", "preference", "convention"],
                    "default": "fact",
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "supersedes": {"type": "string", "description": "Handle of unit being superseded"},
            },
            "required": ["fact", "scope"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    from ..observability.counters import get_counters
    try:
        get_counters().remember_calls += 1
    except Exception:
        pass
    try:
        result = remember(
            settings,
            fact=args["fact"],
            scope=args["scope"],
            kind=args.get("kind", "fact"),
            confidence=args.get("confidence"),
            supersedes=args.get("supersedes"),
        )
    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(
        type="text",
        text=json.dumps({
            "handle": result.handle,
            "slug": result.slug,
            "path": str(result.path),
        }),
    )]
