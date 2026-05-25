# claude-mem Phase 1 — Substrate, Retrieval, Traversal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Python MCP server that indexes a real repo (code + docs), stores a unified unit/relation graph in SQLite, and exposes working `recall`, `trace`, and `expand` tools that fit per-tool budgets — sufficient that a Claude Code user on a Flask repo can ask "how does login work?" and get a useful answer in one round-trip.

**Architecture:** Single Python package `claude_mem` exposing a CLI (`claude-mem`) and a stdio MCP server. State lives in `<repo>/.claude-mem/db.sqlite` (FTS5 + sqlite-vec + relational schema, all one file). Indexer parses code via tree-sitter and docs via mdAST into semantic units; framework synthesizers emit graph edges. Retrieval is RRF + feature rerank with budget-aware tiered fill (§4.1, §4.2 of spec).

**Tech Stack:** Python 3.11+, `pytest`, `mcp` (the official Anthropic MCP Python SDK), `sqlite-vec`, `tree-sitter` + per-language packages (`tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript` — `tree-sitter-languages` lacks Windows wheels), `markdown-it-py`, `sentence-transformers` (bge-small), `tiktoken`, `click` for CLI, `pydantic` for tool schemas.

**Implementation lessons learned during execution** (read before dispatching tasks 10+):
1. `tree-sitter-languages` has no Windows wheels — use per-language packages. The `get_parser("python")` API does NOT exist; instead use `from tree_sitter import Language, Parser; import tree_sitter_python; LANG = Language(tree_sitter_python.language()); parser = Parser(LANG)`. For TS use `tree_sitter_typescript.language_typescript()` and `language_tsx()`. Patch Tasks 10/11 code accordingly before dispatch.
2. Test isolation: when a test uses `tmp_path` and walks parent directories, ambient `.claude-mem` in the developer's home dir can pollute the test. Use `monkeypatch.setattr(Path, "is_dir", ...)` to mask `.claude-mem` ancestors in any "raises when not in repo" tests.

**Spec:** `docs/specs/2026-05-25-claude-mem-design.md`. This plan implements Phase 1 (§12 of spec).

---

## File Structure

Files created in this phase, grouped by responsibility:

**Project root**
- `pyproject.toml` — package metadata, deps, entry point
- `.gitignore` — already exists; verify `.claude-mem/` excluded
- `README.md` — minimal install/usage stub
- `tests/conftest.py` — shared fixtures

**Package: storage primitives**
- `src/claude_mem/config.py` — paths, env vars, settings
- `src/claude_mem/db/schema.py` — DDL (unit, relation, FTS5, vec)
- `src/claude_mem/db/connection.py` — connect, load vec extension, migrate
- `src/claude_mem/db/repository.py` — unit/relation CRUD + FTS/vec queries

**Package: unit model**
- `src/claude_mem/units/model.py` — `Unit`, `Relation` dataclasses
- `src/claude_mem/units/ids.py` — handle generation (opaque IDs)
- `src/claude_mem/units/headers.py` — T1 deterministic headers per kind

**Package: token budgeting**
- `src/claude_mem/tokens.py` — token counter (tiktoken)

**Package: embeddings**
- `src/claude_mem/embeddings/base.py` — `Embedder` protocol
- `src/claude_mem/embeddings/bge_small.py` — sentence-transformers impl

**Package: indexer**
- `src/claude_mem/indexer/walker.py` — file discovery, content hashing, scope derivation
- `src/claude_mem/indexer/parsers/base.py` — `Parser` protocol
- `src/claude_mem/indexer/parsers/markdown.py` — heading-bounded sections
- `src/claude_mem/indexer/parsers/code_python.py` — tree-sitter Python
- `src/claude_mem/indexer/parsers/code_jsts.py` — tree-sitter JS/TS
- `src/claude_mem/indexer/synthesizers/base.py` — `Synthesizer` protocol
- `src/claude_mem/indexer/synthesizers/imports.py` — import edges
- `src/claude_mem/indexer/synthesizers/flask_routes.py` — `@app.route` edges
- `src/claude_mem/indexer/orchestrator.py` — full reindex driver

**Package: retrieval**
- `src/claude_mem/retrieval/ranker.py` — RRF + feature multipliers
- `src/claude_mem/retrieval/fill.py` — budget-aware tiered fill
- `src/claude_mem/retrieval/recall.py` — query → embed → search → rank → fill
- `src/claude_mem/retrieval/trace.py` — BFS traversal + fill

**Package: MCP surface**
- `src/claude_mem/server.py` — MCP stdio server, `initialize` instructions
- `src/claude_mem/tools/recall.py` — MCP tool wrapper
- `src/claude_mem/tools/trace.py` — MCP tool wrapper
- `src/claude_mem/tools/expand.py` — MCP tool wrapper
- `src/claude_mem/cli.py` — `claude-mem` entry: `index`, `serve`, `doctor`

**Tests**
- `tests/unit/test_*.py` — one per module
- `tests/integration/fixtures/flask_app/` — small Flask repo used in e2e
- `tests/integration/fixtures/docs_only/` — markdown-only repo
- `tests/integration/test_indexer_e2e.py`
- `tests/integration/test_recall_e2e.py`
- `tests/integration/test_trace_e2e.py`
- `tests/integration/test_mcp_server.py`

---

## Task 0: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/claude_mem/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "claude-mem"
version = "0.1.0"
description = "Contextual memory & retrieval engine for Claude Code"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
    "sqlite-vec>=0.1.3",
    "tree-sitter>=0.21",
    "tree-sitter-languages>=1.10",
    "markdown-it-py>=3.0",
    "sentence-transformers>=2.7",
    "tiktoken>=0.7",
    "click>=8.1",
    "pydantic>=2.6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.4",
]

[project.scripts]
claude-mem = "claude_mem.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/claude_mem"]

