from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.summarizer.backfill import backfill_summaries


@pytest.mark.asyncio
async def test_backfill_populates_t2(tmp_repo: Path):
    (tmp_repo / "x.py").write_text(
        "def f(a, b):\n    # some non-trivial body\n    return a + b\n\n"
        "def g():\n    " + "x = 1\n    " * 30 + "return x\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Generated summary.")
    stats = await backfill_summaries(s, llm=llm)

    assert stats["units_summarized"] >= 1
    conn = connect(s.db_path)
    n_with_t2 = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
    ).fetchone()[0]
    assert n_with_t2 >= 1


@pytest.mark.asyncio
async def test_backfill_skips_units_with_existing_t2(tmp_repo: Path):
    (tmp_repo / "x.py").write_text("def f():\n    " + "x = 1\n    " * 30 + "return x\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    llm = AsyncMock(); llm.complete = AsyncMock(return_value="first summary")
    await backfill_summaries(s, llm=llm)
    first_call_count = llm.complete.call_count

    await backfill_summaries(s, llm=llm)
    assert llm.complete.call_count == first_call_count
