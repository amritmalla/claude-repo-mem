# claude-mem — Design Spec

**Status:** Draft for review
**Date:** 2026-05-25
**Supersedes:** `research.md` (vision-level; this doc is the v1 contract)

---

## 1. Product Framing

### 1.1 One-liner

A local-first MCP server plus companion Claude Code skills that give Claude durable project memory and hierarchical retrieval over a single repo's code, docs, and prior decisions — so Claude stops re-deriving context every session and stops dumping irrelevant code into prompts.

### 1.2 Load-bearing constraint

**claude-mem must operate within a small active context budget.** Every design choice in this document is justified against that constraint. The default retrieval budget is **~3,000 tokens per query**. Anything larger is opt-in.

### 1.3 Job-to-be-done

When a solo developer opens Claude Code on a repo they've worked on before, Claude should:

1. Already know the durable decisions, conventions, and structure of that repo.
2. Pull only the relevant slice of code/docs into context for the current task.
3. Be able to decompose a large task into small, independently-contextualized sub-tasks.
4. Be able to hand off the current task to a fresh session without losing state.

### 1.4 Primary user

A solo developer working in Claude Code on one repo at a time. Local-first. No team sync, no multi-tenant, no cloud.

### 1.5 Form factor

A **hybrid**:
- **MCP server** (`claude-mem`, Python) — runtime that indexes, retrieves, stores memory, and exposes MCP tools to Claude Code.
- **Companion skills** in the parent `claude-full-stack-2.0` plugin — teach Claude *when* and *how* to call those tools.

### 1.6 Explicitly out of scope for v1

The following from `research.md` are deferred or removed:

- Multi-tenant / team sync / shared memory
- Spring Boot, FastAPI, Postgres, Neo4j, Meilisearch, React UI
- Multi-agent orchestration runtime as a product surface
- General-purpose LLM-app SDK (claude-mem is Claude Code-first)
- Cross-project memory federation
- Telemetry / phone-home

---

## 2. Architecture Overview

### 2.1 Process shape

A single Python package `claude-mem` exposing:

- `claude-mem serve` — stdio MCP server Claude Code connects to. Runs a background file watcher.
- `claude-mem index` — one-shot full reindex CLI.
- `claude-mem distill` — end-of-session memory distillation CLI.
- `claude-mem doctor` — diagnostics.
- `claude-mem install-hooks` — optional git post-commit hook installer.

State lives at `<repo>/.claude-mem/`:

```
.claude-mem/
├── db.sqlite              # FTS5 + sqlite-vec + relational schema
├── blobs/                 # Content-addressed T0 snapshots (gzipped)
├── handoffs/              # Human-readable task snapshots, git-trackable
├── memory/                # User-authored markdown facts, git-trackable
└── scopes.yml             # Optional scope aliases / exclusions
```

The directory is partially git-tracked: `memory/`, `handoffs/`, and `scopes.yml` are committed; `db.sqlite` and `blobs/` are gitignored (derivable).

### 2.2 Subsystems

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP Tool Surface                       │
│  recall · expand · remember · forget · scopes · stats       │
│  plan_task · tasks · handoff · resume                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │     Retriever       │
                │  Hybrid: BM25 (FTS5)│
                │  + vector (sqlite-  │
                │  vec) + scope/      │
                │  recency boost.     │
                │  Budgeted greedy    │
                │  fill on T1.        │
                └──────────┬──────────┘
                           │
   ┌───────────────────────▼───────────────────────────┐
   │                Layered Substrate                  │
   │  ┌──────────┐    ┌──────────┐    ┌──────────┐    │
   │  │  Memory  │    │   Docs   │    │   Code   │    │
   │  │ (authored│    │ (derived)│    │ (derived)│    │
   │  │  + tasks)│    │ markdown │    │ tree-    │    │
   │  │          │    │ + front- │    │ sitter   │    │
   │  │          │    │ matter   │    │ symbols  │    │
   │  └──────────┘    └──────────┘    └──────────┘    │
   │   Shared unit schema. parent_id + relations table │
   │   provides lightweight cross-layer graph.         │
   └─────────┬──────────────────────┬──────────────────┘
             │                      │
   ┌─────────▼────────┐    ┌────────▼────────────┐
   │     Indexer      │    │     Summarizer      │
   │  Watcher + CLI;  │    │  T1: deterministic. │
   │  content_hash    │    │  T2: LLM, cached    │
   │  diff; reindexes │    │  by content_hash.   │
   │  only changed    │    │  Distillation: LLM  │
   │  units.          │    │  over transcript.   │
   └──────────────────┘    └─────────────────────┘
