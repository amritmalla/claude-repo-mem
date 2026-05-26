from __future__ import annotations

import asyncio
from dataclasses import replace

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository, _row_to_unit  # type: ignore[attr-defined]
from ..llm.base import LLMClient
from .summarize import summarize_unit


async def backfill_summaries(settings: Settings, *, llm: LLMClient, limit: int = 1000) -> dict:
    conn = connect(settings.db_path)
    repo = Repository(conn)
    rows = conn.execute(
        "SELECT * FROM unit WHERE t2_summary IS NULL AND layer IN ('code','docs') "
        "ORDER BY last_seen_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    n = 0
    for row in rows:
        u = _row_to_unit(row)
        summary = await summarize_unit(u, llm)
        if summary:
            repo.upsert_unit(replace(u, t2_summary=summary))
            n += 1
    conn.close()
    return {"units_summarized": n, "units_considered": len(rows)}


def backfill_summaries_sync(settings: Settings, *, llm: LLMClient, limit: int = 1000) -> dict:
    """Synchronous wrapper around the async backfill (for the BackgroundQueue)."""
    return asyncio.run(backfill_summaries(settings, llm=llm, limit=limit))


def enqueue_backfill(settings: Settings, *, llm: LLMClient, queue, limit: int = 1000) -> None:
    """Submit a backfill job onto the given BackgroundQueue."""
    queue.submit(lambda: backfill_summaries_sync(settings, llm=llm, limit=limit))
