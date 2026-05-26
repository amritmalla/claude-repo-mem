# claude-mem Phase 3 — Handoff, Resume, Watcher, Skills — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land `handoff` / `resume` so a task can survive a session boundary; ship a file watcher that keeps the index hot while `claude-mem serve` is running; ship companion skill content (`claude-mem-recall`, `claude-mem-trace`, `claude-mem-handoff`) inside the plugin tree.

**Architecture:** Handoff renders the current task's state (intent, decisions, open questions, recent memory writes, context handles) to a markdown file under `.claude-mem/handoffs/<task_id>.md` and writes a `task_snapshot` unit. Resume reads that snapshot back, re-runs budgeted fill on the captured `context_handles`, and returns the same shape as `recall` — so a fresh session can pick up at ~2-4k tokens fully oriented. The watcher uses `watchdog` with a 750 ms debounce and calls into a new `incremental_reindex(paths)` codepath that only re-parses changed files. Skills are markdown shipped from `plugin/skills/`.

**Tech Stack:** Phase 1-2 stack plus `watchdog` for the file watcher. No new LLM dependencies.

**Spec:** `docs/specs/2026-05-25-claude-mem-design.md` §6.2, §6.3 (handoff/resume), §7 (incremental indexing), §11 (skills).

**Phase 1-2 lessons carried forward:**
- `rsplit(":", 1)[0]` on `source_ref` for Windows drive letters.
- Tests that walk parents need `monkeypatch.setattr(Path, "is_dir", ...)` to mask ambient `~/.claude-mem`.
- `superseded_by` FK requires a real unit row — use `TOMBSTONE_HANDLE` sentinel for tombstones, similarly use a `RESUMED_TASK_HANDLE` if we ever need it (we won't in Phase 3).
- DB schema CHECK already allows `task` layer (Phase 2 added it).
- Sonnet for implementer subagents.

---

## File Structure

New files in this phase:

**Handoff/Resume**
- `src/claude_mem/handoff/__init__.py` (empty)
- `src/claude_mem/handoff/render.py` — `render_handoff_markdown(task, decisions, questions, memories) -> str`
- `src/claude_mem/handoff/snapshot.py` — `handoff(settings, task_id) -> SnapshotResult` write path
- `src/claude_mem/handoff/resume.py` — `resume(settings, task_id, embedder, budget) -> ResumeResult`
- `src/claude_mem/tools/handoff.py` — MCP tool wrapper
- `src/claude_mem/tools/resume.py` — MCP tool wrapper

**Watcher**
- `src/claude_mem/indexer/incremental.py` — `incremental_reindex(settings, paths, embedder)` codepath
- `src/claude_mem/watcher/__init__.py` (empty)
- `src/claude_mem/watcher/fs_watcher.py` — `FileWatcher` class wrapping `watchdog`
- `src/claude_mem/watcher/debounce.py` — small debounce helper (testable without watchdog)

**CLI**
- Modify: `src/claude_mem/cli.py` — `serve` gains `--watch` flag (default on); add `claude-mem watch` standalone for headless use

**Skills (plugin content)**
- `plugin/.claude-plugin/marketplace.json` (or matching location for the existing plugin tree — TBD by Task 9 inspection)
- `plugin/skills/claude-mem-recall/SKILL.md`
- `plugin/skills/claude-mem-trace/SKILL.md`
- `plugin/skills/claude-mem-handoff/SKILL.md`

**Tests**
- `tests/unit/test_handoff_render.py`
- `tests/unit/test_handoff_snapshot.py`
- `tests/unit/test_resume.py`
- `tests/integration/test_mcp_handoff.py`
- `tests/integration/test_mcp_resume.py`
- `tests/unit/test_debounce.py`
- `tests/unit/test_incremental.py`
- `tests/integration/test_watcher.py` (marked `slow` — exercises real watchdog)
- `tests/integration/test_phase3_acceptance.py` — end-to-end handoff/resume across simulated session boundary

---

## Cross-cutting design decisions (read before starting)

### Handoff markdown file format

```markdown
---
task_id: task://task/abc123def456
parent_id: task://task/parent789
status: active
created_at: 2026-05-27T12:34:56Z
scope: backend/auth
---

# Handoff: Add token refresh endpoint

## Intent
We want POST /auth/refresh to issue a new token given a valid (non-expired) refresh
token, and to invalidate the previous refresh token in the same call.

## Acceptance
- [ ] POST /auth/refresh returns a new access + refresh token pair
- [ ] Old refresh token is invalidated on use
- [ ] Reusing an old refresh token returns 401

## Decisions made this session
- Use RS256 for signing (memory://decision/abc12345)
- Refresh tokens are single-use (memory://decision/def67890)

## Open questions
- Should refresh tokens be revocable per-device, or only globally?

## Context handles (pre-sized bundle)
- code://function/4a7b8c9d   src/auth/jwt.py:issue_token
- code://route/1e2f3a4b      POST /auth/login
- docs://section/5c6d7e8f    Authentication > Token lifecycle

## Recent memory writes
- memory://decision/abc12345  "We chose RS256 over HS256."
- memory://convention/9z8y7x  "Tests run with pytest -q on Windows."
```

The frontmatter is parseable YAML; the body is human-readable. `resume()` parses both: the frontmatter for task identity, the "Context handles" section for the bundle to rehydrate.

### `task_snapshot` unit shape

A `task_snapshot` unit links the task to its handoff markdown file. One snapshot per handoff invocation (snapshots are append-only; later handoffs add new snapshots, never overwrite).

```
id:           snapshot://task_snapshot/<hash>
layer:        task
kind:         task_snapshot
scope:        <task's scope>
source_ref:   <absolute path to .claude-mem/handoffs/<task_id>.md>
content_hash: sha256 of markdown
parent_id:    <the task's id>
metadata:     {"task_id": "...", "rendered_at": <ts>}
```

The `task_snapshot` kind was already approved into `KIND_VALID_FOR_LAYER["task"]` in Phase 2's `units/typed.py`.

### `resume` response shape

Mirrors `recall` output for callers' convenience, plus the rendered markdown:

```python
{
  "task_id": "task://task/abc",
  "snapshot_markdown": "<full file contents>",
  "hydrated_items": [
    {"handle": "...", "header": "...", "tier_2": "..."},
    ...
  ],
  "overflow_handles": ["...", "..."]  # handles that didn't fit in the budget
}
```

### Watcher design

- `watchdog.Observer` with a `PatternMatchingEventHandler` accepting the same extensions as `walker.SUPPORTED_EXTS`.
- 750 ms debounce: collect paths into a set; after the quiet period, call `incremental_reindex(paths)`.
- Skipped if the path is under any of `walker.SKIP_DIRS` OR under `.claude-mem/` except `.claude-mem/memory/` (matches walker).
- The watcher process logs to stderr only; it does NOT print to stdout (stdout is the MCP stdio channel).
- For testability, the debounce helper is a pure function/class with an injectable clock and an explicit `flush()`.

### Incremental reindex

`incremental_reindex(settings, changed_paths, embedder)` re-runs parsers ONLY for `changed_paths`. It:
1. Re-parses each touched file, computes new units + relations for that file.
2. Deletes prior units whose `source_ref` matches the file but whose ID no longer appears (renames inside a file = stale unit cleanup).
3. Re-runs synthesizers on the whole snapshot (cheap — they're regex-based).
4. Re-embeds only the new/changed units.

This is intentionally simpler than full diff-based incremental indexing — the spec §7.2 calls for hash-based change detection per file, which is what `walker.hash_file` already supplies.

### Skill content

Each skill is a single `SKILL.md` with YAML frontmatter:
```markdown
---
name: claude-mem-recall
description: Use BEFORE Grep/Read when looking for code, symbols, or documentation in this repo. Calls recall(query) on the local claude-mem MCP server; returns ranked, budgeted, tiered results.
---
```

The body explains when to trigger and includes 2-3 worked examples. The plugin loader picks these up by directory scan; no registration code needed beyond the markdown files themselves.

---

## Task 0: `task_snapshot` kind already valid — verify only

Phase 2 added `task_snapshot` to `KIND_VALID_FOR_LAYER["task"]`. This task just adds a regression test so a refactor doesn't drop it.

**Files:**
- Test: `tests/unit/test_typed_unit.py` — append one assertion

- [ ] **Step 1: Add assertion**

Append to `tests/unit/test_typed_unit.py`:

```python
def test_task_snapshot_kind_valid():
    from claude_mem.units.typed import KIND_VALID_FOR_LAYER
    assert "task_snapshot" in KIND_VALID_FOR_LAYER["task"]
```

- [ ] **Step 2: Run**

`.venv/Scripts/python -m pytest tests/unit/test_typed_unit.py -q`
Expected: 6 passed (was 5).

- [ ] **Step 3: Commit**

```
git add tests/unit/test_typed_unit.py
git commit -m "test: pin task_snapshot kind in KIND_VALID_FOR_LAYER"
```

---

## Task 1: Handoff markdown renderer (pure function)

**Files:**
- Create: `src/claude_mem/handoff/__init__.py` (empty)
- Create: `src/claude_mem/handoff/render.py`
- Test: `tests/unit/test_handoff_render.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_handoff_render.py`:

```python
from claude_mem.handoff.render import render_handoff_markdown, HandoffPayload
from claude_mem.tasks.model import TaskView


def _task(**overrides) -> TaskView:
    base = dict(
        handle="task://task/abc123def456",
        title="Add token refresh endpoint",
        intent="POST /auth/refresh issues new tokens and invalidates the previous one.",
        status="active",
        scope="backend/auth",
        acceptance=["POST /auth/refresh returns new pair", "Old refresh token invalidated"],
        context_handles=["code://function/4a7b8c9d", "docs://section/5c6d7e8f"],
        open_questions=["Should tokens be per-device revocable?"],
        decisions_made=["memory://decision/abc12345"],
        parent="task://task/parent789",
    )
    base.update(overrides)
    return TaskView(**base)


def test_frontmatter_has_required_fields():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert md.startswith("---\n")
    assert "task_id: task://task/abc123def456" in md
    assert "status: active" in md
    assert "scope: backend/auth" in md


def test_body_includes_intent_and_acceptance():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert "# Handoff: Add token refresh endpoint" in md
    assert "POST /auth/refresh issues new tokens" in md
    assert "- [ ] POST /auth/refresh returns new pair" in md


def test_context_handles_section_lists_each_handle():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert "## Context handles" in md
    assert "code://function/4a7b8c9d" in md
    assert "docs://section/5c6d7e8f" in md


def test_recent_memories_rendered_when_present():
    md = render_handoff_markdown(HandoffPayload(
        task=_task(),
        recent_memories=[
            ("memory://decision/abc12345", "We chose RS256 over HS256."),
            ("memory://convention/9z8y7x", "Tests run with pytest -q on Windows."),
        ],
    ))
    assert "## Recent memory writes" in md
    assert "We chose RS256 over HS256." in md
    assert "memory://decision/abc12345" in md


def test_empty_sections_omitted():
    """When a section has no items, it should not appear at all."""
    bare = _task(acceptance=[], open_questions=[], context_handles=[], decisions_made=[])
    md = render_handoff_markdown(HandoffPayload(task=bare, recent_memories=[]))
    assert "## Acceptance" not in md
    assert "## Open questions" not in md
    assert "## Context handles" not in md
    assert "## Recent memory writes" not in md


def test_open_questions_rendered():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert "## Open questions" in md
    assert "Should tokens be per-device revocable?" in md
```

- [ ] **Step 2: Run, confirm FAIL** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/claude_mem/handoff/render.py`:

```python
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import List, Tuple

from ..tasks.model import TaskView


@dataclass
class HandoffPayload:
    task: TaskView
    recent_memories: List[Tuple[str, str]] = field(default_factory=list)
    # decisions_made is already on TaskView; we render it via the task itself.


def render_handoff_markdown(payload: HandoffPayload) -> str:
    t = payload.task
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[str] = []

    # Frontmatter
    out.append("---")
    out.append(f"task_id: {t.handle}")
    if t.parent:
        out.append(f"parent_id: {t.parent}")
    out.append(f"status: {t.status}")
    out.append(f"created_at: {now}")
    out.append(f"scope: {t.scope}")
    out.append("---")
    out.append("")

    # Title + intent
    out.append(f"# Handoff: {t.title}")
    out.append("")
    out.append("## Intent")
    out.append(t.intent.strip() or "(no intent set)")
    out.append("")

    if t.acceptance:
        out.append("## Acceptance")
        for a in t.acceptance:
            out.append(f"- [ ] {a}")
        out.append("")

    if t.decisions_made:
        out.append("## Decisions made this session")
        for d in t.decisions_made:
            out.append(f"- {d}")
        out.append("")

    if t.open_questions:
        out.append("## Open questions")
        for q in t.open_questions:
            out.append(f"- {q}")
        out.append("")

    if t.context_handles:
        out.append("## Context handles")
        for h in t.context_handles:
            out.append(f"- {h}")
        out.append("")

    if payload.recent_memories:
        out.append("## Recent memory writes")
        for handle, text in payload.recent_memories:
            short = text.strip().splitlines()[0][:100] if text.strip() else ""
            out.append(f"- {handle}  \"{short}\"")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
```

- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest tests/unit/test_handoff_render.py -q` — expect 6 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/handoff/__init__.py src/claude_mem/handoff/render.py tests/unit/test_handoff_render.py
git commit -m "feat(handoff): markdown renderer with frontmatter + optional sections"
```

---

## Task 2: `handoff()` write path — snapshot + unit

**Files:**
- Create: `src/claude_mem/handoff/snapshot.py`
- Test: `tests/unit/test_handoff_snapshot.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_handoff_snapshot.py`:

```python
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.tasks.planner import plan_task
from claude_mem.memory.writer import remember
from claude_mem.handoff.snapshot import handoff, SnapshotResult
import json


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


@pytest.fixture
async def task_id(settings):
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(settings, intent="ship feature", llm=llm)
    return plan.root.handle


@pytest.mark.asyncio
async def test_handoff_writes_markdown_file(settings, task_id):
    result = handoff(settings, task_id=task_id)
    assert isinstance(result, SnapshotResult)
    assert result.markdown_path.exists()
    content = result.markdown_path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert task_id in content
    assert "# Handoff:" in content


@pytest.mark.asyncio
async def test_handoff_creates_task_snapshot_unit(settings, task_id):
    result = handoff(settings, task_id=task_id)
    repo = Repository(connect(settings.db_path))
    snap = repo.get_unit(result.snapshot_handle)
    assert snap is not None
    assert snap.layer == "task"
    assert snap.kind == "task_snapshot"
    assert snap.parent_id == task_id
    assert snap.source_ref and snap.source_ref.endswith(".md")


@pytest.mark.asyncio
async def test_handoff_includes_recent_memories(settings, task_id):
    remember(settings, fact="We use RS256.", scope="backend/auth", kind="decision")
    remember(settings, fact="Tests run with pytest -q.", scope="tooling", kind="convention")
    result = handoff(settings, task_id=task_id)
    content = result.markdown_path.read_text(encoding="utf-8")
    assert "RS256" in content
    assert "pytest -q" in content


@pytest.mark.asyncio
async def test_handoff_unknown_task_raises(settings):
    with pytest.raises(KeyError):
        handoff(settings, task_id="task://task/doesnotexist")


@pytest.mark.asyncio
async def test_handoff_rejects_non_task_unit(settings):
    # Insert a non-task unit and try to hand off on its id.
    from claude_mem.units.model import Unit
    repo = Repository(connect(settings.db_path))
    repo.upsert_unit(Unit(
        id="code://function/x", layer="code", kind="function", scope="x",
        source_ref=None, content_hash="h", t1_header="t",
        created_at=0, last_seen_at=0,
    ))
    with pytest.raises(ValueError):
        handoff(settings, task_id="code://function/x")
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/handoff/snapshot.py`:

```python
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..tasks.model import unit_metadata_to_task
from ..units.model import Unit
from .render import HandoffPayload, render_handoff_markdown


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_handle: str
    markdown_path: Path
    task_id: str


RECENT_MEMORY_LIMIT = 10


def handoff(settings: Settings, *, task_id: str) -> SnapshotResult:
    """Render the task to .claude-mem/handoffs/<task_id_short>.md and write a task_snapshot unit."""
    conn = connect(settings.db_path)
    repo = Repository(conn)

    task_unit = repo.get_unit(task_id)
    if task_unit is None:
        raise KeyError(task_id)
    if task_unit.layer != "task" or task_unit.kind != "task":
        raise ValueError(
            f"handoff() requires a task unit (kind='task'); got "
            f"layer={task_unit.layer!r} kind={task_unit.kind!r}"
        )

    task = unit_metadata_to_task(task_unit)

    # Recent memory writes — most recently seen first, capped.
    rows = conn.execute(
        "SELECT id, metadata FROM unit WHERE layer='memory' AND superseded_by IS NULL "
        "ORDER BY last_seen_at DESC LIMIT ?",
        (RECENT_MEMORY_LIMIT,),
    ).fetchall()
    recent_memories: list[tuple[str, str]] = []
    for r in rows:
        meta = json.loads(r["metadata"]) if r["metadata"] else {}
        body = meta.get("body", "")
        recent_memories.append((r["id"], body))

    payload = HandoffPayload(task=task, recent_memories=recent_memories)
    md = render_handoff_markdown(payload)

    # Write file
    handoffs_dir = settings.handoffs_dir
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    short = task_id.rsplit("/", 1)[-1]
    path = handoffs_dir / f"{short}.md"
    path.write_text(md, encoding="utf-8")

    # Write task_snapshot unit
    now = int(time.time())
    content_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()
    snap_id = f"snapshot://task_snapshot/{content_hash[:12]}"
    snap = Unit(
        id=snap_id,
        layer="task",
        kind="task_snapshot",
        scope=task.scope,
        source_ref=str(path),
        content_hash=content_hash,
        t1_header=f"[task_snapshot] {task.title[:80]}",
        created_at=now,
        last_seen_at=now,
        parent_id=task_id,
        metadata=json.dumps({"task_id": task_id, "rendered_at": now}),
    )
    repo.upsert_unit(snap)
    return SnapshotResult(snapshot_handle=snap_id, markdown_path=path, task_id=task_id)
```

Note: `snap_id` uses the prefix `snapshot://` which is NOT in `units/ids.VALID_LAYERS`. The schema doesn't require the id prefix to match `layer`; the layer column is what gets CHECKed. So this is fine. But to keep things uniform, in Step 3 use `task://task_snapshot/<hash>` instead:

```python
snap_id = f"task://task_snapshot/{content_hash[:12]}"
```

(Update the test assertion accordingly — none of the tests above check the prefix specifically.)

- [ ] **Step 4: Run** — expect 5 passed. If the FK constraint trips on `parent_id` (it shouldn't — the parent task was inserted by `plan_task` first), inspect; otherwise green.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/handoff/snapshot.py tests/unit/test_handoff_snapshot.py
git commit -m "feat(handoff): handoff() writes markdown snapshot + task_snapshot unit"
```

---

## Task 3: `handoff` MCP tool

**Files:**
- Create: `src/claude_mem/tools/handoff.py`
- Test: `tests/integration/test_mcp_handoff.py`
- Modify: `src/claude_mem/server.py`

- [ ] **Step 1: Failing test**

`tests/integration/test_mcp_handoff.py`:

```python
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.tasks.planner import plan_task
from claude_mem.tools.handoff import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "handoff"
    assert "task_id" in s.inputSchema["properties"]
    assert s.inputSchema.get("required") == ["task_id"]


@pytest.mark.asyncio
async def test_handle_returns_snapshot(settings):
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(settings, intent="big task", llm=llm)
    out = await handle(settings, {"task_id": plan.root.handle})
    payload = json.loads(out[0].text)
    assert payload["task_id"] == plan.root.handle
    assert payload["snapshot_handle"].startswith("task://task_snapshot/")
    assert Path(payload["markdown_path"]).exists()


@pytest.mark.asyncio
async def test_handle_unknown_task_returns_error(settings):
    out = await handle(settings, {"task_id": "task://task/zzzzzzzzzzzz"})
    payload = json.loads(out[0].text)
    assert "error" in payload
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/tools/handoff.py`:

```python
from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..handoff.snapshot import handoff


def tool_schema() -> Tool:
    return Tool(
        name="handoff",
        description=(
            "Render the current state of a task to a markdown snapshot under "
            ".claude-mem/handoffs/ and write a task_snapshot unit. Use at the end "
            "of a working session or before a context-budget reset. Returns the "
            "snapshot handle and the markdown path."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Handle of the task to snapshot"},
            },
            "required": ["task_id"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    try:
        result = handoff(settings, task_id=args["task_id"])
    except (KeyError, ValueError) as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(type="text", text=json.dumps({
        "task_id": result.task_id,
        "snapshot_handle": result.snapshot_handle,
        "markdown_path": str(result.markdown_path),
    }))]
```

- [ ] **Step 4: Register in `server.py`**

Add the import:
```python
from .tools import handoff as handoff_tool
```
Add to `_list` return list:
```python
handoff_tool.tool_schema(),
```
Add to `_call`:
```python
if name == "handoff":
    return await handoff_tool.handle(s, arguments)
```

- [ ] **Step 5: Run** — 3 new tests + all prior still pass.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/tools/handoff.py src/claude_mem/server.py tests/integration/test_mcp_handoff.py
git commit -m "feat(tools): handoff MCP tool"
```

---

## Task 4: `resume()` read path

**Files:**
- Create: `src/claude_mem/handoff/resume.py`
- Test: `tests/unit/test_resume.py`

`resume()` finds the latest `task_snapshot` for a task, reads the markdown file, re-fetches the `context_handles` from the task's metadata, and returns the bundle. It does NOT call recall again — the bundle is whatever the task carried into handoff.

- [ ] **Step 1: Failing test**

`tests/unit/test_resume.py`:

```python
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.units.model import Unit
from claude_mem.tasks.planner import plan_task
from claude_mem.handoff.snapshot import handoff
from claude_mem.handoff.resume import resume, ResumeResult


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


@pytest.fixture
async def task_with_context(settings):
    # Seed a code unit so context_handles can be hydrated.
    repo = Repository(connect(settings.db_path))
    repo.upsert_unit(Unit(
        id="code://function/abc",
        layer="code", kind="function", scope="backend/auth",
        source_ref="src/auth.py", content_hash="h",
        t1_header="python issue_token(user)",
        created_at=0, last_seen_at=0,
        t2_summary="Issues a signed JWT for the user.",
    ))
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(
        settings, intent="add refresh", llm=llm,
        context_handles=["code://function/abc"],
    )
    return plan.root.handle


@pytest.mark.asyncio
async def test_resume_returns_markdown_and_items(settings, task_with_context):
    handoff(settings, task_id=task_with_context)
    result = resume(settings, task_id=task_with_context, budget=4000)
    assert isinstance(result, ResumeResult)
    assert result.task_id == task_with_context
    assert "# Handoff:" in result.snapshot_markdown
    handles = [it["handle"] for it in result.hydrated_items]
    assert "code://function/abc" in handles


@pytest.mark.asyncio
async def test_resume_no_snapshot_raises(settings):
    with pytest.raises(KeyError):
        resume(settings, task_id="task://task/nope", budget=4000)


@pytest.mark.asyncio
async def test_resume_uses_t2_summary_when_under_budget(settings, task_with_context):
    handoff(settings, task_id=task_with_context)
    result = resume(settings, task_id=task_with_context, budget=4000)
    [item] = [it for it in result.hydrated_items if it["handle"] == "code://function/abc"]
    assert "Issues a signed JWT" in item.get("tier_2", "")


@pytest.mark.asyncio
async def test_resume_overflow_handles_when_budget_tight(settings, task_with_context):
    # Add 20 more units to context_handles, then resume with tight budget.
    repo = Repository(connect(settings.db_path))
    extra = []
    for i in range(20):
        h = f"code://function/x{i:02d}"
        repo.upsert_unit(Unit(
            id=h, layer="code", kind="function", scope="x",
            source_ref=f"src/x{i}.py", content_hash="h",
            t1_header=f"function x{i}", created_at=0, last_seen_at=0,
            t2_summary="some summary",
        ))
        extra.append(h)
    # Append to context_handles in the task metadata.
    from claude_mem.tasks.model import unit_metadata_to_task, task_to_unit_metadata
    from dataclasses import replace
    task_unit = repo.get_unit(task_with_context)
    task = unit_metadata_to_task(task_unit)
    task.context_handles = task.context_handles + extra
    meta_json = json.dumps(task_to_unit_metadata(task))
    repo.upsert_unit(replace(task_unit, metadata=meta_json))
    handoff(settings, task_id=task_with_context)

    result = resume(settings, task_id=task_with_context, budget=200)  # tight
    assert len(result.overflow_handles) > 0
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/handoff/resume.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..tasks.model import unit_metadata_to_task


@dataclass
class ResumeResult:
    task_id: str
    snapshot_markdown: str
    hydrated_items: List[dict] = field(default_factory=list)
    overflow_handles: List[str] = field(default_factory=list)


def resume(settings: Settings, *, task_id: str, budget: int = 4000) -> ResumeResult:
    conn = connect(settings.db_path)
    repo = Repository(conn)

    task_unit = repo.get_unit(task_id)
    if task_unit is None:
        raise KeyError(f"unknown task: {task_id}")

    # Find latest task_snapshot for this task.
    snap_row = conn.execute(
        "SELECT * FROM unit WHERE layer='task' AND kind='task_snapshot' AND parent_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if snap_row is None:
        raise KeyError(f"no snapshot exists for {task_id}")

    md_path = Path(snap_row["source_ref"])
    snapshot_markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

    task = unit_metadata_to_task(task_unit)
    handles = list(task.context_handles)

    hydrated: list[dict] = []
    overflow: list[str] = []
    used = 0
    for h in handles:
        u = repo.get_unit(h)
        if u is None:
            overflow.append(h)
            continue
        # Prefer t2_summary if present, else t1_header.
        body = u.t2_summary or u.t1_header
        cost = _approx_tokens(body) + _approx_tokens(u.t1_header)
        if used + cost > budget:
            overflow.append(h)
            continue
        used += cost
        hydrated.append({
            "handle": h,
            "header": u.t1_header,
            "tier_2": u.t2_summary or "",
            "layer": u.layer,
            "kind": u.kind,
        })

    return ResumeResult(
        task_id=task_id,
        snapshot_markdown=snapshot_markdown,
        hydrated_items=hydrated,
        overflow_handles=overflow,
    )


def _approx_tokens(text: str) -> int:
    """Rough heuristic: ~4 chars per token."""
    return max(1, len(text or "") // 4)
```

- [ ] **Step 4: Run** — 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/handoff/resume.py tests/unit/test_resume.py
git commit -m "feat(handoff): resume() returns snapshot markdown + budgeted hydrated bundle"
```

---

## Task 5: `resume` MCP tool

**Files:**
- Create: `src/claude_mem/tools/resume.py`
- Test: `tests/integration/test_mcp_resume.py`
- Modify: `src/claude_mem/server.py`

- [ ] **Step 1: Failing test**

`tests/integration/test_mcp_resume.py`:

```python
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.units.model import Unit
from claude_mem.tasks.planner import plan_task
from claude_mem.handoff.snapshot import handoff
from claude_mem.tools.resume import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "resume"
    assert "task_id" in s.inputSchema["properties"]
    assert s.inputSchema.get("required") == ["task_id"]


@pytest.mark.asyncio
async def test_handle_returns_resume_bundle(settings):
    repo = Repository(connect(settings.db_path))
    repo.upsert_unit(Unit(
        id="code://function/abc", layer="code", kind="function", scope="x",
        source_ref=None, content_hash="h", t1_header="def f()",
        created_at=0, last_seen_at=0, t2_summary="Does f.",
    ))
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [{"title": "A", "intent": "a", "acceptance": []}]
    }))
    plan = await plan_task(
        settings, intent="x", llm=llm, context_handles=["code://function/abc"],
    )
    handoff(settings, task_id=plan.root.handle)

    out = await handle(settings, {"task_id": plan.root.handle})
    payload = json.loads(out[0].text)
    assert payload["task_id"] == plan.root.handle
    assert "snapshot_markdown" in payload
    assert payload["hydrated_items"]
    assert payload["hydrated_items"][0]["handle"] == "code://function/abc"


@pytest.mark.asyncio
async def test_handle_unknown_task_returns_error(settings):
    out = await handle(settings, {"task_id": "task://task/zzzzzzzzzzzz"})
    payload = json.loads(out[0].text)
    assert "error" in payload
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/tools/resume.py`:

```python
from __future__ import annotations

import json
from typing import Any
from mcp.types import Tool, TextContent
from ..config import Settings
from ..handoff.resume import resume


def tool_schema() -> Tool:
    return Tool(
        name="resume",
        description=(
            "Pick up a task from its most recent handoff snapshot. Returns the "
            "snapshot markdown and a budgeted bundle of the task's context handles. "
            "Use at the start of a fresh session when continuing work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "budget": {"type": "integer", "default": 4000, "minimum": 200},
            },
            "required": ["task_id"],
        },
    )


