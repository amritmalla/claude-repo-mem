from pathlib import Path
from claude_repo_mem.indexer.parsers.code_python import PythonParser


SAMPLE = '''\
import os
from .utils import helper

GLOBAL = 42


def top_level(x: int) -> int:
    """Top level function."""
    return x + 1


class AuthService:
    """Auth service."""

    def __init__(self, db):
        self.db = db

    def login(self, user: str, pw: str) -> str:
        return "token"
'''


def test_emits_function_class_and_method(tmp_path: Path):
    p = tmp_path / "auth.py"
    p.write_text(SAMPLE)
    result = PythonParser().parse(p, p.read_text())
    kinds = sorted(u.kind for u in result.units)
    assert kinds == ["class", "function", "method", "method"]


def test_function_t1_includes_signature(tmp_path: Path):
    p = tmp_path / "auth.py"
    p.write_text(SAMPLE)
    result = PythonParser().parse(p, p.read_text())
    fn = next(u for u in result.units if u.kind == "function")
    assert "top_level" in fn.t1_header
    assert "x: int" in fn.t1_header
    assert "-> int" in fn.t1_header


def test_class_t1_includes_docstring(tmp_path: Path):
    p = tmp_path / "auth.py"
    p.write_text(SAMPLE)
    result = PythonParser().parse(p, p.read_text())
    cls = next(u for u in result.units if u.kind == "class")
    assert "AuthService" in cls.t1_header
    assert "Auth service" in cls.t1_header


def test_method_has_class_as_parent(tmp_path: Path):
    p = tmp_path / "auth.py"
    p.write_text(SAMPLE)
    result = PythonParser().parse(p, p.read_text())
    cls = next(u for u in result.units if u.kind == "class")
    methods = [u for u in result.units if u.kind == "method"]
    assert all(m.parent_id == cls.id for m in methods)


def test_t0_body_in_metadata(tmp_path: Path):
    p = tmp_path / "auth.py"
    p.write_text(SAMPLE)
    result = PythonParser().parse(p, p.read_text())
    fn = next(u for u in result.units if u.kind == "function")
    assert "return x + 1" in fn.metadata


def test_empty_file_emits_nothing(tmp_path: Path):
    p = tmp_path / "empty.py"
    p.write_text("\n\n# just a comment\n")
    result = PythonParser().parse(p, p.read_text())
    assert result.units == []