```

Four subsystems, each independently testable. Boundaries:

- **Retriever** depends only on the substrate's read interface. No knowledge of how units got there.
- **Substrate** is pure storage + query primitives. No LLM calls.
- **Indexer** is the only writer to derived layers (code/docs). It never writes memory.
- **Summarizer** is the only LLM caller in the indexing path. Memory layer reads/writes go through the substrate directly.

### 2.3 Key behaviors

1. **Retrieval is budgeted greedy fill on T1 summaries.** Given a query and a budget B (default 3,000 tokens): embed the query, run hybrid search across all three layers, rank with a single blended score, pack T1 summaries until B is hit. Return the ranked list with opaque handles for everything that didn't fit.

2. **Expansion is one handle at a time, Claude-driven.** `expand(handle, tier)` returns just that unit at the requested tier (T2 LLM summary or T0 full content). Claude controls token spend explicitly. The server never auto-expands.

3. **Reindex is incremental and idempotent.** Files are content-hashed; unchanged files are skipped. Changed files are re-parsed into semantic units, unit content_hashes are diffed, and only changed/new units are re-embedded and re-summarized. LLM cost is paid only for actual diffs.

4. **Memory is authored, not derived.** Memory units are the only layer Claude or the user writes directly. They carry explicit `scope`, `confidence`, and `superseded_by` so the retriever can prefer fresh over stale.

5. **Tasks are memory.** A task is a memory unit of kind `task`. Breakdown produces child task units with attached `context_handles`. Handoff produces `task_snapshot` units. No new storage primitives.

6. **No LLM in the hot retrieval path.** `recall` and `expand` are pure storage + ranking. LLM cost is bounded to: (a) T2 summary generation during indexing, (b) distillation at session end, (c) task decomposition in `plan_task`. All three are explicit, batched, or user-triggered.

---

## 3. Data Model

### 3.1 Unit schema (shared across all three layers)

```sql
CREATE TABLE unit (
  id              TEXT PRIMARY KEY,         -- e.g. mem://fn/<hash>
  layer           TEXT NOT NULL,            -- memory | docs | code
  kind            TEXT NOT NULL,            -- function|class|section|fact|decision|preference|task|task_snapshot
  scope           TEXT NOT NULL,            -- e.g. backend/auth
  source_ref      TEXT,                     -- file path + range, or memory/*.md path
  content_hash    TEXT NOT NULL,            -- sha256 of T0 content
  t1_header       TEXT NOT NULL,            -- deterministic, e.g. signature or heading
  t2_summary      TEXT,                     -- LLM-generated, null until summarized
  embedding       BLOB,                     -- sqlite-vec
  parent_id       TEXT REFERENCES unit(id),
  superseded_by   TEXT REFERENCES unit(id),
  confidence      REAL,                     -- memory layer only
  created_at      INTEGER NOT NULL,
  last_seen_at    INTEGER NOT NULL,         -- updated on every reindex that sees the unit
  metadata        TEXT                      -- JSON, kind-specific
);

CREATE VIRTUAL TABLE unit_fts USING fts5(
  id UNINDEXED, t1_header, t2_summary, content='unit'
);

CREATE VIRTUAL TABLE unit_vec USING vec0(
  id TEXT PRIMARY KEY,
  embedding FLOAT[384]   -- bge-small dimension
);

CREATE TABLE relation (
  src_id   TEXT NOT NULL REFERENCES unit(id),
  dst_id   TEXT NOT NULL REFERENCES unit(id),
  kind     TEXT NOT NULL,    -- mentions | decides_about | implements | supersedes | child_task | resumes
  PRIMARY KEY (src_id, dst_id, kind)
);
```

### 3.2 Task-specific metadata (JSON in `metadata`)

For `kind = 'task'`:

```json
{
  "title": "...",
  "intent": "...",
  "status": "pending|active|done|blocked",
  "acceptance": ["..."],
  "context_handles": ["mem://...", "code://...", "doc://..."],
  "open_questions": ["..."],
  "decisions_made": ["mem://..."],
  "session_id": "..."
}
```

For `kind = 'task_snapshot'`:

```json
{
  "task_id": "...",
  "resume_markdown_path": ".claude-mem/handoffs/<task_id>.md",
  "snapshot_at": 1735000000
}
```

### 3.3 Why one table

Three layers, one schema, one ranking function. Cross-layer relations (memory→function, decision→doc) live in `relation` without requiring a real graph DB. This is the "lightweight graph" — a pragmatic substitute for Neo4j that handles every cross-layer query we need.

---

## 4. Retrieval

### 4.1 Ranking

Single blended score per candidate unit:

```
score = w_bm25 * bm25_norm
      + w_vec  * cosine_norm
      + w_scope * scope_match
      + w_recency * recency_decay(last_seen_at)
      + w_layer * layer_boost[layer]
      - w_super * is_superseded
```

Defaults (subject to tuning):

| Term | Weight | Notes |
|---|---|---|
| `w_bm25` | 0.30 | FTS5 normalized to [0,1] |
| `w_vec` | 0.40 | cosine on bge-small embeddings |
| `w_scope` | 0.15 | 1.0 if query scope matches unit scope, decayed by tree distance |
| `w_recency` | 0.10 | exp decay, half-life 30 days |
| `w_layer` | 0.05 | memory: +1.0, docs: +0.3, code: 0 |
| `w_super` | 1.0 (penalty) | superseded units are filtered by default |

### 4.2 Budgeted greedy fill

```
1. Embed query.
2. Pull top-K (default 100) candidates via hybrid search across all layers.
3. Rank by §4.1 score.
4. Greedy pack: for each candidate in score order,
   include t1_header if it fits in remaining budget; else add to overflow.
5. Return { items: [...], overflow_handles: [...], budget_used, budget_total }.
```

### 4.3 Scope filtering

`recall(query, scopes=["backend/auth"])` filters candidates to units in matching scopes before ranking. This is the primary mechanism for preventing context pollution.

---

## 5. MCP Tool Surface (10 tools)

All tools return structured JSON. All handles are opaque strings (`mem://...`, `code://...`, `doc://...`, `task://...`).

| Tool | Inputs | Returns |
|---|---|---|
| `recall` | `query`, `budget?`, `scopes?`, `layers?`, `include_superseded?` | Ranked T1 items + overflow handles |
| `expand` | `handle`, `tier` ∈ `t2`\|`t0` | Unit content at the requested tier |
| `remember` | `fact`, `scope`, `kind?`, `confidence?`, `supersedes?` | New memory handle |
| `forget` | `handle` \| `query`+`scope` | Count of tombstoned units |
| `scopes` | — | Known scopes with unit counts |
| `stats` | — | Index size, last reindex, cache hit rate, layer counts |
| `plan_task` | `intent`, `parent_id?`, `budget?` | Task tree with attached context bundles |
| `tasks` | `filter?` (status, scope, recency) | List of task units |
| `handoff` | `task_id?` (defaults to active) | Snapshot handle + markdown path |
| `resume` | `task_id` | Hydrated bundle as if a `recall` response |

The surface is small, single-purpose, and read/write-separated. Claude can be taught each tool in isolation via a companion skill.

---

## 6. Tasks and Handoff

### 6.1 `plan_task` flow

1. Caller provides an `intent` (and optionally a `parent_id`).
2. Server runs `recall(intent, budget=4k)` to gather context for decomposition.
3. Server makes one LLM call with the gathered context and a fixed decomposition prompt: "Break this intent into 2–6 independent sub-tasks. For each, write a 1-line title, a 3–5-line goal, and acceptance bullets."
4. For each proposed sub-task, server runs `recall(sub_task.intent, budget=2k)` and attaches the returned handles as the sub-task's `context_handles`.
5. Server writes the parent task + children to `unit` with `relation(parent, child, 'child_task')`.
6. Returns the task tree.

The expensive "understand the whole repo" cost is paid once. Each sub-task can be picked up by a fresh Claude session (or subagent) with a sized bundle.

### 6.2 `handoff` flow

1. Caller invokes `handoff()` (or `handoff(task_id)` for a specific task).
2. Server collects: task metadata, recent `decisions_made`, current `open_questions`, last N `remember()` writes scoped to the task, the task's `context_handles`.
3. Server renders a markdown snapshot to `.claude-mem/handoffs/<task_id>.md` (human-readable, git-friendly) and writes a `task_snapshot` unit pointing at it.
4. Returns the snapshot handle.

### 6.3 `resume` flow

1. Fresh session calls `resume(task_id)`.
2. Server loads the snapshot, reads the markdown, hydrates the `context_handles` via `recall`-equivalent budgeted fill.
3. Returns a single structured response: `{ snapshot_markdown, hydrated_items, overflow_handles }`.
4. New session starts at ~2–4k tokens of context, fully oriented.

### 6.4 Why this matters for the budget thesis

Without tasks, every session re-discovers context (large reads, large prompts, fast bloat). With tasks:

- **Breakdown** trades one big context budget for N small focused ones.
- **Handoff** caps session length — instead of context bloating until the conversation chokes, you snapshot and resume in a fresh session at a known budget.
- **Subagent dispatch** becomes practical because each agent gets a sized bundle, not the whole repo.

---

## 7. Indexing

### 7.1 Triggers (layered)

- **Manual:** `claude-mem index` — full reindex, for first run or recovery.
- **Watcher (default-on while `serve` is running):** debounced filesystem watcher, re-hashes touched files, re-parses changed ones.
- **Git hook (optional):** `claude-mem install-hooks` installs a post-commit hook for users who don't want the watcher running.

### 7.2 Incremental algorithm

```
For each changed file F:
  content_hash_new = sha256(F)
  if content_hash_new == stored(F): skip
  units_new = parse(F)                    # tree-sitter for code, mdAST for docs
  For each unit U in units_new:
    if exists(U.id) and U.content_hash == stored(U.id).content_hash:
      touch(U.last_seen_at); continue
    upsert(U) with t1_header computed deterministically
    enqueue_for_t2_and_embed(U)
  For each previously-known unit in F not in units_new:
    mark stale (eligible for tombstoning after grace period)
```

T2 summary and embedding are computed asynchronously in a background worker — `recall` works on units with only T1 populated, just with weaker ranking.

### 7.3 Parser registry

- **Code:** tree-sitter via `tree-sitter-languages`. Unit kinds: `function`, `method`, `class`, `interface`, `module`. Languages: Python + JS/TS in Phase 1; Java, Go, Rust added in Phase 4.
- **Docs:** markdown via `markdown-it-py` with frontmatter. Unit kinds: `section` (heading-bounded), `frontmatter`.
- **Memory:** flat markdown files in `.claude-mem/memory/<scope>/<slug>.md` with YAML frontmatter. Unit kind: `fact`, `decision`, `preference`, `convention`.

---

## 8. Memory Writes

### 8.1 In-session writes — `remember(fact, scope, ...)`

Claude calls `remember` when it learns something durable. The companion skill `claude-mem-recall` teaches it the trigger conditions: an explicit decision, a discovered convention, a corrected misunderstanding, a user-stated preference.

Conflict handling: if a unit in the same scope has cosine similarity above a threshold (default 0.85) and either an explicit `supersedes` is passed or simple negation heuristics detect contradiction, the old unit is marked `superseded_by` the new one. No silent deletion. `recall(..., include_superseded=true)` exposes the history for audit.

### 8.2 End-of-session distillation — `claude-mem distill`

Invoked by the user (or a session-end hook) at the end of a working session. The CLI:

1. Reads the recent transcript (Claude Code's conversation history).
2. Makes one LLM call with a fixed extraction prompt: "Extract durable facts, decisions, conventions, and preferences from this session. For each, propose `{fact, scope, kind, confidence}`. Skip ephemeral content."
3. Presents the proposed memory writes to the user for confirm/edit/skip.
4. Writes confirmed entries as memory units.

This is the **only** path to memory that runs without explicit per-fact intent. Human gate prevents the junk-drawer failure mode.

---

## 9. Embeddings and Summaries

### 9.1 Embedding model

- **Default:** `bge-small-en-v1.5` (384-dim, ~100MB, CPU-fast) via `sentence-transformers`.
- **Pluggable:** `CLAUDE_MEM_EMBED=openai:text-embedding-3-small` or `voyage:voyage-3` swaps in API embeddings. Behind a `Embedder` interface; one method, `embed(texts) -> vectors`.
- **Rationale:** local default keeps installation friction near zero and works offline. API option exists for users who want stronger recall and accept the cost/latency/privacy trade.

### 9.2 T2 summary model

- Uses the user's existing Claude Code authentication (same credentials as the parent plugin). No separate API key required.
- Haiku-class model. Summaries are short (~100 tokens) and prompt-stable.
- Cached forever by `content_hash`. A unit's summary is only regenerated if its content changes.

### 9.3 T1 (deterministic) headers

| Layer | Unit kind | T1 header |
|---|---|---|
| Code | function/method | `<lang> <name>(<params>) -> <return>` |
| Code | class/interface | `<lang> class <name>(<bases>): <docstring first line>` |
| Docs | section | `# <heading path>` (e.g. `# Auth > JWT > Refresh`) |
| Memory | fact/decision | first 80 chars of the fact, prefixed by `[<kind>]` |
| Memory | task | `[task:<status>] <title>` |

T1 is always present, always cheap, never requires LLM.

---

## 10. Scopes

### 10.1 Auto-derivation

By default, a unit's scope is derived from its `source_ref` path: `backend/auth/jwt.py` → scope `backend/auth`. Markdown unit scope falls back to the directory containing the file unless frontmatter declares `scope: ...`.

### 10.2 User overrides — `.claude-mem/scopes.yml`

```yaml
aliases:
  backend/auth: [backend/security, backend/identity]
exclusions:
  - vendor/**
  - .venv/**
  - dist/**
```

No required configuration to start. The file exists only if the user wants to override defaults.

### 10.3 Scope use in retrieval

- `recall(scopes=[...])` hard-filters to matching scopes.
- Without explicit scopes, ranking soft-boosts units whose scope matches keywords extracted from the query (heuristic, not LLM).

---

## 11. Companion Skills (in `claude-full-stack-2.0`)

Four small skills, each a single markdown file under `skills/claude-mem/`:

| Skill | Triggers on | Teaches |
|---|---|---|
| `claude-mem-bootstrap` | First-time setup on a repo | Run `claude-mem index`, derive scopes, verify `serve` is reachable |
| `claude-mem-recall` | Start of any task, before reading files | When to `recall` vs work from existing context; how to interpret budget overflow |
| `claude-mem-task` | Long or multi-part task intent | When to `plan_task`; how to dispatch sub-tasks to subagents with bundles; how to write `decisions_made` back |
| `claude-mem-handoff` | End of session, context bloat, task switch | When to `handoff()` and `resume(task_id)` |

The skills are the contract between Claude Code's behavior and the MCP server's capabilities. They are how we shape Claude's usage patterns toward small active context.

---

## 12. Build Plan (phased)

### Phase 1 — Substrate and retrieval (weeks 1–3)

- SQLite schema, FTS5, sqlite-vec integration
- Indexer for code (tree-sitter, Python+JS+TS first) and docs
- T1 deterministic headers; embeddings via bge-small
- `recall` and `expand` MCP tools
- `claude-mem index` CLI
- **Exit criterion:** on a real repo, `recall("how does auth work")` returns a ranked list of relevant T1 summaries within 3k tokens in <500ms.

### Phase 2 — Memory and tasks (weeks 4–6)

- Memory layer schema and write path
- `remember`, `forget`, `scopes`, `stats` tools
- T2 LLM summaries via Claude Code auth
- `plan_task`, `tasks` tools
- Distillation CLI with user-confirm UX
- **Exit criterion:** a working session ends with a usable distilled memory set; `plan_task` produces sub-tasks with attached bundles that another session can pick up.

### Phase 3 — Handoff and integration (weeks 7–8)

- `handoff`, `resume` tools and markdown snapshot rendering
- File watcher daemon in `serve`
- Companion skills in parent plugin
- `claude-mem doctor`, install-hooks
- **Exit criterion:** end-to-end demo — start task, decompose, work in subagents, handoff, resume in fresh session — all within budget.

### Phase 4 — Polish (week 9+)

- Pluggable embedder (OpenAI/Voyage)
- Ranking weight tuning against a real workload
- Additional languages for tree-sitter (Java, Go, Rust)
- Performance: incremental embedding queue, summary backlog management

---

## 13. Non-goals (restated)

To keep the v1 surface honest, these are explicit non-goals — not "later," but "not the product":

- A general-purpose RAG SDK.
- A documentation site or web UI.
- Team sync, conflict resolution across users, cloud storage.
- A query language beyond `recall(query, scopes?, layers?)`.
- A graph database. The `relation` table is sufficient.
- Real-time semantic understanding beyond what tree-sitter + embeddings provide. Call-graph reasoning, type inference, dataflow are out.

---

## 14. Success Metrics

Local, observable, no telemetry:

- **Token reduction ratio:** baseline token usage on a representative task with naive context loading, vs. with claude-mem. Target: ≥ 60% reduction for typical "implement feature X" tasks on a 50k-LOC repo.
- **Retrieval latency:** p50 < 200ms, p95 < 500ms for `recall` on a 50k-LOC repo.
- **Reindex cost:** full reindex of a 50k-LOC repo completes in < 5 minutes on CPU; incremental reindex of one changed file < 2 seconds.
- **Handoff fidelity:** a task handed off and resumed in a fresh session can be continued without the user re-explaining state. Measured by user survey on first 10 dogfood sessions.

---

## 15. Open Questions (to resolve during implementation, not now)

1. Ranking weight defaults (§4.1) need real-workload calibration.
2. Subagent dispatch UX: should `plan_task` optionally spawn subagents directly, or always return a tree for Claude to dispatch?
3. Memory `confidence` semantics: numeric (0–1), categorical (high/med/low), or both?
4. Whether `forget` should support time-window queries ("forget anything I said about X this week").
5. Whether `.claude-mem/memory/` markdown should be the source of truth (regenerable into SQLite) or a snapshot (SQLite is truth, markdown is exported). Default current choice: markdown is truth, SQLite is derived.

---
