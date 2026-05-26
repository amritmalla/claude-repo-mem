"""Phase 2 acceptance — end-to-end pipeline check."""
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.memory.writer import remember
from claude_mem.summarizer.backfill import backfill_summaries
from claude_mem.tasks.planner import plan_task
from claude_mem.distill.confirm import run_distill


FIXTURE_TRANSCRIPT = Path(__file__).parent / "fixtures" / "synthetic_session.jsonl"


@pytest.mark.asyncio
async def test_phase2_end_to_end(tmp_repo: Path):
    # 1. Minimal repo + reindex.
    (tmp_repo / "auth.py").write_text(
        "def login(user, pw):\n    " + "x = 1\n    " * 30 + "return user\n"
    )
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    full_reindex(settings, embedder=None)

    # 2. Two remembers.
    r1 = remember(settings, fact="We use RS256.", scope="backend/auth", kind="decision", confidence=0.9)
    r2 = remember(settings, fact="Tests run with pytest -q.", scope="tooling", kind="convention", confidence=0.8)

    # 3. Backfill summaries with fake LLM.
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="canned summary")
    stats = await backfill_summaries(settings, llm=llm)
    assert stats["units_summarized"] >= 1

    # 4. plan_task with fake LLM returning 2 children.
    planner_llm = AsyncMock()
    planner_llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [
            {"title": "Add /refresh route", "intent": "expose refresh endpoint", "acceptance": ["returns new token"]},
            {"title": "Invalidate old", "intent": "blacklist old", "acceptance": ["old token rejected"]},
        ]
    }))
    plan = await plan_task(
        settings, intent="add token refresh", llm=planner_llm,
        context_handles=[r1.handle],
    )
    assert len(plan.children) == 2
    assert all(c.context_handles == [r1.handle] for c in plan.children)

    # 5. Distill with --yes equivalent.
    distill_llm = AsyncMock()
    distill_llm.complete = AsyncMock(return_value=json.dumps({
        "proposals": [
            {"kind": "decision", "scope": "backend/auth", "confidence": 0.95,
             "fact": "Chose RS256 over HS256 for gateway verification."}
        ]
    }))
    result = await run_distill(
        settings, llm=distill_llm, transcript_path=FIXTURE_TRANSCRIPT, auto_accept=True,
    )
    assert result["written"] >= 1

    # 6. Assertions.
    conn = connect(settings.db_path)
    n_mem = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer='memory' AND superseded_by IS NULL"
    ).fetchone()[0]
    assert n_mem >= 3  # r1, r2, distilled

    n_with_t2 = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
    ).fetchone()[0]
    assert n_with_t2 >= 1

    n_tasks = conn.execute("SELECT COUNT(*) FROM unit WHERE layer='task'").fetchone()[0]
    assert n_tasks == 3  # root + 2 children

    n_conf = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer='memory' AND confidence IS NOT NULL"
    ).fetchone()[0]
    assert n_conf >= 2
