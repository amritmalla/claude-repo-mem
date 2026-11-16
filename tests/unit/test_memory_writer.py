from contextlib import closing
import hashlib
from pathlib import Path

import pytest
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.memory.writer import remember, MemoryWriteResult


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


@pytest.mark.parametrize("scope", ["../escaped", "backend/../../escaped"])
def test_remember_rejects_parent_traversal_without_writing(settings, scope):
    with pytest.raises(ValueError, match="scope"):
        remember(settings, fact="Must stay inside memory", scope=scope)

    assert not settings.memory_dir.exists()
    assert not (settings.state_dir / "escaped").exists()
    assert not (settings.repo_root / "escaped").exists()
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0] == 0


@pytest.mark.parametrize("scope", [
    "",
    ".",
    "./backend",
    "backend/../auth",
    "backend/./auth",
    "backend//auth",
    "backend/",
    "backend/.. /escaped",
    "backend./auth",
    "backend /auth",
    "/backend/auth",
    "//server/share",
    "C:/escaped",
    "C:escaped",
    r"C:\escaped",
    r"..\escaped",
    r"backend\..\..\escaped",
    r"\\server\share",
    "backend\nkind: decision",
    "backend\x00auth",
])
def test_remember_rejects_invalid_scope(settings, scope):
    with pytest.raises(ValueError, match="scope"):
        remember(settings, fact="Must stay inside memory", scope=scope)

    assert not settings.memory_dir.exists()


def _directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")


def test_remember_rejects_scope_link_outside_memory(settings):
    outside = settings.repo_root / "outside"
    outside.mkdir()
    settings.memory_dir.mkdir()
    _directory_link(settings.memory_dir / "linked", outside)

    with pytest.raises(ValueError, match="memory directory"):
        remember(settings, fact="Must stay inside memory", scope="linked/nested")

    assert list(outside.iterdir()) == []


def test_remember_accepts_scope_link_inside_memory(settings):
    target = settings.memory_dir / "backend"
    target.mkdir(parents=True)
    _directory_link(settings.memory_dir / "linked", target)

    result = remember(settings, fact="We use JWT.", scope="linked/auth")

    assert result.path.resolve().is_relative_to(settings.memory_dir.resolve())
    assert (target / "auth" / f"{result.slug}.md").exists()


@pytest.mark.parametrize("collision", [False, True])
def test_remember_rejects_file_link_outside_memory(settings, collision):
    outside = settings.repo_root / "outside.md"
    outside.write_text("Keep this content", encoding="utf-8")
    scope_dir = settings.memory_dir / "backend"
    scope_dir.mkdir(parents=True)
    fact = "We use JWT."
    slug = "we-use-jwt"
    if collision:
        (scope_dir / f"{slug}.md").write_text("Existing memory", encoding="utf-8")
        suffix = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:6]
        slug = f"{slug}-{suffix}"
    try:
        (scope_dir / f"{slug}.md").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="memory directory"):
        remember(settings, fact=fact, scope="backend")

    assert outside.read_text(encoding="utf-8") == "Keep this content"
