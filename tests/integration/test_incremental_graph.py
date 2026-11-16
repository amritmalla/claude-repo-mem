from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import connect, init_db
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.indexer.incremental import incremental_reindex
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.indexer.parsers.code_python import PythonParser
from claude_repo_mem.memory.writer import remember
from claude_repo_mem.retrieval.trace import trace
from claude_repo_mem.units.model import Relation
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings(tmp_repo: Path):
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    return settings


def _graph(settings):
    with closing(connect(settings.db_path)) as conn:
        return (
            {tuple(row) for row in conn.execute(
                "SELECT id, t1_header, source_ref, scope FROM unit WHERE kind='route'",
            )},
            {tuple(row) for row in conn.execute("SELECT * FROM relation")},
        )


@pytest.mark.parametrize("framework", ["flask", "django", "express"])
@pytest.mark.parametrize("change", ["handler", "declaration", "remove"])
def test_incremental_routes_match_current_source(settings, framework, change):
    root = settings.repo_root
    if framework == "flask":
        handler = declaration = root / "app.py"
        original = "@app.route('/old')\ndef login(): return 1\n"
    elif framework == "django":
        handler, declaration = root / "views.py", root / "urls.py"
        original = "def login(request): return 1\n"
        declaration.write_text("urlpatterns = [path('old/', views.login)]\n", encoding="utf-8")
    else:
        handler = declaration = root / "app.js"
        original = "function login(req, res) { return 1; }\napp.get('/old', login);\n"
    handler.write_text(original, encoding="utf-8")
    full_reindex(settings)
    assert len(_graph(settings)[0]) == 1

    changed = handler if change == "handler" else declaration
    if change == "handler":
        changed.write_text(original.replace("return 1", "return 2"), encoding="utf-8")
    elif change == "declaration":
        changed.write_text(changed.read_text(encoding="utf-8").replace("old", "current"), encoding="utf-8")
    else:
        changed.write_text(original.split("\n", 1)[1] if framework == "flask" else "", encoding="utf-8")

    incremental_reindex(settings, [changed])

    routes, edges = _graph(settings)
    if change == "remove":
        assert routes == set()
        assert not any(kind == "route_to" for _, _, kind in edges)
    else:
        assert len(routes) == 1
        route_id, header, _, scope = next(iter(routes))
        assert ("current" if change == "declaration" else "old") in header
        assert scope == "root"
        with closing(connect(settings.db_path)) as conn:
            [edge] = Repository(conn).neighbors(route_id, kinds=["route_to"])
            target = Repository(conn).get_unit(edge.dst_id)
            assert target.source_ref.startswith(handler.as_posix() + ":")
            if change == "handler":
                assert "return 2" in target.metadata

    expected = replace(settings, db_path=settings.state_dir / "expected.sqlite")
    init_db(expected.db_path)
    full_reindex(expected)
    assert _graph(settings) == _graph(expected)


@pytest.mark.parametrize("language", ["python", "javascript"])
@pytest.mark.parametrize("change", ["importer", "target", "new-target", "delete-target"])
def test_incremental_refreshes_cross_file_imports(settings, language, change):
    root = settings.repo_root
    if language == "python":
        caller, target, alternate = root / "caller.py", root / "target.py", root / "alternate.py"
        text = "from target import helper\ndef caller(): return helper()\n"
        target_text = "def helper(): return 1\n"
    else:
        caller, target, alternate = root / "caller.js", root / "target.js", root / "alternate.js"
        text = "import { helper } from './target';\nfunction caller() { return helper(); }\n"
        target_text = "function helper() { return 1; }\n"
    caller.write_text(text, encoding="utf-8")
    alternate.write_text(target_text, encoding="utf-8")
    if change != "new-target":
        target.write_text(target_text, encoding="utf-8")
    full_reindex(settings)
    if change == "importer":
        caller.write_text(text.replace("target", "alternate"), encoding="utf-8")
        changed, expected_target = caller, alternate
    elif change == "delete-target":
        target.unlink()
        changed, expected_target = target, None
    else:
        target.write_text(target_text.replace("return 1", "return 2"), encoding="utf-8")
        changed, expected_target = target, target

    incremental_reindex(settings, [changed])

    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        caller_unit = next(u for u in repo.get_units([row[0] for row in conn.execute("SELECT id FROM unit")])
                           if u.source_ref and u.source_ref.startswith(caller.as_posix() + ":"))
        edges = repo.neighbors(caller_unit.id, kinds=["imports"])
        if expected_target is None:
            assert edges == []
        else:
            assert len(edges) == 1
            target_unit = repo.get_unit(edges[0].dst_id)
            assert target_unit.source_ref.startswith(expected_target.as_posix() + ":")
            if change in ("target", "new-target"):
                assert "return 2" in target_unit.metadata


