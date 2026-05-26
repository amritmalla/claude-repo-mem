import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.tools.plan_task import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "plan_task"
    assert "intent" in s.inputSchema["required"]


@pytest.mark.asyncio
async def test_handle_returns_task_tree(settings):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": ["x"]}]
    }))
    out = await handle(settings, llm, {"intent": "Add token refresh"})
    payload = json.loads(out[0].text)
    assert payload["root"]["handle"].startswith("task://")
    assert len(payload["children"]) == 1
    assert payload["children"][0]["title"] == "A"
