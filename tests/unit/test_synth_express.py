from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex


def test_express_get_emits_route(tmp_repo: Path):
    (tmp_repo / "routes.js").write_text(
        "function login(req, res) { return res.send('ok'); }\n"
        "app.get('/login', login);\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    headers = [r["t1_header"] for r in conn.execute(
        "SELECT t1_header FROM unit WHERE kind='route'"
    ).fetchall()]
    assert any("express" in h and "/login" in h and "GET" in h for h in headers)


def test_express_post_method_captured(tmp_repo: Path):
    (tmp_repo / "routes.js").write_text(
        "function logout(req, res) { return res.send('ok'); }\n"
        "app.post('/logout', logout);\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    headers = [r["t1_header"] for r in conn.execute(
        "SELECT t1_header FROM unit WHERE kind='route'"
    ).fetchall()]
    assert any("POST" in h and "/logout" in h for h in headers)