def test_incremental_updates_react_hook_edges(settings):
    source = settings.repo_root / "Counter.jsx"
    template = "function Counter() {\n  const [n, setN] = useState(0);\n  %s\n  return null;\n}\n"
    source.write_text(template % "", encoding="utf-8")
    full_reindex(settings)

    for body, expected in [("setN(n + 1);", 1), ("", 0)]:
        source.write_text(template % body, encoding="utf-8")
        incremental_reindex(settings, [source])
        with closing(connect(settings.db_path)) as conn:
            edges = conn.execute("SELECT src_id, dst_id FROM relation WHERE kind='mutates_state_of'").fetchall()
            assert len(edges) == expected
            assert all(src == dst for src, dst in edges)


def test_incremental_only_reparses_changed_file_and_preserves_other_state(settings):
    source = settings.repo_root / "app.py"
    source.write_text("@app.route('/login')\ndef login(): return 1\n", encoding="utf-8")
    other = settings.repo_root / "other.py"
    other.write_text("@app.route('/other')\ndef other(): return 1\n", encoding="utf-8")
    full_reindex(settings, FakeEmbedder())
    memory = remember(settings, fact="Keep route context", scope="auth")
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        route = next(repo.get_unit(row[0]) for row in conn.execute(
            "SELECT id FROM unit WHERE kind='route' AND t1_header LIKE '%/other%'",
        ))
        repo.upsert_unit(replace(route, t2_summary="Keep this summary"))
        original_route = repo.get_unit(route.id)
        vector = conn.execute("SELECT embedding FROM unit_vec WHERE id=?", (route.id,)).fetchone()[0]
        repo.add_relation(Relation(memory.handle, route.id, "mentions"))

    source.write_text("@app.route('/login')\ndef login(): return 2\n", encoding="utf-8")
    original_parse = PythonParser.parse
    parsed = []

    def record_parse(parser, path, text):
        parsed.append(path)
        return original_parse(parser, path, text)

    with patch.object(PythonParser, "parse", record_parse):
        incremental_reindex(settings, [source])

    assert parsed == [source]
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        assert repo.get_unit(route.id) == original_route
        assert conn.execute("SELECT embedding FROM unit_vec WHERE id=?", (route.id,)).fetchone()[0] == vector
        assert repo.neighbors(memory.handle) == [Relation(memory.handle, route.id, "mentions")]
    routes, _ = _graph(settings)
    login = next(row[0] for row in routes if "/login" in row[1])
    result = trace(settings, seeds=[login])
    assert any("return 2" in item.content for item in result.items)


