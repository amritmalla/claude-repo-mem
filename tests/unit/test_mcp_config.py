from pathlib import Path

from claude_repo_mem.mcp_config import build_server_entry, DEFAULT_EMBEDDER


def test_build_server_entry_defaults():
    root = Path("/abs/repo")
    entry = build_server_entry(root, embedder=None, watch=True)
    assert entry["command"] == "claude-repo-mem"
    assert entry["args"] == ["serve", "--watch", "--root", str(root.resolve())]


def test_build_server_entry_no_watch():
    entry = build_server_entry(Path("/abs/repo"), embedder=None, watch=False)
    assert "--watch" not in entry["args"]
    assert "--no-watch" in entry["args"]


def test_build_server_entry_custom_embedder():
    entry = build_server_entry(Path("/abs/repo"), embedder="openai", watch=True)
    assert "--embedder" in entry["args"]
    assert entry["args"][entry["args"].index("--embedder") + 1] == "openai"


def test_build_server_entry_omits_default_embedder():
    entry = build_server_entry(Path("/abs/repo"), embedder=DEFAULT_EMBEDDER, watch=True)
    assert "--embedder" not in entry["args"]
