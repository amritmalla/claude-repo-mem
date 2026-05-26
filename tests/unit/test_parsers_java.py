from pathlib import Path
from claude_mem.indexer.parsers.code_java import JavaParser


SAMPLE = """\
package com.example;

public class AuthService {
    public String issueToken(String userId) {
        return userId;
    }

    private void invalidate(String token) {
    }
}
"""


def test_class_and_methods(tmp_path):
    p = tmp_path / "AuthService.java"
    p.write_text(SAMPLE)
    result = JavaParser().parse(p, p.read_text())
    kinds = [(u.kind, u.t1_header) for u in result.units]
    assert any(k == "class" and "AuthService" in h for k, h in kinds)
    assert any(k == "method" and "issueToken" in h and "String" in h for k, h in kinds)
    cls = next(u for u in result.units if u.kind == "class")
    methods = [u for u in result.units if u.kind == "method"]
    assert methods
    for u in methods:
        assert u.parent_id == cls.id


def test_interface_unit():
    from pathlib import Path
    p = Path("X.java")
    src = "public interface I { String m(); }\n"
    result = JavaParser().parse(p, src)
    assert any(u.kind == "interface" and "I" in u.t1_header for u in result.units)


def test_supports():
    p = JavaParser()
    assert p.supports(Path("X.java"))
    assert not p.supports(Path("x.py"))
