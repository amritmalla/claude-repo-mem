from click.testing import CliRunner
from claude_mem.cli import main


def test_serve_help_lists_watch_flag():
    runner = CliRunner()
    res = runner.invoke(main, ["serve", "--help"])
    assert res.exit_code == 0
    assert "--watch" in res.output
    assert "--no-watch" in res.output
