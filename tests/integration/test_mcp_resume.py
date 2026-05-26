import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.units.model import Unit
from claude_repo_mem.tasks.planner import plan_task
from claude_repo_mem.handoff.snapshot import handoff
from claude_repo_mem.tools.resume import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "resume"
    assert "task_id" in s.inputSchema["properties"]
    assert s.inputSchema.get("required") == ["task_id"]


@pytest.mark.asyncio
async def test_handle_returns_resume_bundle(settings):
    repo = Repository(connect(settings.db_path))
    repo.upsert_unit(Unit(
        id="code://function/abc", layer="code", kind="function", scope="x",
        source_ref=None, content_hash="h", t1_header="def f()",
        created_at=0, last_seen_at=0, t2_summary="Does f.",
    ))
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(
        settings, intent="x", llm=llm, context_handles=["code://function/abc"],
    )
    handoff(settings, task_id=plan.root.handle)

    out = await handle(settings, {"task_id": plan.root.handle})
    payload = json.loads(out[0].text)
    assert payload["task_id"] == plan.root.handle
    assert "snapshot_markdown" in payload
    assert payload["hydrated_items"]
    assert payload["hydrated_items"][0]["handle"] == "code://function/abc"


@pytest.mark.asyncio
async def test_handle_unknown_task_returns_error(settings):
    out = await handle(settings, {"task_id": "task://task/zzzzzzzzzzzz"})
    payload = json.loads(out[0].text)
    assert "error" in payload
