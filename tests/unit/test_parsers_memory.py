from pathlib import Path
import json
import pytest
from claude_mem.indexer.parsers.memory_md import MemoryMarkdownParser


SAMPLE = """\
---
kind: decision
scope: backend/auth
confidence: 0.9
---

We chose RS256 over HS256 so the API gateway can verify tokens without
holding the signing key.
"""


def test_parses_decision(tmp_path: Path):
    (tmp_path / ".claude-mem" / "memory" / "backend" / "auth").mkdir(parents=True)
    p = tmp_path / ".claude-mem" / "memory" / "backend" / "auth" / "rs256.md"
    p.write_text(SAMPLE)
    result = MemoryMarkdownParser().parse(p, p.read_text())
    assert len(result.units) == 1
    u = result.units[0]
    assert u.layer == "memory"
    assert u.kind == "decision"
    assert u.scope == "backend/auth"
    assert u.confidence == 0.9
    assert "RS256" in u.t1_header


def test_supersedes_recorded(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nkind: fact\nscope: x\nsupersedes: mem://decision/old123456\n---\n\nnew fact\n")
    result = MemoryMarkdownParser().parse(p, p.read_text())
    u = result.units[0]
    meta = json.loads(u.metadata)
    assert meta["supersedes"] == "mem://decision/old123456"


def test_invalid_kind_raises(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nkind: nonsense\nscope: x\n---\n\nbody\n")
    with pytest.raises(ValueError):
        MemoryMarkdownParser().parse(p, p.read_text())


def test_missing_kind_defaults_to_fact(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nscope: x\n---\n\nbody\n")
    result = MemoryMarkdownParser().parse(p, p.read_text())
    assert result.units[0].kind == "fact"


def test_supports():
    p = MemoryMarkdownParser()
    assert p.supports(Path(".claude-mem/memory/x/y.md"))
    assert not p.supports(Path("docs/readme.md"))
    assert not p.supports(Path("x.py"))
