import json
from pathlib import Path
import pytest
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.memory.writer import remember
from claude_repo_mem.tools.forget import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "forget"
    assert "handle" in s.inputSchema["properties"]


@pytest.mark.asyncio
async def test_handle_tombstones(settings):
    r = remember(settings, fact="x", scope="x")
    out = await handle(settings, {"handle": r.handle})
    payload = json.loads(out[0].text)
    assert payload.get("ok") is True


@pytest.mark.asyncio
async def test_handle_unknown_returns_error(settings):
    out = await handle(settings, {"handle": "memory://decision/zzzzzzzzzzzz"})
    payload = json.loads(out[0].text)
    assert "error" in payload