async def handle(settings: Settings, args: dict[str, Any]) -> list[TextContent]:
    try:
        r = resume(settings, task_id=args["task_id"], budget=args.get("budget", 4000))
    except KeyError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    return [TextContent(type="text", text=json.dumps({
        "task_id": r.task_id,
        "snapshot_markdown": r.snapshot_markdown,
        "hydrated_items": r.hydrated_items,
        "overflow_handles": r.overflow_handles,
    }))]
```

- [ ] **Step 4: Register in `server.py`** — mirror Task 3.

- [ ] **Step 5: Run** — 3 new passing.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/tools/resume.py src/claude_mem/server.py tests/integration/test_mcp_resume.py
git commit -m "feat(tools): resume MCP tool"
```

---

## Task 6: Debounce helper (testable, no watchdog dep)

**Files:**
- Create: `src/claude_mem/watcher/__init__.py` (empty)
- Create: `src/claude_mem/watcher/debounce.py`
- Test: `tests/unit/test_debounce.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_debounce.py`:

```python
from claude_mem.watcher.debounce import PathDebouncer


def test_collects_paths_until_flush():
    fired: list[set] = []
    d = PathDebouncer(on_flush=lambda paths: fired.append(set(paths)))
    d.add("a.py")
    d.add("b.py")
    d.add("a.py")  # dup
    assert not fired
    d.flush()
    assert fired == [{"a.py", "b.py"}]


def test_flush_with_no_changes_is_noop():
    fired: list[set] = []
    PathDebouncer(on_flush=lambda paths: fired.append(set(paths))).flush()
    assert not fired


def test_flush_clears_buffer():
    fired: list[set] = []
    d = PathDebouncer(on_flush=lambda paths: fired.append(set(paths)))
    d.add("a.py")
    d.flush()
    d.flush()
    assert fired == [{"a.py"}]


def test_due_at_advances_after_add():
    """Each add() resets the due time; until quiet period elapses, not due."""
    fake_now = [100.0]
    d = PathDebouncer(on_flush=lambda paths: None, quiet_ms=500, now_fn=lambda: fake_now[0])
    d.add("a.py")
    assert not d.is_due()
    fake_now[0] += 0.4
    assert not d.is_due()
    fake_now[0] += 0.2  # total 0.6s after add — past 0.5s quiet
    assert d.is_due()


def test_due_resets_on_subsequent_add():
    fake_now = [100.0]
    d = PathDebouncer(on_flush=lambda paths: None, quiet_ms=500, now_fn=lambda: fake_now[0])
    d.add("a.py")
    fake_now[0] += 0.4
    d.add("b.py")  # resets
    fake_now[0] += 0.4
    assert not d.is_due()  # only 0.4s since last add
    fake_now[0] += 0.2
    assert d.is_due()
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/watcher/debounce.py`:

