from pathlib import Path
from claude_mem.config import Settings


def test_settings_finds_repo_root_via_dot_claude_mem(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    s = Settings.discover()
    assert s.repo_root == tmp_repo
    assert s.state_dir == tmp_repo / ".claude-mem"
    assert s.db_path == tmp_repo / ".claude-mem" / "db.sqlite"


def test_settings_walks_up_for_repo_root(tmp_repo: Path, monkeypatch):
    sub = tmp_repo / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    s = Settings.discover()
    assert s.repo_root == tmp_repo


def test_settings_raises_when_not_in_repo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Isolate from any ambient .claude-mem in the real ancestry
    # (e.g. ~/.claude-mem from other tooling on the developer's machine).
    original_is_dir = Path.is_dir

    def fake_is_dir(self: Path) -> bool:
        if self.name == ".claude-mem":
            return False
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    import pytest
    with pytest.raises(FileNotFoundError):
        Settings.discover()


def test_embedder_env_override(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.setenv("CLAUDE_MEM_EMBED", "openai:text-embedding-3-small")
    s = Settings.discover()
    assert s.embedder == "openai:text-embedding-3-small"


def test_embedder_default(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.delenv("CLAUDE_MEM_EMBED", raising=False)
    s = Settings.discover()
    assert s.embedder == "bge-small"
