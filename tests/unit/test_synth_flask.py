from pathlib import Path
from claude_mem.indexer.synthesizers.flask_routes import FlaskRoutesSynthesizer
from claude_mem.indexer.parsers.code_python import PythonParser


SAMPLE = '''\
from flask import Flask
app = Flask(__name__)

@app.route("/login", methods=["POST"])
def login():
    return "ok"

@app.route("/users/<id>")
def get_user(id):
    return id
'''


def test_emits_route_units_and_edges(tmp_path: Path):
    p = tmp_path / "app.py"
    p.write_text(SAMPLE)
    parsed = PythonParser().parse(p, p.read_text())
    sources = {p: p.read_text()}
    extra_units, rels = FlaskRoutesSynthesizer().synthesize_with_units(
        list(parsed.units), sources, repo_root=tmp_path
    )
    route_units = [u for u in extra_units if u.kind == "route"]
    assert len(route_units) == 2
    assert any('/login' in u.t1_header for u in route_units)
    assert any('/users/<id>' in u.t1_header for u in route_units)
    assert all(r.kind == "route_to" for r in rels)
    assert len(rels) == 2


def test_no_routes_emits_nothing(tmp_path: Path):
    p = tmp_path / "app.py"
    p.write_text("def x(): pass\n")
    parsed = PythonParser().parse(p, p.read_text())
    sources = {p: p.read_text()}
    extra_units, rels = FlaskRoutesSynthesizer().synthesize_with_units(
        list(parsed.units), sources, repo_root=tmp_path
    )
    assert extra_units == []
    assert rels == []