```python
from __future__ import annotations

import time
from typing import Callable, Iterable, Optional


class PathDebouncer:
    """Collect path strings; fire `on_flush(paths)` after a quiet period.

    Pure data; does not own a timer thread. Caller polls `is_due()` and calls
    `flush()` (or just calls `flush()` directly to force a fire).
    """

    def __init__(
        self,
        *,
        on_flush: Callable[[Iterable[str]], None],
        quiet_ms: int = 750,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_flush = on_flush
        self._quiet_s = quiet_ms / 1000.0
        self._now = now_fn
        self._paths: set[str] = set()
        self._last_add_at: Optional[float] = None

    def add(self, path: str) -> None:
        self._paths.add(path)
        self._last_add_at = self._now()

    def is_due(self) -> bool:
        if not self._paths or self._last_add_at is None:
            return False
        return (self._now() - self._last_add_at) >= self._quiet_s

    def flush(self) -> None:
        if not self._paths:
            return
        paths = self._paths
        self._paths = set()
        self._last_add_at = None
        self._on_flush(paths)
```

- [ ] **Step 4: Run** — 5 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/watcher/__init__.py src/claude_mem/watcher/debounce.py tests/unit/test_debounce.py
git commit -m "feat(watcher): PathDebouncer (pure, testable)"
```

---

## Task 7: Incremental reindex

**Files:**
- Create: `src/claude_mem/indexer/incremental.py`
- Test: `tests/unit/test_incremental.py`

- [ ] **Step 1: Failing test**

`tests/unit/test_incremental.py`:

```python
from pathlib import Path
import pytest
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.indexer.incremental import incremental_reindex


