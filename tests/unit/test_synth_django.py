from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex


def test_django_path_emits_route(tmp_repo: Path):
    (tmp_repo / "views.py").write_text("def login(request):\n    return None\n")
    (tmp_repo / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [path('login/', views.login, name='login')]\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    headers = [r["t1_header"] for r in conn.execute(
        "SELECT t1_header FROM unit WHERE kind='route'"
    ).fetchall()]
    assert any("django" in h and "login" in h for h in headers)


def test_django_route_to_relation(tmp_repo: Path):
    (tmp_repo / "views.py").write_text("def logout(request):\n    return None\n")
    (tmp_repo / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [path('logout/', views.logout)]\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM relation WHERE kind='route_to'"
    ).fetchone()[0]
    assert n >= 1
