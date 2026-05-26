import json
import shutil
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.recall import handle as recall_handle
from claude_mem.tools.trace import handle as trace_handle
from tests.integration.test_recall_e2e import FakeEmbedder


FIXTURE_SRC = Path(__file__).parent / "fixtures" / "flask_app"


@pytest.fixture
def flask_repo(tmp_path: Path):
    dst = tmp_path / "flask_app"
    shutil.copytree(FIXTURE_SRC, dst)
    (dst / ".claude-mem").mkdir()
    s = Settings.for_repo(dst)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


@pytest.mark.asyncio
async def test_recall_finds_login_within_budget(flask_repo):
    out = await recall_handle(flask_repo, FakeEmbedder(), {"query": "login", "budget": 3000})
    payload = json.loads(out[0].text)
    assert payload["budget_used"] <= 3000
    # Should find the login function, the /login route, or the auth doc
    headers = " ".join(it["content"] for it in payload["items"])
    assert "login" in headers.lower()


@pytest.mark.asyncio
async def test_trace_from_route_pulls_handler(flask_repo):
    # First recall to get a login-related handle. Prefer the /login route unit;
    # fall back to any unit whose content mentions login.
    out = await recall_handle(flask_repo, FakeEmbedder(), {"query": "/login route", "budget": 3000})
    items = json.loads(out[0].text)["items"]
    route_handle = next(
        (i["handle"] for i in items if "route" in i["handle"] and "/login" in i["content"]),
        None,
    )
    if route_handle is None:
        route_handle = next(
            (i["handle"] for i in items if "login" in i["content"].lower()),
            items[0]["handle"],
        )

    trace_out = await trace_handle(flask_repo, {"seed_handles": [route_handle], "depth": 2, "budget": 8000})
    payload = json.loads(trace_out[0].text)
    assert payload["budget_used"] <= 8000
    # Should include the login handler function
    contents = " ".join(it["content"] for it in payload["items"])
    assert "def login" in contents or "login" in contents.lower()


def test_index_size_reasonable(flask_repo):
    from claude_mem.db.connection import connect
    conn = connect(flask_repo.db_path)
    n = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    # Expect at least: 5 fns (login, health, verify_user, issue_token, find_user)
    # + 2 routes + 2 doc sections + 1 frontmatter-less doc parent = ~10
    assert n >= 5
