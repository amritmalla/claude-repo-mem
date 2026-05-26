from pathlib import Path
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex


def test_indexes_java_go_rust(tmp_repo: Path):
    (tmp_repo / "A.java").write_text("public class A { void m() {} }\n")
    (tmp_repo / "b.go").write_text("package x\nfunc B() {}\n")
    (tmp_repo / "c.rs").write_text("pub fn c() {}\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    headers = " ".join(
        r["t1_header"] for r in conn.execute(
            "SELECT t1_header FROM unit WHERE layer='code'"
        ).fetchall()
    )
    assert "java" in headers
    assert "go" in headers
    assert "rust" in headers
