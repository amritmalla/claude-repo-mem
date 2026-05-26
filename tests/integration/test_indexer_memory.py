from pathlib import Path
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex


def test_memory_md_indexed_as_memory_layer(tmp_repo: Path):
    mem_dir = tmp_repo / ".claude-repo-mem" / "memory" / "backend" / "auth"
    mem_dir.mkdir(parents=True)
    (mem_dir / "rs256.md").write_text(
        "---\nkind: decision\nscope: backend/auth\nconfidence: 0.9\n---\n\nWe chose RS256.\n"
    )
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    full_reindex(settings, embedder=None)
    conn = connect(settings.db_path)
    rows = conn.execute(
        "SELECT layer, kind, scope, confidence FROM unit WHERE layer='memory'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["layer"] == "memory"
    assert rows[0]["kind"] == "decision"
    assert rows[0]["scope"] == "backend/auth"
    assert abs(rows[0]["confidence"] - 0.9) < 1e-6


def test_memory_md_not_picked_up_by_docs_parser(tmp_repo: Path):
    mem_dir = tmp_repo / ".claude-repo-mem" / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "x.md").write_text("---\nkind: fact\nscope: x\n---\n\nbody\n")
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    full_reindex(settings, embedder=None)
    conn = connect(settings.db_path)
    n_docs = conn.execute("SELECT COUNT(*) FROM unit WHERE layer='docs'").fetchone()[0]
    assert n_docs == 0
