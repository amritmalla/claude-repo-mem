from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..db.connection import connect
from ..observability.counters import get_counters


def tool_schema() -> Tool:
    return Tool(
        name="stats",
        description="Index size, layer breakdown, and tool-call counters.",
        inputSchema={"type": "object", "properties": {}},
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    conn = connect(settings.db_path)
    total = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    by_layer_rows = conn.execute(
        "SELECT layer, COUNT(*) AS n FROM unit GROUP BY layer"
    ).fetchall()
    n_rels = conn.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    payload = {
        "total_units": total,
        "by_layer": {r["layer"]: r["n"] for r in by_layer_rows},
        "total_relations": n_rels,
        "counters": get_counters().to_dict(),
    }
    return [TextContent(type="text", text=json.dumps(payload))]
