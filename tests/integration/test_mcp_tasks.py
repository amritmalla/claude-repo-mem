import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.tasks.planner import plan_task
from claude_mem.tools.tasks import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    assert tool_schema().name == "tasks"


@pytest.mark.asyncio
async def test_lists_persisted_tasks(settings):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    await plan_task(settings, intent="parent", llm=llm)
    out = await handle(settings, {})
    payload = json.loads(out[0].text)
    titles = [t["title"] for t in payload["tasks"]]
    assert "A" in titles


@pytest.mark.asyncio
async def test_status_filter(settings):
    out = await handle(settings, {"status": "done"})
    payload = json.loads(out[0].text)
    assert payload["tasks"] == []
