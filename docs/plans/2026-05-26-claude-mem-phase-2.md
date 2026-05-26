# claude-mem Phase 2 — Memory, Tasks, Summaries, Distillation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the durable memory layer (`remember` / `forget`), T2 LLM summaries, the task system (`plan_task` / `tasks`), end-of-session distillation (`claude-mem distill`), three more framework synthesizers (Django / Express / React hooks), and observability via `stats()` / `scopes()`. Phase 2 exit: a working session ends with a usable distilled memory set, and `plan_task` produces sub-tasks with attached bundles that a fresh session can pick up.

**Architecture:** Memory is a new layer on the existing unit/relation substrate — markdown files in `.claude-mem/memory/<scope>/<slug>.md` (user-authored truth) get indexed exactly like docs. Tasks are units of kind `task` with structured JSON metadata; relations of kind `child_task` form the tree. The LLM access path uses **MCP sampling** (server-side `sampling/createMessage`) as the primary implementation behind a small `LLMClient` protocol, with an Anthropic-SDK fallback retained as a one-task escape hatch if Claude Code doesn't expose sampling at runtime. Summaries are computed lazily-but-cached on `content_hash`; distillation is a separate CLI command that reads the Claude Code transcript JSONL and proposes memory writes for user confirmation.

**Tech Stack:** Phase 1 stack plus `prompt_toolkit` (interactive distill UX), `anthropic` (fallback LLM client only — not used in default path).

**Spec:** `docs/specs/2026-05-25-claude-mem-design.md`. This plan implements Phase 2 (§12 of spec) plus parts of §6 (Tasks/Handoff — `handoff` and `resume` stay in Phase 3) and §8 (Memory writes).

**Lessons carried from Phase 1 execution** (apply throughout):
- Use `rsplit(":", 1)[0]` on `source_ref` (Windows drive letter colons).
- Tests that walk parent dirs must mask ambient `~/.claude-mem` via `monkeypatch.setattr(Path, "is_dir", ...)`.
- Sonnet for implementer subagents; haiku tends to "improve" beyond scope.
- `tree-sitter-languages` doesn't ship Windows wheels — already using per-language packages.

---

## File Structure

New files in this phase:

**Memory layer**
- `src/claude_mem/units/memory.py` — Fact/Decision/Preference/Convention dataclasses over `Unit`
- `src/claude_mem/indexer/parsers/memory_md.py` — parser for `.claude-mem/memory/*.md`
- `src/claude_mem/memory/writer.py` — `remember()`, `forget()` write path with supersede detection

**LLM client**
- `src/claude_mem/llm/base.py` — `LLMClient` protocol
- `src/claude_mem/llm/mcp_sampling.py` — primary impl (asks the MCP host for sampling)
- `src/claude_mem/llm/anthropic_api.py` — escape-hatch impl, env-var-keyed (added in P2.16)
- `src/claude_mem/llm/factory.py` — selects implementation by env

**Summarizer**
- `src/claude_mem/summarizer/prompts.py` — fixed prompt templates
- `src/claude_mem/summarizer/summarize.py` — `summarize_unit(unit, llm) -> str | None`
- `src/claude_mem/summarizer/backfill.py` — finds units missing T2, drives summarizer

**Tasks**
- `src/claude_mem/tasks/model.py` — `Task` typed view over `Unit` with `kind="task"`
- `src/claude_mem/tasks/prompts.py` — fixed decomposition prompt
- `src/claude_mem/tasks/planner.py` — `plan_task()` orchestration

**Synthesizers (new)**
- `src/claude_mem/indexer/synthesizers/django_urls.py`
- `src/claude_mem/indexer/synthesizers/express_routes.py`
- `src/claude_mem/indexer/synthesizers/react_hooks.py`

**MCP tools (new)**
- `src/claude_mem/tools/remember.py`
- `src/claude_mem/tools/forget.py`
- `src/claude_mem/tools/scopes.py`
- `src/claude_mem/tools/stats.py`
- `src/claude_mem/tools/plan_task.py`
- `src/claude_mem/tools/tasks.py`

**Distillation**
- `src/claude_mem/distill/transcript.py` — locate + parse Claude Code session JSONL
- `src/claude_mem/distill/extract.py` — LLM call to propose memory writes
- `src/claude_mem/distill/confirm.py` — interactive confirm/edit UX

**Observability**
- `src/claude_mem/observability/counters.py` — process-local counters for `stats()`

**Tests**
- `tests/unit/test_memory_*.py`, `test_llm_*.py`, `test_summarizer*.py`, `test_tasks_*.py`, `test_synth_*.py`, `test_distill_*.py`
- `tests/integration/test_phase2_acceptance.py`

---

## Cross-cutting design decisions (read before starting)

### Memory markdown file format

A memory file lives at `<repo>/.claude-mem/memory/<scope>/<slug>.md` and is the source of truth — SQLite indexes are derived. Format:

```markdown
---
kind: decision           # fact | decision | preference | convention
scope: backend/auth      # required; matches dir path by default
confidence: 0.9          # optional, 0..1
supersedes: mem://decision/abc12345  # optional handle
created_at: 2026-05-26T10:00:00Z
---

We chose RS256 over HS256 so the API gateway can verify tokens without
holding the signing key.
```

Frontmatter is YAML. Body is the fact/decision text. The unit's `t1_header` is built from `kind` + truncated body (per spec §9.3). One file = one unit.

### Task metadata schema

For a unit with `kind="task"`, `metadata` is JSON:

```json
{
  "title": "Add token refresh endpoint",
  "intent": "5-line goal description",
  "status": "pending",
  "acceptance": ["GET /refresh returns new token", "Old token invalidated"],
  "context_handles": ["code://function/abc", "mem://decision/xyz"],
  "open_questions": [],
  "decisions_made": [],
  "session_id": null
}
```

Parent→child task edges live in the `relation` table with `kind="child_task"`.

### LLMClient protocol

```python
class LLMClient(Protocol):
    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str: ...
```

Two implementations in v1:
- `McpSamplingClient` (default) — requires the MCP tool handler to receive a `Context` and call `ctx.session.create_message()`. Hosts that don't support sampling will fail at call time with a clear error.
- `AnthropicApiClient` — env-var fallback (`ANTHROPIC_API_KEY`), shipped to give users an immediate working path while sampling support spreads.

Selection: `CLAUDE_MEM_LLM=mcp|anthropic` env var, defaults to `mcp`.

### Distillation transcript location

Claude Code stores session transcripts at `~/.claude/projects/<slug>/<session_id>.jsonl` where `<slug>` is a path-mangled repo path. The exact slug format is platform-specific; locate the most recent file by mtime under `~/.claude/projects/` matching the current repo. On Windows, `~` is `%USERPROFILE%`. JSONL format: one event per line, each with `type`, `message.role`, `message.content`.

If the transcript can't be found, `distill` accepts `--transcript <path>` as an explicit override.

---

## Task 0: Memory schema delta + Task kind validation

Phase 1 already allows `task` and `memory` layers in the schema. This task extends the `Unit.kind` validation surface (memory needs `fact`/`decision`/`preference`/`convention`; task needs `task`/`task_snapshot`) and adds a small typed metadata helper.

**Files:**
- Modify: `src/claude_mem/units/model.py` — add `KIND_VALID_FOR_LAYER` constants
- Create: `src/claude_mem/units/typed.py` — `metadata_json(unit) -> dict`, `with_metadata(unit, dict) -> Unit`
- Test: `tests/unit/test_typed_unit.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_typed_unit.py`:

