from pathlib import Path
import json
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.tasks.planner import plan_task
from claude_mem.memory.writer import remember
from claude_mem.handoff.snapshot import handoff, SnapshotResult


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


async def _seed_task(settings):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(settings, intent="ship feature", llm=llm)
    return plan.root.handle


@pytest.mark.asyncio
async def test_handoff_writes_markdown_file(settings):
    task_id = await _seed_task(settings)
    result = handoff(settings, task_id=task_id)
    assert isinstance(result, SnapshotResult)
    assert result.markdown_path.exists()
    content = result.markdown_path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert task_id in content
    assert "# Handoff:" in content


@pytest.mark.asyncio
async def test_handoff_creates_task_snapshot_unit(settings):
    task_id = await _seed_task(settings)
    result = handoff(settings, task_id=task_id)
    repo = Repository(connect(settings.db_path))
    snap = repo.get_unit(result.snapshot_handle)
    assert snap is not None
    assert snap.layer == "task"
    assert snap.kind == "task_snapshot"
    assert snap.parent_id == task_id
    assert snap.source_ref and snap.source_ref.endswith(".md")


@pytest.mark.asyncio
async def test_handoff_includes_recent_memories(settings):
    task_id = await _seed_task(settings)
    remember(settings, fact="We use RS256.", scope="backend/auth", kind="decision")
    remember(settings, fact="Tests run with pytest -q.", scope="tooling", kind="convention")
    result = handoff(settings, task_id=task_id)
    content = result.markdown_path.read_text(encoding="utf-8")
    assert "RS256" in content
    assert "pytest -q" in content


@pytest.mark.asyncio
async def test_handoff_unknown_task_raises(settings):
    with pytest.raises(KeyError):
        handoff(settings, task_id="task://task/doesnotexist")


@pytest.mark.asyncio
async def test_handoff_rejects_non_task_unit(settings):
    from claude_mem.units.model import Unit
    repo = Repository(connect(settings.db_path))
    repo.upsert_unit(Unit(
        id="code://function/x", layer="code", kind="function", scope="x",
        source_ref=None, content_hash="h", t1_header="t",
        created_at=0, last_seen_at=0,
    ))
    with pytest.raises(ValueError):
        handoff(settings, task_id="code://function/x")
