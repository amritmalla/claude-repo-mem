from pathlib import Path
from claude_mem.indexer.parsers.markdown import MarkdownParser


def test_parses_simple_doc(tmp_path: Path):
    p = tmp_path / "design.md"
    p.write_text("# Auth\n\nIntro paragraph.\n\n## JWT\n\nJWT details.\n\n## OAuth\n\nOAuth details.\n")
    parsed = MarkdownParser().parse(p, p.read_text())
    headings = [u.t1_header for u in parsed.units]
    assert "# Auth" in headings
    assert "# Auth > JWT" in headings
    assert "# Auth > OAuth" in headings


def test_section_content_excludes_subsections(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("# A\n\nA body.\n\n## B\n\nB body.\n")
    parsed = MarkdownParser().parse(p, p.read_text())
    a = next(u for u in parsed.units if u.t1_header == "# A")
    assert "A body." in a.metadata  # body stored in metadata JSON
    assert "B body." not in a.metadata


def test_frontmatter_becomes_parent(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("---\nid: my-doc\nscope: backend/auth\n---\n\n# Title\n\nbody.\n")
    parsed = MarkdownParser().parse(p, p.read_text())
    front = next(u for u in parsed.units if u.kind == "frontmatter")
    title = next(u for u in parsed.units if u.kind == "section")
    assert title.parent_id == front.id
    assert title.scope == "backend/auth"   # scope from frontmatter overrides default


def test_no_headings_emits_one_section(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("Just a paragraph.\nNo headings.\n")
    parsed = MarkdownParser().parse(p, p.read_text())
    sections = [u for u in parsed.units if u.kind == "section"]
    assert len(sections) == 1
    assert sections[0].t1_header == "# x"   # falls back to filename stem