```python
import pytest
from claude_mem.units.model import Unit
from claude_mem.units.typed import metadata_json, with_metadata, KIND_VALID_FOR_LAYER


def _u(**overrides) -> Unit:
    base = dict(
        id="mem://decision/a", layer="memory", kind="decision", scope="x",
        source_ref=None, content_hash="h", t1_header="header",
        created_at=0, last_seen_at=0,
    )
    base.update(overrides)
    return Unit(**base)


def test_metadata_json_parses_string():
    u = _u(metadata='{"a": 1, "b": "two"}')
    assert metadata_json(u) == {"a": 1, "b": "two"}


def test_metadata_json_none_returns_empty_dict():
    u = _u(metadata=None)
    assert metadata_json(u) == {}


def test_metadata_json_invalid_returns_empty():
    u = _u(metadata="not json")
    assert metadata_json(u) == {}


def test_with_metadata_serializes():
    u = _u()
    u2 = with_metadata(u, {"hello": "world"})
    assert u2.metadata == '{"hello": "world"}'
    assert u2.id == u.id


def test_kind_valid_for_layer_constants():
    assert "decision" in KIND_VALID_FOR_LAYER["memory"]
    assert "task" in KIND_VALID_FOR_LAYER["task"]
    assert "section" in KIND_VALID_FOR_LAYER["docs"]
    assert "function" in KIND_VALID_FOR_LAYER["code"]
```

- [ ] **Step 2: Confirm FAIL** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/claude_mem/units/typed.py`:

```python
from __future__ import annotations

import json
from typing import Any
from dataclasses import replace

from .model import Unit


KIND_VALID_FOR_LAYER: dict[str, set[str]] = {
    "memory": {"fact", "decision", "preference", "convention"},
    "task": {"task", "task_snapshot"},
    "docs": {"section", "frontmatter"},
    "code": {"function", "method", "class", "route", "interface", "module"},
}


def metadata_json(unit: Unit) -> dict[str, Any]:
    """Parse metadata as JSON. Returns {} for None, missing, or invalid."""
    if not unit.metadata:
        return {}
    try:
        v = json.loads(unit.metadata)
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def with_metadata(unit: Unit, data: dict[str, Any]) -> Unit:
    return replace(unit, metadata=json.dumps(data))
```

`src/claude_mem/units/model.py` — append at end:

```python
# Re-export for convenience; canonical home is typed.py
from .typed import KIND_VALID_FOR_LAYER  # noqa: E402,F401
```

(If a circular import surfaces, drop the re-export — typed.py is the canonical home.)

- [ ] **Step 4: Confirm PASS** — 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/units/typed.py src/claude_mem/units/model.py tests/unit/test_typed_unit.py
git commit -m "feat(units): typed metadata accessors and kind/layer validation table"
```

---

## Task 1: LLMClient protocol

**Files:**
- Create: `src/claude_mem/llm/__init__.py` (empty)
- Create: `src/claude_mem/llm/base.py`
- Test: `tests/unit/test_llm_base.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_llm_base.py`:

```python
from claude_mem.llm.base import LLMClient, LLMError


def test_protocol_has_complete():
    assert hasattr(LLMClient, "complete")


def test_llm_error_is_exception():
    e = LLMError("oops")
    assert isinstance(e, Exception)
    assert "oops" in str(e)
```

- [ ] **Step 2: FAIL** — import error.

- [ ] **Step 3: Implement**

`src/claude_mem/llm/base.py`:

```python
from __future__ import annotations

from typing import Protocol


class LLMError(Exception):
    """Raised by LLMClient implementations on any failure."""


class LLMClient(Protocol):
    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str: ...
```

- [ ] **Step 4: PASS** — 2 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/llm/__init__.py src/claude_mem/llm/base.py tests/unit/test_llm_base.py
git commit -m "feat(llm): LLMClient protocol and LLMError"
```

---

## Task 2: MCP sampling LLM client

This implementation requires a `Context` passed to MCP tool handlers. We won't wire it into all handlers yet — that happens incrementally as features need LLM access. For this task we just produce the client class and a unit test using a mock context.

**Files:**
- Create: `src/claude_mem/llm/mcp_sampling.py`
- Test: `tests/unit/test_llm_mcp_sampling.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_llm_mcp_sampling.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from claude_mem.llm.mcp_sampling import McpSamplingClient
from claude_mem.llm.base import LLMError


@pytest.mark.asyncio
async def test_complete_calls_create_message():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="text", text="hello back")]
    ))
    client = McpSamplingClient(ctx)
    out = await client.complete("sys", "usr", max_tokens=100)
    assert out == "hello back"
    ctx.session.create_message.assert_called_once()


@pytest.mark.asyncio
async def test_complete_passes_system_and_user():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="text", text="x")]
    ))
    await McpSamplingClient(ctx).complete("system text", "user text")
    kwargs = ctx.session.create_message.call_args.kwargs
    # System and user should appear in the request somewhere; we accept
    # whichever field name the SDK uses by inspecting all values for the strings.
    serialized = repr(kwargs)
    assert "system text" in serialized
    assert "user text" in serialized


@pytest.mark.asyncio
async def test_complete_raises_llmerror_on_underlying_failure():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(LLMError):
        await McpSamplingClient(ctx).complete("s", "u")


@pytest.mark.asyncio
async def test_complete_handles_no_text_content():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(return_value=MagicMock(content=[]))
    out = await McpSamplingClient(ctx).complete("s", "u")
    assert out == ""
```

- [ ] **Step 2: FAIL** — import error.

- [ ] **Step 3: Implement**

`src/claude_mem/llm/mcp_sampling.py`:

```python
from __future__ import annotations

from typing import Any

from .base import LLMClient, LLMError


