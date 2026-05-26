import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.queue.background import BackgroundQueue
from claude_mem.summarizer.backfill import (
    enqueue_backfill,
    backfill_summaries_sync,
)


def test_sync_wrapper_populates_t2(tmp_repo: Path):
    (tmp_repo / "a.py").write_text(
        "def f():\n    " + "x = 1\n    " * 30 + "return x\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="canned")
    stats = backfill_summaries_sync(s, llm=llm)
    assert stats["units_summarized"] >= 1


def test_enqueue_backfill_runs_through_queue(tmp_repo: Path):
    (tmp_repo / "a.py").write_text(
        "def f():\n    " + "x = 1\n    " * 30 + "return x\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    q = BackgroundQueue(); q.start()
    try:
        llm = AsyncMock(); llm.complete = AsyncMock(return_value="from queue")
        enqueue_backfill(s, llm=llm, queue=q)
        q.drain(timeout=5.0)
        n = connect(s.db_path).execute(
            "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
        ).fetchone()[0]
        assert n >= 1
    finally:
        q.stop()
