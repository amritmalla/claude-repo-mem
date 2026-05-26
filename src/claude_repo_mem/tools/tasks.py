from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any
from mcp.types import Tool, TextContent

from ..config import Settings
from ..db.connection import connect
from ..db.repository import _row_to_unit  # type: ignore[attr-defined]
from ..tasks.model import unit_metadata_to_task


def tool_schema() -> Tool:
    return Tool(
        name="tasks",
        description="List tasks. Filter by status, scope, or recency (since_days).",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "active", "done", "blocked"]},
                "scope": {"type": "string"},
                "since_days": {"type": "integer"},
            },
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    conn = connect(settings.db_path)
    sql = "SELECT * FROM unit WHERE layer='task'"
    params: list[Any] = []
    if scope := args.get("scope"):
        sql += " AND scope = ?"
        params.append(scope)
    if since := args.get("since_days"):
        sql += " AND last_seen_at >= ?"
        params.append(int(time.time()) - int(since) * 86400)
    sql += " ORDER BY last_seen_at DESC LIMIT 500"

    rows = conn.execute(sql, params).fetchall()
    out = []
    status_filter = args.get("status")
    for row in rows:
        u = _row_to_unit(row)
        t = unit_metadata_to_task(u)
        if status_filter and t.status != status_filter:
            continue
        out.append({
            "handle": t.handle, "title": t.title, "intent": t.intent,
            "status": t.status, "scope": t.scope, "acceptance": t.acceptance,
            "context_handles": t.context_handles, "parent": t.parent,
        })
    return [TextContent(type="text", text=json.dumps({"tasks": out}))]
