from pathlib import Path
import yaml
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.bench.runner import run_benchmark, BenchResult


def test_runner_reports_recall_at_k(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text(
        "def login_user(user, pw):\n    return user\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)

    fixture = tmp_repo / "queries.yaml"
    fixture.write_text(yaml.safe_dump({
        "queries": [
            {"q": "login", "expect_header_substring": "login"},
            {"q": "nonexistent_gibberish_xyz", "expect_header_substring": "zzzz_no_match"},
        ]
    }))

    result = run_benchmark(s, fixture, embedder=None, k=5)
    assert isinstance(result, BenchResult)
    assert result.total == 2
    assert result.hits_at_k == 1


def test_runner_handles_empty_fixture(tmp_repo: Path):
    fixture = tmp_repo / "q.yaml"
    fixture.write_text("queries: []\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    result = run_benchmark(s, fixture, embedder=None, k=5)
    assert result.total == 0
    assert result.recall_at_k == 0.0