@pytest.mark.parametrize("failure", ["read", "write"])
def test_incremental_graph_failure_keeps_previous_snapshot(settings, monkeypatch, failure):
    source = settings.repo_root / "app.py"
    other = settings.repo_root / "other.py"
    source.write_text("@app.route('/login')\ndef login(): return 1\n", encoding="utf-8")
    other.write_text("def other(): return 1\n", encoding="utf-8")
    full_reindex(settings, FakeEmbedder())

    def snapshot():
        with closing(connect(settings.db_path)) as conn:
            return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
                    for table in ("unit", "unit_fts", "unit_vec", "relation")}

    before = snapshot()
    source.write_text("@app.route('/current')\ndef login(): return 2\n", encoding="utf-8")
    if failure == "read":
        original = Path.read_text

        def fail_read(path, *args, **kwargs):
            if path == other:
                raise PermissionError("Cannot read related source")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fail_read)
    else:
        original = Repository.add_relation

        def fail_write(repo, relation):
            original(repo, relation)
            raise RuntimeError("Graph write failed")

        monkeypatch.setattr(Repository, "add_relation", fail_write)

    with pytest.raises((OSError, ValueError, RuntimeError)):
        incremental_reindex(settings, [source])

    assert snapshot() == before


def test_incremental_refreshes_routes_after_file_rename(settings):
    old = settings.repo_root / "old.py"
    old.write_text("@app.route('/login')\ndef login(): return 1\n", encoding="utf-8")
    full_reindex(settings)
    old_route = next(iter(_graph(settings)[0]))[0]
    new = old.with_name("current.py")
    old.rename(new)

    incremental_reindex(settings, [Path("old.py"), Path("current.py")])

    routes, _ = _graph(settings)
    assert len(routes) == 1
    route_id, _, reference, _ = next(iter(routes))
    assert route_id != old_route
    assert reference.startswith(new.as_posix() + ":")
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        [edge] = repo.neighbors(route_id, kinds=["route_to"])
        assert repo.get_unit(edge.dst_id).source_ref.startswith(new.as_posix() + ":")


def test_incremental_updates_class_parent_references(settings):
    source = settings.repo_root / "app.py"
    source.write_text("class Worker:\n    def run(self): return 1\n", encoding="utf-8")
    full_reindex(settings)
    source.write_text("class Worker:\n    def run(self): return 2\n", encoding="utf-8")

    incremental_reindex(settings, [source])

    with closing(connect(settings.db_path)) as conn:
        units = Repository(conn).list_units()
        assert len(units) == 2
        parent = next(unit for unit in units if unit.kind == "class")
        method = next(unit for unit in units if unit.kind == "method")
        assert method.parent_id == parent.id
        assert "return 2" in method.metadata
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_incremental_matches_source_paths_exactly(settings):
    source = settings.repo_root / "module_.py"
    neighbor = settings.repo_root / "moduleX.py"
    source.write_text("def replaced(): return 1\n", encoding="utf-8")
    neighbor.write_text("def retained(): return 1\n", encoding="utf-8")
    full_reindex(settings, FakeEmbedder())
    with closing(connect(settings.db_path)) as conn:
        retained = next(unit for unit in Repository(conn).list_units() if "retained" in unit.t1_header)
    source.write_text("def current(): return 2\n", encoding="utf-8")

    incremental_reindex(settings, [source])

    with closing(connect(settings.db_path)) as conn:
        assert Repository(conn).get_unit(retained.id) == retained
        assert conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0] == 2


def test_incremental_embeds_new_routes_without_reembedding_unrelated_routes(settings):
    source = settings.repo_root / "app.py"
    source.write_text("@app.route('/login')\ndef login(): return 1\n", encoding="utf-8")
    other = settings.repo_root / "other.py"
    other.write_text("@app.route('/other')\ndef other(): return 1\n", encoding="utf-8")
    full_reindex(settings, FakeEmbedder())
    source.write_text("@app.route('/current')\ndef login(): return 1\n", encoding="utf-8")
    embedder = FakeEmbedder()

    with patch.object(embedder, "embed", wraps=embedder.embed) as embed:
        incremental_reindex(settings, [source], embedder)

    texts = embed.call_args.args[0]
    assert any("/current" in text for text in texts)
    assert not any("/other" in text for text in texts)
    with closing(connect(settings.db_path)) as conn:
        assert {row[0] for row in conn.execute("SELECT id FROM unit_vec")} == {
            row[0] for row in conn.execute("SELECT id FROM unit")
        }
