import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from claude_repo_mem.cli import main


def test_init_scaffolds_dir_and_mcp_json(tmp_path: Path):
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert (tmp_path / ".claude-repo-mem").is_dir()
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "claude-repo-mem" in data["mcpServers"]
    args = data["mcpServers"]["claude-repo-mem"]["args"]
    assert "--root" in args


def test_init_prints_next_steps(tmp_path: Path):
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "claude-repo-mem index" in res.output


def test_init_with_hooks_writes_hook(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path), "--hooks"])
    assert res.exit_code == 0, res.output
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert hook.exists()


def test_init_conflict_requires_force(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"claude-repo-mem": {"command": "claude-repo-mem", "args": ["custom"]}}
    }))
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path)])
    assert res.exit_code != 0
    assert "force" in res.output.lower()


def test_init_target_desktop(tmp_path, monkeypatch):
    from claude_repo_mem import mcp_config
    cfg = tmp_path / "desktop" / "claude_desktop_config.json"
    monkeypatch.setattr(mcp_config, "desktop_config_path", lambda: cfg)
    repo = tmp_path / "proj"
    repo.mkdir()
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(repo), "--target", "desktop"])
    assert res.exit_code == 0, res.output
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "claude-repo-mem-proj" in data["mcpServers"]
