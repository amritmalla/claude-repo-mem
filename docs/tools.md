# MCP tool reference

`claude-repo-mem` exposes 11 tools over MCP. Claude Code calls them automatically
once the server is wired into your workspace (see [usage.md](usage.md)); this page
documents what each one does, its parameters, and what it returns.

## Operating principle

The server advertises itself as the authoritative source for the repo's code,
docs, and accumulated decisions. The intended call pattern:

- **`recall` before native Read/Grep** — it returns ranked, summarized, scoped
  results within a token budget instead of whole files.
- **`trace` instead of repeated `expand`** — it returns full source for connected
  nodes (callers, handlers, hooks, routes) in one round-trip.
- Reach for native file tools only when recall returns nothing useful, when
  working on files outside the repo, or when verifying an edit not yet reindexed.

## Tiers and handles

Retrieval results are filled at three tiers:

| Tier | Content |
|------|---------|
| `T0` | Full source / full content |
| `T2` | LLM-generated summary |
| `T1` | Header only (signature, heading) |

Every result carries an opaque **handle**. Handles are how you move between
tools — feed a handle from `recall` into `trace`, `expand`, `remember`
(`supersedes`), or `forget`.

---

## Retrieval

### `recall`

Hybrid (lexical + vector) retrieval. Returns ranked results budget-filled across
tiers: T0 for top hits, T2 for the mid-tier, T1 for the tail.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `query` | string | — | **Required.** Natural-language query. |
| `budget` | integer | 3000 | Max tokens to return. |
| `scopes` | string[] | — | Scope filter, e.g. `["backend/auth"]`. |
| `layers` | string[] | — | Restrict to `memory`, `docs`, and/or `code`. |
| `include_superseded` | boolean | false | Include tombstoned/superseded units. |

**Returns:** `items` (each with `handle`, `tier`, `content`, `rank`, `scope`,
`layer`), plus `overflow_handles`, `budget_used`, `budget_total`, and a
`tier_histogram`.

### `trace`

Traverse from one or more seed handles to connected units and return full source
inline for the top hits in a single call.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `seed_handles` | string[] | — | **Required.** Handles from a prior `recall`. |
| `depth` | integer | — | Max BFS hops (capped at 3). |
| `budget` | integer | 8000 | Max tokens to return. |
| `relations` | string[] | — | Filter on relation kinds, e.g. `["route_to","imports"]`. |

**Returns:** the same shape as `recall` (`items`, `overflow_handles`,
`budget_used`, `budget_total`, `tier_histogram`).

### `expand`

Return a single unit at a specific tier. Use for long-tail drill-down — the common
"top result + full code" case is already covered by `recall` and `trace`.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `handle` | string | — | **Required.** Handle from `recall`/`trace`. |
| `tier` | string | `T0` | One of `T0`, `T2`, `T1`. |

**Returns:** `handle`, `tier`, `content`, `scope`, `layer`, `kind`, `source_ref`.
Returns `{"error": "handle not found"}` for an unknown handle.

---

## Memory

### `remember`

Write a durable memory entry. Use when you learn something the user will care
about across sessions: a decision, convention, preference, or fact about the repo.
Memory files are written to `.claude-repo-mem/memory/<scope>/<slug>.md` and are
git-trackable.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `fact` | string | — | **Required.** The text to remember. |
| `scope` | string | — | **Required.** Scope, e.g. `backend/auth`. |
| `kind` | string | `fact` | One of `fact`, `decision`, `preference`, `convention`. |
| `confidence` | number | — | 0–1. |
| `supersedes` | string | — | Handle of a unit this entry replaces. |

**Returns:** `handle`, `slug`, and the markdown `path`.

### `forget`

Tombstone a memory unit by handle. Marks the unit superseded and appends
`tombstoned: true` to the markdown frontmatter — the file is **not** deleted. Use
when a memory has become wrong or obsolete.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `handle` | string | — | **Required.** |

**Returns:** `{"ok": true}`, or `{"error": ...}` if the handle is unknown.

### `scopes`

List known scopes for the repo with live unit counts.

No parameters. **Returns:** `scopes` — a list of `{scope, count}`, busiest first.

---

## Tasks and handoff

### `plan_task`

Decompose a high-level intent into 2–6 independent child tasks via the LLM,
persist the task tree, and return it. Use at the start of a multi-step task before
writing code. Requires an LLM backend (see [usage.md](usage.md#llm-backend)).

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `intent` | string | — | **Required.** |
| `parent_id` | string | — | Attach under an existing task. |
| `scope` | string | `root` | Scope for the new tasks. |
| `context_handles` | string[] | — | Handles to attach as context. |

**Returns:** `root` (`handle`, `title`, `intent`) and `children` (each with
`handle`, `title`, `intent`, `acceptance`, `context_handles`).

### `tasks`

List tasks, filtered by status, scope, or recency.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `status` | string | — | One of `pending`, `active`, `done`, `blocked`. |
| `scope` | string | — | Scope filter. |
| `since_days` | integer | — | Only tasks seen within N days. |

**Returns:** `tasks` — each with `handle`, `title`, `intent`, `status`, `scope`,
`acceptance`, `context_handles`, `parent`.

### `handoff`

Render the current state of a task to a markdown snapshot under
`.claude-repo-mem/handoffs/` and write a `task_snapshot` unit. Use at the end of a
session or before a context-budget reset.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `task_id` | string | — | **Required.** Handle of the task to snapshot. |

**Returns:** `task_id`, `snapshot_handle`, `markdown_path`.

### `resume`

Pick up a task from its most recent handoff snapshot. Returns the snapshot
markdown plus a budgeted bundle of the task's context handles. Use at the start of
a fresh session when continuing work.

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `task_id` | string | — | **Required.** |
| `budget` | integer | 4000 | Min 200. Token budget for hydrated context. |

**Returns:** `task_id`, `snapshot_markdown`, `hydrated_items`, `overflow_handles`.

---

## Diagnostics

### `stats`

Index size, layer breakdown, and tool-call counters.

No parameters. **Returns:** `total_units`, `by_layer`, `total_relations`, and
`counters` (per-tool call counts). The same data is available from the CLI via
`claude-repo-mem doctor`.
