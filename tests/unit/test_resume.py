import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.units.model import Unit
from claude_mem.tasks.planner import plan_task
from claude_mem.handoff.snapshot import handoff
from claude_mem.handoff.resume import resume, ResumeResult


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


async def _seed_task_with_context(settings, extra_handles=None):
    repo = Repository(connect(settings.db_path))
    repo.upsert_unit(Unit(
        id="code://function/abc",
        layer="code", kind="function", scope="backend/auth",
        source_ref="src/auth.py", content_hash="h",
        t1_header="python issue_token(user)",
        created_at=0, last_seen_at=0,
        t2_summary="Issues a signed JWT for the user.",
    ))
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    handles = ["code://function/abc"] + list(extra_handles or [])
    plan = await plan_task(
        settings, intent="add refresh", llm=llm,
        context_handles=handles,
    )
    return plan.root.handle


@pytest.mark.asyncio
async def test_resume_returns_markdown_and_items(settings):
    task_id = await _seed_task_with_context(settings)
    handoff(settings, task_id=task_id)
    result = resume(settings, task_id=task_id, budget=4000)
    assert isinstance(result, ResumeResult)
    assert result.task_id == task_id
    assert "# Handoff:" in result.snapshot_markdown
    handles = [it["handle"] for it in result.hydrated_items]
    assert "code://function/abc" in handles


@pytest.mark.asyncio
async def test_resume_no_snapshot_raises(settings):
    with pytest.raises(KeyError):
        resume(settings, task_id="task://task/nope", budget=4000)


@pytest.mark.asyncio
async def test_resume_uses_t2_summary(settings):
    task_id = await _seed_task_with_context(settings)
    handoff(settings, task_id=task_id)
    result = resume(settings, task_id=task_id, budget=4000)
    [item] = [it for it in result.hydrated_items if it["handle"] == "code://function/abc"]
    assert "Issues a signed JWT" in item.get("tier_2", "")


@pytest.mark.asyncio
async def test_resume_overflow_handles_when_budget_tight(settings):
    # Seed 20 extra units, all with text long enough to blow a 200-token budget.
    repo = Repository(connect(settings.db_path))
    extra = []
    long_summary = "summary " * 50  # plenty of tokens
    for i in range(20):
        h = f"code://function/x{i:02d}"
        repo.upsert_unit(Unit(
            id=h, layer="code", kind="function", scope="x",
            source_ref=f"src/x{i}.py", content_hash="h",
            t1_header=f"function x{i} with a longer header to consume budget",
            created_at=0, last_seen_at=0,
            t2_summary=long_summary,
        ))
        extra.append(h)
    task_id = await _seed_task_with_context(settings, extra_handles=extra)
    handoff(settings, task_id=task_id)

    result = resume(settings, task_id=task_id, budget=200)
    assert len(result.overflow_handles) > 0
