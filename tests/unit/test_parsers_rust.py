from pathlib import Path
from claude_repo_mem.indexer.parsers.code_rust import RustParser


SAMPLE = """\
pub struct Service { secret: String }

pub trait TokenIssuer {
    fn issue(&self, uid: &str) -> String;
}

impl Service {
    pub fn new(secret: String) -> Self {
        Self { secret }
    }
    pub fn issue(&self, uid: &str) -> String {
        format!("{}{}", uid, self.secret)
    }
}

pub fn helper(x: i32) -> i32 { x + 1 }
"""


def test_rust_units(tmp_path):
    p = tmp_path / "lib.rs"
    p.write_text(SAMPLE)
    result = RustParser().parse(p, p.read_text())
    kinds = {u.kind for u in result.units}
    assert {"struct", "trait", "method", "function"}.issubset(kinds)
    helper = next(u for u in result.units if u.kind == "function" and "helper" in u.t1_header)
    assert "i32" in helper.t1_header
    methods = [u for u in result.units if u.kind == "method"]
    assert any("Service" in m.t1_header and "issue" in m.t1_header for m in methods)


def test_supports():
    assert RustParser().supports(Path("x.rs"))
    assert not RustParser().supports(Path("x.go"))
