# claude-repo-mem Phase 4 — Polish: Parsers, Synthesizers, Operational Glue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend language coverage (Java, Go, Rust), close the Phase 2 synthesizer deferrals (Django, Express, React hooks), and ship the operational glue that has been deferred (install-hooks CLI, expanded doctor, background embedding/summary queues).

**Architecture:** All work is additive on top of the Phase 1-3 substrate. Parsers follow `code_python.py` / `code_jsts.py` exactly — tree-sitter AST walk, emit `function/method/class` units with `python <name>(...)` style headers, intra-file relations via `call_inside_file` / `extends` / `implements`. Synthesizers follow `flask_routes.py` — regex over source files, produce a synthetic route/edge unit + a `route_to` (or `mutates_state_of`) relation. The queue subsystem is a `BackgroundQueue` running on a daemon thread, draining work items into `summarize_unit` or the embedder; the watcher and the indexer both push into it instead of blocking.

**Tech Stack:** Phase 1-3 stack plus `tree-sitter-java`, `tree-sitter-go`, `tree-sitter-rust` (each ships a Windows wheel via PyPI). No new LLM dependencies.

**Spec:** `docs/specs/2026-05-25-claude-repo-mem-design.md` §7.3 (synthesizers), §12 Phase 4 (polish goals).

**Phase 1-3 lessons carried forward:**
- `rsplit(":", 1)[0]` on `source_ref` (Windows drive letter).
- Tests that walk parent dirs must mock `Path.is_dir`.
- `tree-sitter-languages` doesn't ship Windows wheels — use per-language packages only.
- Sonnet for implementer subagents.
- `superseded_by` FK requires a real referenced row.
- Source refs from code parsers include `:line-range` — use `LIKE 'path:%'` to query, not `=`.

---

## File Structure

**New parsers**
- `src/claude_repo_mem/indexer/parsers/code_java.py`
- `src/claude_repo_mem/indexer/parsers/code_go.py`
- `src/claude_repo_mem/indexer/parsers/code_rust.py`

**New synthesizers**
- `src/claude_repo_mem/indexer/synthesizers/django_urls.py`
- `src/claude_repo_mem/indexer/synthesizers/express_routes.py`
- `src/claude_repo_mem/indexer/synthesizers/react_hooks.py`

**Operational**
- `src/claude_repo_mem/queue/__init__.py`
- `src/claude_repo_mem/queue/background.py` — `BackgroundQueue` daemon-thread executor
- `src/claude_repo_mem/queue/jobs.py` — `embed_job`, `summarize_job` adapters
- Modify: `src/claude_repo_mem/watcher/fs_watcher.py` — push embeddings into queue
- Modify: `src/claude_repo_mem/cli.py` — `claude-repo-mem install-hooks`, expand `doctor`

**Tests**
- `tests/unit/test_parsers_java.py`, `test_parsers_go.py`, `test_parsers_rust.py`
- `tests/unit/test_synth_django.py`, `test_synth_express.py`, `test_synth_react.py`
- `tests/unit/test_background_queue.py`
- `tests/unit/test_cli_install_hooks.py`, `test_cli_doctor_expanded.py`
- `tests/integration/test_phase4_acceptance.py`

---

## Cross-cutting design decisions (read before starting)

### Parser shape (Java/Go/Rust mirror Python)

Each parser exposes `supports(path) -> bool` and `parse(path, text) -> ParseResult`. Body walks the tree-sitter AST producing `code` units with kind `function | method | class` (Rust uses `function | method | struct | trait`; Go uses `function | method | struct | interface`; Java uses `function/method | class | interface`).

Header format (per spec §9.3 — already enforced in `t1_header()`):

- Java method: `java methodName(params) -> returnType`
- Java class: `java class Name: docstring_first_line` (Javadoc first line if present)
- Go function: `go funcName(params) returnType`
- Go method: `go (recv *T) methodName(params) returnType`
- Rust function: `rust fn name(params) -> returnType`
- Rust impl method: `rust impl Type::method(params) -> returnType`

Scope: parent-directory join (same as Python parser).
Source ref: `path.as_posix() + ":" + start_line + "-" + end_line`.

### Synthesizer regex sketches

