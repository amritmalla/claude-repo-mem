import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.tasks.planner import plan_task
from claude_mem.tools.handoff import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "handoff"
    assert "task_id" in s.inputSchema["properties"]
    assert s.inputSchema.get("required") == ["task_id"]


@pytest.mark.asyncio
async def test_handle_returns_snapshot(settings):
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(settings, intent="big task", llm=llm)
    out = await handle(settings, {"task_id": plan.root.handle})
    payload = json.loads(out[0].text)
    assert payload["task_id"] == plan.root.handle
    assert payload["snapshot_handle"].startswith("task://task_snapshot/")
    assert Path(payload["markdown_path"]).exists()


@pytest.mark.asyncio
async def test_handle_unknown_task_returns_error(settings):
    out = await handle(settings, {"task_id": "task://task/zzzzzzzzzzzz"})
    payload = json.loads(out[0].text)
    assert "error" in payload
