from pathlib import Path
import subprocess
from click.testing import CliRunner
from claude_mem.cli import main


def _init_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)


def test_install_hooks_writes_post_commit(tmp_path: Path):
    _init_git(tmp_path)
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    assert "claude-mem index" in hook.read_text()


def test_install_hooks_refuses_to_clobber(tmp_path: Path):
    _init_git(tmp_path)
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("# pre-existing\n")
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path)])
    assert res.exit_code != 0
    out = res.output.lower()
    assert "exists" in out or "force" in out


def test_install_hooks_force_clobbers(tmp_path: Path):
    _init_git(tmp_path)
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("# pre-existing\n")
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path), "--force"])
    assert res.exit_code == 0, res.output
    assert "claude-mem index" in hook.read_text()


def test_install_hooks_refuses_non_git(tmp_path: Path):
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path)])
    assert res.exit_code != 0
    assert "git" in res.output.lower()