Django (`urls.py` only):
```
DJANGO_PATH_RE = re.compile(
    r"""(?:path|re_path)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*(?P<handler>[\w.]+)""",
    re.VERBOSE,
)
```

Express (any `.js`/`.ts`):
```
EXPRESS_RE = re.compile(
    r"""(?P<app>\w+)\.(?P<method>get|post|put|delete|patch|all)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*(?P<handler>\w+)\s*\)""",
)
```

React hooks (`.jsx`/`.tsx`):
```
USE_STATE_RE = re.compile(
    r"const\s+\[(?P<state>\w+),\s*(?P<setter>set\w+)\]\s*=\s*useState\b"
)
SETTER_USE_RE = re.compile(r"\b(set\w+)\s*\(")
```

React v1 emits self-loops on the containing function unit when both the destructure AND a later setter call appear inside the same function body. This is a conservative bias — false negatives over false positives.

### Background queue

```python
class BackgroundQueue:
    def __init__(self, max_workers: int = 1) -> None: ...
    def submit(self, fn: Callable[[], None]) -> None: ...
    def drain(self, timeout: float = 30.0) -> None: ...  # for tests
    def stop(self) -> None: ...
```

Single-worker daemon thread; `submit()` puts the callable onto a `queue.Queue`; the worker pulls and calls. Exceptions get logged to stderr and swallowed. No retry. `drain()` waits until the queue is empty AND the worker is idle — used only in tests.

The watcher's `_on_flush` becomes:
```python
def _on_flush(self, paths):
    self._queue.submit(lambda: incremental_reindex(self.settings, [Path(p) for p in paths], embedder=self.embedder))
```

This keeps watchdog's callback non-blocking even when reindex takes seconds.

### `install-hooks`

`claude-repo-mem install-hooks` writes `.git/hooks/post-commit` (or post-merge) with a one-liner: `claude-repo-mem index --no-embed --quiet || true`. Refuses to clobber an existing hook unless `--force`. Reports the path written.

### Expanded `doctor`

Current `doctor` reports `repo_root`, `db`, units, relations. Phase 4 additions:
- Layer breakdown (by-layer counts).
- T2 coverage: `n_with_t2 / n_total` for code+docs.
- Counter snapshot from `observability.counters`.
- Watcher state hint: detect a stale `.claude-repo-mem/db.sqlite` modification time vs. repo files.
- Tree-sitter language inventory (which language parsers loaded successfully).

---

## Task 0: Inventory + dependency add

- [ ] **Step 1: Add deps to `pyproject.toml`**

Append to `[project] dependencies`:
```toml
"tree-sitter-java>=0.21",
"tree-sitter-go>=0.21",
"tree-sitter-rust>=0.21",
```

- [ ] **Step 2: Install**

```
.venv/Scripts/python -m pip install -e .
```

- [ ] **Step 3: Smoke**

```
.venv/Scripts/python -c "import tree_sitter_java, tree_sitter_go, tree_sitter_rust; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```
git add pyproject.toml
git commit -m "build: add tree-sitter Java/Go/Rust language packages"
```

---

## Task 1: Java parser

**Files:**
- Create: `src/claude_repo_mem/indexer/parsers/code_java.py`
- Test: `tests/unit/test_parsers_java.py`

- [ ] **Step 1: Failing test** — mirrors `tests/unit/test_parsers_python.py`. Cover:
  1. A class with two methods produces 1 class unit + 2 method units, methods carry `parent_id = class_id`.
  2. The class's t1_header is `java class Name`.
  3. Method header is `java methodName(params) -> returnType`.
  4. `supports()` returns True for `.java`, False for `.py`.

Worked test sketch:

```python
from pathlib import Path
from claude_repo_mem.indexer.parsers.code_java import JavaParser