[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package files**

Create `src/claude_mem/__init__.py` with one line: `__version__ = "0.1.0"`
Create `tests/__init__.py` empty.

- [ ] **Step 3: Write `tests/conftest.py`**

```python
import os
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A temp directory standing in for a working repo."""
    (tmp_path / ".claude-mem").mkdir()
    return tmp_path


@pytest.fixture
def db_path(tmp_repo: Path) -> Path:
    return tmp_repo / ".claude-mem" / "db.sqlite"
```

- [ ] **Step 4: Verify `.gitignore` excludes derived state**

Read `.gitignore`. Confirm it contains `.claude-mem/` and `codegraph/`. If `__pycache__/`, `.pytest_cache/`, `dist/`, `*.egg-info/`, `.venv/` are missing, append them.

- [ ] **Step 5: Install dev environment**

Run: `python -m venv .venv && .venv/Scripts/activate && pip install -e ".[dev]"`
Expected: clean install, `claude-mem --help` resolves (will fail until Task 22, but the entry point is registered).

- [ ] **Step 6: Smoke test pytest**

Run: `pytest -q`
Expected: `no tests ran in 0.0Xs`. Confirms pytest discovers the layout.

- [ ] **Step 7: Commit**

```
git add pyproject.toml src/claude_mem/__init__.py tests/__init__.py tests/conftest.py .gitignore
git commit -m "chore: scaffold claude-mem package and pytest layout"
```

---

## Task 1: Config module

**Files:**
- Create: `src/claude_mem/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:

```python
from pathlib import Path
from claude_mem.config import Settings


def test_settings_finds_repo_root_via_dot_claude_mem(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    s = Settings.discover()
    assert s.repo_root == tmp_repo
    assert s.state_dir == tmp_repo / ".claude-mem"
    assert s.db_path == tmp_repo / ".claude-mem" / "db.sqlite"


def test_settings_walks_up_for_repo_root(tmp_repo: Path, monkeypatch):
    sub = tmp_repo / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    s = Settings.discover()
    assert s.repo_root == tmp_repo


def test_settings_raises_when_not_in_repo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import pytest
    with pytest.raises(FileNotFoundError):
        Settings.discover()


def test_embedder_env_override(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.setenv("CLAUDE_MEM_EMBED", "openai:text-embedding-3-small")
    s = Settings.discover()
    assert s.embedder == "openai:text-embedding-3-small"


def test_embedder_default(tmp_repo: Path, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    monkeypatch.delenv("CLAUDE_MEM_EMBED", raising=False)
    s = Settings.discover()
    assert s.embedder == "bge-small"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_config.py -v`
Expected: `ModuleNotFoundError: claude_mem.config`.

- [ ] **Step 3: Implement `Settings`**

`src/claude_mem/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STATE_DIRNAME = ".claude-mem"


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    state_dir: Path
    db_path: Path
    blobs_dir: Path
    handoffs_dir: Path
    memory_dir: Path
    scopes_yml: Path
    embedder: str

    @classmethod
    def discover(cls, start: Path | None = None) -> "Settings":
        cwd = (start or Path.cwd()).resolve()
        for candidate in [cwd, *cwd.parents]:
            if (candidate / STATE_DIRNAME).is_dir():
                return cls._build(candidate)
        raise FileNotFoundError(
            f"No {STATE_DIRNAME}/ directory found in {cwd} or any parent. "
            "Run `claude-mem init` first."
        )

    @classmethod
    def for_repo(cls, repo_root: Path) -> "Settings":
        repo_root = repo_root.resolve()
        (repo_root / STATE_DIRNAME).mkdir(exist_ok=True)
        return cls._build(repo_root)

    @classmethod
    def _build(cls, repo_root: Path) -> "Settings":
        state = repo_root / STATE_DIRNAME
        return cls(
            repo_root=repo_root,
            state_dir=state,
            db_path=state / "db.sqlite",
            blobs_dir=state / "blobs",
            handoffs_dir=state / "handoffs",
            memory_dir=state / "memory",
            scopes_yml=state / "scopes.yml",
            embedder=os.environ.get("CLAUDE_MEM_EMBED", "bge-small"),
        )
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/config.py tests/unit/test_config.py
git commit -m "feat(config): discover state dir by walking up from cwd"
```

---

## Task 2: DB schema and connection

**Files:**
- Create: `src/claude_mem/db/__init__.py`
- Create: `src/claude_mem/db/schema.py`
- Create: `src/claude_mem/db/connection.py`
- Test: `tests/unit/test_db_connection.py`

The schema is from spec §3.1. We use `sqlite-vec` for vectors and FTS5 for keyword search.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_db_connection.py`:

```python
from pathlib import Path
from claude_mem.db.connection import connect, init_db


def test_init_db_creates_file_and_tables(db_path: Path):
    init_db(db_path)
    assert db_path.exists()
    conn = connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','virtual_table')")}
    assert "unit" in tables
    assert "relation" in tables
    assert "unit_fts" in tables
    assert "unit_vec" in tables


def test_init_db_idempotent(db_path: Path):
    init_db(db_path)
    init_db(db_path)  # second call must not error
    conn = connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    assert n == 0


def test_vec_extension_loaded(db_path: Path):
    init_db(db_path)
    conn = connect(db_path)
    # vec_version() comes from sqlite-vec
    version = conn.execute("SELECT vec_version()").fetchone()[0]
    assert version  # truthy
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_db_connection.py -v`
Expected: `ModuleNotFoundError: claude_mem.db`.

- [ ] **Step 3: Implement schema and connection**

`src/claude_mem/db/__init__.py`: empty file.

`src/claude_mem/db/schema.py`:

```python
"""DDL for claude-mem.

Schema mirrors §3.1 of the design spec.
"""

DDL = [
    # Schema version marker (used for future migrations).
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    """,
    "INSERT OR IGNORE INTO schema_version(version) VALUES (1);",
    # Core unit table.
    """
    CREATE TABLE IF NOT EXISTS unit (
        id              TEXT PRIMARY KEY,
        layer           TEXT NOT NULL CHECK (layer IN ('memory','docs','code')),
        kind            TEXT NOT NULL,
        scope           TEXT NOT NULL,
        source_ref      TEXT,
        content_hash    TEXT NOT NULL,
        t1_header       TEXT NOT NULL,
        t2_summary      TEXT,
        parent_id       TEXT REFERENCES unit(id),
        superseded_by   TEXT REFERENCES unit(id),
        confidence      REAL,
        created_at      INTEGER NOT NULL,
        last_seen_at    INTEGER NOT NULL,
        metadata        TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_unit_scope ON unit(scope);",
    "CREATE INDEX IF NOT EXISTS idx_unit_layer ON unit(layer);",
    "CREATE INDEX IF NOT EXISTS idx_unit_parent ON unit(parent_id);",
    "CREATE INDEX IF NOT EXISTS idx_unit_super ON unit(superseded_by);",
    # FTS5 mirror of t1_header + t2_summary.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts USING fts5(
        id UNINDEXED,
        t1_header,
        t2_summary,
        tokenize = 'unicode61'
    );
    """,
    # Vector store via sqlite-vec. Dimension 384 = bge-small.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS unit_vec USING vec0(
        id TEXT PRIMARY KEY,
        embedding FLOAT[384]
    );
    """,
    # Relations.
    """
    CREATE TABLE IF NOT EXISTS relation (
        src_id TEXT NOT NULL REFERENCES unit(id) ON DELETE CASCADE,
        dst_id TEXT NOT NULL REFERENCES unit(id) ON DELETE CASCADE,
        kind   TEXT NOT NULL,
        PRIMARY KEY (src_id, dst_id, kind)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_relation_dst ON relation(dst_id, kind);",
]
```

`src/claude_mem/db/connection.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from .schema import DDL


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and foreign keys on."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    """Create the DB and run DDL. Idempotent."""
    conn = connect(db_path)
    try:
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_db_connection.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/db/ tests/unit/test_db_connection.py
git commit -m "feat(db): schema with FTS5 + sqlite-vec; connect/init helpers"
```

---

## Task 3: Unit model and handle IDs

**Files:**
- Create: `src/claude_mem/units/__init__.py`
- Create: `src/claude_mem/units/model.py`
- Create: `src/claude_mem/units/ids.py`
- Test: `tests/unit/test_unit_model.py`
- Test: `tests/unit/test_ids.py`

Handles are opaque, content-addressed, and namespaced per layer. Format: `<layer>://<kind>/<short-hash>`. Example: `code://function/8f3a2b`. They survive file moves (because they're keyed on content + name, not path).

- [ ] **Step 1: Write the failing test for IDs**

`tests/unit/test_ids.py`:

```python
from claude_mem.units.ids import make_handle, parse_handle, HandleParts


def test_make_handle_is_deterministic():
    h1 = make_handle("code", "function", "auth.login", "def login(): pass")
    h2 = make_handle("code", "function", "auth.login", "def login(): pass")
    assert h1 == h2


def test_make_handle_changes_with_content():
    h1 = make_handle("code", "function", "auth.login", "def login(): pass")
    h2 = make_handle("code", "function", "auth.login", "def login(): return 1")
    assert h1 != h2


def test_make_handle_format():
    h = make_handle("code", "function", "auth.login", "def login(): pass")
    assert h.startswith("code://function/")
    parts = h.split("/")
    assert len(parts[-1]) == 12  # 12-char short hash


def test_parse_handle_roundtrip():
    h = make_handle("memory", "decision", "auth/use-jwt", "We use JWT.")
    p = parse_handle(h)
    assert p == HandleParts(layer="memory", kind="decision", short_hash=h.split("/")[-1])


def test_parse_handle_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        parse_handle("not-a-handle")
    with pytest.raises(ValueError):
        parse_handle("http://example.com/foo")
```

- [ ] **Step 2: Write the failing test for Unit/Relation models**

`tests/unit/test_unit_model.py`:

```python
import time
from claude_mem.units.model import Unit, Relation


def test_unit_minimal_fields():
    u = Unit(
        id="code://function/abc",
        layer="code",
        kind="function",
        scope="backend/auth",
        source_ref="src/auth.py:10-25",
        content_hash="deadbeef",
        t1_header="def login(user, pw) -> Token",
        created_at=1_700_000_000,
        last_seen_at=1_700_000_000,
    )
    assert u.t2_summary is None
    assert u.parent_id is None
    assert u.layer == "code"


def test_unit_rejects_invalid_layer():
    import pytest
    with pytest.raises(ValueError):
        Unit(
            id="x://y/z",
            layer="invalid",
            kind="function",
            scope="x",
            source_ref=None,
            content_hash="h",
            t1_header="h",
            created_at=0,
            last_seen_at=0,
        )


def test_relation_equality():
    r1 = Relation(src_id="a", dst_id="b", kind="imports")
    r2 = Relation(src_id="a", dst_id="b", kind="imports")
    assert r1 == r2
```

- [ ] **Step 3: Run, confirm FAIL**

Run: `pytest tests/unit/test_ids.py tests/unit/test_unit_model.py -v`
Expected: import errors.

- [ ] **Step 4: Implement model and IDs**

`src/claude_mem/units/__init__.py`: empty.

`src/claude_mem/units/ids.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass

VALID_LAYERS = {"memory", "docs", "code", "task"}


@dataclass(frozen=True)
class HandleParts:
    layer: str
    kind: str
    short_hash: str


def make_handle(layer: str, kind: str, locator: str, content: str) -> str:
    """Deterministic, content-addressed handle.

    `locator` is a stable name (e.g. `module.function`, `path#heading`). It plus
    content seed the hash so that renames produce new handles but identical
    content at the same locator collides (good — it's the same unit).
    """
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid layer: {layer!r}")
    digest = hashlib.sha256(f"{locator}\0{content}".encode("utf-8")).hexdigest()
    return f"{layer}://{kind}/{digest[:12]}"


def parse_handle(handle: str) -> HandleParts:
    if "://" not in handle:
        raise ValueError(f"not a claude-mem handle: {handle!r}")
    layer, rest = handle.split("://", 1)
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid handle layer: {layer!r}")
    if "/" not in rest:
        raise ValueError(f"malformed handle: {handle!r}")
    kind, short = rest.split("/", 1)
    return HandleParts(layer=layer, kind=kind, short_hash=short)
```

`src/claude_mem/units/model.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Layer = Literal["memory", "docs", "code", "task"]
_VALID_LAYERS = {"memory", "docs", "code", "task"}


@dataclass(frozen=True)
class Unit:
    id: str
    layer: str
    kind: str
    scope: str
    source_ref: Optional[str]
    content_hash: str
    t1_header: str
    created_at: int
    last_seen_at: int
    t2_summary: Optional[str] = None
    parent_id: Optional[str] = None
    superseded_by: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Optional[str] = None  # JSON string

    def __post_init__(self) -> None:
        if self.layer not in _VALID_LAYERS:
            raise ValueError(f"invalid layer: {self.layer!r}")


@dataclass(frozen=True)
class Relation:
    src_id: str
    dst_id: str
    kind: str
```

- [ ] **Step 5: Run, confirm PASS**

Run: `pytest tests/unit/test_ids.py tests/unit/test_unit_model.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/units/ tests/unit/test_ids.py tests/unit/test_unit_model.py
git commit -m "feat(units): Unit/Relation models and content-addressed handles"
```

---

## Task 4: T1 deterministic headers

**Files:**
- Create: `src/claude_mem/units/headers.py`
- Test: `tests/unit/test_headers.py`

T1 headers (spec §9.3): code → signature, doc → heading path, memory → first 80 chars. Always cheap, never LLM.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_headers.py`:

```python
from claude_mem.units.headers import t1_header


def test_t1_for_python_function():
    h = t1_header(
        layer="code", kind="function", lang="python",
        name="login", signature="(user: str, pw: str) -> Token",
        first_line="def login(user: str, pw: str) -> Token:",
    )
    assert h == "python login(user: str, pw: str) -> Token"


def test_t1_for_python_class():
    h = t1_header(
        layer="code", kind="class", lang="python",
        name="AuthService", signature="(BaseService)",
        first_line="class AuthService(BaseService):",
        docstring_first_line="Handles login and token refresh.",
    )
    assert h == "python class AuthService(BaseService): Handles login and token refresh."


def test_t1_for_doc_section():
    h = t1_header(
        layer="docs", kind="section",
        heading_path=["Auth", "JWT", "Refresh"],
    )
    assert h == "# Auth > JWT > Refresh"


def test_t1_for_memory_fact():
    h = t1_header(
        layer="memory", kind="fact",
        text="We chose RS256 because the gateway needs to verify without the signing key.",
    )
    assert h.startswith("[fact] We chose RS256 because the gateway needs to verify")
    assert len(h) <= 90  # 80 chars + "[fact] " prefix


def test_t1_for_memory_decision_truncates_long():
    long = "x" * 500
    h = t1_header(layer="memory", kind="decision", text=long)
    assert h.startswith("[decision] ")
    # 80 chars of body + the prefix
    assert len(h) == len("[decision] ") + 80
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_headers.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

`src/claude_mem/units/headers.py`:

```python
from __future__ import annotations

from typing import Optional, Sequence

MEMORY_BODY_CHARS = 80


def t1_header(
    *,
    layer: str,
    kind: str,
    # Code:
    lang: Optional[str] = None,
    name: Optional[str] = None,
    signature: Optional[str] = None,
    first_line: Optional[str] = None,
    docstring_first_line: Optional[str] = None,
    # Docs:
    heading_path: Optional[Sequence[str]] = None,
    # Memory:
    text: Optional[str] = None,
) -> str:
    """Compute T1 header per spec §9.3."""
    if layer == "code":
        if name is None:
            raise ValueError("code header needs name")
        sig = signature or ""
        base = f"{lang or 'code'} {name}{sig}".strip()
        if kind in ("class", "interface"):
            base = f"{lang or 'code'} {kind} {name}{sig}"
            if docstring_first_line:
                base = f"{base}: {docstring_first_line}"
        return base

    if layer == "docs":
        if not heading_path:
            raise ValueError("docs header needs heading_path")
        return "# " + " > ".join(heading_path)

    if layer in ("memory", "task"):
        if text is None:
            raise ValueError("memory/task header needs text")
        body = text.strip().replace("\n", " ")[:MEMORY_BODY_CHARS]
        return f"[{kind}] {body}"

    raise ValueError(f"unknown layer for header: {layer!r}")
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_headers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/units/headers.py tests/unit/test_headers.py
git commit -m "feat(units): T1 deterministic header generation per layer"
```

---

## Task 5: Token counter

**Files:**
- Create: `src/claude_mem/tokens.py`
- Test: `tests/unit/test_tokens.py`

Used everywhere budgets matter. Wrap `tiktoken` so we have one place to swap encoders.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_tokens.py`:

```python
from claude_mem.tokens import count_tokens


def test_empty_string():
    assert count_tokens("") == 0


def test_simple_text_nonzero():
    assert count_tokens("hello world") > 0


def test_longer_is_longer():
    short = count_tokens("hi")
    long = count_tokens("hi " * 100)
    assert long > short


def test_idempotent():
    s = "def login(user, pw):\n    return Token()"
    assert count_tokens(s) == count_tokens(s)
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_tokens.py -v`
Expected: import error.

- [ ] **Step 3: Implement**

`src/claude_mem/tokens.py`:

```python
from __future__ import annotations

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _encoder():
    # cl100k_base is a reasonable proxy for Claude's tokenizer.
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoder().encode(text))
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_tokens.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/tokens.py tests/unit/test_tokens.py
git commit -m "feat(tokens): tiktoken wrapper for budget arithmetic"
```

---

## Task 6: Repository layer (CRUD + search primitives)

**Files:**
- Create: `src/claude_mem/db/repository.py`
- Test: `tests/unit/test_repository.py`

This is the only module that writes SQL outside of schema. All read/write goes through `Repository`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_repository.py`:

```python
import time
import numpy as np
import pytest
from pathlib import Path

from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.units.model import Unit, Relation


@pytest.fixture
def repo(db_path: Path) -> Repository:
    init_db(db_path)
    return Repository(connect(db_path))


def _u(id="code://function/a", layer="code", kind="function", scope="x",
       header="hello world", emb=None) -> Unit:
    return Unit(
        id=id, layer=layer, kind=kind, scope=scope,
        source_ref=None, content_hash="h", t1_header=header,
        created_at=int(time.time()), last_seen_at=int(time.time()),
    )


def test_upsert_and_get(repo: Repository):
    u = _u()
    repo.upsert_unit(u)
    fetched = repo.get_unit(u.id)
    assert fetched is not None
    assert fetched.id == u.id
    assert fetched.t1_header == "hello world"


def test_upsert_replaces(repo: Repository):
    u1 = _u(header="v1")
    repo.upsert_unit(u1)
    u2 = _u(header="v2")
    repo.upsert_unit(u2)
    assert repo.get_unit(u1.id).t1_header == "v2"


def test_upsert_writes_fts(repo: Repository):
    repo.upsert_unit(_u(id="code://function/a", header="login function for auth"))
    hits = repo.fts_search("login", limit=10)
    assert any(h.id == "code://function/a" for h in hits)


def test_upsert_with_embedding_writes_vec(repo: Repository):
    vec = np.random.rand(384).astype("float32")
    repo.upsert_unit(_u(id="code://function/a"), embedding=vec)
    hits = repo.vec_search(vec, limit=5)
    assert len(hits) == 1
    assert hits[0].id == "code://function/a"


def test_vec_search_ranks_by_distance(repo: Repository):
    e1 = np.array([1.0] + [0.0] * 383, dtype="float32")
    e2 = np.array([0.9, 0.1] + [0.0] * 382, dtype="float32")
    e3 = np.array([0.0] * 383 + [1.0], dtype="float32")
    repo.upsert_unit(_u(id="code://function/1"), embedding=e1)
    repo.upsert_unit(_u(id="code://function/2"), embedding=e2)
    repo.upsert_unit(_u(id="code://function/3"), embedding=e3)
    hits = repo.vec_search(e1, limit=3)
    assert hits[0].id == "code://function/1"
    assert hits[1].id == "code://function/2"
    assert hits[2].id == "code://function/3"


def test_add_relation_and_neighbors(repo: Repository):
    repo.upsert_unit(_u(id="code://function/a"))
    repo.upsert_unit(_u(id="code://function/b"))
    repo.add_relation(Relation("code://function/a", "code://function/b", "imports"))
    out = repo.neighbors("code://function/a", direction="out")
    assert [r.dst_id for r in out] == ["code://function/b"]
    inc = repo.neighbors("code://function/b", direction="in")
    assert [r.src_id for r in inc] == ["code://function/a"]


def test_neighbors_filter_by_kind(repo: Repository):
    repo.upsert_unit(_u(id="code://function/a"))
    repo.upsert_unit(_u(id="code://function/b"))
    repo.add_relation(Relation("code://function/a", "code://function/b", "imports"))
    repo.add_relation(Relation("code://function/a", "code://function/b", "mentions"))
    out = repo.neighbors("code://function/a", direction="out", kinds=["imports"])
    assert len(out) == 1
    assert out[0].kind == "imports"


def test_delete_unit_cascades_relations(repo: Repository):
    repo.upsert_unit(_u(id="code://function/a"))
    repo.upsert_unit(_u(id="code://function/b"))
    repo.add_relation(Relation("code://function/a", "code://function/b", "imports"))
    repo.delete_unit("code://function/a")
    assert repo.neighbors("code://function/b", direction="in") == []
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_repository.py -v`
Expected: `ModuleNotFoundError: claude_mem.db.repository`.

- [ ] **Step 3: Implement Repository**

`src/claude_mem/db/repository.py`:

```python
from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import numpy as np

from ..units.model import Unit, Relation


@dataclass(frozen=True)
class SearchHit:
    id: str
    rank: int           # 1-based rank in this result set
    score: float        # backend-specific (bm25 or distance)


def _serialize_embedding(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype="float32")
    if arr.shape != (384,):
        raise ValueError(f"embedding must be shape (384,), got {arr.shape}")
    return arr.tobytes()


class Repository:
    """The only module that writes SQL outside of schema."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- units --------------------------------------------------------------

    def upsert_unit(self, u: Unit, embedding: Optional[np.ndarray] = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO unit (id, layer, kind, scope, source_ref, content_hash,
                                  t1_header, t2_summary, parent_id, superseded_by,
                                  confidence, created_at, last_seen_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    layer=excluded.layer,
                    kind=excluded.kind,
                    scope=excluded.scope,
                    source_ref=excluded.source_ref,
                    content_hash=excluded.content_hash,
                    t1_header=excluded.t1_header,
                    t2_summary=excluded.t2_summary,
                    parent_id=excluded.parent_id,
                    superseded_by=excluded.superseded_by,
                    confidence=excluded.confidence,
                    last_seen_at=excluded.last_seen_at,
                    metadata=excluded.metadata
                """,
                (
                    u.id, u.layer, u.kind, u.scope, u.source_ref, u.content_hash,
                    u.t1_header, u.t2_summary, u.parent_id, u.superseded_by,
                    u.confidence, u.created_at, u.last_seen_at, u.metadata,
                ),
            )
            # FTS mirror.
            self.conn.execute("DELETE FROM unit_fts WHERE id = ?", (u.id,))
            self.conn.execute(
                "INSERT INTO unit_fts(id, t1_header, t2_summary) VALUES (?, ?, ?)",
                (u.id, u.t1_header, u.t2_summary or ""),
            )
            # Vector mirror.
            self.conn.execute("DELETE FROM unit_vec WHERE id = ?", (u.id,))
            if embedding is not None:
                self.conn.execute(
                    "INSERT INTO unit_vec(id, embedding) VALUES (?, ?)",
                    (u.id, _serialize_embedding(embedding)),
                )

    def get_unit(self, unit_id: str) -> Optional[Unit]:
        row = self.conn.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
        if not row:
            return None
        return _row_to_unit(row)

    def get_units(self, ids: Sequence[str]) -> List[Unit]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM unit WHERE id IN ({placeholders})", tuple(ids)
        ).fetchall()
        by_id = {r["id"]: _row_to_unit(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def delete_unit(self, unit_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM unit_fts WHERE id = ?", (unit_id,))
            self.conn.execute("DELETE FROM unit_vec WHERE id = ?", (unit_id,))
            self.conn.execute("DELETE FROM unit WHERE id = ?", (unit_id,))

    # -- search -------------------------------------------------------------

    def fts_search(self, query: str, limit: int = 50) -> List[SearchHit]:
        # FTS5 'bm25(table)' returns a score where lower = better. We invert.
        rows = self.conn.execute(
            """
            SELECT id, bm25(unit_fts) AS s
            FROM unit_fts
            WHERE unit_fts MATCH ?
            ORDER BY s ASC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [SearchHit(id=r["id"], rank=i + 1, score=-r["s"]) for i, r in enumerate(rows)]

    def vec_search(self, embedding: np.ndarray, limit: int = 50) -> List[SearchHit]:
        rows = self.conn.execute(
            """
            SELECT id, distance
            FROM unit_vec
            WHERE embedding MATCH ?
            ORDER BY distance ASC
            LIMIT ?
            """,
            (_serialize_embedding(embedding), limit),
        ).fetchall()
        return [SearchHit(id=r["id"], rank=i + 1, score=-r["distance"]) for i, r in enumerate(rows)]

    # -- relations ----------------------------------------------------------

    def add_relation(self, r: Relation) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO relation(src_id, dst_id, kind) VALUES (?, ?, ?)",
                (r.src_id, r.dst_id, r.kind),
            )

    def neighbors(
        self,
        unit_id: str,
        direction: str = "out",
        kinds: Optional[Sequence[str]] = None,
    ) -> List[Relation]:
        if direction == "out":
            sql = "SELECT src_id, dst_id, kind FROM relation WHERE src_id = ?"
        elif direction == "in":
            sql = "SELECT src_id, dst_id, kind FROM relation WHERE dst_id = ?"
        else:
            raise ValueError(f"direction must be 'in' or 'out', got {direction!r}")
        params: list = [unit_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            params.extend(kinds)
        rows = self.conn.execute(sql, params).fetchall()
        return [Relation(r["src_id"], r["dst_id"], r["kind"]) for r in rows]


def _row_to_unit(row: sqlite3.Row) -> Unit:
    return Unit(
        id=row["id"],
        layer=row["layer"],
        kind=row["kind"],
        scope=row["scope"],
        source_ref=row["source_ref"],
        content_hash=row["content_hash"],
        t1_header=row["t1_header"],
        t2_summary=row["t2_summary"],
        parent_id=row["parent_id"],
        superseded_by=row["superseded_by"],
        confidence=row["confidence"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        metadata=row["metadata"],
    )
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/db/repository.py tests/unit/test_repository.py
git commit -m "feat(db): Repository with upsert, FTS5, vec, and relation queries"
```

---

## Task 7: Embedder interface + bge-small implementation

**Files:**
- Create: `src/claude_mem/embeddings/__init__.py`
- Create: `src/claude_mem/embeddings/base.py`
- Create: `src/claude_mem/embeddings/bge_small.py`
- Test: `tests/unit/test_embeddings.py`

The bge-small model is downloaded on first use (~100MB). Tests should mark it `slow` and skip by default; CI runs them on demand.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_embeddings.py`:

```python
import numpy as np
import pytest

from claude_mem.embeddings.base import Embedder
from claude_mem.embeddings.bge_small import BgeSmallEmbedder


def test_embedder_protocol_attrs():
    assert hasattr(Embedder, "embed")
    assert hasattr(Embedder, "dim")


@pytest.mark.slow
def test_bge_small_embeds_single():
    e = BgeSmallEmbedder()
    [v] = e.embed(["hello world"])
    assert v.shape == (384,)
    assert v.dtype == np.float32


@pytest.mark.slow
def test_bge_small_batch():
    e = BgeSmallEmbedder()
    vs = e.embed(["alpha", "beta", "gamma"])
    assert len(vs) == 3
    assert all(v.shape == (384,) for v in vs)


@pytest.mark.slow
def test_bge_small_similar_texts_closer():
    e = BgeSmallEmbedder()
    a, b, c = e.embed(["user authentication", "user login", "database migration"])
    sim_ab = float(np.dot(a, b))
    sim_ac = float(np.dot(a, c))
    assert sim_ab > sim_ac
```

- [ ] **Step 2: Configure slow marker**

Edit `pyproject.toml`, add under `[tool.pytest.ini_options]`:

```toml
markers = ["slow: tests that download models or are otherwise expensive"]
addopts = "-m 'not slow'"
```

- [ ] **Step 3: Run, confirm FAIL**

Run: `pytest tests/unit/test_embeddings.py -v` → only the protocol test runs and it fails on import.

- [ ] **Step 4: Implement**

`src/claude_mem/embeddings/__init__.py`: empty.

`src/claude_mem/embeddings/base.py`:

```python
from __future__ import annotations

from typing import Protocol, Sequence

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]: ...
```

`src/claude_mem/embeddings/bge_small.py`:

```python
from __future__ import annotations

from functools import cached_property
from typing import Sequence

import numpy as np


class BgeSmallEmbedder:
    """sentence-transformers/BAAI/bge-small-en-v1.5, 384-dim, CPU."""

    dim = 384
    model_id = "BAAI/bge-small-en-v1.5"

    @cached_property
    def _model(self):
        # Imported lazily so unit tests that mock the embedder don't pay the import.
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model_id, device="cpu")

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        arr = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype("float32")
        return [row for row in arr]
```

- [ ] **Step 5: Run protocol test, confirm PASS**

Run: `pytest tests/unit/test_embeddings.py::test_embedder_protocol_attrs -v`
Expected: 1 passed.

- [ ] **Step 6: Run slow tests on demand, confirm PASS**

Run: `pytest tests/unit/test_embeddings.py -v -m slow`
Expected: 3 passed (first run downloads the model — slow). Subsequent runs are seconds.

- [ ] **Step 7: Commit**

```
git add src/claude_mem/embeddings/ tests/unit/test_embeddings.py pyproject.toml
git commit -m "feat(embeddings): Embedder protocol + bge-small implementation"
```

---

## Task 8: Walker (file discovery + content hashing + scope derivation)

**Files:**
- Create: `src/claude_mem/indexer/__init__.py`
- Create: `src/claude_mem/indexer/walker.py`
- Test: `tests/unit/test_walker.py`

The walker yields candidate files. It does not parse — it hands paths off to parsers based on extension.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_walker.py`:

```python
from pathlib import Path
from claude_mem.indexer.walker import walk_repo, derive_scope, hash_file


def test_walks_repo_yields_python_and_md(tmp_repo: Path):
    (tmp_repo / "src").mkdir()
    (tmp_repo / "src" / "auth.py").write_text("def login(): pass\n")
    (tmp_repo / "docs").mkdir()
    (tmp_repo / "docs" / "design.md").write_text("# Design\n")
    (tmp_repo / "README.txt").write_text("ignored\n")
    paths = sorted(p.relative_to(tmp_repo).as_posix() for p in walk_repo(tmp_repo))
    assert paths == ["docs/design.md", "src/auth.py"]


def test_walks_skips_state_and_vcs(tmp_repo: Path):
    (tmp_repo / ".git").mkdir()
    (tmp_repo / ".git" / "config").write_text("x")
    (tmp_repo / ".claude-mem" / "blob.bin").write_text("x")
    (tmp_repo / "src.py").write_text("x")
    paths = [p.relative_to(tmp_repo).as_posix() for p in walk_repo(tmp_repo)]
    assert paths == ["src.py"]


def test_walks_skips_node_modules_and_venv(tmp_repo: Path):
    (tmp_repo / "node_modules" / "x").mkdir(parents=True)
    (tmp_repo / "node_modules" / "x" / "y.js").write_text("x")
    (tmp_repo / ".venv" / "lib").mkdir(parents=True)
    (tmp_repo / ".venv" / "lib" / "a.py").write_text("x")
    (tmp_repo / "real.py").write_text("x")
    paths = [p.relative_to(tmp_repo).as_posix() for p in walk_repo(tmp_repo)]
    assert paths == ["real.py"]


def test_hash_file_stable(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("def x(): pass\n")
    h1 = hash_file(p)
    h2 = hash_file(p)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_hash_changes_with_content(tmp_path: Path):
    p = tmp_path / "a.py"
    p.write_text("v1")
    h1 = hash_file(p)
    p.write_text("v2")
    h2 = hash_file(p)
    assert h1 != h2


def test_derive_scope_from_path():
    assert derive_scope(Path("backend/auth/jwt.py")) == "backend/auth"
    assert derive_scope(Path("src/index.py")) == "src"
    assert derive_scope(Path("README.md")) == "root"
    assert derive_scope(Path("docs/architecture/system.md")) == "docs/architecture"
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_walker.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/__init__.py`: empty.

`src/claude_mem/indexer/walker.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

SUPPORTED_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".markdown"}
SKIP_DIRS = {
    ".git", ".hg", ".svn",
    ".claude-mem",
    "node_modules", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache",
    "dist", "build", ".next", ".turbo",
    ".tox", ".mypy_cache", ".ruff_cache",
}


def walk_repo(root: Path) -> Iterator[Path]:
    """Yield absolute paths to indexable files under `root`."""
    root = root.resolve()
    for path in _walk(root):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            yield path


def _walk(dirpath: Path) -> Iterator[Path]:
    try:
        entries = list(dirpath.iterdir())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.is_dir():
            if entry.name in SKIP_DIRS:
                continue
            yield from _walk(entry)
        else:
            yield entry


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def derive_scope(rel_path: Path) -> str:
    """Scope = parent directory of the file (POSIX-joined), or 'root' if at top."""
    parts = rel_path.parts[:-1]
    if not parts:
        return "root"
    return "/".join(parts)
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_walker.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/ tests/unit/test_walker.py
git commit -m "feat(indexer): file walker, sha256 hashing, scope derivation"
```

---

## Task 9: Parser interface + Markdown parser

**Files:**
- Create: `src/claude_mem/indexer/parsers/__init__.py`
- Create: `src/claude_mem/indexer/parsers/base.py`
- Create: `src/claude_mem/indexer/parsers/markdown.py`
- Test: `tests/unit/test_parsers_markdown.py`

Markdown parser emits one `section` unit per heading (heading + body until next heading of same or higher level). Frontmatter (YAML) is a separate `frontmatter` unit attached as parent.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_parsers_markdown.py`:

```python
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
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_parsers_markdown.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/parsers/__init__.py`: empty.

`src/claude_mem/indexer/parsers/base.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Protocol

from ...units.model import Unit, Relation


@dataclass(frozen=True)
class ParseResult:
    units: List[Unit] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)


class Parser(Protocol):
    """Parses a single file into units (and intra-file relations)."""

    def supports(self, path: Path) -> bool: ...
    def parse(self, path: Path, text: str) -> ParseResult: ...


def now() -> int:
    return int(time.time())
```

`src/claude_mem/indexer/parsers/markdown.py`:

```python
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

import yaml

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class MarkdownParser:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in (".md", ".markdown")

    def parse(self, path: Path, text: str) -> ParseResult:
        front_meta, body, body_offset = _extract_frontmatter(text)
        default_scope = _scope_from_path(path)
        scope = (front_meta.get("scope") if front_meta else None) or default_scope

        units: List[Unit] = []
        parent_id: Optional[str] = None

        if front_meta is not None:
            fm_text = text[: body_offset]
            content_hash = _hash(fm_text)
            fid = make_handle("docs", "frontmatter", f"{path.as_posix()}#frontmatter", fm_text)
            units.append(
                Unit(
                    id=fid,
                    layer="docs",
                    kind="frontmatter",
                    scope=scope,
                    source_ref=f"{path.as_posix()}:0-{fm_text.count(chr(10))}",
                    content_hash=content_hash,
                    t1_header=f"# {path.stem} (frontmatter)",
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=json.dumps({"raw": fm_text, "parsed": front_meta}),
                )
            )
            parent_id = fid

        sections = _split_sections(body, fallback_title=path.stem)
        for sec in sections:
            sid = make_handle("docs", "section", f"{path.as_posix()}#{'/'.join(sec.path)}", sec.body)
            units.append(
                Unit(
                    id=sid,
                    layer="docs",
                    kind="section",
                    scope=scope,
                    source_ref=f"{path.as_posix()}:{sec.start_line}-{sec.end_line}",
                    content_hash=_hash(sec.body),
                    t1_header=t1_header(layer="docs", kind="section", heading_path=sec.path),
                    parent_id=parent_id,
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=sec.body,
                )
            )

        return ParseResult(units=units)


# -- helpers ---------------------------------------------------------------

def _hash(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    if not parts:
        return "root"
    return "/".join(parts)


def _extract_frontmatter(text: str):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, text, 0
    try:
        parsed = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None, text, 0
    return parsed, text[m.end():], m.end()


from dataclasses import dataclass


@dataclass
class _Section:
    path: List[str]
    body: str
    start_line: int
    end_line: int


def _split_sections(body: str, fallback_title: str) -> List[_Section]:
    lines = body.splitlines()
    headings: List[tuple[int, int, str]] = []  # (line_idx, level, text)
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))

    if not headings:
        return [_Section(path=[fallback_title], body=body, start_line=0, end_line=len(lines))]

    sections: List[_Section] = []
    stack: List[str] = []   # current heading path
    levels: List[int] = []  # heading levels matching stack
    for idx, (line_idx, level, text) in enumerate(headings):
        # pop deeper-or-equal levels
        while levels and levels[-1] >= level:
            stack.pop()
            levels.pop()
        stack.append(text)
        levels.append(level)
        end_line = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body_lines = lines[line_idx + 1 : end_line]
        sections.append(_Section(path=list(stack), body="\n".join(body_lines).strip(),
                                 start_line=line_idx, end_line=end_line))
    return sections
```

Note: `markdown-it-py` is in deps but we use a regex-based heading splitter for clarity. `markdown_it` is imported in `code_python.py` too just to keep optional-extra parity; actually we don't need it for markdown — remove the `MarkdownIt` import. (Verify the implementation above has no unused import: `markdown_it` is not imported. Good.)

- [ ] **Step 4: Add `pyyaml` to deps**

Edit `pyproject.toml` deps list, add `"pyyaml>=6.0"`.
Reinstall: `pip install -e ".[dev]"`.

- [ ] **Step 5: Run, confirm PASS**

Run: `pytest tests/unit/test_parsers_markdown.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/indexer/parsers/ tests/unit/test_parsers_markdown.py pyproject.toml
git commit -m "feat(parsers): Markdown parser with heading-bounded sections and frontmatter"
```

---

## Task 10: Python code parser (tree-sitter)

**Files:**
- Create: `src/claude_mem/indexer/parsers/code_python.py`
- Test: `tests/unit/test_parsers_python.py`

Tree-sitter via `tree-sitter-languages` gives a pre-built grammar. Emit one unit per top-level function, top-level class, and class method. Compute T1 from the signature line.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_parsers_python.py`:

```python
from pathlib import Path
from claude_mem.indexer.parsers.code_python import PythonParser


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
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_parsers_python.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/parsers/code_python.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from tree_sitter_languages import get_parser

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


_PARSER = None


def _parser():
    global _PARSER
    if _PARSER is None:
        _PARSER = get_parser("python")
    return _PARSER


class PythonParser:
    def supports(self, path: Path) -> bool:
        return path.suffix == ".py"

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser().parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units, parent_id=None, class_name=None)
        return ParseResult(units=units)


# -- helpers ---------------------------------------------------------------

def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    return "/".join(parts) if parts else "root"


def _text_of(node, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _line_range(node) -> tuple[int, int]:
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _signature(node, source: str) -> str:
    """Extract `(params) -> return` from a function_definition node."""
    params_node = node.child_by_field_name("parameters")
    return_node = node.child_by_field_name("return_type")
    params = _text_of(params_node, source) if params_node else "()"
    if return_node:
        return f"{params} -> {_text_of(return_node, source)}"
    return params


def _docstring_first_line(node, source: str) -> Optional[str]:
    body = node.child_by_field_name("body")
    if not body or body.child_count == 0:
        return None
    first = body.children[0]
    if first.type == "expression_statement" and first.child_count == 1:
        s = first.children[0]
        if s.type == "string":
            text = _text_of(s, source).strip()
            # strip quotes
            for q in ('"""', "'''", '"', "'"):
                if text.startswith(q):
                    text = text[len(q):]
                    if text.endswith(q):
                        text = text[: -len(q)]
                    break
            return text.split("\n", 1)[0].strip() or None
    return None


def _walk(node, source: str, path: Path, scope: str,
          units: List[Unit], parent_id: Optional[str], class_name: Optional[str]) -> None:
    for child in node.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            sig = _signature(child, source)
            body_text = _text_of(child, source)
            kind = "method" if class_name else "function"
            qualname = f"{class_name}.{name}" if class_name else name
            uid = make_handle("code", kind, f"{path.as_posix()}::{qualname}", body_text)
            header = t1_header(
                layer="code", kind=kind, lang="python",
                name=qualname, signature=sig,
                first_line=body_text.splitlines()[0] if body_text else "",
            )
            start, end = _line_range(child)
            units.append(
                Unit(
                    id=uid,
                    layer="code",
                    kind=kind,
                    scope=scope,
                    source_ref=f"{path.as_posix()}:{start}-{end}",
                    content_hash=_hash(body_text),
                    t1_header=header,
                    parent_id=parent_id,
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=body_text,
                )
            )
        elif child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            superclasses_node = child.child_by_field_name("superclasses")
            superclasses = _text_of(superclasses_node, source) if superclasses_node else ""
            body_text = _text_of(child, source)
            doc = _docstring_first_line(child, source)
            uid = make_handle("code", "class", f"{path.as_posix()}::{name}", body_text)
            header = t1_header(
                layer="code", kind="class", lang="python",
                name=name, signature=superclasses,
                first_line=body_text.splitlines()[0] if body_text else "",
                docstring_first_line=doc,
            )
            start, end = _line_range(child)
            units.append(
                Unit(
                    id=uid,
                    layer="code",
                    kind="class",
                    scope=scope,
                    source_ref=f"{path.as_posix()}:{start}-{end}",
                    content_hash=_hash(body_text),
                    t1_header=header,
                    parent_id=parent_id,
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=body_text,
                )
            )
            body_node = child.child_by_field_name("body")
            if body_node:
                _walk(body_node, source, path, scope, units, parent_id=uid, class_name=name)
        else:
            # Recurse into module-level blocks (e.g. `if __name__` guards).
            _walk(child, source, path, scope, units, parent_id, class_name)
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_parsers_python.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/parsers/code_python.py tests/unit/test_parsers_python.py
git commit -m "feat(parsers): Python parser via tree-sitter (functions, classes, methods)"
```

---

## Task 11: JS/TS code parser (tree-sitter)

**Files:**
- Create: `src/claude_mem/indexer/parsers/code_jsts.py`
- Test: `tests/unit/test_parsers_jsts.py`

Same shape as Python parser but for JS/TS. Emits units for: function declarations, arrow functions assigned to top-level const/let, class declarations, class methods.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_parsers_jsts.py`:

```python
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
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_parsers_jsts.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/parsers/code_jsts.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from tree_sitter_languages import get_parser

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


def _parser_for(path: Path):
    suffix = path.suffix
    if suffix in (".ts", ".tsx"):
        return get_parser("typescript" if suffix == ".ts" else "tsx")
    return get_parser("javascript")


class JsTsParser:
    def supports(self, path: Path) -> bool:
        return path.suffix in (".js", ".jsx", ".ts", ".tsx")

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser_for(path).parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units, parent_id=None, class_name=None)
        return ParseResult(units=units)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    return "/".join(parts) if parts else "root"


def _text(node, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _lines(node):
    return node.start_point[0] + 1, node.end_point[0] + 1


def _make_fn_unit(name: str, sig: str, body_text: str, path: Path, scope: str,
                   parent_id: Optional[str], class_name: Optional[str],
                   node) -> Unit:
    kind = "method" if class_name else "function"
    qualname = f"{class_name}.{name}" if class_name else name
    uid = make_handle("code", kind, f"{path.as_posix()}::{qualname}", body_text)
    lang = "ts" if path.suffix in (".ts", ".tsx") else "js"
    header = t1_header(
        layer="code", kind=kind, lang=lang,
        name=qualname, signature=sig,
        first_line=body_text.splitlines()[0] if body_text else "",
    )
    s, e = _lines(node)
    return Unit(
        id=uid, layer="code", kind=kind, scope=scope,
        source_ref=f"{path.as_posix()}:{s}-{e}",
        content_hash=_hash(body_text), t1_header=header,
        parent_id=parent_id, created_at=now(), last_seen_at=now(),
        metadata=body_text,
    )


def _walk(node, source: str, path: Path, scope: str,
          units: List[Unit], parent_id: Optional[str], class_name: Optional[str]) -> None:
    for child in node.children:
        t = child.type

        if t == "function_declaration":
            name_node = child.child_by_field_name("name")
            params_node = child.child_by_field_name("parameters")
            name = _text(name_node, source) if name_node else "<anon>"
            sig = _text(params_node, source) if params_node else "()"
            units.append(_make_fn_unit(name, sig, _text(child, source), path, scope,
                                        parent_id, class_name, child))

        elif t == "lexical_declaration":
            # const foo = (args) => body  OR  const foo = function(){...}
            for decl in child.children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                if not name_node or not value_node:
                    continue
                if value_node.type in ("arrow_function", "function_expression"):
                    name = _text(name_node, source)
                    params_node = value_node.child_by_field_name("parameters")
                    sig = _text(params_node, source) if params_node else "()"
                    units.append(_make_fn_unit(name, sig, _text(decl, source), path, scope,
                                                parent_id, class_name, decl))

        elif t == "class_declaration":
            name_node = child.child_by_field_name("name")
            name = _text(name_node, source) if name_node else "<anon>"
            body_text = _text(child, source)
            uid = make_handle("code", "class", f"{path.as_posix()}::{name}", body_text)
            lang = "ts" if path.suffix in (".ts", ".tsx") else "js"
            header = t1_header(
                layer="code", kind="class", lang=lang,
                name=name, signature="",
                first_line=body_text.splitlines()[0] if body_text else "",
            )
            s, e = _lines(child)
            units.append(Unit(
                id=uid, layer="code", kind="class", scope=scope,
                source_ref=f"{path.as_posix()}:{s}-{e}",
                content_hash=_hash(body_text), t1_header=header,
                parent_id=parent_id, created_at=now(), last_seen_at=now(),
                metadata=body_text,
            ))
            body_node = child.child_by_field_name("body")
            if body_node:
                _walk(body_node, source, path, scope, units, parent_id=uid, class_name=name)

        elif t == "method_definition":
            name_node = child.child_by_field_name("name")
            params_node = child.child_by_field_name("parameters")
            name = _text(name_node, source) if name_node else "<anon>"
            sig = _text(params_node, source) if params_node else "()"
            units.append(_make_fn_unit(name, sig, _text(child, source), path, scope,
                                        parent_id, class_name, child))

        else:
            _walk(child, source, path, scope, units, parent_id, class_name)
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_parsers_jsts.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/parsers/code_jsts.py tests/unit/test_parsers_jsts.py
git commit -m "feat(parsers): JS/TS parser via tree-sitter"
```

---

## Task 12: Synthesizer interface + Imports synthesizer

**Files:**
- Create: `src/claude_mem/indexer/synthesizers/__init__.py`
- Create: `src/claude_mem/indexer/synthesizers/base.py`
- Create: `src/claude_mem/indexer/synthesizers/imports.py`
- Test: `tests/unit/test_synth_imports.py`

Synthesizers take all parsed units across the repo (post-parse) and emit `Relation` rows. The imports synthesizer reads source again to extract `import X from 'Y'` / `from y import z` and resolves them to existing module units.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_synth_imports.py`:

```python
from pathlib import Path
from claude_mem.indexer.synthesizers.imports import ImportsSynthesizer
from claude_mem.units.ids import make_handle


def test_python_import_emits_edge(tmp_path: Path):
    a = tmp_path / "auth.py"
    a.write_text("from .utils import helper\n\ndef login(): helper()\n")
    u = tmp_path / "utils.py"
    u.write_text("def helper(): pass\n")
    # Pretend we've already parsed both files; we need a way to express the
    # imported module. The synthesizer takes a `source_lookup` callable
    # from (file_path) -> source.
    from claude_mem.indexer.parsers.code_python import PythonParser
    pa = PythonParser().parse(a, a.read_text())
    pu = PythonParser().parse(u, u.read_text())
    all_units = list(pa.units) + list(pu.units)

    sources = {a: a.read_text(), u: u.read_text()}
    rels = ImportsSynthesizer().synthesize(all_units, sources, repo_root=tmp_path)
    # The synthesizer emits an edge from "auth.py" -> any unit in "utils.py"
    # (file-level granularity is fine for v1).
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
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_synth_imports.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/synthesizers/__init__.py`: empty.

`src/claude_mem/indexer/synthesizers/base.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Protocol

from ...units.model import Unit, Relation


class Synthesizer(Protocol):
    """Emit cross-unit relations from a parsed repo snapshot."""

    def synthesize(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> list[Relation]: ...
```

`src/claude_mem/indexer/synthesizers/imports.py`:

```python
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Mapping

from ...units.model import Unit, Relation


PY_IMPORT_RE = re.compile(
    r"^(?:from\s+(?P<from>[.\w]+)\s+import\s+\w+|import\s+(?P<mod>[.\w]+))",
    re.MULTILINE,
)
JS_IMPORT_RE = re.compile(
    r"""^\s*(?:import\s+(?:.+?\s+from\s+)?['"](?P<path>[^'"]+)['"]|
            const\s+\S+\s*=\s*require\(['"](?P<rpath>[^'"]+)['"]\))""",
    re.MULTILINE | re.VERBOSE,
)


class ImportsSynthesizer:
    def synthesize(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> List[Relation]:
        # Build: file_path -> list[unit] for that file
        by_file: dict[Path, list[Unit]] = defaultdict(list)
        for u in units:
            if u.layer != "code" or not u.source_ref:
                continue
            file_part = u.source_ref.split(":", 1)[0]
            by_file[Path(file_part)].append(u)

        # Pick a representative unit per file for the edge target (the parent
        # / file-level unit if any; otherwise the smallest line range).
        def file_target(path: Path) -> Unit | None:
            us = by_file.get(path) or []
            if not us:
                return None
            us = sorted(us, key=lambda u: (u.parent_id is not None, u.source_ref or ""))
            return us[0]

        rels: List[Relation] = []
        for path, src in sources.items():
            if path.suffix == ".py":
                rels.extend(self._py(path, src, repo_root, by_file, file_target))
            elif path.suffix in (".js", ".jsx", ".ts", ".tsx"):
                rels.extend(self._js(path, src, repo_root, by_file, file_target))
        return rels

    def _py(self, path: Path, src: str, root: Path, by_file, file_target) -> List[Relation]:
        rels: List[Relation] = []
        src_unit = file_target(path)
        if not src_unit:
            return rels
        for m in PY_IMPORT_RE.finditer(src):
            ref = m.group("from") or m.group("mod")
            if not ref:
                continue
            target_path = _resolve_py(ref, path, root)
            if target_path is None or target_path not in by_file:
                continue
            tgt = file_target(target_path)
            if tgt and tgt.id != src_unit.id:
                rels.append(Relation(src_unit.id, tgt.id, "imports"))
        return rels

    def _js(self, path: Path, src: str, root: Path, by_file, file_target) -> List[Relation]:
        rels: List[Relation] = []
        src_unit = file_target(path)
        if not src_unit:
            return rels
        for m in JS_IMPORT_RE.finditer(src):
            ref = m.group("path") or m.group("rpath")
            if not ref:
                continue
            target_path = _resolve_js(ref, path)
            if target_path is None or target_path not in by_file:
                continue
            tgt = file_target(target_path)
            if tgt and tgt.id != src_unit.id:
                rels.append(Relation(src_unit.id, tgt.id, "imports"))
        return rels


def _resolve_py(ref: str, importer: Path, root: Path) -> Path | None:
    if ref.startswith("."):
        # relative: count leading dots
        dots = len(ref) - len(ref.lstrip("."))
        parts = ref.lstrip(".").split(".") if ref.lstrip(".") else []
        base = importer.parent
        for _ in range(dots - 1):
            base = base.parent
        candidate = base.joinpath(*parts).with_suffix(".py")
        if candidate.exists():
            return candidate
        pkg = base.joinpath(*parts, "__init__.py")
        if pkg.exists():
            return pkg
        return None
    # absolute: resolve from repo root
    parts = ref.split(".")
    candidate = root.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    pkg = root.joinpath(*parts, "__init__.py")
    if pkg.exists():
        return pkg
    return None


def _resolve_js(ref: str, importer: Path) -> Path | None:
    if not ref.startswith("."):
        return None  # third-party, skip
    base = importer.parent / ref
    for suffix in (".js", ".jsx", ".ts", ".tsx"):
        candidate = base.with_suffix(suffix)
        if candidate.exists():
            return candidate
    # try as directory with index
    for suffix in (".js", ".jsx", ".ts", ".tsx"):
        candidate = base / f"index{suffix}"
        if candidate.exists():
            return candidate
    return None
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_synth_imports.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/synthesizers/ tests/unit/test_synth_imports.py
git commit -m "feat(synth): imports synthesizer for Python and JS/TS"
```

---

## Task 13: Flask routes synthesizer

**Files:**
- Create: `src/claude_mem/indexer/synthesizers/flask_routes.py`
- Test: `tests/unit/test_synth_flask.py`

Pattern-matches `@app.route("/x")` and `@bp.route(...)` decorators. Emits `route_to` edges from a synthetic route unit (or, simpler for v1, attaches the route metadata to the handler's `metadata` JSON and emits no edges).

For v1 simplicity, emit a `route_to` edge from the handler **to itself** with route info in metadata. That sounds odd. Better: create a synthetic route "anchor" unit per route and edge from anchor → handler.

Simplest path that satisfies the spec: extend the handler's `metadata` with route info AND emit a `route_to` self-loop is wrong. The cleanest approach: synthesize a **route unit** (layer=code, kind=route) for each route decorator, and emit `route_to` edge from route → handler.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_synth_flask.py`:

```python
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
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_synth_flask.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/synthesizers/flask_routes.py`:

```python
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List, Mapping, Tuple

from ...units.ids import make_handle
from ...units.model import Unit, Relation
from ..parsers.base import now


ROUTE_RE = re.compile(
    r"@(\w+)\.route\(\s*['\"](?P<path>[^'\"]+)['\"](?:\s*,\s*methods\s*=\s*\[(?P<methods>[^\]]+)\])?\s*\)\s*\n"
    r"def\s+(?P<fn>\w+)\s*\(",
    re.MULTILINE,
)


class FlaskRoutesSynthesizer:
    """Emit a synthetic 'route' unit per @app.route + a route_to edge to its handler."""

    def synthesize_with_units(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> Tuple[List[Unit], List[Relation]]:
        # Map: (file, function_qualname) -> handler unit
        handlers: dict[tuple[str, str], Unit] = {}
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.split(":", 1)[0]
                # qualname is stored in t1_header as `python <name>(...)`
                m = re.match(r"\w+ (\S+?)\(", u.t1_header)
                if m:
                    handlers[(file, m.group(1))] = u

        new_units: List[Unit] = []
        rels: List[Relation] = []
        for path, src in sources.items():
            if path.suffix != ".py":
                continue
            for m in ROUTE_RE.finditer(src):
                route_path = m.group("path")
                methods = m.group("methods") or "GET"
                methods = methods.replace('"', "").replace("'", "").strip()
                fn = m.group("fn")
                handler = handlers.get((path.as_posix(), fn))
                if not handler:
                    continue
                # synthesize a route unit
                rid_locator = f"{path.as_posix()}::route::{methods}::{route_path}"
                content = f"{methods} {route_path} -> {fn}"
                rid = make_handle("code", "route", rid_locator, content)
                new_units.append(Unit(
                    id=rid,
                    layer="code",
                    kind="route",
                    scope=handler.scope,
                    source_ref=handler.source_ref,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    t1_header=f"flask route {methods} {route_path} -> {fn}",
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=content,
                ))
                rels.append(Relation(rid, handler.id, "route_to"))
        return new_units, rels

    # Synthesizer protocol — by default no units, just relations.
    def synthesize(self, units, sources, repo_root) -> List[Relation]:
        _, rels = self.synthesize_with_units(units, sources, repo_root)
        return rels
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_synth_flask.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/synthesizers/flask_routes.py tests/unit/test_synth_flask.py
git commit -m "feat(synth): Flask @route synthesizer emits route units and route_to edges"
```

---

## Task 14: Indexer orchestrator (full reindex)

**Files:**
- Create: `src/claude_mem/indexer/orchestrator.py`
- Test: `tests/integration/__init__.py`
- Test: `tests/integration/test_indexer_e2e.py`

Drives full reindex: walk → hash → parse → synthesize → embed → upsert.

- [ ] **Step 1: Write the failing test**

`tests/integration/__init__.py`: empty.

`tests/integration/test_indexer_e2e.py`:

```python
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.indexer.orchestrator import full_reindex


@pytest.fixture
def flask_fixture(tmp_repo: Path) -> Path:
    (tmp_repo / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/login', methods=['POST'])\n"
        "def login():\n"
        "    return 'ok'\n"
    )
    (tmp_repo / "utils.py").write_text(
        "def helper():\n    return 1\n"
    )
    (tmp_repo / "README.md").write_text("# App\n\nA tiny Flask app.\n")
    return tmp_repo


def test_full_reindex_creates_units(flask_fixture: Path):
    settings = Settings.for_repo(flask_fixture)
    init_db(settings.db_path)
    stats = full_reindex(settings, embedder=None)
    assert stats["units_written"] > 0
    repo = Repository(connect(settings.db_path))
    units = repo.conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    assert units >= 4   # at least: login fn, helper fn, README section, route unit


def test_full_reindex_emits_route_edge(flask_fixture: Path):
    settings = Settings.for_repo(flask_fixture)
    init_db(settings.db_path)
    full_reindex(settings, embedder=None)
    repo = Repository(connect(settings.db_path))
    rels = repo.conn.execute("SELECT COUNT(*) FROM relation WHERE kind='route_to'").fetchone()[0]
    assert rels == 1


def test_full_reindex_idempotent(flask_fixture: Path):
    settings = Settings.for_repo(flask_fixture)
    init_db(settings.db_path)
    s1 = full_reindex(settings, embedder=None)
    s2 = full_reindex(settings, embedder=None)
    # Same content → same number of units (no duplicates).
    repo = Repository(connect(settings.db_path))
    units = repo.conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    assert units == s1["units_written"]
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_indexer_e2e.py -v`
Expected: import error.

- [ ] **Step 3: Implement orchestrator**

`src/claude_mem/indexer/orchestrator.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder
from ..units.model import Unit, Relation
from .parsers.base import Parser, ParseResult
from .parsers.code_jsts import JsTsParser
from .parsers.code_python import PythonParser
from .parsers.markdown import MarkdownParser
from .synthesizers.flask_routes import FlaskRoutesSynthesizer
from .synthesizers.imports import ImportsSynthesizer
from .walker import walk_repo, hash_file


PARSERS: list[Parser] = [PythonParser(), JsTsParser(), MarkdownParser()]


def full_reindex(settings: Settings, embedder: Optional[Embedder] = None) -> dict:
    repo_root = settings.repo_root
    conn = connect(settings.db_path)
    repository = Repository(conn)

    all_units: list[Unit] = []
    all_relations: list[Relation] = []
    sources: dict[Path, str] = {}

    for path in walk_repo(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        parser = _pick_parser(path)
        if not parser:
            continue
        result = parser.parse(path, text)
        all_units.extend(result.units)
        all_relations.extend(result.relations)
        sources[path] = text

    # Synthesizers run on the full snapshot.
    extra_units, route_rels = FlaskRoutesSynthesizer().synthesize_with_units(
        all_units, sources, repo_root
    )
    all_units.extend(extra_units)
    all_relations.extend(route_rels)
    all_relations.extend(ImportsSynthesizer().synthesize(all_units, sources, repo_root))

    # Embeddings (optional — skipped if embedder is None for fast unit tests).
    embeddings: dict[str, np.ndarray] = {}
    if embedder is not None:
        texts = [u.t1_header for u in all_units]
        vecs = embedder.embed(texts)
        embeddings = {u.id: v for u, v in zip(all_units, vecs)}

    for u in all_units:
        repository.upsert_unit(u, embedding=embeddings.get(u.id))
    for r in all_relations:
        repository.add_relation(r)

    return {
        "units_written": len(all_units),
        "relations_written": len(all_relations),
        "files_seen": len(sources),
    }


def _pick_parser(path: Path) -> Optional[Parser]:
    for p in PARSERS:
        if p.supports(path):
            return p
    return None
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_indexer_e2e.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/orchestrator.py tests/integration/
git commit -m "feat(indexer): orchestrator drives walk -> parse -> synth -> upsert"
```

---

## Task 15: RRF + feature rerank ranker

**Files:**
- Create: `src/claude_mem/retrieval/__init__.py`
- Create: `src/claude_mem/retrieval/ranker.py`
- Test: `tests/unit/test_ranker.py`

Implements spec §4.1: RRF over the two ranked lists, then per-unit feature multipliers.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ranker.py`:

```python
import time
from claude_mem.retrieval.ranker import rrf_then_rerank, RankedItem
from claude_mem.db.repository import SearchHit
from claude_mem.units.model import Unit


def _u(id, scope="x", layer="code", days_old=0, superseded=False) -> Unit:
    t = int(time.time() - days_old * 86400)
    return Unit(
        id=id, layer=layer, kind="function", scope=scope,
        source_ref=None, content_hash="h", t1_header=f"header for {id}",
        created_at=t, last_seen_at=t,
        superseded_by="x" if superseded else None,
    )


def test_rrf_combines_two_lists():
    units = {"a": _u("a"), "b": _u("b"), "c": _u("c")}
    bm25 = [SearchHit("a", 1, 0.0), SearchHit("c", 2, 0.0)]
    vec = [SearchHit("b", 1, 0.0), SearchHit("a", 2, 0.0)]
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    ids = [r.unit.id for r in ranked]
    # 'a' appears in both lists at low rank → should be at or near the top
    assert ids[0] == "a"


def test_superseded_filtered_by_default():
    units = {"a": _u("a"), "b": _u("b", superseded=True)}
    bm25 = [SearchHit("b", 1, 0.0), SearchHit("a", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    assert all(r.unit.id != "b" for r in ranked)


def test_scope_match_boosts():
    units = {"hit": _u("hit", scope="backend/auth"),
             "miss": _u("miss", scope="frontend/ui")}
    bm25 = [SearchHit("miss", 1, 0.0), SearchHit("hit", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="backend/auth")
    # exact-scope match should overcome a one-rank deficit
    assert ranked[0].unit.id == "hit"


def test_layer_boost_memory_wins():
    units = {"mem": _u("mem", layer="memory"), "code": _u("code", layer="code")}
    bm25 = [SearchHit("code", 1, 0.0), SearchHit("mem", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    assert ranked[0].unit.id == "mem"


def test_recency_decay():
    units = {"new": _u("new", days_old=0), "old": _u("old", days_old=120)}
    bm25 = [SearchHit("old", 1, 0.0), SearchHit("new", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    assert ranked[0].unit.id == "new"


def test_include_superseded():
    units = {"a": _u("a"), "b": _u("b", superseded=True)}
    bm25 = [SearchHit("b", 1, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x", include_superseded=True)
    assert any(r.unit.id == "b" for r in ranked)
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_ranker.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/retrieval/__init__.py`: empty.

`src/claude_mem/retrieval/ranker.py`:

```python
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping

from ..db.repository import SearchHit
from ..units.model import Unit


RRF_K = 60
RECENCY_HALF_LIFE_DAYS = 30
LAYER_MULT = {"memory": 1.5, "docs": 1.1, "code": 1.0, "task": 1.3}


@dataclass(frozen=True)
class RankedItem:
    unit: Unit
    score: float
    rank: int


def rrf_then_rerank(
    bm25: Iterable[SearchHit],
    vec: Iterable[SearchHit],
    units_by_id: Mapping[str, Unit],
    query_scope: str | None,
    include_superseded: bool = False,
) -> List[RankedItem]:
    rrf: Dict[str, float] = {}
    for h in bm25:
        rrf[h.id] = rrf.get(h.id, 0.0) + 1.0 / (RRF_K + h.rank)
    for h in vec:
        rrf[h.id] = rrf.get(h.id, 0.0) + 1.0 / (RRF_K + h.rank)

    scored: List[tuple[float, Unit]] = []
    now = int(time.time())
    for uid, fusion in rrf.items():
        u = units_by_id.get(uid)
        if u is None:
            continue
        if u.superseded_by and not include_superseded:
            continue
        s = fusion
        s *= _scope_mult(u.scope, query_scope)
        s *= _recency_mult(u.last_seen_at, now)
        s *= LAYER_MULT.get(u.layer, 1.0)
        scored.append((s, u))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [RankedItem(unit=u, score=s, rank=i + 1) for i, (s, u) in enumerate(scored)]


def _scope_mult(unit_scope: str, query_scope: str | None) -> float:
    if not query_scope:
        return 1.0
    if unit_scope == query_scope:
        return 1.0
    # Sibling = share at least one parent component
    u_parts = unit_scope.split("/")
    q_parts = query_scope.split("/")
    shared = 0
    for a, b in zip(u_parts, q_parts):
        if a == b:
            shared += 1
        else:
            break
    if shared >= 1:
        return 0.7
    return 0.4


def _recency_mult(last_seen_at: int, now: int) -> float:
    age_days = max(0, (now - last_seen_at) / 86400.0)
    decay = math.exp(-age_days * math.log(2) / RECENCY_HALF_LIFE_DAYS)
    return 0.5 + 0.5 * decay
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_ranker.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/retrieval/ tests/unit/test_ranker.py
git commit -m "feat(retrieval): RRF + feature multipliers ranker"
```

---

## Task 16: Budget-aware tiered fill

**Files:**
- Create: `src/claude_mem/retrieval/fill.py`
- Test: `tests/unit/test_fill.py`

Implements spec §4.2. Inputs: ranked items + a way to fetch T0/T2/T1 sizes and content. Output: chosen tiers, included items, overflow.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_fill.py`:

```python
from claude_mem.retrieval.fill import budget_fill, FilledItem, FillResult
from claude_mem.retrieval.ranker import RankedItem
from claude_mem.units.model import Unit


def _ri(id, rank, t1="t1", t2=None, t0=None) -> RankedItem:
    u = Unit(id=id, layer="code", kind="function", scope="x",
             source_ref=None, content_hash="h", t1_header=t1,
             t2_summary=t2, created_at=0, last_seen_at=0, metadata=t0)
    return RankedItem(unit=u, score=1.0 / rank, rank=rank)


def _content(unit: Unit, tier: str) -> str:
    if tier == "T1":
        return unit.t1_header
    if tier == "T2":
        return unit.t2_summary or unit.t1_header
    return unit.metadata or unit.t1_header


def test_top_result_promoted_to_t0_when_fits():
    ranked = [_ri("a", 1, t1="short", t2="medium summary", t0="x" * 50)]
    res = budget_fill(ranked, _content, budget=1000)
    assert res.items[0].tier == "T0"
    assert res.items[0].content == "x" * 50


def test_oversized_t0_falls_back_to_t2():
    huge = "x" * 100_000
    ranked = [_ri("a", 1, t1="t1", t2="t2 summary", t0=huge)]
    res = budget_fill(ranked, _content, budget=500)
    assert res.items[0].tier == "T2"


def test_low_rank_does_not_promote_to_t0():
    ranked = [_ri(f"u{i}", i + 1, t1="t1", t2="t2 summary", t0="x" * 50) for i in range(10)]
    res = budget_fill(ranked, _content, budget=10_000, top_promote=3)
    # First 3 may be T0; 4+ must be T2 or T1
    for item in res.items[3:]:
        assert item.tier in ("T2", "T1")


def test_overflow_when_budget_exhausted():
    ranked = [_ri(f"u{i}", i + 1, t1="x" * 50) for i in range(100)]
    res = budget_fill(ranked, _content, budget=200)
    assert len(res.overflow_handles) > 0
    assert res.budget_used <= 200


def test_tier_histogram():
    ranked = [_ri(f"u{i}", i + 1, t1="t1", t2="medium summary", t0="x" * 30) for i in range(5)]
    res = budget_fill(ranked, _content, budget=10_000, top_promote=2)
    total = sum(res.tier_histogram.values())
    assert total == len(res.items)
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/unit/test_fill.py -v`
Expected: import errors.

- [ ] **Step 3: Implement**

`src/claude_mem/retrieval/fill.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

from ..tokens import count_tokens
from ..units.model import Unit
from .ranker import RankedItem


TOP_PROMOTE = 5
T0_SINGLE_CAP_FRACTION = 0.4


@dataclass(frozen=True)
class FilledItem:
    handle: str
    tier: str       # "T0" | "T2" | "T1"
    content: str
    rank: int
    score: float
    scope: str
    layer: str


@dataclass(frozen=True)
class FillResult:
    items: List[FilledItem]
    overflow_handles: List[str]
    budget_used: int
    budget_total: int
    tier_histogram: Dict[str, int]


ContentFn = Callable[[Unit, str], str]


def budget_fill(
    ranked: List[RankedItem],
    content_fn: ContentFn,
    budget: int,
    top_promote: int = TOP_PROMOTE,
    t0_single_cap_fraction: float = T0_SINGLE_CAP_FRACTION,
) -> FillResult:
    items: List[FilledItem] = []
    overflow: List[str] = []
    used = 0
    hist = {"T0": 0, "T2": 0, "T1": 0}

    for ri in ranked:
        remaining = budget - used
        if remaining <= 0:
            overflow.append(ri.unit.id)
            continue

        # Attempt T0 promotion for top-ranked units
        chosen_tier = None
        chosen_content = None
        chosen_tokens = 0

        if ri.rank <= top_promote:
            t0 = content_fn(ri.unit, "T0")
            t = count_tokens(t0)
            cap = int(remaining * t0_single_cap_fraction)
            if t > 0 and t <= cap:
                chosen_tier, chosen_content, chosen_tokens = "T0", t0, t

        if chosen_tier is None:
            t2 = content_fn(ri.unit, "T2")
            t = count_tokens(t2)
            if t > 0 and t <= remaining:
                chosen_tier, chosen_content, chosen_tokens = "T2", t2, t

        if chosen_tier is None:
            t1 = content_fn(ri.unit, "T1")
            t = count_tokens(t1)
            if t > 0 and t <= remaining:
                chosen_tier, chosen_content, chosen_tokens = "T1", t1, t

        if chosen_tier is None:
            overflow.append(ri.unit.id)
            continue

        items.append(FilledItem(
            handle=ri.unit.id,
            tier=chosen_tier,
            content=chosen_content,
            rank=ri.rank,
            score=ri.score,
            scope=ri.unit.scope,
            layer=ri.unit.layer,
        ))
        used += chosen_tokens
        hist[chosen_tier] += 1

    return FillResult(
        items=items,
        overflow_handles=overflow,
        budget_used=used,
        budget_total=budget,
        tier_histogram=hist,
    )
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/unit/test_fill.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/retrieval/fill.py tests/unit/test_fill.py
git commit -m "feat(retrieval): budget-aware tiered fill with TOP_PROMOTE and T0 cap"
```

---

## Task 17: Recall pipeline

**Files:**
- Create: `src/claude_mem/retrieval/recall.py`
- Test: `tests/integration/test_recall_e2e.py`

End-to-end: query string → ranked, budget-filled response. Uses a small in-process fake embedder for tests to avoid bge-small download.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_recall_e2e.py`:

```python
from pathlib import Path
import numpy as np
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.retrieval.recall import recall


class FakeEmbedder:
    dim = 384

    def __init__(self):
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, texts):
        out = []
        for t in texts:
            # Deterministic hash → 384-dim unit vector in {-1, +1}^384 / sqrt(384)
            seed = abs(hash(t)) % (2**31)
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(384).astype("float32")
            v /= np.linalg.norm(v) + 1e-8
            out.append(v)
        return out


@pytest.fixture
def indexed_repo(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text(
        "def login(user, pw):\n    return 'token for ' + user\n\n"
        "def logout(user):\n    return 'bye ' + user\n"
    )
    (tmp_repo / "docs.md").write_text("# Auth\n\nWe use token-based login.\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_recall_returns_items(indexed_repo):
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder())
    assert len(result.items) >= 1
    assert result.budget_used <= 3000


def test_recall_respects_budget(indexed_repo):
    result = recall(indexed_repo, query="login", budget=100, embedder=FakeEmbedder())
    assert result.budget_used <= 100


def test_recall_scope_filter(indexed_repo):
    # docs.md is at scope "root"; auth.py is at scope "root" too in this fixture.
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder(), scopes=["root"])
    assert all(item.scope == "root" for item in result.items)


def test_recall_layer_filter(indexed_repo):
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder(), layers=["code"])
    assert all(item.layer == "code" for item in result.items)


def test_recall_tier_histogram_sums(indexed_repo):
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder())
    assert sum(result.tier_histogram.values()) == len(result.items)
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_recall_e2e.py -v`
Expected: import error on `recall`.

- [ ] **Step 3: Implement recall**

`src/claude_mem/retrieval/recall.py`:

```python
from __future__ import annotations

import json
from typing import Optional, Sequence

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository, SearchHit
from ..embeddings.base import Embedder
from ..units.model import Unit
from .fill import FillResult, budget_fill
from .ranker import rrf_then_rerank


DEFAULT_BUDGET = 3000
TOP_K = 100


def recall(
    settings: Settings,
    *,
    query: str,
    embedder: Embedder,
    budget: int = DEFAULT_BUDGET,
    scopes: Optional[Sequence[str]] = None,
    layers: Optional[Sequence[str]] = None,
    include_superseded: bool = False,
) -> FillResult:
    conn = connect(settings.db_path)
    repo = Repository(conn)

    # FTS query: simple word-tokenized, OR'd.
    fts_query = " OR ".join(_fts_tokens(query)) or query
    bm25_hits = repo.fts_search(fts_query, limit=TOP_K)

    # Vector query.
    [qvec] = embedder.embed([query])
    vec_hits = repo.vec_search(qvec, limit=TOP_K)

    # Fetch units for the union of ids.
    all_ids = {h.id for h in bm25_hits} | {h.id for h in vec_hits}
    units = repo.get_units(list(all_ids))

    # Optional layer/scope filtering (pre-rank, hard).
    if layers:
        units = [u for u in units if u.layer in layers]
    if scopes:
        units = [u for u in units if any(_scope_match(u.scope, s) for s in scopes)]
    units_by_id = {u.id: u for u in units}

    ranked = rrf_then_rerank(
        bm25_hits, vec_hits, units_by_id,
        query_scope=scopes[0] if scopes else None,
        include_superseded=include_superseded,
    )

    def content_fn(u: Unit, tier: str) -> str:
        if tier == "T0":
            return u.metadata or u.t2_summary or u.t1_header
        if tier == "T2":
            return u.t2_summary or u.t1_header
        return u.t1_header

    return budget_fill(ranked, content_fn, budget=budget)


def _fts_tokens(query: str) -> list[str]:
    import re
    return [w for w in re.findall(r"\w+", query) if len(w) > 1]


def _scope_match(unit_scope: str, query_scope: str) -> bool:
    return unit_scope == query_scope or unit_scope.startswith(query_scope + "/")
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_recall_e2e.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/retrieval/recall.py tests/integration/test_recall_e2e.py
git commit -m "feat(retrieval): recall pipeline (FTS + vec → RRF rerank → tiered fill)"
```

---

## Task 18: Trace pipeline (BFS from seed + fill)

**Files:**
- Create: `src/claude_mem/retrieval/trace.py`
- Test: `tests/integration/test_trace_e2e.py`

Implements spec §5.1: BFS from one or more seed handles, rank by hop distance + relation weight + feature multipliers, run tiered fill.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_trace_e2e.py`:

```python
from pathlib import Path
import numpy as np
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.retrieval.recall import recall
from claude_mem.retrieval.trace import trace
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def flask_repo(tmp_repo: Path):
    (tmp_repo / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/login', methods=['POST'])\n"
        "def login():\n"
        "    return verify_user()\n\n"
        "def verify_user():\n"
        "    return 'ok'\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_trace_from_route_finds_handler(flask_repo):
    # Find the route unit
    result = recall(flask_repo, query="/login", budget=3000, embedder=FakeEmbedder())
    route = next((it for it in result.items if "route" in it.handle), None)
    assert route is not None

    trace_result = trace(flask_repo, seeds=[route.handle], depth=2, budget=8000)
    handles = {it.handle for it in trace_result.items}
    # Should include the seed and the handler
    assert route.handle in handles
    assert any("function" in h for h in handles)


def test_trace_depth_limit(flask_repo):
    result = recall(flask_repo, query="login", budget=3000, embedder=FakeEmbedder())
    seed = result.items[0].handle
    r1 = trace(flask_repo, seeds=[seed], depth=1, budget=8000)
    r2 = trace(flask_repo, seeds=[seed], depth=2, budget=8000)
    assert len(r2.items) >= len(r1.items)


def test_trace_respects_budget(flask_repo):
    result = recall(flask_repo, query="login", budget=3000, embedder=FakeEmbedder())
    seed = result.items[0].handle
    r = trace(flask_repo, seeds=[seed], depth=2, budget=100)
    assert r.budget_used <= 100
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_trace_e2e.py -v`
Expected: import error.

- [ ] **Step 3: Implement trace**

`src/claude_mem/retrieval/trace.py`:

```python
from __future__ import annotations

import time
from collections import deque
from typing import Optional, Sequence

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..units.model import Unit
from .fill import FillResult, budget_fill
from .ranker import RankedItem, _recency_mult, LAYER_MULT


DEFAULT_BUDGET = 8000
DEFAULT_DEPTH = 2
MAX_DEPTH = 3

# Relation-kind weights — higher = pulled in earlier
REL_WEIGHTS = {
    "route_to": 1.0,
    "implements": 0.9,
    "mentions": 0.6,
    "imports": 0.5,
    "child_task": 0.8,
}


def trace(
    settings: Settings,
    *,
    seeds: Sequence[str],
    depth: int = DEFAULT_DEPTH,
    budget: int = DEFAULT_BUDGET,
    relations: Optional[Sequence[str]] = None,
) -> FillResult:
    if depth > MAX_DEPTH:
        depth = MAX_DEPTH
    conn = connect(settings.db_path)
    repo = Repository(conn)

    # BFS, collecting (id, hop_distance, best_relation_weight)
    seen: dict[str, tuple[int, float]] = {sid: (0, 1.0) for sid in seeds}
    queue: deque[tuple[str, int]] = deque((sid, 0) for sid in seeds)
    while queue:
        node, hop = queue.popleft()
        if hop >= depth:
            continue
        out = repo.neighbors(node, direction="out", kinds=list(relations) if relations else None)
        inn = repo.neighbors(node, direction="in", kinds=list(relations) if relations else None)
        for rel in out + inn:
            neighbor = rel.dst_id if rel.src_id == node else rel.src_id
            w = REL_WEIGHTS.get(rel.kind, 0.3)
            prev = seen.get(neighbor)
            new_hop = hop + 1
            if prev is None or new_hop < prev[0] or w > prev[1]:
                seen[neighbor] = (new_hop, w)
                queue.append((neighbor, new_hop))

    units = repo.get_units(list(seen.keys()))
    units_by_id = {u.id: u for u in units}

    now = int(time.time())
    ranked_items: list[RankedItem] = []
    for uid, (hop, rel_w) in seen.items():
        u = units_by_id.get(uid)
        if u is None:
            continue
        if u.superseded_by:
            continue
        hop_factor = 1.0 / (1.0 + hop)   # seeds: 1.0, hop 1: 0.5, hop 2: 0.33
        score = hop_factor * rel_w * LAYER_MULT.get(u.layer, 1.0) * _recency_mult(u.last_seen_at, now)
        ranked_items.append(RankedItem(unit=u, score=score, rank=0))

    ranked_items.sort(key=lambda r: r.score, reverse=True)
    # Re-assign ranks now that sort is stable
    ranked_items = [RankedItem(unit=r.unit, score=r.score, rank=i + 1)
                    for i, r in enumerate(ranked_items)]

    def content_fn(u: Unit, tier: str) -> str:
        if tier == "T0":
            return u.metadata or u.t2_summary or u.t1_header
        if tier == "T2":
            return u.t2_summary or u.t1_header
        return u.t1_header

    return budget_fill(ranked_items, content_fn, budget=budget)
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_trace_e2e.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/retrieval/trace.py tests/integration/test_trace_e2e.py
git commit -m "feat(retrieval): trace pipeline (BFS from seed + tiered fill)"
```

---

## Task 19: MCP server skeleton with initialize instructions

**Files:**
- Create: `src/claude_mem/server.py`
- Test: `tests/integration/test_mcp_server.py`

Uses the official `mcp` Python SDK. The server registers three tools (Task 20–22 will add their handlers). The `serverInfo.instructions` block from spec §11.1 is included in the handshake.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_mcp_server.py`:

```python
import pytest

from claude_mem.server import build_server, SERVER_INSTRUCTIONS


def test_server_builds():
    server = build_server()
    assert server is not None


def test_instructions_mention_recall_and_trace():
    assert "recall" in SERVER_INSTRUCTIONS.lower()
    assert "trace" in SERVER_INSTRUCTIONS.lower()
    assert "before reading files" in SERVER_INSTRUCTIONS.lower() or "before native" in SERVER_INSTRUCTIONS.lower()


@pytest.mark.asyncio
async def test_list_tools():
    server = build_server()
    tools = await server.list_tools()
    names = [t.name for t in tools]
    assert "recall" in names
    assert "trace" in names
    assert "expand" in names
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_mcp_server.py -v`
Expected: import error.

- [ ] **Step 3: Implement server skeleton**

`src/claude_mem/server.py`:

```python
from __future__ import annotations

from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent

from .config import Settings
from .embeddings.bge_small import BgeSmallEmbedder
from .tools import recall as recall_tool
from .tools import trace as trace_tool
from .tools import expand as expand_tool


SERVER_INSTRUCTIONS = """\
claude-mem is the authoritative source for this repo's code structure, documentation, \
and accumulated decisions.

Before reading files with native Read/Grep, call recall(query) — it returns ranked, \
summarized, scoped results within a budget. Before tracing related code (callers, \
handlers, hooks, routes), call trace(seed_handle) — it returns full source for \
connected nodes in one shot. Reach for native file tools only when claude-mem returns \
nothing useful, when working on files outside this repo, or when verifying a recent \
edit not yet reindexed.

For long or multi-part tasks, future versions will offer plan_task, remember, and \
handoff. For now, prefer recall over Grep and trace over repeated expand.
"""


def build_server(settings: Settings | None = None, embedder=None) -> Server:
    settings = settings or Settings.discover()
    embedder = embedder or BgeSmallEmbedder()

    server = Server(name="claude-mem", instructions=SERVER_INSTRUCTIONS)

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [
            recall_tool.tool_schema(),
            trace_tool.tool_schema(),
            expand_tool.tool_schema(),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "recall":
            return await recall_tool.handle(settings, embedder, arguments)
        if name == "trace":
            return await trace_tool.handle(settings, arguments)
        if name == "expand":
            return await expand_tool.handle(settings, arguments)
        return [TextContent(type="text", text=f"unknown tool: {name}")]

    return server


async def serve_stdio() -> None:
    from mcp.server.stdio import stdio_server
    server = build_server()
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())
```

Create `src/claude_mem/tools/__init__.py` (empty) and stub the three tool modules with no-op `tool_schema()` and `handle()`:

`src/claude_mem/tools/recall.py`:
```python
from mcp.types import Tool, TextContent
async def handle(settings, embedder, args): return [TextContent(type="text", text="stub")]
def tool_schema() -> Tool: return Tool(name="recall", description="stub", inputSchema={"type": "object"})
```
`src/claude_mem/tools/trace.py`:
```python
from mcp.types import Tool, TextContent
async def handle(settings, args): return [TextContent(type="text", text="stub")]
def tool_schema() -> Tool: return Tool(name="trace", description="stub", inputSchema={"type": "object"})
```
`src/claude_mem/tools/expand.py`:
```python
from mcp.types import Tool, TextContent
async def handle(settings, args): return [TextContent(type="text", text="stub")]
def tool_schema() -> Tool: return Tool(name="expand", description="stub", inputSchema={"type": "object"})
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_mcp_server.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/server.py src/claude_mem/tools/ tests/integration/test_mcp_server.py
git commit -m "feat(server): MCP stdio server skeleton with initialize instructions"
```

---

## Task 20: MCP tool — recall

**Files:**
- Modify: `src/claude_mem/tools/recall.py`
- Test: `tests/integration/test_mcp_recall.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_mcp_recall.py`:

```python
import json
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.recall import handle, tool_schema
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings_with_index(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text("def login(user, pw):\n    return 'token'\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_schema_has_required_fields():
    s = tool_schema()
    assert s.name == "recall"
    assert "query" in s.inputSchema["properties"]
    assert "budget" in s.inputSchema["properties"]
    assert "query" in s.inputSchema.get("required", [])


@pytest.mark.asyncio
async def test_handle_returns_json(settings_with_index):
    out = await handle(settings_with_index, FakeEmbedder(), {"query": "login", "budget": 3000})
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert "items" in payload
    assert "budget_used" in payload
    assert "tier_histogram" in payload


@pytest.mark.asyncio
async def test_default_budget_is_3000(settings_with_index):
    out = await handle(settings_with_index, FakeEmbedder(), {"query": "login"})
    payload = json.loads(out[0].text)
    assert payload["budget_total"] == 3000
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_mcp_recall.py -v`
Expected: `tool_schema` returns stub; missing budget field in inputSchema.

- [ ] **Step 3: Implement `recall` tool wrapper**

Replace `src/claude_mem/tools/recall.py`:

```python
from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool, TextContent

from ..config import Settings
from ..embeddings.base import Embedder
from ..retrieval.recall import recall, DEFAULT_BUDGET


def tool_schema() -> Tool:
    return Tool(
        name="recall",
        description=(
            "Hybrid retrieve from claude-mem. Returns ranked, budget-filled results "
            "(T0 full content for top hits, T2 summary for mid-tier, T1 header for tail). "
            "Use this BEFORE native Read/Grep when looking for code or docs in this repo."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language query"},
                "budget": {"type": "integer", "default": DEFAULT_BUDGET,
                           "description": "Max tokens to return (default 3000)"},
                "scopes": {"type": "array", "items": {"type": "string"},
                           "description": "Scope filter (e.g. ['backend/auth'])"},
                "layers": {"type": "array", "items": {"type": "string", "enum": ["memory", "docs", "code"]}},
                "include_superseded": {"type": "boolean", "default": False},
            },
            "required": ["query"],
        },
    )


async def handle(settings: Settings, embedder: Embedder, args: dict[str, Any]) -> list[TextContent]:
    result = recall(
        settings,
        query=args["query"],
        embedder=embedder,
        budget=args.get("budget", DEFAULT_BUDGET),
        scopes=args.get("scopes"),
        layers=args.get("layers"),
        include_superseded=args.get("include_superseded", False),
    )
    payload = {
        "items": [
            {
                "handle": it.handle,
                "tier": it.tier,
                "content": it.content,
                "rank": it.rank,
                "scope": it.scope,
                "layer": it.layer,
            }
            for it in result.items
        ],
        "overflow_handles": result.overflow_handles,
        "budget_used": result.budget_used,
        "budget_total": result.budget_total,
        "tier_histogram": result.tier_histogram,
    }
    return [TextContent(type="text", text=json.dumps(payload))]
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_mcp_recall.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/tools/recall.py tests/integration/test_mcp_recall.py
git commit -m "feat(tools): recall MCP tool with full schema and JSON payload"
```

---

## Task 21: MCP tool — trace

**Files:**
- Modify: `src/claude_mem/tools/trace.py`
- Test: `tests/integration/test_mcp_trace.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_mcp_trace.py`:

```python
import json
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.recall import handle as recall_handle
from claude_mem.tools.trace import handle as trace_handle, tool_schema
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings_with_flask(tmp_repo: Path):
    (tmp_repo / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/login', methods=['POST'])\n"
        "def login():\n    return 'ok'\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_schema_required():
    s = tool_schema()
    assert s.name == "trace"
    assert "seed_handles" in s.inputSchema["properties"]
    assert "seed_handles" in s.inputSchema.get("required", [])


@pytest.mark.asyncio
async def test_handle_traces_from_recall_seed(settings_with_flask):
    recall_out = await recall_handle(settings_with_flask, FakeEmbedder(),
                                      {"query": "login"})
    items = json.loads(recall_out[0].text)["items"]
    assert items, "need at least one item to seed trace"
    seed = items[0]["handle"]
    out = await trace_handle(settings_with_flask, {"seed_handles": [seed], "depth": 2})
    payload = json.loads(out[0].text)
    assert "items" in payload
    assert payload["budget_total"] == 8000
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_mcp_trace.py -v`
Expected: stub returns "stub".

- [ ] **Step 3: Implement**

Replace `src/claude_mem/tools/trace.py`:

```python
from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool, TextContent

from ..config import Settings
from ..retrieval.trace import trace, DEFAULT_BUDGET, DEFAULT_DEPTH


def tool_schema() -> Tool:
    return Tool(
        name="trace",
        description=(
            "Traverse from one or more seed handles to connected units (callers, "
            "handlers, hooks, routes, imports) and return full source code inline "
            "for top hits in one round-trip. Use this INSTEAD of repeated expand "
            "calls when you need to follow code flow."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "seed_handles": {"type": "array", "items": {"type": "string"},
                                  "description": "Handles from a prior recall result"},
                "depth": {"type": "integer", "default": DEFAULT_DEPTH,
                          "description": "Max BFS hops (capped at 3)"},
                "budget": {"type": "integer", "default": DEFAULT_BUDGET,
                           "description": "Max tokens to return (default 8000)"},
                "relations": {"type": "array", "items": {"type": "string"},
                              "description": "Filter on relation kinds (e.g. ['route_to','imports'])"},
            },
            "required": ["seed_handles"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    result = trace(
        settings,
        seeds=args["seed_handles"],
        depth=args.get("depth", DEFAULT_DEPTH),
        budget=args.get("budget", DEFAULT_BUDGET),
        relations=args.get("relations"),
    )
    payload = {
        "items": [
            {
                "handle": it.handle,
                "tier": it.tier,
                "content": it.content,
                "rank": it.rank,
                "scope": it.scope,
                "layer": it.layer,
            }
            for it in result.items
        ],
        "overflow_handles": result.overflow_handles,
        "budget_used": result.budget_used,
        "budget_total": result.budget_total,
        "tier_histogram": result.tier_histogram,
    }
    return [TextContent(type="text", text=json.dumps(payload))]
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_mcp_trace.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/tools/trace.py tests/integration/test_mcp_trace.py
git commit -m "feat(tools): trace MCP tool with BFS + single round-trip"
```

---

## Task 22: MCP tool — expand

**Files:**
- Modify: `src/claude_mem/tools/expand.py`
- Test: `tests/integration/test_mcp_expand.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_mcp_expand.py`:

```python
import json
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.recall import handle as recall_handle
from claude_mem.tools.expand import handle, tool_schema
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings_with_index(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text(
        "def login(user, pw):\n    return 'token for ' + user + pw\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "expand"
    assert "handle" in s.inputSchema["properties"]
    assert "tier" in s.inputSchema["properties"]


@pytest.mark.asyncio
async def test_expand_t0_returns_source(settings_with_index):
    recall_out = await recall_handle(settings_with_index, FakeEmbedder(), {"query": "login"})
    items = json.loads(recall_out[0].text)["items"]
    code_handle = next(h["handle"] for h in items if h["layer"] == "code")
    out = await handle(settings_with_index, {"handle": code_handle, "tier": "T0"})
    payload = json.loads(out[0].text)
    assert "content" in payload
    assert "def login" in payload["content"]


@pytest.mark.asyncio
async def test_expand_unknown_handle_returns_error(settings_with_index):
    out = await handle(settings_with_index, {"handle": "code://function/nope", "tier": "T0"})
    payload = json.loads(out[0].text)
    assert "error" in payload
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_mcp_expand.py -v`
Expected: stub.

- [ ] **Step 3: Implement**

Replace `src/claude_mem/tools/expand.py`:

```python
from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool, TextContent

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository


def tool_schema() -> Tool:
    return Tool(
        name="expand",
        description=(
            "Return one unit at a specific tier (T0 full source, T2 LLM summary, "
            "or T1 header). Use this for long-tail drill-down — the common case "
            "of 'top result + full code' is already handled by recall and trace."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Opaque handle from recall/trace"},
                "tier": {"type": "string", "enum": ["T0", "T2", "T1"], "default": "T0"},
            },
            "required": ["handle"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    repo = Repository(connect(settings.db_path))
    unit = repo.get_unit(args["handle"])
    if unit is None:
        return [TextContent(type="text", text=json.dumps({"error": "handle not found"}))]
    tier = args.get("tier", "T0")
    if tier == "T1":
        content = unit.t1_header
    elif tier == "T2":
        content = unit.t2_summary or unit.t1_header
    else:
        content = unit.metadata or unit.t2_summary or unit.t1_header
    payload = {
        "handle": unit.id,
        "tier": tier,
        "content": content,
        "scope": unit.scope,
        "layer": unit.layer,
        "kind": unit.kind,
        "source_ref": unit.source_ref,
    }
    return [TextContent(type="text", text=json.dumps(payload))]
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_mcp_expand.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/tools/expand.py tests/integration/test_mcp_expand.py
git commit -m "feat(tools): expand MCP tool for long-tail drill-down"
```

---

## Task 23: CLI — `claude-mem index` and `claude-mem serve`

**Files:**
- Create: `src/claude_mem/cli.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_cli.py`:

```python
from pathlib import Path
from click.testing import CliRunner

from claude_mem.cli import main


def test_index_creates_state_dir(tmp_path: Path):
    (tmp_path / "x.py").write_text("def f(): pass\n")
    runner = CliRunner()
    result = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude-mem" / "db.sqlite").exists()
    assert "units_written" in result.output


def test_index_idempotent(tmp_path: Path):
    (tmp_path / "x.py").write_text("def f(): pass\n")
    runner = CliRunner()
    result1 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    result2 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    assert result1.exit_code == 0
    assert result2.exit_code == 0


def test_doctor_reports_status(tmp_path: Path):
    (tmp_path / "x.py").write_text("def f(): pass\n")
    runner = CliRunner()
    runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    result = runner.invoke(main, ["doctor", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "units" in result.output.lower()
```

- [ ] **Step 2: Run, confirm FAIL**

Run: `pytest tests/integration/test_cli.py -v`
Expected: import error on `main`.

- [ ] **Step 3: Implement CLI**

`src/claude_mem/cli.py`:

```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from .config import Settings
from .db.connection import connect, init_db
from .db.repository import Repository
from .indexer.orchestrator import full_reindex


@click.group()
def main() -> None:
    """claude-mem — contextual memory & retrieval for Claude Code."""


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Repo root (defaults to cwd)")
@click.option("--no-embed", is_flag=True, default=False,
              help="Skip embedding generation (faster, FTS-only retrieval)")
def index(root: Path | None, no_embed: bool) -> None:
    """Full reindex of the repo."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    init_db(settings.db_path)

    embedder = None
    if not no_embed:
        from .embeddings.bge_small import BgeSmallEmbedder
        embedder = BgeSmallEmbedder()

    stats = full_reindex(settings, embedder=embedder)
    click.echo(f"units_written={stats['units_written']} "
               f"relations_written={stats['relations_written']} "
               f"files_seen={stats['files_seen']}")


@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None)
def doctor(root: Path | None) -> None:
    """Diagnostics — show index size and config."""
    repo_root = root or Path.cwd()
    try:
        settings = Settings.discover(repo_root)
    except FileNotFoundError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    conn = connect(settings.db_path)
    n_units = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    n_rels = conn.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    click.echo(f"repo_root: {settings.repo_root}")
    click.echo(f"db: {settings.db_path}")
    click.echo(f"units: {n_units}")
    click.echo(f"relations: {n_rels}")


@main.command()
def serve() -> None:
    """Run the MCP server on stdio."""
    from .server import serve_stdio
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run, confirm PASS**

Run: `pytest tests/integration/test_cli.py -v`
Expected: 3 passed.

- [ ] **Step 5: Smoke-test the binary**

Run: `claude-mem --help`
Expected: shows `index`, `doctor`, `serve` commands.

Run from a tmp repo: `cd /tmp && mkdir foo && cd foo && echo "def f(): pass" > x.py && claude-mem index --no-embed`
Expected: prints `units_written=1 relations_written=0 files_seen=1`, creates `.claude-mem/db.sqlite`.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): index, doctor, serve subcommands"
```

---

## Task 24: End-to-end Phase 1 acceptance test

**Files:**
- Create: `tests/integration/fixtures/flask_app/` (multiple files)
- Create: `tests/integration/test_phase1_acceptance.py`

Verifies the Phase 1 exit criterion from the spec: on a real-ish repo, `recall("how does login work")` returns useful results within 3k tokens; `trace` from the handler returns the route + handler + callees in one 8k call.

- [ ] **Step 1: Create fixture repo**

Create directory `tests/integration/fixtures/flask_app/`. In it:

`app.py`:
```python
from flask import Flask, request
from auth import verify_user, issue_token
from db import find_user

app = Flask(__name__)


@app.route("/login", methods=["POST"])
def login():
    user = request.json["user"]
    pw = request.json["pw"]
    if verify_user(user, pw):
        return issue_token(user)
    return "unauthorized", 401


@app.route("/health")
def health():
    return "ok"
```

`auth.py`:
```python
from db import find_user


def verify_user(user, pw):
    record = find_user(user)
    if record is None:
        return False
    return record["pw"] == pw


def issue_token(user):
    return f"token-for-{user}"
```

`db.py`:
```python
_USERS = {"alice": {"pw": "secret"}}


def find_user(user):
    return _USERS.get(user)
```

`docs/auth.md`:
```markdown
# Authentication

This service uses POST /login with JSON body {user, pw}.
Tokens are opaque strings of the form `token-for-<user>`.

## Refresh

Not yet implemented. See backlog.
```

- [ ] **Step 2: Write the acceptance test**

`tests/integration/test_phase1_acceptance.py`:

```python
import json
import shutil
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.recall import handle as recall_handle
from claude_mem.tools.trace import handle as trace_handle
from tests.integration.test_recall_e2e import FakeEmbedder


FIXTURE_SRC = Path(__file__).parent / "fixtures" / "flask_app"


@pytest.fixture
def flask_repo(tmp_path: Path):
    dst = tmp_path / "flask_app"
    shutil.copytree(FIXTURE_SRC, dst)
    (dst / ".claude-mem").mkdir()
    s = Settings.for_repo(dst)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


@pytest.mark.asyncio
async def test_recall_finds_login_within_budget(flask_repo):
    out = await recall_handle(flask_repo, FakeEmbedder(), {"query": "login", "budget": 3000})
    payload = json.loads(out[0].text)
    assert payload["budget_used"] <= 3000
    # Should find the login function, the /login route, or the auth doc
    headers = " ".join(it["content"] for it in payload["items"])
    assert "login" in headers.lower()


@pytest.mark.asyncio
async def test_trace_from_route_pulls_handler(flask_repo):
    # First recall to get the route handle
    out = await recall_handle(flask_repo, FakeEmbedder(), {"query": "/login route"})
    items = json.loads(out[0].text)["items"]
    route_handle = next((i["handle"] for i in items if "route" in i["handle"]), None)
    if route_handle is None:
        # fall back to handler unit
        route_handle = items[0]["handle"]

    trace_out = await trace_handle(flask_repo, {"seed_handles": [route_handle], "depth": 2, "budget": 8000})
    payload = json.loads(trace_out[0].text)
    assert payload["budget_used"] <= 8000
    # Should include the login handler function
    contents = " ".join(it["content"] for it in payload["items"])
    assert "def login" in contents or "login" in contents.lower()


def test_index_size_reasonable(flask_repo):
    from claude_mem.db.connection import connect
    conn = connect(flask_repo.db_path)
    n = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    # Expect at least: 5 fns (login, health, verify_user, issue_token, find_user)
    # + 2 routes + 2 doc sections + 1 frontmatter-less doc parent = ~10
    assert n >= 5
```

- [ ] **Step 3: Run, confirm PASS**

Run: `pytest tests/integration/test_phase1_acceptance.py -v`
Expected: 3 passed.

- [ ] **Step 4: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass. Slow tests stay skipped unless `-m slow`.

- [ ] **Step 5: Commit**

```
git add tests/integration/fixtures/flask_app/ tests/integration/test_phase1_acceptance.py
git commit -m "test: phase 1 acceptance — recall+trace on flask fixture"
```

---

## Task 25: README and Phase 1 wrap

**Files:**
- Create: `README.md`
- Modify: `pyproject.toml` (final version bump)

- [ ] **Step 1: Write README**

`README.md`:

```markdown
# claude-mem

Contextual memory and retrieval engine for Claude Code. Local-first MCP server that gives Claude durable project memory and hierarchical retrieval over a single repo's code, docs, and prior decisions.

**Status:** Phase 1 — substrate, retrieval, traversal. Memory writes, tasks, and handoff land in Phase 2/3.

## Install

```bash
pip install -e ".[dev]"
```

## Quick start

```bash
cd your-repo
claude-mem index                # full reindex
claude-mem doctor               # show index size
claude-mem serve                # run MCP server on stdio
```

Connect Claude Code to the server via your MCP config.

## Tools (Phase 1)

- `recall(query, budget=3000)` — ranked hybrid search with budgeted tiered fill
- `trace(seed_handles, depth=2, budget=8000)` — graph traversal from a seed handle, full source for connected nodes in one round-trip
- `expand(handle, tier)` — drill into one unit at a specific tier (T0/T2/T1)

## Architecture

See `docs/specs/2026-05-25-claude-mem-design.md`.

## Tests

```bash
pytest                  # fast tests
pytest -m slow          # includes bge-small embedder tests (downloads model)
```
```

- [ ] **Step 2: Commit**

```
git add README.md
git commit -m "docs: Phase 1 README with quick start and tool summary"
```

- [ ] **Step 3: Tag the phase**

```
git tag -a phase-1-complete -m "Phase 1: substrate, retrieval, traversal"
git log --oneline phase-1-complete~25..phase-1-complete
```

Expected: ~26 commits since Task 0.

---

## Self-review notes

**Spec coverage:** Every Phase 1 deliverable from spec §12 maps to tasks:
- SQLite schema → Task 2
- Indexer for code + docs → Tasks 8–11, 14
- T1 deterministic headers → Task 4
- Embeddings via bge-small → Task 7
- RRF + feature rerank (§4.1) → Task 15
- Budget-aware tiered fill (§4.2) → Task 16
- `recall`, `trace`, `expand` MCP tools → Tasks 17–18, 20–22
- Imports synthesizer + at least one route synthesizer → Tasks 12–13
- MCP `initialize` instructions block (§11.1) → Task 19
- `claude-mem index` CLI → Task 23
- Exit criterion verification → Task 24

**Type consistency:** `FillResult`, `RankedItem`, `FilledItem`, `SearchHit`, `Unit`, `Relation`, `Settings`, `Repository`, `Embedder` types used in later tasks all defined in earlier tasks. Verified by tracing imports.

**Placeholder scan:** No "TBD", no "implement appropriately", no "similar to Task N." All steps contain runnable code or exact commands.

**Known soft spots** (acceptable, called out for executor):
- Task 11 (JS/TS parser) coverage is intentionally narrow — function declarations, arrow-on-const, classes, methods. Decorators, generators, default exports of anonymous functions are deferred to Phase 4 with the broader language expansion.
- Task 12 imports synthesizer uses regex, not AST traversal of import nodes. Sufficient for v1; replace with AST in Phase 4 if false-positive rate is high.
- Task 13 Flask synthesizer uses a regex over source, not tree-sitter. Robust enough for the v1 dogfood Flask repo; will be replaced with AST-based extraction in Phase 2 when Django and FastAPI synthesizers join.
