from pathlib import Path
from claude_mem.indexer.parsers.code_jsts import JsTsParser


SAMPLE_JS = """\
import { db } from './db';

export function login(user, pw) {
  return db.find(user);
}

export const greet = (name) => `hi ${name}`;

export class AuthService {
  constructor(db) { this.db = db; }
  login(user) { return this.db.find(user); }
}
"""


def test_parses_function_declaration(tmp_path: Path):
    p = tmp_path / "auth.js"
    p.write_text(SAMPLE_JS)
    result = JsTsParser().parse(p, p.read_text())
    fns = [u for u in result.units if u.kind == "function"]
    assert any("login" in u.t1_header for u in fns)


def test_parses_arrow_assigned_to_const(tmp_path: Path):
    p = tmp_path / "auth.js"
    p.write_text(SAMPLE_JS)
    result = JsTsParser().parse(p, p.read_text())
    fns = [u for u in result.units if u.kind == "function"]
    assert any("greet" in u.t1_header for u in fns)


def test_parses_class_and_methods(tmp_path: Path):
    p = tmp_path / "auth.js"
    p.write_text(SAMPLE_JS)
    result = JsTsParser().parse(p, p.read_text())
    classes = [u for u in result.units if u.kind == "class"]
    methods = [u for u in result.units if u.kind == "method"]
    assert len(classes) == 1
    assert any("constructor" in m.t1_header for m in methods)
    assert any("login" in m.t1_header for m in methods)


def test_supports_ts_and_tsx(tmp_path: Path):
    p = JsTsParser()
    assert p.supports(Path("x.js"))
    assert p.supports(Path("x.jsx"))
    assert p.supports(Path("x.ts"))
    assert p.supports(Path("x.tsx"))
    assert not p.supports(Path("x.py"))
