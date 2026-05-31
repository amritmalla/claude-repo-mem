import json
from pathlib import Path

import pytest

from claude_repo_mem.mcp_config import build_server_entry, DEFAULT_EMBEDDER, merge_mcp_config, McpConfigError


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


def test_merge_creates_file_when_absent(tmp_path: Path):
    action = merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    assert action == "created"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "claude-repo-mem" in data["mcpServers"]


def test_merge_preserves_other_servers(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"other": {"command": "x", "args": []}}
    }))
    merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "other" in data["mcpServers"]
    assert "claude-repo-mem" in data["mcpServers"]


def test_merge_unchanged_when_entry_identical(tmp_path: Path):
    merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    action = merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    assert action == "unchanged"


def test_merge_conflict_without_force(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"claude-repo-mem": {"command": "claude-repo-mem", "args": ["custom"]}}
    }))
    with pytest.raises(McpConfigError):
        merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)


def test_merge_force_replaces_conflicting_entry(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"claude-repo-mem": {"command": "claude-repo-mem", "args": ["custom"]}}
    }))
    action = merge_mcp_config(tmp_path, embedder=None, watch=True, force=True)
    assert action == "updated"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert data["mcpServers"]["claude-repo-mem"]["args"] != ["custom"]


def test_merge_rejects_malformed_json(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text("{not valid json")
    with pytest.raises(McpConfigError):
        merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
