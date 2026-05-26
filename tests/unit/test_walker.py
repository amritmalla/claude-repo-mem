from pathlib import Path
from claude_repo_mem.indexer.walker import walk_repo, derive_scope, hash_file


def test_walks_repo_yields_python_and_md(tmp_repo: Path):
    (tmp_repo / "src").mkdir()
    (tmp_repo / "src" / "auth.py").write_text("def login(): pass\n")
    (tmp_repo / "docs").mkdir()
    (tmp_repo / "docs" / "design.md").write_text("# Design\n")
    (tmp_repo / "README.txt").write_text("ignored\n")
    paths = sorted(p.relative_to(tmp_repo).as_posix() for p in walk_repo(tmp_repo))
    assert paths == ["docs/design.md", "src/auth.py"]


def test_walks_skips_state_and_vcs(tmp_repo: Path):
    (tmp_repo / ".git").mkdir()
    (tmp_repo / ".git" / "config").write_text("x")
    (tmp_repo / ".claude-repo-mem" / "blob.bin").write_text("x")
    (tmp_repo / "src.py").write_text("x")
    paths = [p.relative_to(tmp_repo).as_posix() for p in walk_repo(tmp_repo)]
    assert paths == ["src.py"]


def test_walks_skips_node_modules_and_venv(tmp_repo: Path):
    (tmp_repo / "node_modules" / "x").mkdir(parents=True)
    (tmp_repo / "node_modules" / "x" / "y.js").write_text("x")
    (tmp_repo / ".venv" / "lib").mkdir(parents=True)
    (tmp_repo / ".venv" / "lib" / "a.py").write_text("x")
    (tmp_repo / "real.py").write_text("x")
    paths = [p.relative_to(tmp_repo).as_posix() for p in walk_repo(tmp_repo)]
    assert paths == ["real.py"]


def test_hash_file_stable(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("def x(): pass\n")
    h1 = hash_file(p)
    h2 = hash_file(p)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_hash_changes_with_content(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("v1")
    h1 = hash_file(p)
    p.write_text("v2")
    h2 = hash_file(p)
    assert h1 != h2


def test_derive_scope_from_path():
    assert derive_scope(Path("backend/auth/jwt.py")) == "backend/auth"
    assert derive_scope(Path("src/index.py")) == "src"
    assert derive_scope(Path("README.md")) == "root"
    assert derive_scope(Path("docs/architecture/system.md")) == "docs/architecture"
