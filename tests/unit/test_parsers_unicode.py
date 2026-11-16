import hashlib
from pathlib import Path

import pytest

from claude_repo_mem.indexer.parsers.code_go import GoParser
from claude_repo_mem.indexer.parsers.code_java import JavaParser
from claude_repo_mem.indexer.parsers.code_jsts import JsTsParser
from claude_repo_mem.indexer.parsers.code_python import PythonParser
from claude_repo_mem.indexer.parsers.code_rust import RustParser


CASES = [
    (PythonParser(), "example.py", "#", 'def café(prénom: str) -> str:\n    return "नमस्ते 😀"',
     [("function", "python café(prénom: str) -> str", 'def café(prénom: str) -> str:\n    return "नमस्ते 😀"')]),
    (JsTsParser(), "example.js", "//", 'function café(prénom) { return "नमस्ते 😀"; }',
     [("function", "js café(prénom)", 'function café(prénom) { return "नमस्ते 😀"; }')]),
    (JsTsParser(), "example.jsx", "//", 'function café(prénom) { return <span>漢字 😀</span>; }',
     [("function", "js café(prénom)", 'function café(prénom) { return <span>漢字 😀</span>; }')]),
    (JsTsParser(), "example.ts", "//", 'function café(prénom: string) { return "नमस्ते 😀"; }',
     [("function", "ts café(prénom: string)", 'function café(prénom: string) { return "नमस्ते 😀"; }')]),
    (JsTsParser(), "example.tsx", "//", 'function café(prénom: string) { return <span>漢字 😀</span>; }',
     [("function", "ts café(prénom: string)", 'function café(prénom: string) { return <span>漢字 😀</span>; }')]),
    (JavaParser(), "Example.java", "//",
     'class Café {\n    String saluer(String prénom) { return "नमस्ते 😀"; }\n}', [
         ("class", "java class Café", 'class Café {\n    String saluer(String prénom) { return "नमस्ते 😀"; }\n}'),
         ("method", "java Café.saluer(String prénom) -> String", 'String saluer(String prénom) { return "नमस्ते 😀"; }'),
     ]),
    (GoParser(), "example.go", "//", 'package example\n\nfunc café(prénom string) string { return "नमस्ते 😀" }',
     [("function", "go café(prénom string) string", 'func café(prénom string) string { return "नमस्ते 😀" }')]),
    (RustParser(), "example.rs", "//", 'fn café(prénom: &str) -> &str { "नमस्ते 😀" }',
     [("function", "rust fn café(prénom: &str) -> &str", 'fn café(prénom: &str) -> &str { "नमस्ते 😀" }')]),
]


@pytest.mark.parametrize(("parser", "name", "comment", "body", "expected"), CASES,
                         ids=[case[1] for case in CASES])
def test_unicode_source_headers_hashes_and_line_ranges(tmp_path: Path, parser, name, comment, body, expected):
    path = tmp_path / "répertoire" / name
    source = f"{comment} café नेपाली 漢字 😀\n{body}\n"

    units = parser.parse(path, source).units

    assert len(units) == len(expected)
    for unit, (kind, header, content) in zip(units, expected):
        assert unit.kind == kind
        assert unit.t1_header == header
        assert unit.metadata == content
        assert unit.content_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
        start = source[:source.index(content)].count("\n") + 1
        end = start + content.count("\n")
        assert unit.source_ref == f"{path.as_posix()}:{start}-{end}"


@pytest.mark.parametrize(("parser", "name", "comment", "body", "expected"), CASES,
                         ids=[case[1] for case in CASES])
def test_unicode_comment_does_not_change_unit_identity(tmp_path: Path, parser, name, comment, body, expected):
    path = tmp_path / name
    plain = parser.parse(path, f"{comment} Plain comment\n{body}\n").units
    unicode = parser.parse(path, f"{comment} café नेपाली 漢字 😀\n{body}\n").units

    assert [(u.id, u.content_hash, u.t1_header, u.metadata, u.parent_id) for u in unicode] == [
        (u.id, u.content_hash, u.t1_header, u.metadata, u.parent_id) for u in plain
    ]


@pytest.mark.parametrize(("parser", "name", "source", "headers"), [
    (PythonParser(), "example.py", 'class Café:\n    """サービス 😀"""\n    def saluer(self, prénom):\n        return "नमस्ते"',
     ["python class Café: サービス 😀", "python Café.saluer(self, prénom)"]),
    (JsTsParser(), "example.js", 'class Café { saluer(prénom) { return "नमस्ते"; } }',
     ["js class Café", "js Café.saluer(prénom)"]),
    (JavaParser(), "Example.java", 'class Café { Café(String prénom) {} String saluer() { return "नमस्ते"; } }',
     ["java class Café", "java Café.Café(String prénom) -> void", "java Café.saluer() -> String"]),
    (GoParser(), "example.go", 'package example\ntype Café struct { nom string }\nfunc (c *Café) saluer(prénom string) string { return "नमस्ते" }',
     ["go Café", "go (c *Café) saluer(prénom string) string"]),
    (RustParser(), "example.rs", 'struct Café;\nimpl Café { fn saluer(&self, prénom: &str) -> String { format!("नमस्ते {}", prénom) } }',
     ["rust Café", "rust impl Café::saluer(&self, prénom: &str) -> String"]),
])
def test_unicode_class_names_receivers_and_docstrings(parser, name, source, headers):
    units = parser.parse(Path(name), source).units

    assert [unit.t1_header for unit in units] == headers
    assert all(unit.metadata in source for unit in units)
    if name.endswith((".py", ".js", ".java")):
        parent = units[0]
        assert all(unit.parent_id == parent.id for unit in units[1:])
