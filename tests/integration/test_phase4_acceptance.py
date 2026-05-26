"""Phase 4 acceptance — language coverage + synthesizers."""
from pathlib import Path
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex


def test_multilang_and_synths(tmp_repo: Path):
    # Java
    (tmp_repo / "A.java").write_text(
        "public class A { public String m(String s) { return s; } }\n"
    )
    # Go
    (tmp_repo / "b.go").write_text(
        "package x\n"
        "type S struct{}\n"
        "func (s *S) Issue() string { return \"\" }\n"
    )
    # Rust
    (tmp_repo / "c.rs").write_text(
        "pub struct S; impl S { pub fn issue(&self) -> i32 { 0 } }\n"
    )
    # Django
    (tmp_repo / "views.py").write_text("def login(request):\n    return None\n")
    (tmp_repo / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [path('login/', views.login)]\n"
    )
    # Express
    (tmp_repo / "routes.js").write_text(
        "function logout(req, res) { return res.send('ok'); }\n"
        "app.post('/logout', logout);\n"
    )
    # React
    (tmp_repo / "Comp.jsx").write_text(
        "function Comp() {\n"
        "  const [n, setN] = useState(0);\n"
        "  const c = () => setN(n + 1);\n"
        "  return null;\n"
        "}\n"
    )

    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)

    by_lang = {
        r["t1_header"].split(" ", 1)[0]
        for r in conn.execute(
            "SELECT t1_header FROM unit WHERE layer='code' AND kind IN ('function','method','class','struct','trait','interface')"
        ).fetchall()
        if r["t1_header"]
    }
    assert {"java", "go", "rust", "python"}.issubset(by_lang)

    n_routes = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE kind='route'"
    ).fetchone()[0]
    assert n_routes >= 2  # django + express

    n_state = conn.execute(
        "SELECT COUNT(*) FROM relation WHERE kind='mutates_state_of'"
    ).fetchone()[0]
    assert n_state >= 1
