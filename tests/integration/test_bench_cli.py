from pathlib import Path
import yaml
from click.testing import CliRunner
from claude_repo_mem.cli import main
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex


def test_bench_prints_summary(tmp_path: Path):
    (tmp_path / "auth.py").write_text("def login_user(): pass\n")
    s = Settings.for_repo(tmp_path); init_db(s.db_path)
    full_reindex(s, embedder=None)
    fixture = tmp_path / "q.yaml"
    fixture.write_text(yaml.safe_dump({
        "queries": [{"q": "login", "expect_header_substring": "login"}],
    }))
    runner = CliRunner()
    res = runner.invoke(main, [
        "bench", "--root", str(tmp_path),
        "--fixture", str(fixture), "--no-embed",
    ])
    assert res.exit_code == 0, res.output
    assert "recall@5" in res.output
    assert "1/1" in res.output