class McpSamplingClient:
    """LLMClient that asks the MCP host for sampling via `ctx.session.create_message`.

    The exact MCP Python SDK API for sampling varies by version. We try the
    common shape first; if the SDK uses a different field name for the prompt
    or system, the test for `complete_passes_system_and_user` will surface that
    via serialized inspection of the call kwargs.
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        try:
            # Common SDK shape: pass a list of "messages" plus a "system_prompt".
            # If your SDK version uses different names, adapt here.
            result = await self.ctx.session.create_message(
                messages=[{"role": "user", "content": user}],
                system_prompt=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except TypeError:
            # Fallback: some SDK builds use `system=` instead of `system_prompt=`.
            try:
                result = await self.ctx.session.create_message(
                    messages=[{"role": "user", "content": user}],
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as e:
                raise LLMError(f"MCP sampling failed: {e}") from e
        except Exception as e:
            raise LLMError(f"MCP sampling failed: {e}") from e

        content = getattr(result, "content", None) or []
        for item in content:
            if getattr(item, "type", None) == "text":
                return getattr(item, "text", "") or ""
        return ""
```

- [ ] **Step 4: PASS** — 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/llm/mcp_sampling.py tests/unit/test_llm_mcp_sampling.py
git commit -m "feat(llm): MCP sampling client (primary LLM implementation)"
```

---

## Task 3: LLM factory + env-var selection

The factory chooses an implementation by env. For now `mcp` (default) returns a placeholder that errors if no Context is bound, since the MCP server hasn't been wired to provide Context to tool handlers yet (Task 5 wires it).

**Files:**
- Create: `src/claude_mem/llm/factory.py`
- Test: `tests/unit/test_llm_factory.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_llm_factory.py`:

```python
import pytest
from unittest.mock import MagicMock

from claude_mem.llm.factory import make_llm_client
from claude_mem.llm.mcp_sampling import McpSamplingClient
from claude_mem.llm.base import LLMError


def test_default_is_mcp(monkeypatch):
    monkeypatch.delenv("CLAUDE_MEM_LLM", raising=False)
    ctx = MagicMock()
    c = make_llm_client(ctx=ctx)
    assert isinstance(c, McpSamplingClient)


def test_explicit_mcp(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_LLM", "mcp")
    c = make_llm_client(ctx=MagicMock())
    assert isinstance(c, McpSamplingClient)


def test_mcp_without_ctx_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_LLM", "mcp")
    with pytest.raises(LLMError):
        make_llm_client(ctx=None)


def test_unknown_value_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_LLM", "bogus")
    with pytest.raises(LLMError):
        make_llm_client(ctx=MagicMock())
```

- [ ] **Step 2: FAIL** — import error.

- [ ] **Step 3: Implement**

`src/claude_mem/llm/factory.py`:

```python
from __future__ import annotations

import os
from typing import Any

from .base import LLMClient, LLMError
from .mcp_sampling import McpSamplingClient


def make_llm_client(*, ctx: Any | None = None) -> LLMClient:
    choice = os.environ.get("CLAUDE_MEM_LLM", "mcp").lower()
    if choice == "mcp":
        if ctx is None:
            raise LLMError(
                "MCP sampling client requires an MCP Context; "
                "ensure the tool handler is wired to receive one."
            )
        return McpSamplingClient(ctx)
    if choice == "anthropic":
        # Defer import until Task 16 (anthropic_api.py) lands.
        try:
            from .anthropic_api import AnthropicApiClient  # type: ignore
        except ImportError as e:
            raise LLMError(
                "anthropic LLM client not yet available; "
                "see Task 16 in the Phase 2 plan."
            ) from e
        return AnthropicApiClient()
    raise LLMError(f"unknown CLAUDE_MEM_LLM value: {choice!r}")
```

- [ ] **Step 4: PASS** — 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/llm/factory.py tests/unit/test_llm_factory.py
git commit -m "feat(llm): factory selects client by CLAUDE_MEM_LLM env var"
```

---

## Task 4: Memory markdown parser

Parses `.claude-mem/memory/*.md` files into memory units. Same shape as the docs Markdown parser but produces `layer="memory"`, kind from frontmatter, and respects `confidence` / `supersedes` fields.

**Files:**
- Create: `src/claude_mem/indexer/parsers/memory_md.py`
- Test: `tests/unit/test_parsers_memory.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_parsers_memory.py`:

```python
from pathlib import Path
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
    # supersedes is stored in metadata JSON, not in the model's superseded_by
    # (which points the *other* direction: this unit is superseded BY the value).
    # The orchestrator resolves the supersedes pointer in a later pass.
    import json
    meta = json.loads(u.metadata)
    assert meta["supersedes"] == "mem://decision/old123456"


def test_invalid_kind_raises(tmp_path: Path):
    import pytest
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
    assert not p.supports(Path("docs/readme.md"))  # not under memory/
    assert not p.supports(Path("x.py"))
```

- [ ] **Step 2: FAIL** — import error.

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/parsers/memory_md.py`:

```python
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import List

import yaml

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from ...units.typed import KIND_VALID_FOR_LAYER
from .base import ParseResult, now


VALID_KINDS = KIND_VALID_FOR_LAYER["memory"]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class MemoryMarkdownParser:
    def supports(self, path: Path) -> bool:
        if path.suffix.lower() not in (".md", ".markdown"):
            return False
        parts = [p.lower() for p in path.parts]
        try:
            i = parts.index(".claude-mem")
        except ValueError:
            return False
        return i + 1 < len(parts) and parts[i + 1] == "memory"

    def parse(self, path: Path, text: str) -> ParseResult:
        m = FRONTMATTER_RE.match(text)
        front: dict = {}
        body = text
        if m:
            front = yaml.safe_load(m.group(1)) or {}
            body = text[m.end():]

        kind = (front.get("kind") or "fact").lower()
        if kind not in VALID_KINDS:
            raise ValueError(
                f"{path}: invalid memory kind {kind!r}; "
                f"must be one of {sorted(VALID_KINDS)}"
            )
        scope = front.get("scope") or _default_scope(path)
        confidence = front.get("confidence")
        confidence = float(confidence) if confidence is not None else None
        supersedes = front.get("supersedes")
        body = body.strip()

        uid = make_handle("memory", kind, f"{path.as_posix()}", body)
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        header = t1_header(layer="memory", kind=kind, text=body)

        metadata = {"body": body}
        if supersedes:
            metadata["supersedes"] = supersedes

        unit = Unit(
            id=uid,
            layer="memory",
            kind=kind,
            scope=scope,
            source_ref=path.as_posix(),
            content_hash=content_hash,
            t1_header=header,
            created_at=now(),
            last_seen_at=now(),
            confidence=confidence,
            metadata=json.dumps(metadata),
        )
        return ParseResult(units=[unit])


def _default_scope(path: Path) -> str:
    """Derive scope from the path under .claude-mem/memory/."""
    parts = list(path.parts)
    try:
        i = [p.lower() for p in parts].index(".claude-mem")
        # parts[i+1] should be "memory"; scope = everything between memory/ and file
        scope_parts = parts[i + 2 : -1]
        return "/".join(scope_parts) if scope_parts else "root"
    except (ValueError, IndexError):
        return "root"
```

- [ ] **Step 4: PASS** — 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/parsers/memory_md.py tests/unit/test_parsers_memory.py
git commit -m "feat(parsers): Memory markdown parser with kind/scope/confidence frontmatter"
```

---

## Task 5: Indexer integration — pick MemoryMarkdownParser before the generic Markdown parser

`MemoryMarkdownParser.supports()` is more specific than `MarkdownParser.supports()`. To make the orchestrator dispatch correctly, register Memory parser FIRST in the `PARSERS` list.

**Files:**
- Modify: `src/claude_mem/indexer/orchestrator.py`
- Test: `tests/integration/test_indexer_memory.py`

- [ ] **Step 1: Failing test**

`tests/integration/test_indexer_memory.py`:

```python
from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex


def test_memory_md_indexed_as_memory_layer(tmp_repo: Path):
    mem_dir = tmp_repo / ".claude-mem" / "memory" / "backend" / "auth"
    mem_dir.mkdir(parents=True)
    (mem_dir / "rs256.md").write_text(
        "---\nkind: decision\nscope: backend/auth\nconfidence: 0.9\n---\n\nWe chose RS256.\n"
    )
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    stats = full_reindex(settings, embedder=None)
    conn = connect(settings.db_path)
    rows = conn.execute(
        "SELECT layer, kind, scope, confidence FROM unit WHERE layer='memory'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["layer"] == "memory"
    assert rows[0]["kind"] == "decision"
    assert rows[0]["scope"] == "backend/auth"
    assert abs(rows[0]["confidence"] - 0.9) < 1e-6


def test_memory_md_not_picked_up_by_docs_parser(tmp_repo: Path):
    """Memory file must not produce duplicate docs units."""
    mem_dir = tmp_repo / ".claude-mem" / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "x.md").write_text("---\nkind: fact\nscope: x\n---\n\nbody\n")
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    full_reindex(settings, embedder=None)
    conn = connect(settings.db_path)
    n_docs = conn.execute("SELECT COUNT(*) FROM unit WHERE layer='docs'").fetchone()[0]
    assert n_docs == 0
```

NOTE: Phase 1's walker currently SKIPS `.claude-mem/` entirely (see `SKIP_DIRS` in `walker.py`). This is correct for derived state (db.sqlite, blobs/) but excludes memory files. You need to change the walker to recurse INTO `.claude-mem/memory/` while still skipping the other contents. Update `walk_repo` to special-case this.

- [ ] **Step 2: Update walker**

`src/claude_mem/indexer/walker.py` — change `_walk` to allow `.claude-mem/memory` traversal:

```python
def _walk(dirpath: Path, in_state_memory: bool = False) -> Iterator[Path]:
    try:
        entries = list(dirpath.iterdir())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.is_dir():
            if entry.name == ".claude-mem":
                # Only descend into the memory/ subdir of state.
                mem = entry / "memory"
                if mem.is_dir():
                    yield from _walk(mem, in_state_memory=True)
                continue
            if entry.name in SKIP_DIRS:
                continue
            yield from _walk(entry, in_state_memory=in_state_memory)
        else:
            yield entry
```

The `in_state_memory` flag isn't strictly required (the parser checks the path itself), but it's useful documentation.

Verify the walker tests still pass: `pytest tests/unit/test_walker.py`.

- [ ] **Step 3: Register MemoryMarkdownParser FIRST in orchestrator**

`src/claude_mem/indexer/orchestrator.py`:

```python
from .parsers.memory_md import MemoryMarkdownParser
...
PARSERS: list[Parser] = [MemoryMarkdownParser(), PythonParser(), JsTsParser(), MarkdownParser()]
```

- [ ] **Step 4: Confirm new tests PASS, all prior tests still PASS.**

`.venv\Scripts\python -m pytest -q` should be Phase 1's 98 + (5 from Task 4 + 4 from Tasks 1-3 LLM scaffolding + 5 from Task 0 typed + 2 from this task) = 114 total. Adjust if some Phase 1 walker tests need updating because `.claude-mem` is no longer fully skipped.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/orchestrator.py src/claude_mem/indexer/walker.py tests/integration/test_indexer_memory.py
git commit -m "feat(indexer): ingest .claude-mem/memory/*.md as memory layer units"
```

---

## Task 6: `remember` write path (no MCP tool yet)

Pure write function — takes fact text + scope + kind, writes a memory markdown file AND upserts the SQLite unit. The MCP tool wrapper comes in Task 7.

**Files:**
- Create: `src/claude_mem/memory/__init__.py` (empty)
- Create: `src/claude_mem/memory/writer.py`
- Test: `tests/unit/test_memory_writer.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_memory_writer.py`:

```python
from pathlib import Path
import json
import pytest
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.memory.writer import remember, MemoryWriteResult
from claude_mem.units.typed import metadata_json


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_remember_creates_md_file(settings):
    result = remember(settings, fact="We use JWT.", scope="backend/auth", kind="decision")
    md_path = settings.memory_dir / "backend" / "auth" / f"{result.slug}.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "kind: decision" in content
    assert "scope: backend/auth" in content
    assert "We use JWT." in content


def test_remember_upserts_unit(settings):
    result = remember(settings, fact="We use JWT.", scope="backend/auth")
    repo = Repository(connect(settings.db_path))
    u = repo.get_unit(result.handle)
    assert u is not None
    assert u.layer == "memory"
    assert u.kind == "fact"  # default
    assert u.scope == "backend/auth"


def test_remember_default_kind_is_fact(settings):
    result = remember(settings, fact="X", scope="x")
    repo = Repository(connect(settings.db_path))
    assert repo.get_unit(result.handle).kind == "fact"


def test_remember_supersedes_marks_old_unit(settings):
    r1 = remember(settings, fact="We use HS256.", scope="backend/auth", kind="decision")
    r2 = remember(
        settings, fact="We use RS256.", scope="backend/auth", kind="decision",
        supersedes=r1.handle,
    )
    repo = Repository(connect(settings.db_path))
    old = repo.get_unit(r1.handle)
    assert old.superseded_by == r2.handle


def test_remember_invalid_kind_raises(settings):
    with pytest.raises(ValueError):
        remember(settings, fact="x", scope="x", kind="nonsense")


def test_remember_returns_result_struct(settings):
    r = remember(settings, fact="x", scope="y")
    assert isinstance(r, MemoryWriteResult)
    assert r.handle.startswith("memory://")
    assert r.slug
    assert r.path.exists()
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/memory/writer.py`:

```python
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..indexer.parsers.memory_md import MemoryMarkdownParser
from ..units.typed import KIND_VALID_FOR_LAYER


@dataclass(frozen=True)
class MemoryWriteResult:
    handle: str
    slug: str
    path: Path


VALID_KINDS = KIND_VALID_FOR_LAYER["memory"]


def remember(
    settings: Settings,
    *,
    fact: str,
    scope: str,
    kind: str = "fact",
    confidence: Optional[float] = None,
    supersedes: Optional[str] = None,
) -> MemoryWriteResult:
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid memory kind: {kind!r}")

    scope_dir = settings.memory_dir.joinpath(*scope.split("/"))
    scope_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(fact)
    path = scope_dir / f"{slug}.md"

    # If a file already exists with that slug, append a short hash to disambiguate.
    if path.exists():
        h = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:6]
        slug = f"{slug}-{h}"
        path = scope_dir / f"{slug}.md"

    frontmatter = {
        "kind": kind,
        "scope": scope,
        "created_at": _dt.datetime.utcnow().isoformat() + "Z",
    }
    if confidence is not None:
        frontmatter["confidence"] = confidence
    if supersedes:
        frontmatter["supersedes"] = supersedes

    body = fact.strip()
    md = "---\n"
    for k, v in frontmatter.items():
        md += f"{k}: {v}\n"
    md += "---\n\n"
    md += body + "\n"
    path.write_text(md, encoding="utf-8")

    # Parse it back through the same parser so the unit-construction is identical
    # to a normal indexer pass.
    parsed = MemoryMarkdownParser().parse(path, md)
    [unit] = parsed.units
    conn = connect(settings.db_path)
    repo = Repository(conn)
    repo.upsert_unit(unit)

    # If supersedes is set, mark the old unit.
    if supersedes:
        from dataclasses import replace
        old = repo.get_unit(supersedes)
        if old is not None:
            repo.upsert_unit(replace(old, superseded_by=unit.id))

    return MemoryWriteResult(handle=unit.id, slug=slug, path=path)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_chars: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_chars] or "memory"
```

- [ ] **Step 4: PASS** — 6 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/memory/__init__.py src/claude_mem/memory/writer.py tests/unit/test_memory_writer.py
git commit -m "feat(memory): remember() writes markdown + SQLite unit with supersede"
```

---

## Task 7: `remember` MCP tool

**Files:**
- Create: `src/claude_mem/tools/remember.py`
- Test: `tests/integration/test_mcp_remember.py`
- Modify: `src/claude_mem/server.py` — register the new tool

- [ ] **Step 1: Failing test**

`tests/integration/test_mcp_remember.py`:

```python
import json
from pathlib import Path
import pytest
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.tools.remember import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "remember"
    props = s.inputSchema["properties"]
    assert "fact" in props
    assert "scope" in props
    assert "kind" in props
    assert {"fact", "scope"}.issubset(s.inputSchema.get("required", []))


@pytest.mark.asyncio
async def test_handle_writes_memory(settings):
    out = await handle(settings, {"fact": "We use JWT.", "scope": "backend/auth"})
    payload = json.loads(out[0].text)
    assert payload["handle"].startswith("memory://")
    assert "path" in payload


@pytest.mark.asyncio
async def test_handle_invalid_kind_returns_error(settings):
    out = await handle(settings, {"fact": "x", "scope": "x", "kind": "bogus"})
    payload = json.loads(out[0].text)
    assert "error" in payload
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/tools/remember.py`:

```python
from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..memory.writer import remember


def tool_schema() -> Tool:
    return Tool(
        name="remember",
        description=(
            "Write a durable memory entry. Use when you learn something the user "
            "will care about across sessions: a decision, convention, preference, "
            "or fact about this repo. Returns an opaque handle and the markdown "
            "file path. Memory files live at .claude-mem/memory/<scope>/<slug>.md "
            "and are git-trackable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The text to remember"},
                "scope": {"type": "string", "description": "Scope, e.g. 'backend/auth'"},
                "kind": {
                    "type": "string",
                    "enum": ["fact", "decision", "preference", "convention"],
                    "default": "fact",
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "supersedes": {"type": "string", "description": "Handle of unit being superseded"},
            },
            "required": ["fact", "scope"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    try:
        result = remember(
            settings,
            fact=args["fact"],
            scope=args["scope"],
            kind=args.get("kind", "fact"),
            confidence=args.get("confidence"),
            supersedes=args.get("supersedes"),
        )
    except ValueError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(
        type="text",
        text=json.dumps({
            "handle": result.handle,
            "slug": result.slug,
            "path": str(result.path),
        }),
    )]
```

- [ ] **Step 4: Register in `server.py`**

In `build_server`, add the import:

```python
from .tools import remember as remember_tool
```

In `_list`, add `remember_tool.tool_schema()` to the returned list.
In `_call`, add:

```python
if name == "remember":
    return await remember_tool.handle(settings or Settings.discover(), arguments)
```

(`remember` doesn't need an embedder.)

- [ ] **Step 5: PASS** — 3 new + existing MCP server `test_list_tools` must now also see `remember`. Update that test if it asserts an exact list.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/tools/remember.py src/claude_mem/server.py tests/integration/test_mcp_remember.py
git commit -m "feat(tools): remember MCP tool"
```

---

## Task 8: `forget` write path + MCP tool

`forget(handle)` marks a memory unit as tombstoned by setting `superseded_by` to a special sentinel `tombstone://`. Forget DOES NOT delete the markdown file — it appends `tombstoned: true` to the frontmatter so the file stays human-readable and re-indexing preserves the state.

**Files:**
- Modify: `src/claude_mem/memory/writer.py` — add `forget()`
- Create: `src/claude_mem/tools/forget.py`
- Test: `tests/unit/test_memory_forget.py`
- Test: `tests/integration/test_mcp_forget.py`

- [ ] **Step 1: Failing tests**

`tests/unit/test_memory_forget.py`:

```python
import pytest
from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.db.repository import Repository
from claude_mem.db.connection import connect
from claude_mem.memory.writer import remember, forget, TOMBSTONE_HANDLE


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_forget_marks_superseded_by_tombstone(settings):
    r = remember(settings, fact="X", scope="x")
    forget(settings, handle=r.handle)
    repo = Repository(connect(settings.db_path))
    u = repo.get_unit(r.handle)
    assert u.superseded_by == TOMBSTONE_HANDLE


def test_forget_updates_markdown_frontmatter(settings):
    r = remember(settings, fact="X", scope="x")
    forget(settings, handle=r.handle)
    assert "tombstoned: true" in r.path.read_text()


def test_forget_unknown_handle_raises(settings):
    with pytest.raises(KeyError):
        forget(settings, handle="memory://decision/zzzzzzzz")


def test_forget_only_works_on_memory_layer(settings):
    # Forget refuses to tombstone non-memory units.
    repo = Repository(connect(settings.db_path))
    from claude_mem.units.model import Unit
    repo.upsert_unit(Unit(
        id="code://function/a", layer="code", kind="function", scope="x",
        source_ref=None, content_hash="h", t1_header="t", created_at=0, last_seen_at=0,
    ))
    with pytest.raises(ValueError):
        forget(settings, handle="code://function/a")
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement `forget()` in `writer.py`**

Append:

```python
TOMBSTONE_HANDLE = "tombstone://"


def forget(settings: Settings, *, handle: str) -> None:
    conn = connect(settings.db_path)
    repo = Repository(conn)
    unit = repo.get_unit(handle)
    if unit is None:
        raise KeyError(handle)
    if unit.layer != "memory":
        raise ValueError(f"forget() only operates on memory units; got {unit.layer}")

    # Update the markdown file (if it still exists).
    if unit.source_ref:
        path = Path(unit.source_ref)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            # Insert tombstoned: true after the opening --- if not already there.
            if "tombstoned: true" not in text:
                text = re.sub(r"^(---\n)", r"\1tombstoned: true\n", text, count=1)
                path.write_text(text, encoding="utf-8")

    from dataclasses import replace
    repo.upsert_unit(replace(unit, superseded_by=TOMBSTONE_HANDLE))
```

(`re` and `Path` and `Repository` already imported at the top of the file.)

- [ ] **Step 4: Implement `forget` MCP tool**

`src/claude_mem/tools/forget.py`:

```python
from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..memory.writer import forget


def tool_schema() -> Tool:
    return Tool(
        name="forget",
        description=(
            "Tombstone a memory unit by handle. Marks the unit as superseded; "
            "appends `tombstoned: true` to the markdown frontmatter (file is NOT "
            "deleted). Use when a memory has become wrong or obsolete."
        ),
        inputSchema={
            "type": "object",
            "properties": {"handle": {"type": "string"}},
            "required": ["handle"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    try:
        forget(settings, handle=args["handle"])
        return [TextContent(type="text", text=json.dumps({"ok": True}))]
    except (KeyError, ValueError) as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
```

Register in `server.py` (add to import list, `_list`, and `_call`).

- [ ] **Step 5: PASS** + commit

```
git add src/claude_mem/memory/writer.py src/claude_mem/tools/forget.py src/claude_mem/server.py tests/unit/test_memory_forget.py tests/integration/test_mcp_forget.py
git commit -m "feat(memory): forget() tombstones memory units; MCP tool exposed"
```

(Write the MCP test in this commit too — mirror Task 7's pattern: schema test + two handle/error tests.)

---

## Task 9: `scopes` MCP tool

Lists known scopes for the current repo with unit counts.

**Files:**
- Create: `src/claude_mem/tools/scopes.py`
- Test: `tests/integration/test_mcp_scopes.py`
- Modify: `src/claude_mem/server.py`

- [ ] **Step 1: Failing test**

`tests/integration/test_mcp_scopes.py`:

```python
import json
import pytest
from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.scopes import handle, tool_schema


@pytest.fixture
def indexed(tmp_repo: Path):
    (tmp_repo / "backend").mkdir()
    (tmp_repo / "backend" / "auth").mkdir()
    (tmp_repo / "backend" / "auth" / "jwt.py").write_text("def x(): pass\n")
    (tmp_repo / "frontend").mkdir()
    (tmp_repo / "frontend" / "ui.py").write_text("def y(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "scopes"


@pytest.mark.asyncio
async def test_lists_scopes_with_counts(indexed):
    out = await handle(indexed, {})
    payload = json.loads(out[0].text)
    by_scope = {s["scope"]: s["count"] for s in payload["scopes"]}
    assert "backend/auth" in by_scope
    assert "frontend" in by_scope
    assert all(c > 0 for c in by_scope.values())
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/tools/scopes.py`:

```python
from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..db.connection import connect


def tool_schema() -> Tool:
    return Tool(
        name="scopes",
        description="List known scopes for this repo with unit counts.",
        inputSchema={"type": "object", "properties": {}},
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    conn = connect(settings.db_path)
    rows = conn.execute(
        "SELECT scope, COUNT(*) AS n FROM unit "
        "WHERE superseded_by IS NULL "
        "GROUP BY scope ORDER BY n DESC"
    ).fetchall()
    payload = {"scopes": [{"scope": r["scope"], "count": r["n"]} for r in rows]}
    return [TextContent(type="text", text=json.dumps(payload))]
```

Register in server. Commit:

```
git add src/claude_mem/tools/scopes.py src/claude_mem/server.py tests/integration/test_mcp_scopes.py
git commit -m "feat(tools): scopes MCP tool"
```

---

## Task 10: Observability counters + `stats` MCP tool

Process-local counters track tool-call activity and (later) fallback-to-native-tool rate. v1 just exposes basic counts.

**Files:**
- Create: `src/claude_mem/observability/__init__.py` (empty)
- Create: `src/claude_mem/observability/counters.py`
- Create: `src/claude_mem/tools/stats.py`
- Test: `tests/unit/test_counters.py`
- Test: `tests/integration/test_mcp_stats.py`

- [ ] **Step 1: Failing tests**

`tests/unit/test_counters.py`:

```python
from claude_mem.observability.counters import Counters, reset_counters, get_counters


def test_default_zero():
    reset_counters()
    c = get_counters()
    assert c.recall_calls == 0
    assert c.trace_calls == 0
    assert c.expand_calls == 0
    assert c.remember_calls == 0


def test_increment():
    reset_counters()
    c = get_counters()
    c.recall_calls += 1
    c.recall_calls += 1
    assert get_counters().recall_calls == 2
```

`tests/integration/test_mcp_stats.py`:

```python
import json
import pytest
from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.stats import handle, tool_schema


@pytest.fixture
def indexed(tmp_repo: Path):
    (tmp_repo / "x.py").write_text("def x(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)
    return s


def test_schema():
    assert tool_schema().name == "stats"


@pytest.mark.asyncio
async def test_returns_counts(indexed):
    out = await handle(indexed, {})
    payload = json.loads(out[0].text)
    assert "total_units" in payload
    assert "by_layer" in payload
    assert "counters" in payload
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/observability/counters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Counters:
    recall_calls: int = 0
    trace_calls: int = 0
    expand_calls: int = 0
    remember_calls: int = 0
    forget_calls: int = 0
    plan_task_calls: int = 0
    summarize_llm_calls: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


_COUNTERS = Counters()


def get_counters() -> Counters:
    return _COUNTERS


def reset_counters() -> None:
    global _COUNTERS
    _COUNTERS = Counters()
```

`src/claude_mem/tools/stats.py`:

```python
from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..db.connection import connect
from ..observability.counters import get_counters


def tool_schema() -> Tool:
    return Tool(
        name="stats",
        description="Index size, layer breakdown, and tool-call counters.",
        inputSchema={"type": "object", "properties": {}},
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    conn = connect(settings.db_path)
    total = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    by_layer_rows = conn.execute(
        "SELECT layer, COUNT(*) AS n FROM unit GROUP BY layer"
    ).fetchall()
    n_rels = conn.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    payload = {
        "total_units": total,
        "by_layer": {r["layer"]: r["n"] for r in by_layer_rows},
        "total_relations": n_rels,
        "counters": get_counters().to_dict(),
    }
    return [TextContent(type="text", text=json.dumps(payload))]
```

Register in server. Increment counters in the existing tool handlers (`recall.py`, `trace.py`, `expand.py`, `remember.py`, `forget.py`) — one line each at the top of `handle`.

- [ ] **Step 4: PASS** — 2 unit + 2 integration. Commit:

```
git add src/claude_mem/observability/ src/claude_mem/tools/stats.py src/claude_mem/server.py \
        src/claude_mem/tools/recall.py src/claude_mem/tools/trace.py src/claude_mem/tools/expand.py \
        src/claude_mem/tools/remember.py src/claude_mem/tools/forget.py \
        tests/unit/test_counters.py tests/integration/test_mcp_stats.py
git commit -m "feat(observability): counters + stats MCP tool"
```

---

## Task 11: Summarizer prompts + `summarize_unit`

Pure function that takes a `Unit` and an `LLMClient`, returns the T2 summary string (or None on failure).

**Files:**
- Create: `src/claude_mem/summarizer/__init__.py` (empty)
- Create: `src/claude_mem/summarizer/prompts.py`
- Create: `src/claude_mem/summarizer/summarize.py`
- Test: `tests/unit/test_summarizer.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_summarizer.py`:

```python
import pytest
from unittest.mock import AsyncMock
from claude_mem.summarizer.summarize import summarize_unit
from claude_mem.units.model import Unit


def _u(layer, kind, body):
    return Unit(
        id=f"{layer}://{kind}/a", layer=layer, kind=kind, scope="x",
        source_ref=None, content_hash="h", t1_header="t",
        created_at=0, last_seen_at=0,
        metadata=body,
    )


@pytest.mark.asyncio
async def test_summarize_function_unit():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Calls verify_user, returns token.")
    u = _u("code", "function", "def login(user, pw):\n    if verify_user(user, pw):\n        return issue_token(user)")
    summary = await summarize_unit(u, llm)
    assert "verify_user" in summary
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_section_unit_uses_doc_prompt():
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="X is described.")
    u = _u("docs", "section", "# Authentication\n\nWe use POST /login...")
    await summarize_unit(u, llm)
    args = llm.complete.call_args
    # System prompt should mention "documentation" or "doc"
    assert "doc" in args.kwargs.get("system", args.args[0]).lower()


@pytest.mark.asyncio
async def test_summarize_memory_unit_returns_none():
    # Memory bodies are already short; no need to summarize.
    llm = AsyncMock()
    u = _u("memory", "decision", "We use JWT.")
    summary = await summarize_unit(u, llm)
    assert summary is None
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_handles_llm_error():
    from claude_mem.llm.base import LLMError
    llm = AsyncMock(); llm.complete = AsyncMock(side_effect=LLMError("nope"))
    u = _u("code", "function", "def x(): pass")
    summary = await summarize_unit(u, llm)
    assert summary is None
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/summarizer/prompts.py`:

```python
CODE_SYSTEM = """\
You produce one-sentence to short-paragraph summaries of code units for retrieval.