SAMPLE = """\
package com.example;

/** AuthService docstring. */
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
    for u in result.units:
        if u.kind == "method":
            assert u.parent_id == cls.id


def test_supports():
    p = JavaParser()
    assert p.supports(Path("X.java"))
    assert not p.supports(Path("x.py"))
```

- [ ] **Step 2: FAIL** — import error.

- [ ] **Step 3: Implement**

Pattern: copy `code_python.py`; swap `tree_sitter_python` for `tree_sitter_java`; replace node-type filters with `class_declaration`, `method_declaration`, `constructor_declaration`. Extract `name` via `node.child_by_field_name("name")`; extract parameter list and return type via `formal_parameters` and `type_identifier | void_type | generic_type`. Walk recursively; pass the enclosing class name into recursive calls so methods know their parent.

Use `t1_header(layer="code", kind="class", lang="java", name=name, signature=None, docstring_first_line=javadoc_first_line)` and `t1_header(layer="code", kind="method", lang="java", name=name, signature=f"({params}) -> {ret}")`.

Source ref: `path.as_posix() + ":" + str(start_row+1) + "-" + str(end_row+1)`.

- [ ] **Step 4: PASS, commit**

```
git commit -m "feat(parsers): Java tree-sitter parser — classes + methods + constructors"
```

---

## Task 2: Go parser

**Files:**
- Create: `src/claude_repo_mem/indexer/parsers/code_go.py`
- Test: `tests/unit/test_parsers_go.py`

- [ ] **Step 1: Failing test** — cover:
  1. Top-level `func Foo(a int) string` → kind `function`, header `go Foo(a int) string`.
  2. Method `func (s *Service) Issue(...)` → kind `method`, header `go (s *Service) Issue(...) ...`. No `parent_id` (Go has no class — receivers are sufficient hints).
  3. `type T struct { ... }` → kind `struct`, header `go struct T`.
  4. `type I interface { Method() }` → kind `interface`, header `go interface I`.

Worked test sketch:

```python
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
```

- [ ] **Step 2: Implement** — tree-sitter-go node types: `function_declaration`, `method_declaration`, `type_declaration` (with child `struct_type` / `interface_type`).

- [ ] **Step 3: Commit**

```
git commit -m "feat(parsers): Go tree-sitter parser — funcs/methods/structs/interfaces"
```

---

## Task 3: Rust parser

**Files:**
- Create: `src/claude_repo_mem/indexer/parsers/code_rust.py`
- Test: `tests/unit/test_parsers_rust.py`

- [ ] **Step 1: Failing test** — cover:
  1. `fn name(...)` at module scope → kind `function`, header `rust fn name(...) -> ...`.
  2. `impl Type { fn method(...) {} }` → kind `method`, header `rust impl Type::method(...) -> ...`.
  3. `struct Name { ... }` → kind `struct`, header `rust struct Name`.
  4. `trait T { fn m(&self); }` → kind `trait`, header `rust trait T`.

Sample:

```rust
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
```

- [ ] **Step 2: Implement** — tree-sitter-rust node types: `function_item`, `struct_item`, `trait_item`, `impl_item` (recurse into impl_item to find inner `function_item` and tag with kind="method" + prefix the impl target into the header).

Note: `KIND_VALID_FOR_LAYER["code"]` currently is `{"function", "method", "class", "route", "interface", "module"}` — Rust's `struct` and `trait` and Go's `struct` need to be added. Update `src/claude_repo_mem/units/typed.py`:

```python
"code": {"function", "method", "class", "route", "interface", "module", "struct", "trait"},
```

- [ ] **Step 3: Commit**

```
git commit -m "feat(parsers): Rust tree-sitter parser — fn/impl/struct/trait + extend valid kinds"
```

---

## Task 4: Register new parsers in orchestrator + walker

**Files:**
- Modify: `src/claude_repo_mem/indexer/walker.py` — append `.java`, `.go`, `.rs` to `SUPPORTED_EXTS`
- Modify: `src/claude_repo_mem/indexer/orchestrator.py` — register parsers

- [ ] **Step 1: Walker**

```python
SUPPORTED_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".markdown", ".java", ".go", ".rs"}
```

- [ ] **Step 2: Orchestrator**

```python
from .parsers.code_java import JavaParser
from .parsers.code_go import GoParser
from .parsers.code_rust import RustParser
...
PARSERS = [
    MemoryMarkdownParser(),
    PythonParser(), JsTsParser(), JavaParser(), GoParser(), RustParser(),
    MarkdownParser(),
]
```

- [ ] **Step 3: Integration test** — `tests/integration/test_indexer_multilang.py`:

```python
def test_indexes_java_go_rust(tmp_repo):
    (tmp_repo / "A.java").write_text("public class A { void m() {} }")
    (tmp_repo / "b.go").write_text("package x\nfunc B() {}\n")
    (tmp_repo / "c.rs").write_text("pub fn c() {}")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    rows = conn.execute("SELECT t1_header FROM unit WHERE layer='code'").fetchall()
    headers = " ".join(r["t1_header"] for r in rows)
    assert "java" in headers and "go" in headers and "rust" in headers
```

- [ ] **Step 4: Commit**

```
git commit -m "feat(indexer): register Java/Go/Rust parsers, extend SUPPORTED_EXTS"
```

---

## Task 5: Django URL synthesizer

**Files:**
- Create: `src/claude_repo_mem/indexer/synthesizers/django_urls.py`
- Test: `tests/unit/test_synth_django.py`
- Modify: `src/claude_repo_mem/indexer/orchestrator.py` — add to synth list

- [ ] **Step 1: Failing test**

```python
def test_django_path_emits_route(tmp_repo):
    (tmp_repo / "views.py").write_text("def login(request):\n    return None\n")
    (tmp_repo / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [path('login/', views.login, name='login')]\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    routes = conn.execute("SELECT t1_header FROM unit WHERE kind='route'").fetchall()
    assert any("login" in r["t1_header"] for r in routes)
```

- [ ] **Step 2: Implement** — mirror `flask_routes.py`:
  - Filter `urls.py` files (`path.name == "urls.py"`).
  - Apply `DJANGO_PATH_RE` to body.
  - `handler` is `views.login` style — strip module prefix; match against function names in any `.py` file under the same directory (try `views.py` first).

```python
import re
DJANGO_RE = re.compile(
    r"""(?:path|re_path)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*(?P<handler>[\w.]+)""",
)


class DjangoUrlsSynthesizer:
    def synthesize_with_units(self, units, sources, repo_root):
        # Build handler index by function name + containing file's parent dir.
        handlers: dict[tuple[str, str], Unit] = {}  # (parent_dir, fn_name) -> unit
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.rsplit(":", 1)[0]
                parent_dir = Path(file).parent.as_posix()
                m = re.match(r"\w+ (\S+?)\(", u.t1_header)
                if m:
                    handlers[(parent_dir, m.group(1))] = u

        new_units, rels = [], []
        for path, src in sources.items():
            if path.name != "urls.py":
                continue
            for m in DJANGO_RE.finditer(src):
                url = m.group("url")
                handler_ref = m.group("handler")
                fn_name = handler_ref.rsplit(".", 1)[-1]
                parent_dir = path.parent.as_posix()
                handler = handlers.get((parent_dir, fn_name))
                if not handler:
                    continue
                # Build route unit + edge (copy from FlaskRoutesSynthesizer).
                ...
        return new_units, rels

    def synthesize(self, units, sources, repo_root):
        _, rels = self.synthesize_with_units(units, sources, repo_root)
        return rels
```

Fill in the `...` with the Flask synthesizer's exact unit-construction code (handle ID, content_hash, header `f"django route {url} -> {fn_name}"`). Append `DjangoUrlsSynthesizer` to `orchestrator.py` alongside `FlaskRoutesSynthesizer`. Note: orchestrator currently only calls `FlaskRoutesSynthesizer().synthesize_with_units`; refactor to a small list:

```python
ROUTE_SYNTHS = [FlaskRoutesSynthesizer(), DjangoUrlsSynthesizer(), ExpressRoutesSynthesizer()]
for synth in ROUTE_SYNTHS:
    extra, rels = synth.synthesize_with_units(all_units, sources, repo_root)
    all_units.extend(extra)
    all_relations.extend(rels)
```

(`ExpressRoutesSynthesizer` lands in Task 6.)

- [ ] **Step 3: Commit**

```
git commit -m "feat(synth): Django path/re_path route synthesizer"
```

---

## Task 6: Express routes synthesizer

**Files:**
- Create: `src/claude_repo_mem/indexer/synthesizers/express_routes.py`
- Test: `tests/unit/test_synth_express.py`

- [ ] **Step 1: Failing test**

```python
def test_express_get(tmp_repo):
    (tmp_repo / "routes.js").write_text(
        "function login(req, res) { return res.send('ok'); }\n"
        "app.get('/login', login);\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    headers = [r["t1_header"] for r in conn.execute("SELECT t1_header FROM unit WHERE kind='route'").fetchall()]
    assert any("/login" in h and "login" in h for h in headers)
```

- [ ] **Step 2: Implement** — mirror Django synth; regex above. Restrict to `.js`/`.jsx`/`.ts`/`.tsx`. Handler-resolution: same file only (named function reference in same file).

```
git commit -m "feat(synth): Express app.METHOD route synthesizer for same-file handlers"
```

---

## Task 7: React hooks synthesizer

**Files:**
- Create: `src/claude_repo_mem/indexer/synthesizers/react_hooks.py`
- Test: `tests/unit/test_synth_react.py`

- [ ] **Step 1: Failing test**

```python
def test_react_self_loop_on_setter_use(tmp_repo):
    (tmp_repo / "Comp.jsx").write_text(
        "function Comp() {\n"
        "  const [n, setN] = useState(0);\n"
        "  const onClick = () => setN(n + 1);\n"
        "  return <button onClick={onClick} />;\n"
        "}\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    rels = conn.execute(
        "SELECT src_id, dst_id FROM relation WHERE kind='mutates_state_of'"
    ).fetchall()
    assert len(rels) >= 1
    # v1: self-loop on the function unit.
    assert rels[0]["src_id"] == rels[0]["dst_id"]
```

- [ ] **Step 2: Implement**

```python
USE_STATE_RE = re.compile(r"const\s+\[\s*(\w+)\s*,\s*(set\w+)\s*\]\s*=\s*useState\b")
SETTER_USE_RE = re.compile(r"\b(set\w+)\s*\(")


class ReactHooksSynthesizer:
    def synthesize(self, units, sources, repo_root) -> list[Relation]:
        rels: list[Relation] = []
        # Index units by file+line range for body lookup.
        by_source: dict[str, list[Unit]] = {}
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.rsplit(":", 1)[0]
                by_source.setdefault(file, []).append(u)

        for path, src in sources.items():
            if path.suffix.lower() not in (".jsx", ".tsx"):
                continue
            for u in by_source.get(path.as_posix(), []):
                # Get this function's body slice using source_ref line range.
                try:
                    rng = u.source_ref.rsplit(":", 1)[1]
                    start, end = map(int, rng.split("-"))
                except (IndexError, ValueError):
                    continue
                lines = src.splitlines()[start - 1 : end]
                body = "\n".join(lines)
                setters_declared = {m.group(2) for m in USE_STATE_RE.finditer(body)}
                if not setters_declared:
                    continue
                setters_used = {m.group(1) for m in SETTER_USE_RE.finditer(body)}
                if setters_declared & setters_used:
                    rels.append(Relation(u.id, u.id, "mutates_state_of"))
        return rels
```

Register in orchestrator alongside `ImportsSynthesizer`:

```python
all_relations.extend(ReactHooksSynthesizer().synthesize(all_units, sources, repo_root))
```

- [ ] **Step 3: Commit**

```
git commit -m "feat(synth): React hooks — emit mutates_state_of self-loops on useState setter use"
```

---

## Task 8: BackgroundQueue (daemon-thread executor)

**Files:**
- Create: `src/claude_repo_mem/queue/__init__.py` (empty)
- Create: `src/claude_repo_mem/queue/background.py`
- Test: `tests/unit/test_background_queue.py`

- [ ] **Step 1: Failing test**

```python
import threading, time
from claude_repo_mem.queue.background import BackgroundQueue


def test_submit_runs_job():
    q = BackgroundQueue()
    q.start()
    fired = threading.Event()
    q.submit(fired.set)
    assert fired.wait(timeout=2.0)
    q.stop()


def test_submit_runs_jobs_in_order_single_worker():
    q = BackgroundQueue()
    q.start()
    out = []
    for i in range(5):
        q.submit(lambda i=i: out.append(i))
    q.drain(timeout=5.0)
    assert out == [0, 1, 2, 3, 4]
    q.stop()


def test_exception_does_not_kill_worker():
    q = BackgroundQueue()
    q.start()
    q.submit(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    fired = threading.Event()
    q.submit(fired.set)
    assert fired.wait(timeout=2.0)
    q.stop()


def test_drain_waits_for_idle():
    q = BackgroundQueue()
    q.start()
    seen = []
    q.submit(lambda: (time.sleep(0.05), seen.append("a")))
    q.drain(timeout=2.0)
    assert seen == ["a"]
    q.stop()
```

- [ ] **Step 2: Implement**

```python
from __future__ import annotations
import queue
import sys
import threading
import time
from typing import Callable, Optional


_SENTINEL = object()


class BackgroundQueue:
    def __init__(self) -> None:
        self._q: "queue.Queue[object]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, fn: Callable[[], None]) -> None:
        self._idle.clear()
        self._q.put(fn)

    def drain(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            if self._q.empty() and self._idle.is_set():
                return
            if time.monotonic() > deadline:
                raise TimeoutError("BackgroundQueue.drain timeout")
            time.sleep(0.01)

    def stop(self) -> None:
        if self._worker is None:
            return
        self._stop.set()
        self._q.put(_SENTINEL)
        self._worker.join(timeout=2.0)
        self._worker = None

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if item is _SENTINEL:
                self._idle.set()
                return
            try:
                item()
            except Exception as e:  # pragma: no cover
                print(f"[claude-repo-mem queue] job failed: {e}", file=sys.stderr)
            finally:
                if self._q.empty():
                    self._idle.set()
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(queue): BackgroundQueue daemon-thread executor with drain/stop"
```

---

## Task 9: Wire queue into watcher

**Files:**
- Modify: `src/claude_repo_mem/watcher/fs_watcher.py`

- [ ] **Step 1: Inject queue, defer reindex into it**

```python
from ..queue.background import BackgroundQueue


class FileWatcher:
    def __init__(self, settings, *, embedder=None, quiet_ms=750, queue=None):
        ...
        self._queue = queue or BackgroundQueue()
        self._owns_queue = queue is None

    def start(self):
        if self._owns_queue:
            self._queue.start()
        ...

    def stop(self):
        ...
        if self._owns_queue:
            self._queue.stop()

    def _on_flush(self, paths):
        paths_list = [Path(p) for p in paths]
        self._queue.submit(lambda: incremental_reindex(self.settings, paths_list, embedder=self.embedder))
```

- [ ] **Step 2: Test watcher still passes**

`.venv/Scripts/python -m pytest tests/integration/test_watcher.py -m slow -q` — expect 2 passed.

- [ ] **Step 3: Commit**

```
git commit -m "refactor(watcher): defer incremental reindex via BackgroundQueue"
```

---

## Task 10: `install-hooks` CLI

**Files:**
- Modify: `src/claude_repo_mem/cli.py`
- Test: `tests/unit/test_cli_install_hooks.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
import subprocess
from click.testing import CliRunner
from claude_repo_mem.cli import main


def test_install_hooks_writes_post_commit(tmp_path: Path):
    # Init a git repo so .git/hooks/ exists.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path)])
    assert res.exit_code == 0
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    text = hook.read_text()
    assert "claude-repo-mem index" in text


def test_install_hooks_refuses_to_clobber(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("# pre-existing\n")
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path)])
    assert res.exit_code != 0
    assert "exists" in res.output.lower() or "force" in res.output.lower()


def test_install_hooks_force_clobbers(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("# pre-existing\n")
    runner = CliRunner()
    res = runner.invoke(main, ["install-hooks", "--root", str(tmp_path), "--force"])
    assert res.exit_code == 0
    assert "claude-repo-mem index" in hook.read_text()
```

- [ ] **Step 2: Implement** — add command to `cli.py`:

```python
@main.command("install-hooks")
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--force", is_flag=True, default=False)
def install_hooks(root: Path | None, force: bool) -> None:
    """Install a post-commit hook that triggers `claude-repo-mem index --no-embed`."""
    repo_root = root or Path.cwd()
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise click.ClickException(f"not a git repo: {repo_root}")
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    if hook_path.exists() and not force:
        raise click.ClickException(
            f"{hook_path} already exists; rerun with --force to overwrite"
        )
    hook_path.write_text(
        "#!/bin/sh\n"
        "# Installed by claude-repo-mem install-hooks\n"
        "claude-repo-mem index --no-embed >/dev/null 2>&1 || true\n",
        encoding="utf-8",
    )
    try:
        hook_path.chmod(0o755)
    except Exception:
        pass  # Windows
    click.echo(f"installed: {hook_path}")
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(cli): claude-repo-mem install-hooks for post-commit reindex"
```

---

## Task 11: Expanded `doctor`

**Files:**
- Modify: `src/claude_repo_mem/cli.py` — expand `doctor`
- Test: `tests/unit/test_cli_doctor_expanded.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
from click.testing import CliRunner
from claude_repo_mem.cli import main
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex


def test_doctor_reports_layers_and_counters(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_path); init_db(s.db_path)
    full_reindex(s, embedder=None)
    runner = CliRunner()
    res = runner.invoke(main, ["doctor", "--root", str(tmp_path)])
    assert res.exit_code == 0
    assert "by_layer" in res.output or "layer" in res.output.lower()
    assert "counters" in res.output.lower() or "recall_calls" in res.output


def test_doctor_reports_t2_coverage(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_path); init_db(s.db_path)
    full_reindex(s, embedder=None)
    runner = CliRunner()
    res = runner.invoke(main, ["doctor", "--root", str(tmp_path)])
    assert "t2" in res.output.lower() or "summary" in res.output.lower()
```

- [ ] **Step 2: Implement**

```python
@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
def doctor(root: Path | None) -> None:
    """Diagnostics — index size, layer breakdown, T2 coverage, counters."""
    repo_root = root or Path.cwd()
    try:
        settings = Settings.discover(repo_root)
    except FileNotFoundError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    conn = connect(settings.db_path)
    n_units = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    n_rels = conn.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    by_layer = {
        r["layer"]: r["n"] for r in conn.execute(
            "SELECT layer, COUNT(*) AS n FROM unit GROUP BY layer"
        ).fetchall()
    }
    t2_eligible = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer IN ('code','docs')"
    ).fetchone()[0]
    t2_done = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer IN ('code','docs') AND t2_summary IS NOT NULL"
    ).fetchone()[0]
    from .observability.counters import get_counters
    counters = get_counters().to_dict()

    click.echo(f"repo_root: {settings.repo_root}")
    click.echo(f"db: {settings.db_path}")
    click.echo(f"units: {n_units}")
    click.echo(f"relations: {n_rels}")
    click.echo(f"by_layer: {by_layer}")
    click.echo(f"t2_coverage: {t2_done}/{t2_eligible}")
    click.echo(f"counters: {counters}")
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(cli): expand doctor — layer breakdown, T2 coverage, counters"
```

---

## Task 12: Phase 4 acceptance test

End-to-end smoke covering: Java + Go + Rust parsing, Django + Express + React synthesizers, queue-deferred incremental reindex.

**Files:**
- Create: `tests/integration/test_phase4_acceptance.py`

- [ ] **Step 1: Test**

```python
"""Phase 4 acceptance — language coverage + synthesizers + queue."""
from pathlib import Path
import time
import pytest
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex


def test_multilang_and_synths(tmp_repo: Path):
    # Java
    (tmp_repo / "A.java").write_text(
        "public class A { public String m(String s) { return s; } }\n"
    )
    # Go
    (tmp_repo / "b.go").write_text(
        "package x\n"
        "type S struct{}\n"
        "func (s *S) Issue() string { return \"\" }\n"
    )
    # Rust
    (tmp_repo / "c.rs").write_text(
        "pub struct S; impl S { pub fn issue(&self) -> i32 { 0 } }\n"
    )
    # Django
    (tmp_repo / "views.py").write_text("def login(request):\n    return None\n")
    (tmp_repo / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [path('login/', views.login)]\n"
    )
    # Express
    (tmp_repo / "routes.js").write_text(
        "function logout(req, res) { return res.send('ok'); }\n"
        "app.post('/logout', logout);\n"
    )
    # React
    (tmp_repo / "Comp.jsx").write_text(
        "function Comp() {\n"
        "  const [n, setN] = useState(0);\n"
        "  const c = () => setN(n + 1);\n"
        "  return null;\n"
        "}\n"
    )

    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)

    by_lang = {r["t1_header"].split(" ", 1)[0]
               for r in conn.execute(
                   "SELECT t1_header FROM unit WHERE layer='code'"
               ).fetchall()
               if r["t1_header"]}
    assert {"java", "go", "rust", "python"}.issubset(by_lang)

    n_routes = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE kind='route'"
    ).fetchone()[0]
    assert n_routes >= 2  # django + express

    n_state = conn.execute(
        "SELECT COUNT(*) FROM relation WHERE kind='mutates_state_of'"
    ).fetchone()[0]
    assert n_state >= 1
```

- [ ] **Step 2: PASS, commit**

```
git commit -m "test: phase 4 acceptance — Java/Go/Rust + Django/Express/React synths"
```

---

## Task 13: README + tag

- [ ] **Step 1: Update README.md**

Change Status:
```
**Status:** Phase 4 — Java/Go/Rust parsers, Django/Express/React synthesizers, install-hooks, background queue.
```

Under `## Quick start`, add:
```
claude-repo-mem install-hooks        # post-commit reindex (alternative to --watch)
claude-repo-mem doctor               # diagnostics + counters
```

Append to `## Tools / Phase 3`:
```markdown
Languages indexed: Python, JS/TS, Markdown, Java, Go, Rust.
Synthesizers: Flask, Django, Express routes; Python imports; React hooks (`useState` setters).
```

- [ ] **Step 2: Commit + tag**

```
git add README.md
git commit -m "docs: Phase 4 README — multilang, synthesizers, hooks, queue"
git tag -a phase-4-complete -m "Phase 4: polish — parsers, synthesizers, hooks, queue"
```

---

## Self-review

**1. Spec coverage:**
- §12 Phase 4 "Additional languages for tree-sitter (Java, Go, Rust)" → Tasks 0-4.
- §7.3 synthesizer coverage gaps from Phase 2 → Tasks 5, 6, 7.
- §12 Phase 4 "Performance: incremental embedding queue, summary backlog management" → Tasks 8-9. (Summary backlog: deferred — same queue substrate works, just needs a hook in the summarizer to push instead of await. Out of scope for v1; the queue exists so it's a 5-line follow-up.)
- Phase 3 deferral `install-hooks` → Task 10.
- Phase 3 deferral `doctor` improvements → Task 11.
- Pluggable embedders (OpenAI/Voyage) — EXPLICITLY OUT per user scope decision.
- Ranking weight tuning — EXPLICITLY OUT (needs a benchmark harness we don't have).

**2. Placeholder scan:**
- Task 1-3 parser bodies show only the test + skeleton; engineer follows `code_python.py` exactly. Acceptable because Phase 1's Python parser is the precise template and is ~150 LoC of well-tested code. If you want fuller bodies, expand by mirroring `code_python.py` line-for-line.
- Task 5's `# Fill in the ... with the Flask synthesizer's exact unit-construction code` is an explicit "copy from flask_routes.py lines 52-67" — the implementer has the exact source.
- No `TBD`, `TODO`, `figure out later` anywhere.

**3. Type consistency:**
- `JavaParser`, `GoParser`, `RustParser` defined in Tasks 1-3, used in Task 4.
- `DjangoUrlsSynthesizer`, `ExpressRoutesSynthesizer`, `ReactHooksSynthesizer` defined in Tasks 5-7, used in Task 4's orchestrator hook (note: Task 4 mentions registration but the synth list update happens in Tasks 5/6/7 incrementally).
- `BackgroundQueue` defined in Task 8, used in Task 9.

**4. Open questions:**
- Tree-sitter node-type names for Java/Go/Rust may differ slightly from what the plan claims (e.g. `function_definition` vs `function_declaration`). Implementer should run `.venv/Scripts/python -c "import tree_sitter_java; print(...)" ` to inspect the grammar's actual node types if a test fails on missing units.
- React synth's "self-loop" representation is a v1 hack; spec §7.3 envisions cleaner state-handle nodes. Acceptable for now; refine in Phase 5.

---

## Execution handoff

Plan ready. Two options:

1. **Inline execution** with superpowers:executing-plans.
2. **Subagent-driven** with superpowers:subagent-driven-development.

13 tasks. Parsers (Tasks 1-3) are the biggest LOC; synthesizers (5-7) and queue (8-9) are small. Sonnet handles this comfortably.
