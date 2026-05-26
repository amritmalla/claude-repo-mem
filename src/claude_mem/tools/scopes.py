from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..db.connection import connect


def tool_schema() -> Tool:
    return Tool(
        name="scopes",
        description="List known scopes for this repo with unit counts.",
        inputSchema={"type": "object", "properties": {}},
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    conn = connect(settings.db_path)
    rows = conn.execute(
        "SELECT scope, COUNT(*) AS n FROM unit "
        "WHERE superseded_by IS NULL "
        "GROUP BY scope ORDER BY n DESC"
    ).fetchall()
    payload = {"scopes": [{"scope": r["scope"], "count": r["n"]} for r in rows]}
    return [TextContent(type="text", text=json.dumps(payload))]