@pytest.fixture
def indexed(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    (tmp_repo / "b.py").write_text("def g(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)
    return s, tmp_repo


def test_incremental_picks_up_new_function(indexed):
    s, root = indexed
    p = root / "a.py"
    p.write_text("def f(): pass\ndef newly_added(): pass\n")
    stats = incremental_reindex(s, [p], embedder=None)
    assert stats["files_processed"] == 1
    conn = connect(s.db_path)
    names = [r["t1_header"] for r in conn.execute(
        "SELECT t1_header FROM unit WHERE source_ref LIKE ? AND layer='code'",
        (f"%{p.as_posix().split('/')[-1]}",),
    ).fetchall()]
    assert any("newly_added" in n for n in names)


def test_incremental_does_not_touch_other_files(indexed):
    s, root = indexed
    p = root / "a.py"
    p.write_text("def replaced(): pass\n")
    conn = connect(s.db_path)
    before = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer='code' AND source_ref LIKE ?",
        (f"%b.py",),
    ).fetchone()[0]
    incremental_reindex(s, [p], embedder=None)
    after = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer='code' AND source_ref LIKE ?",
        (f"%b.py",),
    ).fetchone()[0]
    assert before == after


def test_incremental_handles_deleted_file(indexed, tmp_path):
    s, root = indexed
    p = root / "a.py"
    p.unlink()
    incremental_reindex(s, [p], embedder=None)
    conn = connect(s.db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE source_ref LIKE ?",
        (f"%a.py",),
    ).fetchone()[0]
    assert n == 0


