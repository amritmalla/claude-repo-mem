import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.tasks.planner import plan_task


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


@pytest.mark.asyncio
async def test_plan_task_creates_root_and_children(settings):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [
            {"title": "A", "intent": "do a", "acceptance": ["done a"]},
            {"title": "B", "intent": "do b", "acceptance": ["done b"]},
        ]
    }))
    result = await plan_task(settings, intent="big thing", llm=llm)
    assert result.root.handle.startswith("task://")
    assert len(result.children) == 2
    assert result.children[0].title == "A"
    assert result.children[0].acceptance == ["done a"]

    repo = Repository(connect(settings.db_path))
    assert repo.get_unit(result.root.handle) is not None
    for c in result.children:
        assert repo.get_unit(c.handle) is not None


@pytest.mark.asyncio
async def test_plan_task_malformed_json_returns_single_subtask(settings):
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="not json at all")
    result = await plan_task(settings, intent="x", llm=llm)
    assert len(result.children) == 1
    assert "decompose" in result.children[0].title.lower()


@pytest.mark.asyncio
async def test_plan_task_propagates_context_handles(settings):
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    result = await plan_task(
        settings, intent="i", llm=llm,
        context_handles=["code://function/abc"],
    )
    assert result.children[0].context_handles == ["code://function/abc"]
