from pathlib import Path
from claude_mem.indexer.parsers.code_go import GoParser


SAMPLE = """\
package auth

type Service struct {
    secret string
}

type TokenIssuer interface {
    Issue(uid string) string
}

func NewService(secret string) *Service {
    return &Service{secret: secret}
}

func (s *Service) Issue(uid string) string {
    return uid + s.secret
}
"""


def test_go_units(tmp_path):
    p = tmp_path / "auth.go"
    p.write_text(SAMPLE)
    result = GoParser().parse(p, p.read_text())
    kinds = {u.kind for u in result.units}
    assert {"function", "method", "struct", "interface"}.issubset(kinds)
    method = next(u for u in result.units if u.kind == "method")
    assert "Service" in method.t1_header and "Issue" in method.t1_header
    fn = next(u for u in result.units if u.kind == "function")
    assert "NewService" in fn.t1_header


def test_supports():
    assert GoParser().supports(Path("x.go"))
    assert not GoParser().supports(Path("x.java"))