def test_incremental_returns_stats(indexed):
    s, root = indexed
    incremental_reindex(s, [root / "a.py"], embedder=None)
    # stats returned (sanity)
```

- [ ] **Step 2: FAIL.**

- [ ] **Step 3: Implement**

`src/claude_mem/indexer/incremental.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder
from ..units.model import Unit
from .orchestrator import PARSERS, _pick_parser, _relativize_scope


def incremental_reindex(
    settings: Settings,
    paths: Iterable[Path],
    embedder: Optional[Embedder] = None,
) -> dict:
    """Re-parse only the given paths and upsert their units. Delete units whose
    `source_ref` matches a path that no longer exists or whose ID is no longer
    produced by the parser for that path.
    """
    conn = connect(settings.db_path)
    repo = Repository(conn)
    repo_root = settings.repo_root
    files_processed = 0
    new_unit_ids: set[str] = set()

    for path in paths:
        files_processed += 1
        path_posix = path.as_posix()
        # Capture existing units for this source.
        existing_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM unit WHERE source_ref = ?", (path_posix,)
            ).fetchall()
        }

        if not path.exists():
            # File deleted — remove all units that originated from it.
            for uid in existing_ids:
                conn.execute("DELETE FROM relation WHERE src_id = ? OR dst_id = ?", (uid, uid))
                conn.execute("DELETE FROM unit_fts WHERE id = ?", (uid,))
                conn.execute("DELETE FROM unit_vec WHERE id = ?", (uid,))
                conn.execute("DELETE FROM unit WHERE id = ?", (uid,))
            conn.commit()
            continue

        parser = _pick_parser(path)
        if parser is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        result = parser.parse(path, text)
        produced_ids: set[str] = set()
        new_units = [_relativize_scope(u, repo_root) for u in result.units]
        for u in new_units:
            produced_ids.add(u.id)
            new_unit_ids.add(u.id)

        # Embed (optional).
        embeddings: dict[str, "object"] = {}
        if embedder is not None and new_units:
            texts = [u.t1_header for u in new_units]
            vecs = embedder.embed(texts)
            embeddings = {u.id: v for u, v in zip(new_units, vecs)}

        for u in new_units:
            repo.upsert_unit(u, embedding=embeddings.get(u.id))
        for rel in result.relations:
            repo.add_relation(rel)

        # Stale: previously this file produced these ids, but no longer.
        stale = existing_ids - produced_ids
        for uid in stale:
            conn.execute("DELETE FROM relation WHERE src_id = ? OR dst_id = ?", (uid, uid))
            conn.execute("DELETE FROM unit_fts WHERE id = ?", (uid,))
            conn.execute("DELETE FROM unit_vec WHERE id = ?", (uid,))
            conn.execute("DELETE FROM unit WHERE id = ?", (uid,))
        conn.commit()

    return {
        "files_processed": files_processed,
        "units_touched": len(new_unit_ids),
    }
