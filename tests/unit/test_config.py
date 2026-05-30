from pathlib import Path
from claude_repo_mem.config import Settings


def test_settings_finds_repo_root_via_dot_claude_repo_mem(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    s = Settings.discover()
    assert s.repo_root == tmp_repo
    assert s.state_dir == tmp_repo / ".claude-repo-mem"
    assert s.db_path == tmp_repo / ".claude-repo-mem" / "db.sqlite"


def test_settings_walks_up_for_repo_root(tmp_repo: Path, monkeypatch):
    sub = tmp_repo / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    s = Settings.discover()
    assert s.repo_root == tmp_repo


def test_settings_raises_when_not_in_repo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Isolate from any ambient .claude-repo-mem in the real ancestry
    # (e.g. ~/.claude-repo-mem from other tooling on the developer's machine).
    original_is_dir = Path.is_dir

    def fake_is_dir(self: Path) -> bool:
        if self.name == ".claude-repo-mem":
            return False
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    import pytest
    with pytest.raises(FileNotFoundError):
        Settings.discover()


def test_settings_uses_claude_project_dir_fallback(tmp_repo: Path, tmp_path: Path, monkeypatch):
    # Launched from a directory with no .claude-repo-mem in its ancestry
    # (simulating C:\Windows\System32), but CLAUDE_PROJECT_DIR points at the repo.
    elsewhere = tmp_path / "system32"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("CLAUDE_REPO_MEM_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_repo))
    s = Settings.discover()
    assert s.repo_root == tmp_repo


def test_settings_uses_explicit_root_env_override(tmp_repo: Path, tmp_path: Path, monkeypatch):
    elsewhere = tmp_path / "system32"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("CLAUDE_REPO_MEM_ROOT", str(tmp_repo))
    s = Settings.discover()
    assert s.repo_root == tmp_repo


def test_explicit_root_takes_precedence_over_cwd(tmp_path: Path, monkeypatch):
    # Two initialized repos: cwd-discoverable one and an explicitly-pinned one.
    cwd_repo = tmp_path / "cwd_repo"
    (cwd_repo / ".claude-repo-mem").mkdir(parents=True)
    pinned_repo = tmp_path / "pinned_repo"
    (pinned_repo / ".claude-repo-mem").mkdir(parents=True)
    monkeypatch.chdir(cwd_repo)
    monkeypatch.setenv("CLAUDE_REPO_MEM_ROOT", str(pinned_repo))
    s = Settings.discover()
    assert s.repo_root == pinned_repo


def test_cwd_takes_precedence_over_project_dir(tmp_path: Path, monkeypatch):
    cwd_repo = tmp_path / "cwd_repo"
    (cwd_repo / ".claude-repo-mem").mkdir(parents=True)
    other_repo = tmp_path / "other_repo"
    (other_repo / ".claude-repo-mem").mkdir(parents=True)
    monkeypatch.chdir(cwd_repo)
    monkeypatch.delenv("CLAUDE_REPO_MEM_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other_repo))
    s = Settings.discover()
    assert s.repo_root == cwd_repo


def test_embedder_env_override(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.setenv("CLAUDE_REPO_MEM_EMBED", "openai:text-embedding-3-small")
    s = Settings.discover()
    assert s.embedder == "openai:text-embedding-3-small"


def test_embedder_default(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.delenv("CLAUDE_REPO_MEM_EMBED", raising=False)
    s = Settings.discover()
    assert s.embedder == "bge-small"
