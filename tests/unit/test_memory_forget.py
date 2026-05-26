import pytest
from pathlib import Path
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.memory.writer import remember, forget, TOMBSTONE_HANDLE


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_forget_marks_superseded_by_tombstone(settings):
    r = remember(settings, fact="X", scope="x")
    forget(settings, handle=r.handle)
    repo = Repository(connect(settings.db_path))
    u = repo.get_unit(r.handle)
    assert u.superseded_by == TOMBSTONE_HANDLE


def test_forget_updates_markdown_frontmatter(settings):
    r = remember(settings, fact="X", scope="x")
    forget(settings, handle=r.handle)
    assert "tombstoned: true" in r.path.read_text()


def test_forget_unknown_handle_raises(settings):
    with pytest.raises(KeyError):
        forget(settings, handle="memory://decision/zzzzzzzz")


def test_forget_only_works_on_memory_layer(settings):
    repo = Repository(connect(settings.db_path))
    from claude_repo_mem.units.model import Unit
    repo.upsert_unit(Unit(
        id="code://function/a", layer="code", kind="function", scope="x",
        source_ref=None, content_hash="h", t1_header="t", created_at=0, last_seen_at=0,
    ))
    with pytest.raises(ValueError):
        forget(settings, handle="code://function/a")