Constraints:
- Maximum 100 tokens.
- State what the code does, not how it's implemented.
- Mention key callees and external dependencies by name if any.
- No preamble. No "This function...". Start with a verb.
"""

DOCS_SYSTEM = """\
You produce short summaries of documentation sections for retrieval.

Constraints:
- Maximum 100 tokens.
- Capture the section's main claim or instruction, not its examples.
- No preamble. Use plain prose.
"""

USER_TEMPLATE = "Summarize this {kind}:\n\n```\n{body}\n```"
```

`src/claude_mem/summarizer/summarize.py`:

```python
from __future__ import annotations

from typing import Optional

from ..llm.base import LLMClient, LLMError
from ..units.model import Unit
from .prompts import CODE_SYSTEM, DOCS_SYSTEM, USER_TEMPLATE


async def summarize_unit(unit: Unit, llm: LLMClient) -> Optional[str]:
    if unit.layer == "memory":
        return None  # memory bodies are already terse
    body = unit.metadata or unit.t1_header
    if not body or len(body) < 80:
        return None  # too short to be worth summarizing
    system = CODE_SYSTEM if unit.layer == "code" else DOCS_SYSTEM
    user = USER_TEMPLATE.format(kind=unit.kind, body=body[:8000])
    try:
        return await llm.complete(system=system, user=user, max_tokens=200, temperature=0.0)
    except LLMError:
        return None
```

- [ ] **Step 4: PASS** — 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/summarizer/ tests/unit/test_summarizer.py
git commit -m "feat(summarizer): summarize_unit() with code/docs prompts; memory skipped"
```

---

## Task 12: Summary backfill driver

Iterates over units with `t2_summary IS NULL`, calls `summarize_unit`, writes back via `upsert_unit`. Skipped if `LLMClient` raises (already handled per-unit).

**Files:**
- Create: `src/claude_mem/summarizer/backfill.py`
- Test: `tests/integration/test_backfill.py`

- [ ] **Step 1: Failing test**

`tests/integration/test_backfill.py`:

```python
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.summarizer.backfill import backfill_summaries


@pytest.mark.asyncio
async def test_backfill_populates_t2(tmp_repo: Path):
    (tmp_repo / "x.py").write_text(
        "def f(a, b):\n    # some non-trivial body\n    return a + b\n\n"
        "def g():\n    " + "x = 1\n    " * 30 + "return x\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Generated summary.")
    stats = await backfill_summaries(s, llm=llm)

    assert stats["units_summarized"] >= 1
    conn = connect(s.db_path)
    n_with_t2 = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
    ).fetchone()[0]
    assert n_with_t2 >= 1


@pytest.mark.asyncio
async def test_backfill_skips_units_with_existing_t2(tmp_repo: Path):
    (tmp_repo / "x.py").write_text("def f():\n    " + "x = 1\n    " * 30 + "return x\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    llm = AsyncMock(); llm.complete = AsyncMock(return_value="first summary")
    await backfill_summaries(s, llm=llm)
    first_call_count = llm.complete.call_count

    # Second pass: nothing new to summarize.
    await backfill_summaries(s, llm=llm)
    assert llm.complete.call_count == first_call_count
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/summarizer/backfill.py`:

```python
from __future__ import annotations

from dataclasses import replace

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository, _row_to_unit  # type: ignore[attr-defined]
from ..llm.base import LLMClient
from .summarize import summarize_unit


async def backfill_summaries(settings: Settings, *, llm: LLMClient, limit: int = 1000) -> dict:
    conn = connect(settings.db_path)
    repo = Repository(conn)
    rows = conn.execute(
        "SELECT * FROM unit WHERE t2_summary IS NULL AND layer IN ('code','docs') "
        "ORDER BY last_seen_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    n = 0
    for row in rows:
        u = _row_to_unit(row)
        summary = await summarize_unit(u, llm)
        if summary:
            repo.upsert_unit(replace(u, t2_summary=summary))
            n += 1
    return {"units_summarized": n, "units_considered": len(rows)}
```

Note the import of `_row_to_unit` is intentionally private; consider promoting it to a public helper in repository.py if reused elsewhere. For now keep the type: ignore.

- [ ] **Step 4: PASS** + commit

```
git add src/claude_mem/summarizer/backfill.py tests/integration/test_backfill.py
git commit -m "feat(summarizer): backfill T2 summaries for units missing them"
```

---

## Task 13: Django URL synthesizer

Pattern: `path("login/", views.login, name="login")` in `urls.py`, emit `route_to` from a synthetic route unit → the resolved handler.

**Files:**
- Create: `src/claude_mem/indexer/synthesizers/django_urls.py`
- Test: `tests/unit/test_synth_django.py`
- Modify: `src/claude_mem/indexer/orchestrator.py` — include DjangoUrlsSynthesizer in the synth list

(The full code is structurally identical to FlaskRoutesSynthesizer from Phase 1; pattern-match `path(...)` and `re_path(...)`. Test covers `urls.py` recognition, dotted handler resolution (`views.login` → handler function in views.py), and the case where the handler isn't found.)

- [ ] Test stub showing the expected interface (write the full body):

```python
def test_django_path_emits_route_edge(tmp_path):
    (tmp_path / "views.py").write_text(
        "def login(request):\n    return None\n"
    )
    (tmp_path / "urls.py").write_text(
        "from django.urls import path\nfrom . import views\n"
        "urlpatterns = [path('login/', views.login, name='login')]\n"
    )
    # parse both files, run synth, assert one route unit + one route_to relation
    ...
```

Detailed regex (start here):

```python
DJANGO_PATH_RE = re.compile(
    r"""(?:path|re_path)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*
        (?P<handler>[\w.]+)""",
    re.VERBOSE,
)
```

When `handler` contains a dot (`views.login`), strip the module prefix and match against function names in any `views.py` in the same directory. Otherwise match within the same file.

- [ ] Implement, test, register synthesizer in `orchestrator.py` (append to the synthesizer list), commit:

```
git add src/claude_mem/indexer/synthesizers/django_urls.py src/claude_mem/indexer/orchestrator.py tests/unit/test_synth_django.py
git commit -m "feat(synth): Django path/re_path route synthesizer"
```

---

## Task 14: Express routes synthesizer

Pattern: `app.get('/x', handler)` or `app.post(...)` etc. The handler can be an inline arrow function, a named function reference, or a member expression. Match the named-function-reference case for v1; emit a route unit + `route_to` to the resolved handler function in the same file.

**Files:**
- Create: `src/claude_mem/indexer/synthesizers/express_routes.py`
- Test: `tests/unit/test_synth_express.py`
- Modify: `orchestrator.py`

(Same structure as Flask/Django. Regex: `app\.(get|post|put|delete|patch)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*(?P<handler>\w+)\s*\)`.)

Commit:
```
git commit -m "feat(synth): Express route synthesizer for named-function handlers"
```

---

## Task 15: React hooks synthesizer

Emits `mutates_state_of` edges from `useState`/`useReducer` setter call sites → the component function unit. v1 is conservative: only match `setX(...)` where `[x, setX] = useState(...)` was declared in the same component function.

**Files:**
- Create: `src/claude_mem/indexer/synthesizers/react_hooks.py`
- Test: `tests/unit/test_synth_react.py`
- Modify: `orchestrator.py`

This synthesizer is more complex because it requires intra-function analysis. Acceptable v1 simplification: regex over the function body — if `\[(\w+),\s*(set\w+)\]\s*=\s*useState\(` appears, AND any subsequent `set\w+\(` matches the setter name, emit an edge from the call-site-function to itself. (It's a self-loop in v1; the "where the state lives" annotation is what matters for retrieval, not graph traversal.)

Commit:
```
git commit -m "feat(synth): React hooks synthesizer for useState setter discovery"
```

---

## Task 16: (CONDITIONAL) Anthropic API LLM client fallback

**Only land this if MCP sampling is confirmed unsupported by Claude Code at this time.** If sampling works, skip this task — `make_llm_client(ctx=None)` will already raise a clear error.

**Files:**
- Create: `src/claude_mem/llm/anthropic_api.py`
- Test: `tests/unit/test_llm_anthropic.py` (marked `slow` if it hits the real API; otherwise mock)

```python
import os
from anthropic import AsyncAnthropic
from .base import LLMClient, LLMError


class AnthropicApiClient:
    def __init__(self, model: str = "claude-haiku-4-5"):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY not set")
        self.client = AsyncAnthropic(api_key=key)
        self.model = model

    async def complete(self, system: str, user: str, *, max_tokens: int = 1024, temperature: float = 0.0) -> str:
        try:
            resp = await self.client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            raise LLMError(f"Anthropic API call failed: {e}") from e
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "")
        return ""
```

Commit:
```
git commit -m "feat(llm): Anthropic API fallback client (selected via CLAUDE_MEM_LLM=anthropic)"
```

---

## Task 17: Task model helpers

Typed accessors over `Unit` with `kind="task"`.

**Files:**
- Create: `src/claude_mem/tasks/__init__.py` (empty)
- Create: `src/claude_mem/tasks/model.py`
- Test: `tests/unit/test_task_model.py`

- [ ] Spec the dataclass:

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

TaskStatus = Literal["pending", "active", "done", "blocked"]


@dataclass
class TaskView:
    handle: str
    title: str
    intent: str
    status: TaskStatus
    scope: str
    acceptance: list[str] = field(default_factory=list)
    context_handles: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    parent: Optional[str] = None
    session_id: Optional[str] = None


def task_to_unit_metadata(t: TaskView) -> dict: ...
def unit_metadata_to_task(unit) -> TaskView: ...
```

Write the tests (round-trip metadata, default fields, status validation), implement, commit:

```
git commit -m "feat(tasks): TaskView dataclass with Unit metadata serialization"
```

---

## Task 18: `plan_task` decomposition prompt + planner

The planner runs an LLM call with this system prompt:

```
You are decomposing a software task into 2-6 INDEPENDENT sub-tasks.

For each sub-task produce exactly:
- title: 1-line imperative
- intent: 3-5 sentences describing the goal and approach
- acceptance: 2-4 bullet points of "done when..."

Sub-tasks must be independently executable: each one should be assignable
to a fresh agent session and completable without the others.

Respond ONLY with valid JSON of the form:
{"subtasks": [{"title": "...", "intent": "...", "acceptance": ["..."]}]}

No preamble. No markdown. JSON only.
```

User prompt format:
```
{recall_bundle}

Decompose this task:
{intent}
```

`{recall_bundle}` is the concatenated content of a `recall(query=intent, budget=4000)` pass — the planner pre-fetches context so decomposition is grounded.

**Files:**
- Create: `src/claude_mem/tasks/prompts.py`
- Create: `src/claude_mem/tasks/planner.py`
- Test: `tests/unit/test_planner.py`

- [ ] Write tests with a mocked LLM returning a known JSON payload; verify the planner parses correctly, falls back gracefully on malformed JSON (return a single-subtask "could not decompose" entry), and writes child task units with `child_task` relations.

- [ ] Implement, commit:

```
git commit -m "feat(tasks): plan_task() decomposition with grounded context"
```

---

## Task 19: `plan_task` MCP tool wiring

The tool handler receives a `Context` (from MCP) and uses `make_llm_client(ctx=ctx)`. This is the first tool wired to take Context — note the call site change in `server.py`'s `@server.call_tool()` decorator: pass `ctx` through to handlers that need it.

**Files:**
- Create: `src/claude_mem/tools/plan_task.py`
- Test: `tests/integration/test_mcp_plan_task.py` (mock the Context's `create_message`)
- Modify: `server.py`

Schema:
```python
inputSchema={
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "parent_id": {"type": "string"},
        "budget": {"type": "integer", "default": 6000},
    },
    "required": ["intent"],
}
```

Handler returns the task tree (root + immediate children with their attached handles).

Commit:
```
git commit -m "feat(tools): plan_task MCP tool (Context-aware, calls LLM via sampling)"
```

---

## Task 20: `tasks` MCP tool — list tasks

Filter on status, scope, and recency. Pure query.

**Files:**
- Create: `src/claude_mem/tools/tasks.py`
- Test: `tests/integration/test_mcp_tasks.py`

Schema:
```python
inputSchema={
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pending", "active", "done", "blocked"]},
        "scope": {"type": "string"},
        "since_days": {"type": "integer"},
    },
}
```

Return list of `TaskView` dicts.

Commit:
```
git commit -m "feat(tools): tasks listing MCP tool"
```

---

## Task 21: Distillation — transcript locator + JSONL parser

**Files:**
- Create: `src/claude_mem/distill/__init__.py` (empty)
- Create: `src/claude_mem/distill/transcript.py`
- Test: `tests/unit/test_transcript.py`

`find_latest_transcript()` looks under `~/.claude/projects/` for the most recently modified `*.jsonl` whose path-mangled slug appears to match `settings.repo_root`. Provide `--transcript PATH` as an override-able input — `find_latest_transcript()` accepts an explicit path and returns it untouched if given.

`parse_transcript(path) -> list[ChatTurn]` reads JSONL, normalizes each line to `{role, content}` regardless of which event-type wrapper it has.

- [ ] Tests: fixture JSONL with 3 turns, parsing extracts user + assistant content.

```
git commit -m "feat(distill): transcript locator + JSONL parser"
```

---

## Task 22: Distillation — LLM extraction

`extract_memories(transcript, llm) -> list[Proposal]` where `Proposal = {fact, scope, kind, confidence}`. Uses this system prompt:

```
You extract DURABLE engineering knowledge from a Claude Code session transcript.

Durable means: a decision, convention, preference, or fact about THIS repo that
will still be relevant in a future session. NOT ephemeral debugging steps,
incidental tool outputs, or work-in-progress reasoning.

For each durable item, propose:
- kind: fact | decision | preference | convention
- scope: a slash-path like "backend/auth" or "tooling/build" — match the
  conceptual area the item applies to
- confidence: 0..1 (1.0 means the user stated this explicitly; lower means
  inferred)
- fact: 1-2 sentence statement, no preamble

Respond ONLY with JSON: {"proposals": [{"kind": ..., "scope": ..., "confidence": ..., "fact": ...}]}

If there's nothing durable, return {"proposals": []}.
```

**Files:**
- Create: `src/claude_mem/distill/extract.py`
- Test: `tests/unit/test_distill_extract.py` (mocked LLM)

```
git commit -m "feat(distill): extract_memories() proposes durable facts from a transcript"
```

---

## Task 23: Distillation — interactive confirm CLI

`claude-mem distill [--transcript PATH] [--yes]` runs the pipeline:
1. Locate transcript (or use `--transcript`).
2. Parse, extract proposals.
3. For each proposal, show it and prompt `[a]ccept / [e]dit / [s]kip / [q]uit`.
4. On accept, call `remember(...)`.

Uses `prompt_toolkit` for the interactive prompts. `--yes` flag accepts all without prompting (useful for testing/CI).

**Files:**
- Create: `src/claude_mem/distill/confirm.py`
- Modify: `src/claude_mem/cli.py` — register `distill` subcommand
- Test: `tests/integration/test_distill_cli.py` (uses `--yes` and a synthetic transcript)

Commit:
```
git commit -m "feat(distill): interactive claude-mem distill subcommand"
```

---

## Task 24: Phase 2 acceptance test

End-to-end: on a small Flask repo:
1. Run full reindex (Phase 1 features).
2. Call `remember(...)` for two facts.
3. Run `backfill_summaries(...)` with a fake LLM that returns canned summaries.
4. Call `plan_task("add token refresh")` with a fake LLM that returns 2 child subtasks.
5. Run `distill` with `--yes --transcript fixtures/synthetic_session.jsonl`.
6. Assert: memory units exist with confidence set; T2 summaries populated; child tasks have non-empty `context_handles`; distill wrote at least one new memory unit.

**Files:**
- Create: `tests/integration/fixtures/synthetic_session.jsonl`
- Create: `tests/integration/test_phase2_acceptance.py`

Commit:
```
git commit -m "test: phase 2 acceptance — memory + summaries + plan_task + distill"
```

---

## Task 25: README update + phase tag

- [ ] Update `README.md` — add a "Phase 2" section listing the new tools (`remember`, `forget`, `scopes`, `stats`, `plan_task`, `tasks`) and the new `distill` subcommand. Keep total length ≤ 60 lines.

- [ ] Update the **Status** line: `Phase 2 — memory, summaries, tasks, distillation. Handoff and resume land in Phase 3.`

```
git add README.md
git commit -m "docs: Phase 2 README with new tools and distill command"
git tag -a phase-2-complete -m "Phase 2: memory, summaries, tasks, distillation"
```

---

## Self-review checklist

After all tasks complete:

**1. Spec coverage** — every Phase 2 deliverable from spec §12 maps to a task:
- Memory layer schema + write path → Tasks 0, 4, 5, 6, 8
- `remember`, `forget`, `scopes`, `stats` → Tasks 7, 8, 9, 10
- T2 LLM summaries via Claude Code auth → Tasks 1, 2, 3, 11, 12 (with optional fallback in 16)
- `plan_task`, `tasks` → Tasks 17, 18, 19, 20
- Distillation CLI → Tasks 21, 22, 23
- Remaining v1 synthesizers (Django, Express, React) → Tasks 13, 14, 15
- Stats fallback-to-native metric → Task 10 (counters in place; advanced telemetry deferred)

**2. Placeholder scan** — none. All code blocks are concrete; "implement appropriate body" appears nowhere. The exceptions (Tasks 13, 14, 15, 17, 18, 19, 20, 21, 22, 23 with shorter spec text) explicitly show the schema/regex/prompt and direct the implementer to follow the Task 6/7 pattern for shape. The implementer will need to write the tests themselves for those — that's intentional, not a placeholder, but if you want fuller TDD specifications for those tasks, expand them following Tasks 6/7 as the model.

**3. Type consistency** — `LLMClient`, `TaskView`, `MemoryWriteResult`, `Proposal` all defined in named tasks before use.

**4. Open questions to resolve at execution time:**
- MCP sampling SDK API exact shape (Task 2 has fallback try/except built in).
- Claude Code transcript JSONL exact event format (Task 21 may need adjustment based on actual file inspection).
- React hooks synth precision/recall on real React codebases — start conservative; tune in Phase 3.
- `summarize_unit` length threshold (currently 80 chars) — calibrate against a real repo in Task 12 follow-up.

---

## Execution handoff

Plan ready. Two execution options:

1. **Subagent-Driven** (recommended) — start a new Claude Code session, point it at this plan, dispatch a fresh subagent per task with the two-stage review loop (spec compliance → code quality). Use sonnet by default; Tasks 13/14/15/22 may benefit from extending with worked examples first.

2. **Inline execution** — execute tasks in a single session using `superpowers:executing-plans`.

**Recommended:** start a fresh session for Phase 2 — Phase 1's session has substantial context that's mostly noise for Phase 2 implementation work. The Phase 1 lessons that matter (Windows path handling, tree-sitter API, test isolation) are documented at the top of this plan.
