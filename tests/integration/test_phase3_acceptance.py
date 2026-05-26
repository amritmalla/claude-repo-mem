"""Phase 3 acceptance — task survives a session boundary."""
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.memory.writer import remember
from claude_repo_mem.tasks.planner import plan_task
from claude_repo_mem.handoff.snapshot import handoff
from claude_repo_mem.handoff.resume import resume


@pytest.mark.asyncio
async def test_handoff_then_resume_round_trip(tmp_repo: Path):
    # --- Session 1: do work, hand off ---
    (tmp_repo / "auth.py").write_text(
        "def issue_token(user):\n    " + "x = 1\n    " * 30 + "return user\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    conn = connect(s.db_path)
    code_handle = conn.execute(
        "SELECT id FROM unit WHERE layer='code' AND t1_header LIKE '%issue_token%' LIMIT 1"
    ).fetchone()["id"]

    r1 = remember(s, fact="RS256 over HS256 for gateway verification.",
                  scope="backend/auth", kind="decision", confidence=0.9)

    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [
            {"title": "Add /refresh", "intent": "expose refresh", "acceptance": ["returns pair"]},
        ]
    }))
    plan = await plan_task(
        s, intent="add token refresh", llm=llm,
        context_handles=[code_handle, r1.handle],
    )

    snap = handoff(s, task_id=plan.root.handle)
    assert snap.markdown_path.exists()
    assert plan.root.handle in snap.markdown_path.read_text(encoding="utf-8")

    # --- Session 2: cold resume from the same DB ---
    s2 = Settings.for_repo(tmp_repo)
    result = resume(s2, task_id=plan.root.handle, budget=4000)
    assert result.task_id == plan.root.handle
    assert "RS256" in result.snapshot_markdown
    handles = [it["handle"] for it in result.hydrated_items]
    assert code_handle in handles
    assert r1.handle in handles
