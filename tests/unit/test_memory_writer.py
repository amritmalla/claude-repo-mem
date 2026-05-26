from pathlib import Path
import pytest
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.memory.writer import remember, MemoryWriteResult


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_remember_creates_md_file(settings):
    result = remember(settings, fact="We use JWT.", scope="backend/auth", kind="decision")
    md_path = settings.memory_dir / "backend" / "auth" / f"{result.slug}.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "kind: decision" in content
    assert "scope: backend/auth" in content
    assert "We use JWT." in content


def test_remember_upserts_unit(settings):
    result = remember(settings, fact="We use JWT.", scope="backend/auth")
    repo = Repository(connect(settings.db_path))
    u = repo.get_unit(result.handle)
    assert u is not None
    assert u.layer == "memory"
    assert u.kind == "fact"
    assert u.scope == "backend/auth"


def test_remember_default_kind_is_fact(settings):
    result = remember(settings, fact="X", scope="x")
    repo = Repository(connect(settings.db_path))
    assert repo.get_unit(result.handle).kind == "fact"


def test_remember_supersedes_marks_old_unit(settings):
    r1 = remember(settings, fact="We use HS256.", scope="backend/auth", kind="decision")
    r2 = remember(
        settings, fact="We use RS256.", scope="backend/auth", kind="decision",
        supersedes=r1.handle,
    )
    repo = Repository(connect(settings.db_path))
    old = repo.get_unit(r1.handle)
    assert old.superseded_by == r2.handle


def test_remember_invalid_kind_raises(settings):
    with pytest.raises(ValueError):
        remember(settings, fact="x", scope="x", kind="nonsense")


def test_remember_returns_result_struct(settings):
    r = remember(settings, fact="x", scope="y")
    assert isinstance(r, MemoryWriteResult)
    assert r.handle.startswith("memory://")
    assert r.slug
    assert r.path.exists()
