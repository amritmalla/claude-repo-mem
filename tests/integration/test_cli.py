from pathlib import Path
from click.testing import CliRunner

from claude_mem.cli import main


def test_index_creates_state_dir(tmp_path: Path):
    (tmp_path / "x.py").write_text("def f(): pass\n")
    runner = CliRunner()
    result = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude-mem" / "db.sqlite").exists()
    assert "units_written" in result.output


def test_index_idempotent(tmp_path: Path):
    (tmp_path / "x.py").write_text("def f(): pass\n")
    runner = CliRunner()
    result1 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    result2 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    assert result1.exit_code == 0
    assert result2.exit_code == 0


def test_doctor_reports_status(tmp_path: Path):
    (tmp_path / "x.py").write_text("def f(): pass\n")
    runner = CliRunner()
    runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    result = runner.invoke(main, ["doctor", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "units" in result.output.lower()