```

NOTE: this skips synthesizers on the incremental path — they'd require the whole-repo snapshot. Acceptable for v1; the watcher loop can call full synthesizer passes at a coarser cadence if needed.

- [ ] **Step 4: Run** — expect 4 passed.

- [ ] **Step 5: Commit**

```
git add src/claude_mem/indexer/incremental.py tests/unit/test_incremental.py
git commit -m "feat(indexer): incremental_reindex(paths) — per-file re-parse + stale cleanup"
```

---

## Task 8: File watcher integration

**Files:**
- Create: `src/claude_mem/watcher/fs_watcher.py`
- Test: `tests/integration/test_watcher.py` (mark `slow`)
- Modify: `pyproject.toml` — add `watchdog>=4` to dependencies (or `[dev]` extras if you want it optional)

- [ ] **Step 1: Add dependency**

In `pyproject.toml` (under `[project] dependencies`):

```toml
"watchdog>=4",
```

Run: `.venv/Scripts/python -m pip install -e .` to install.

- [ ] **Step 2: Failing test**

`tests/integration/test_watcher.py`:

```python
import time
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.watcher.fs_watcher import FileWatcher


pytestmark = pytest.mark.slow


def test_watcher_reindexes_new_function_after_quiet(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    w = FileWatcher(s, embedder=None, quiet_ms=200)
    w.start()
    try:
        (tmp_repo / "a.py").write_text("def f(): pass\ndef freshly_added(): pass\n")
        # Wait up to 3 seconds for the watcher to pick it up + flush.
        deadline = time.monotonic() + 3.0
        seen = False
        while time.monotonic() < deadline:
            conn = connect(s.db_path)
            rows = conn.execute(
                "SELECT t1_header FROM unit WHERE source_ref LIKE ? AND layer='code'",
                ("%a.py",),
            ).fetchall()
            if any("freshly_added" in r["t1_header"] for r in rows):
                seen = True
                break
            time.sleep(0.1)
        assert seen, "watcher did not pick up the new function within 3s"
    finally:
        w.stop()


def test_watcher_picks_up_deleted_file(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    w = FileWatcher(s, embedder=None, quiet_ms=200)
    w.start()
    try:
        (tmp_repo / "a.py").unlink()
        deadline = time.monotonic() + 3.0
        gone = False
        while time.monotonic() < deadline:
            conn = connect(s.db_path)
            n = conn.execute(
                "SELECT COUNT(*) FROM unit WHERE source_ref LIKE ?",
                ("%a.py",),
            ).fetchone()[0]
            if n == 0:
                gone = True
                break
            time.sleep(0.1)
        assert gone
    finally:
        w.stop()
```

- [ ] **Step 3: FAIL.**

- [ ] **Step 4: Implement**

`src/claude_mem/watcher/fs_watcher.py`:

```python
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..config import Settings
from ..embeddings.base import Embedder
from ..indexer.incremental import incremental_reindex
from ..indexer.walker import SKIP_DIRS, SUPPORTED_EXTS
from .debounce import PathDebouncer


class FileWatcher:
    def __init__(
        self,
        settings: Settings,
        *,
        embedder: Optional[Embedder] = None,
        quiet_ms: int = 750,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self._debouncer = PathDebouncer(
            on_flush=self._on_flush, quiet_ms=quiet_ms,
        )
        self._observer = Observer()
        self._stop = threading.Event()
        self._tick_thread: Optional[threading.Thread] = None
        self._handler = _ChangeHandler(self._on_change)
        self._quiet_ms = quiet_ms

    def start(self) -> None:
        self._observer.schedule(
            self._handler, str(self.settings.repo_root), recursive=True
        )
        self._observer.start()
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._observer.stop()
        self._observer.join(timeout=2.0)
        if self._tick_thread:
            self._tick_thread.join(timeout=2.0)

    def _on_change(self, path: Path) -> None:
        if not self._is_indexable(path):
            return
        self._debouncer.add(str(path))

    def _is_indexable(self, path: Path) -> bool:
        if path.suffix.lower() not in SUPPORTED_EXTS:
            return False
        parts = set(path.parts)
        # Allow .claude-mem/memory; skip everything else under .claude-mem.
        if ".claude-mem" in parts:
            try:
                i = path.parts.index(".claude-mem")
                if i + 1 >= len(path.parts) or path.parts[i + 1] != "memory":
                    return False
            except ValueError:
                pass
        if parts & (SKIP_DIRS - {".claude-mem"}):
            return False
        return True

    def _on_flush(self, paths) -> None:
        try:
            incremental_reindex(self.settings, [Path(p) for p in paths], embedder=self.embedder)
        except Exception as e:  # pragma: no cover — defensive
            print(f"[claude-mem watcher] reindex failed: {e}", file=sys.stderr)

    def _tick_loop(self) -> None:
        while not self._stop.is_set():
            if self._debouncer.is_due():
                self._debouncer.flush()
            time.sleep(min(0.1, self._quiet_ms / 1000.0 / 4))


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, on_change):
        super().__init__()
        self._on_change = on_change

    def on_modified(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))

    def on_created(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))

    def on_deleted(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._on_change(Path(event.src_path))
            if event.dest_path:
                self._on_change(Path(event.dest_path))
```

- [ ] **Step 5: Run the slow tests**

`.venv/Scripts/python -m pytest tests/integration/test_watcher.py -q -m slow` — expect 2 passed.

If they're flaky (FS event timing), bump `quiet_ms` in the test or the deadline.

- [ ] **Step 6: Commit**

```
git add src/claude_mem/watcher/fs_watcher.py tests/integration/test_watcher.py pyproject.toml
git commit -m "feat(watcher): watchdog-based file watcher driving incremental reindex"
```

---

## Task 9: Wire watcher into `serve`

**Files:**
- Modify: `src/claude_mem/cli.py` — add `--watch / --no-watch` flag to `serve` (default on)
- Modify: `src/claude_mem/server.py` (optional) — only if `serve_stdio` needs awareness; otherwise wire watcher entirely in CLI

- [ ] **Step 1: Modify `cli.py` serve command**

```python
@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Repo root (defaults to cwd)")
@click.option("--watch/--no-watch", default=True,
              help="Run a file watcher in the background (default on)")
def serve(root: Path | None, watch: bool) -> None:
    """Run the MCP server on stdio."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    init_db(settings.db_path)

    watcher = None
    if watch:
        from .watcher.fs_watcher import FileWatcher
        watcher = FileWatcher(settings, embedder=None)  # embedder optional; can be added in Phase 4
        watcher.start()

    try:
        from .server import serve_stdio
        asyncio.run(serve_stdio())
    finally:
        if watcher is not None:
            watcher.stop()
```

- [ ] **Step 2: Test by inspection only** — no automated test for the `serve` subcommand because it spins an stdio loop. Verify manually that `claude-mem serve --no-watch` still starts. Add a smoke test that imports the CLI and confirms `--watch` is recognized:

`tests/unit/test_cli_serve_flags.py`:

```python
from click.testing import CliRunner
from claude_mem.cli import main


def test_serve_help_lists_watch_flag():
    runner = CliRunner()
    res = runner.invoke(main, ["serve", "--help"])
    assert res.exit_code == 0
    assert "--watch" in res.output
    assert "--no-watch" in res.output
```

- [ ] **Step 3: Run** — 1 passed.

- [ ] **Step 4: Commit**

```
git add src/claude_mem/cli.py tests/unit/test_cli_serve_flags.py
git commit -m "feat(cli): serve --watch/--no-watch (default on) runs FileWatcher"
```

---

## Task 10: Companion skills (markdown only)

**Files:**
- Create: `plugin/skills/claude-mem-recall/SKILL.md`
- Create: `plugin/skills/claude-mem-trace/SKILL.md`
- Create: `plugin/skills/claude-mem-handoff/SKILL.md`

Inspect repo for existing `plugin/` tree. If it doesn't exist, create the directory. Skills are pure markdown — no tests.

- [ ] **Step 1: Verify plugin tree**

Run `ls plugin/` (or `Get-ChildItem plugin`). If absent, create `plugin/skills/`.

- [ ] **Step 2: Create `claude-mem-recall/SKILL.md`**

```markdown
---
name: claude-mem-recall
description: Use BEFORE Grep/Read when looking for code, symbols, documentation, or prior decisions in this repo. Calls recall(query) on the local claude-mem MCP server; returns ranked, budgeted, tiered results in one round-trip. Triggers on: "find X", "where is Y defined", "show me the auth code", "what did we decide about Z".
---

# claude-mem-recall

You have a local claude-mem MCP server with the entire repo pre-indexed (code,
docs, memory). It runs hybrid lexical + semantic retrieval in <500ms and returns
content already summarized at the right tier for your budget.

## When to call recall
- "Where is `<symbol>` defined?" — call `recall(query="<symbol>")` before opening files.
- "How does authentication work?" — `recall(query="authentication", scopes=["backend/auth"])`.
- "What did we decide about token signing?" — `recall(query="token signing decision")`.

## When NOT to call recall
- Reading a file you already have a path for — just use Read.
- Verifying a recent edit (recall lags by one indexer pass) — use Read.
- Looking at files outside this repo.

## Worked example

User: "How do refresh tokens work in this codebase?"
You: call `recall(query="refresh token flow", scopes=["backend/auth"], budget=4000)`
Response: 3-5 ranked items with T2 summaries, plus a few T1 headers. Use the
handles to drill in with `trace` or `expand` if needed.
```

- [ ] **Step 3: Create `claude-mem-trace/SKILL.md`**

```markdown
---
name: claude-mem-trace
description: Use AFTER recall when you have a seed handle and need to see callers, callees, routes, hooks, or other connected code in a single round-trip. Returns full source for connected nodes within a budget. Triggers on: "what calls X", "what handlers does this route hit", "what uses this hook".
---

# claude-mem-trace

Once you have a handle from `recall`, use `trace(seed_handle, depth=2, budget=8000)`
to fetch the connected subgraph (callers, callees, routes, imports, hooks) with
full source. One call replaces N grep+read pairs.

## When to call trace
- "What calls `issue_token`?" — `trace(seed_handle="code://function/abc", depth=2)`
- "What handler does POST /login map to?" — `trace(seed_handle="code://route/xyz")`
- "Who consumes this React state?" — `trace(seed_handle="code://function/..." )`

## When NOT to call trace
- You have no seed handle — call `recall` first.
- You only need one item — call `expand(handle, tier="t0")` instead.
```

- [ ] **Step 4: Create `claude-mem-handoff/SKILL.md`**

```markdown
---
name: claude-mem-handoff
description: Use at the end of a working session, before context bloat, or when switching tasks. Snapshots the active task (intent, decisions, open questions, recent memories, context handles) to a markdown file under .claude-mem/handoffs/, so a fresh session can `resume(task_id)` without re-explaining state. Triggers on: "let's pick this up later", "I'm going to start a new session", "snapshot this task".
---

# claude-mem-handoff

claude-mem tracks tasks. When you wrap up work — or anticipate hitting a
context-budget wall — call `handoff(task_id)` to render the current state to
a markdown snapshot. In the next session, the user (or you) calls
`resume(task_id)` to load it back at ~2-4k tokens.

## When to handoff
- End of session, work isn't done.
- Context is filling up and you want a clean restart.
- Switching to a parallel task.

## What gets captured
- The task's intent and acceptance criteria.
- Decisions you've made this session (links to memory units).
- Open questions you've raised.
- The pre-sized bundle of context handles you've been working with.
- The most recent memory writes (last 10).

## What does NOT get captured
- Files you read but didn't `remember()` anything about.
- Reasoning steps. (Only durable conclusions land in memory.)

## Worked example

You finish a refactor halfway. Call `handoff(task_id="task://task/abc")`. The
markdown lands at `.claude-mem/handoffs/abc.md` and is git-trackable. Next
session: `resume(task_id="task://task/abc")` and you're back at the same point
with a 4k-token bundle.
```

- [ ] **Step 5: Commit**

```
git add plugin/skills/
git commit -m "docs(skills): companion skills for recall, trace, handoff"
```

---

## Task 11: Phase 3 acceptance test

End-to-end: simulate a session boundary using two settings/db pairs to assert resume works from a cold start.

**Files:**
- Create: `tests/integration/test_phase3_acceptance.py`

- [ ] **Step 1: Test**

```python
"""Phase 3 acceptance — task survives a session boundary."""
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.memory.writer import remember
from claude_mem.tasks.planner import plan_task
from claude_mem.handoff.snapshot import handoff
from claude_mem.handoff.resume import resume


@pytest.mark.asyncio
async def test_handoff_then_resume_round_trip(tmp_repo: Path):
    # --- Session 1: do work, hand off ---
    (tmp_repo / "auth.py").write_text(
        "def issue_token(user):\n    " + "x = 1\n    " * 30 + "return user\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    # Find the code unit handle.
    conn = connect(s.db_path)
    code_handle = conn.execute(
        "SELECT id FROM unit WHERE layer='code' AND t1_header LIKE '%issue_token%' LIMIT 1"
    ).fetchone()["id"]

    # Remember a decision.
    r1 = remember(s, fact="RS256 over HS256 for gateway verification.",
                  scope="backend/auth", kind="decision", confidence=0.9)

    # Plan a task with context handles.
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "subtasks": [
            {"title": "Add /refresh", "intent": "expose refresh", "acceptance": ["returns pair"]},
        ]
    }))
    plan = await plan_task(
        s, intent="add token refresh", llm=llm,
        context_handles=[code_handle, r1.handle],
    )

    # Handoff.
    snap = handoff(s, task_id=plan.root.handle)
    assert snap.markdown_path.exists()
    assert plan.root.handle in snap.markdown_path.read_text(encoding="utf-8")

    # --- Session 2: cold resume from the same DB ---
    # Open a fresh Settings + DB connection to simulate process restart.
    s2 = Settings.for_repo(tmp_repo)
    result = resume(s2, task_id=plan.root.handle, budget=4000)
    assert result.task_id == plan.root.handle
    assert "RS256" in result.snapshot_markdown
    handles = [it["handle"] for it in result.hydrated_items]
    assert code_handle in handles
    assert r1.handle in handles
```

- [ ] **Step 2: Run** — 1 passed.

- [ ] **Step 3: Commit**

```
git add tests/integration/test_phase3_acceptance.py
git commit -m "test: phase 3 acceptance — handoff/resume across simulated session boundary"
```

---

## Task 12: README + tag

- [ ] **Step 1: Update `README.md`**

Change Status line to:
```
**Status:** Phase 3 — handoff, resume, file watcher, companion skills. Phase 4 is polish.
```

Under the `## Tools` section, append a Phase 3 subsection:

```markdown
Phase 3 (continuity):
- `handoff(task_id)` — snapshot a task to `.claude-mem/handoffs/<id>.md` and create a `task_snapshot` unit
- `resume(task_id, budget=4000)` — load the latest snapshot + a budgeted bundle of its context handles
```

Mention the file watcher under `Quick start`:
```markdown
claude-mem serve --watch          # MCP server with background incremental reindexing (default)
claude-mem serve --no-watch       # MCP server, no file watcher
```

- [ ] **Step 2: Commit + tag**

```
git add README.md
git commit -m "docs: Phase 3 README — handoff/resume tools, watcher, skills"
git tag -a phase-3-complete -m "Phase 3: handoff, resume, file watcher, skills"
```

---

## Self-review

**1. Spec coverage:**
- §6.2 handoff flow → Task 2 (write path), Task 3 (MCP tool)
- §6.3 resume flow → Task 4 (read path), Task 5 (MCP tool)
- §7.2 incremental indexing → Task 7 (incremental_reindex)
- §7.1 watcher trigger → Task 8 (FileWatcher), Task 9 (wire into serve)
- §11 skills → Task 10 (claude-mem-recall, claude-mem-trace, claude-mem-handoff)
- Phase 3 exit criterion (end-to-end demo) → Task 11 (acceptance test)

Out of scope by user choice (not in spec's Phase 3 either, deferred to Phase 4 polish):
- `install-hooks` post-commit installer
- `doctor` improvements
- Pluggable embedders

**2. Placeholder scan:** none. Every code block is complete. Tasks 10's markdown bodies are concrete examples; not placeholders.

**3. Type consistency:**
- `HandoffPayload` defined in Task 1, used in Task 2.
- `SnapshotResult` defined in Task 2.
- `ResumeResult` defined in Task 4, returned from Task 5.
- `PathDebouncer` defined in Task 6, used in Task 8.
- `incremental_reindex` defined in Task 7, used in Task 8.
- `FileWatcher` defined in Task 8, used in Task 9.

**4. Open questions:**
- `watchdog` may report duplicate events on some OS / editor combinations (atomic-write editors emit create+delete+move). The debouncer absorbs these naturally, but if integration tests flake, lengthen `quiet_ms` from 200 → 500.
- The `_relativize_scope` helper currently expects `repo_root.parts` — if Windows drive-letter handling regresses on incremental, mirror the fix from Phase 1's `rsplit(":", 1)[0]` trick.

---

## Execution handoff

Plan ready. Two options:

1. **Inline execution** with superpowers:executing-plans — run task-by-task in this session.
2. **Subagent-driven** with superpowers:subagent-driven-development — fresh sonnet per task, two-stage review.

12 tasks, ~150-200 LoC of production code each on the bigger ones. Sonnet inline is fine given the patterns are well-established by Phase 1/2.
