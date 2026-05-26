from pathlib import Path
from claude_mem.indexer.synthesizers.imports import ImportsSynthesizer
from claude_mem.units.ids import make_handle


def test_python_import_emits_edge(tmp_path: Path):
    a = tmp_path / "auth.py"
    a.write_text("from .utils import helper\n\ndef login(): helper()\n")
    u = tmp_path / "utils.py"
    u.write_text("def helper(): pass\n")
    from claude_mem.indexer.parsers.code_python import PythonParser
    pa = PythonParser().parse(a, a.read_text())
    pu = PythonParser().parse(u, u.read_text())
    all_units = list(pa.units) + list(pu.units)

    sources = {a: a.read_text(), u: u.read_text()}
    rels = ImportsSynthesizer().synthesize(all_units, sources, repo_root=tmp_path)
    assert any(r.kind == "imports" for r in rels)


def test_js_import_emits_edge(tmp_path: Path):
    a = tmp_path / "a.js"
    a.write_text("import { x } from './b';\nfunction y() { return x(); }\n")
    b = tmp_path / "b.js"
    b.write_text("export function x() { return 1; }\n")
    from claude_mem.indexer.parsers.code_jsts import JsTsParser
    units = list(JsTsParser().parse(a, a.read_text()).units) + \
            list(JsTsParser().parse(b, b.read_text()).units)
    sources = {a: a.read_text(), b: b.read_text()}
    rels = ImportsSynthesizer().synthesize(units, sources, repo_root=tmp_path)
    assert any(r.kind == "imports" for r in rels)


def test_unresolvable_import_skipped(tmp_path: Path):
    a = tmp_path / "a.py"
    a.write_text("import nonexistent_xyz\n")
    from claude_mem.indexer.parsers.code_python import PythonParser
    units = list(PythonParser().parse(a, a.read_text()).units)
    sources = {a: a.read_text()}
    rels = ImportsSynthesizer().synthesize(units, sources, repo_root=tmp_path)
    assert rels == []
