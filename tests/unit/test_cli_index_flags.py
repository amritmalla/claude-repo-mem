from pathlib import Path
from click.testing import CliRunner
from claude_repo_mem.cli import main


def test_index_help_lists_embedder_and_reset():
    runner = CliRunner()
    res = runner.invoke(main, ["index", "--help"])
    assert res.exit_code == 0
    assert "--embedder" in res.output
    assert "--reset" in res.output


def test_index_reset_clears_db(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    runner = CliRunner()
    res1 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    assert res1.exit_code == 0, res1.output
    db = tmp_path / ".claude-repo-mem" / "db.sqlite"
    assert db.exists()

    res2 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed", "--reset"])
    assert res2.exit_code == 0, res2.output
    assert db.exists()
