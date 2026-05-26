# claude-repo-mem — Design Spec

**Status:** Draft for review
**Date:** 2026-05-25
**Supersedes:** `research.md` (vision-level; this doc is the v1 contract)

---

## 1. Product Framing

### 1.1 One-liner

A local-first MCP server plus companion Claude Code skills that give Claude durable project memory and hierarchical retrieval over a single repo's code, docs, and prior decisions — so Claude stops re-deriving context every session and stops dumping irrelevant code into prompts.

### 1.2 Load-bearing constraint

**claude-repo-mem must operate within a small active context budget — but the right optimization target is wall-clock latency and tool-call count, not raw token frugality.** Forcing Claude into many small tool calls to keep individual responses tiny is a worse outcome than one slightly larger call that finishes the job. Tools therefore get **per-tool budgets** sized to their question (§4 and §5), with the hot-path `recall` kept tight (3k) and traversal-class tools (`trace`, `plan_task`) given headroom because the alternative is grep loops.

The principle stated positively: minimize *total tokens across the turn* and *turns per task*, not tokens-per-tool-call.

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
- **MCP server** (`claude-repo-mem`, Python) — runtime that indexes, retrieves, stores memory, and exposes MCP tools to Claude Code.
- **Companion skills** in the parent `claude-full-stack-2.0` plugin — teach Claude *when* and *how* to call those tools.

### 1.6 Explicitly out of scope for v1

The following from `research.md` are deferred or removed:

- Multi-tenant / team sync / shared memory
- Spring Boot, FastAPI, Postgres, Neo4j, Meilisearch, React UI
- Multi-agent orchestration runtime as a product surface
- General-purpose LLM-app SDK (claude-repo-mem is Claude Code-first)
- Cross-project memory federation
- Telemetry / phone-home

---

## 2. Architecture Overview

### 2.1 Process shape

A single Python package `claude-repo-mem` exposing:

- `claude-repo-mem serve` — stdio MCP server Claude Code connects to. Runs a background file watcher.
- `claude-repo-mem index` — one-shot full reindex CLI.
- `claude-repo-mem distill` — end-of-session memory distillation CLI.
- `claude-repo-mem doctor` — diagnostics.
- `claude-repo-mem install-hooks` — optional git post-commit hook installer.

State lives at `<repo>/.claude-repo-mem/`:

```
.claude-repo-mem/
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
│  recall · trace · expand · remember · forget · scopes · stats│
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

1. **Retrieval is budget-aware tiered fill.** Given a query and a budget B (default 3,000 tokens): embed the query, run hybrid search (BM25 + vector) across all three layers, rank with RRF + feature multipliers, then greedily pack each candidate at the richest tier that fits — T0 for top-ranked small units, T2 for mid-tier, T1 for the long tail. Two guardrails (`TOP_PROMOTE`, `T0_SINGLE_CAP`, §4.2) prevent any single unit from dominating the response. Return the ranked list with opaque handles for everything that overflowed.

2. **Expansion handles the long tail, not the common case.** `expand(handle, tier)` returns one unit at the requested tier (T2 or T0). The common case (top result needs full content) is already handled by §4.2's auto-promotion; `expand` exists for cases where a mid-ranked T2 turns out to be the critical one.

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
  "resume_markdown_path": ".claude-repo-mem/handoffs/<task_id>.md",
  "snapshot_at": 1735000000
}
```

### 3.3 Why one table

Three layers, one schema, one ranking function. Cross-layer relations (memory→function, decision→doc) live in `relation` without requiring a real graph DB. This is the "lightweight graph" — a pragmatic substitute for Neo4j that handles every cross-layer query we need.

---

## 4. Retrieval

### 4.1 Ranking — RRF + feature rerank

Two-stage. **Stage 1** fuses the two retrieval-ranked lists (BM25 and vector) with Reciprocal Rank Fusion. **Stage 2** applies per-unit feature multipliers. Rationale: BM25 and cosine scores live on incomparable scales — linearly combining their normalized values is fragile and demands constant retuning. RRF is scale-free and the industry default (Elastic, Vespa, Weaviate). Scope/recency/layer are per-unit features, not ranked lists, so they belong in a rerank pass, not the fusion.

```
# Stage 1: RRF over the two ranked candidate lists
rrf(u) = 1 / (k + rank_bm25(u)) + 1 / (k + rank_vec(u))      # k = 60

# Stage 2: feature rerank
final(u) = rrf(u)
         * scope_mult(u)
         * recency_mult(u)
         * layer_mult(u)
         * (0 if superseded else 1)
```

Feature multipliers (defaults, subject to calibration):

| Feature | Formula | Notes |
|---|---|---|
| `scope_mult` | 1.0 exact match, 0.7 sibling, 0.4 unrelated | Decay by tree distance |
| `recency_mult` | `0.5 + 0.5 * exp(-age_days * ln2 / 30)` | Half-life 30d, floor 0.5 |
| `layer_mult` | memory 1.5, docs 1.1, code 1.0 | Memory wins ties |
| superseded | hard zero (filtered) | Unless `include_superseded=true` |

A candidate that appears in only one of the two retrieval lists still gets a fusion score from the single contribution; this is RRF's standard behavior and is the right thing for handling vector-only or keyword-only matches.

### 4.2 Budget-aware tiered fill

The retriever does not force Claude to round-trip for every drill-down. Instead it greedily picks the **richest tier that fits** for each candidate in rank order, with two guardrails to preserve the "no surprise blowup" invariant.

```
TOP_PROMOTE = 5            # only top-ranked candidates are eligible for T0 promotion
T0_SINGLE_CAP = 0.4        # a single T0 unit can never exceed 40% of remaining budget

for u in candidates_by_score:
    if rank(u) <= TOP_PROMOTE and size_t0(u) <= remaining * T0_SINGLE_CAP:
        include(u, tier=T0); continue          # top result, fits cleanly → full content
    if size_t2(u) <= remaining:
        include(u, tier=T2); continue          # mid-tier → LLM summary
    if size_t1(u) <= remaining:
        include(u, tier=T1); continue          # tail → deterministic header
    overflow.append(handle(u))                  # didn't fit at any tier
```

Why the guardrails:

- **`TOP_PROMOTE`** ensures budget is spent on breadth (many T1/T2 items) rather than swallowed by a mid-relevance T0. Without it, a 600-token T2-less unit ranked 12th could displace ten T1 results that would have been more useful.
- **`T0_SINGLE_CAP`** caps any single unit at 40% of remaining budget, so no oversized function can dominate the response.

Claude retains `expand(handle, tier)` for cases where the auto-fill missed (e.g. a mid-ranked T2 was actually critical and Claude wants T0). The auto-fill optimizes the common case; expand handles the long tail.

### 4.3 Pipeline

```
1. Embed query.
2. Retrieve top-K (default 100) candidates from BM25 (FTS5) and vector (sqlite-vec) independently.
3. Compute RRF + feature multipliers; sort by final(u).
4. Run budget-aware tiered fill (§4.2).
5. Return { items: [{handle, tier, content}, ...], overflow_handles: [...],
           budget_used, budget_total, tier_histogram }.
```

`tier_histogram` (e.g. `{T0: 1, T2: 4, T1: 8}`) is included so Claude can see at a glance how much detail it got and decide whether to drill further.

### 4.3 Scope filtering

`recall(query, scopes=["backend/auth"])` filters candidates to units in matching scopes before ranking. This is the primary mechanism for preventing context pollution.

---

## 5. MCP Tool Surface (11 tools)

All tools return structured JSON. All handles are opaque strings (`mem://...`, `code://...`, `doc://...`, `task://...`). Each tool has a **default budget** sized to its question (§1.2 rationale); callers can override per call.

| Tool | Inputs | Default budget | Returns |
|---|---|---|---|
| `recall` | `query`, `budget?`, `scopes?`, `layers?`, `include_superseded?` | 3k | Ranked items (tiered fill §4.2) + overflow handles |
| `trace` | `seed_handle(s)`, `depth?` (default 2), `relations?`, `budget?` | 8k | Connected units with **full T0** inline, single call (§5.1) |
| `expand` | `handle`, `tier` ∈ `t2`\|`t0` | unit-sized | One unit at the requested tier (long-tail drill-down) |
| `remember` | `fact`, `scope`, `kind?`, `confidence?`, `supersedes?` | — | New memory handle |
| `forget` | `handle` \| `query`+`scope` | — | Count of tombstoned units |
| `scopes` | — | — | Known scopes with unit counts |
| `stats` | — | — | Index size, last reindex, cache hit rate, layer counts |
| `plan_task` | `intent`, `parent_id?`, `budget?` | 6k | Task tree with attached context bundles |
| `tasks` | `filter?` (status, scope, recency) | — | List of task units |
| `handoff` | `task_id?` (defaults to active) | — | Snapshot handle + markdown path |
| `resume` | `task_id` | 4k | Hydrated bundle as if a `recall` response |

The surface is small, single-purpose, and read/write-separated. Claude can be taught each tool in isolation via a companion skill.

### 5.1 `trace` — traversal from a seed

`recall` answers "what's relevant to this query." `trace` answers "starting from this handle, what's connected, and show me the code." Different question, different tool. Forces a single round-trip instead of N `expand` calls when Claude already knows the entry point.

```
Inputs:
  seed_handle(s)    one or more handles (typically from a prior recall)
  depth             max hops in the relation graph (default 2, cap 3)
  relations         filter on relation kinds (e.g. ['implements','mentions',
                    'route_to','handler_of']); default = all
  budget            token cap (default 8k)

Algorithm:
  1. BFS from seeds in the relation graph, up to `depth` hops.
  2. Rank discovered nodes by: (a) hop distance, (b) relation-kind weight,
     (c) RRF-equivalent feature multipliers (recency, layer).
  3. Run §4.2's tiered fill against the larger trace budget — top results
     inline as T0, mid as T2, tail as T1. Same guardrails apply
     (T0_SINGLE_CAP, TOP_PROMOTE).
  4. Return units in graph order (DFS from seed), each tagged with the
     relation kind that brought it in and its tier.

Returns:
  { seeds: [...], path: [{handle, tier, content, relation, hop_distance}],
    overflow_handles, tier_histogram, budget_used }
```

The mental model: `recall` builds a fresh result set from a query; `trace` walks the graph from a known foothold and brings back the code. Both are budgeted, both are single-shot, both use the same tiered fill so behavior is consistent.

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
3. Server renders a markdown snapshot to `.claude-repo-mem/handoffs/<task_id>.md` (human-readable, git-friendly) and writes a `task_snapshot` unit pointing at it.
4. Returns the snapshot handle.

### 6.3 `resume` flow

1. Fresh session calls `resume(task_id)`.
2. Server loads the snapshot, reads the markdown, hydrates the `context_handles` via `recall`-equivalent budgeted fill.
3. Returns a single structured response: `{ snapshot_markdown, hydrated_items, overflow_handles }`.
4. New session starts at ~2–4k tokens of context, fully oriented.

### 6.4 Design rationale — primary agent over subagents

Prior art (codegraph and similar projects) finds that giving the primary agent enough context to *avoid* spawning exploration subagents is dramatically more efficient than designing for parallel sub-explorers. Subagents are slow, costly, and lose state on completion. claude-repo-mem's task model is built around that finding: `plan_task` produces a tree the primary agent can either work directly or hand to a subagent *with a pre-sized bundle*, and `handoff`/`resume` lets a single primary agent sustain work across sessions without re-discovery. The architecture optimizes for "one agent, fully informed" before it optimizes for "many agents, coordinating."

### 6.5 Why this matters for the budget thesis

Without tasks, every session re-discovers context (large reads, large prompts, fast bloat). With tasks:

- **Breakdown** trades one big context budget for N small focused ones.
- **Handoff** caps session length — instead of context bloating until the conversation chokes, you snapshot and resume in a fresh session at a known budget.
- **Subagent dispatch** becomes practical because each agent gets a sized bundle, not the whole repo.

---

## 7. Indexing

### 7.1 Triggers (layered)

- **Manual:** `claude-repo-mem index` — full reindex, for first run or recovery.
- **Watcher (default-on while `serve` is running):** debounced filesystem watcher, re-hashes touched files, re-parses changed ones.
- **Git hook (optional):** `claude-repo-mem install-hooks` installs a post-commit hook for users who don't want the watcher running.

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

### 7.3 Heuristic synthesizers — framework-aware edges

Pure tree-sitter parsing produces nodes but not the edges Claude needs to follow flow. The classic failure modes are dynamic dispatch boundaries: web framework routes, event handlers, callbacks, hooks. Without bridging these, Claude falls back to repo-wide grep — the exact failure mode claude-repo-mem exists to prevent.

The compromise: not a full call graph (out of scope; would require type inference or a language server), but **targeted, per-framework synthesizers** that emit `relation` rows during indexing. Each synthesizer is a small focused module (~50–200 lines) that pattern-matches known framework conventions and records the edge it found. Synthesizers are intentionally heuristic — they don't try to be sound, they try to be useful enough that Claude doesn't reach for grep.

V1 synthesizers (each gated by language/framework detection):

| Synthesizer | Pattern | Relation emitted |
|---|---|---|
| `py.flask_routes` | `@app.route("/x")` / `@bp.route` decorators | `route_to` |
| `py.fastapi_routes` | `@app.get/post/...("/x")` decorators | `route_to` |
| `py.django_urls` | `urls.py` `path("x", view)` calls | `route_to` |
| `js.express_routes` | `app.get/post(path, handler)` calls | `route_to` |
| `js.react_hooks` | `useState`/`useReducer`/`useCallback` setter usage | `mutates_state_of` |
| `js.react_custom_hooks` | `use*` function calls inside components | `consumed_by` |
| `imports` (all langs) | static import/require statements | `imports` |

Synthesizers run after tree-sitter parsing in the indexer, take parsed units as input, and emit `relation` rows. They are pure functions over already-extracted unit metadata — no LLM, no re-parsing. Failure of one synthesizer never blocks indexing; it just produces fewer edges.

V1 acceptance bar: at least one route-style synthesizer per supported web framework, plus imports. Additional synthesizers (Spring `@RequestMapping`, Express middleware chains, Vue/Svelte reactivity) are added incrementally as language coverage grows in Phase 4.

### 7.4 Parser registry

- **Code:** tree-sitter via `tree-sitter-languages`. Unit kinds: `function`, `method`, `class`, `interface`, `module`. Languages: Python + JS/TS in Phase 1; Java, Go, Rust added in Phase 4.
- **Docs:** markdown via `markdown-it-py` with frontmatter. Unit kinds: `section` (heading-bounded), `frontmatter`.
- **Memory:** flat markdown files in `.claude-repo-mem/memory/<scope>/<slug>.md` with YAML frontmatter. Unit kind: `fact`, `decision`, `preference`, `convention`.

---

## 8. Memory Writes

### 8.1 In-session writes — `remember(fact, scope, ...)`

Claude calls `remember` when it learns something durable. The companion skill `claude-repo-mem-recall` teaches it the trigger conditions: an explicit decision, a discovered convention, a corrected misunderstanding, a user-stated preference.

Conflict handling: if a unit in the same scope has cosine similarity above a threshold (default 0.85) and either an explicit `supersedes` is passed or simple negation heuristics detect contradiction, the old unit is marked `superseded_by` the new one. No silent deletion. `recall(..., include_superseded=true)` exposes the history for audit.

### 8.2 End-of-session distillation — `claude-repo-mem distill`

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
- **Pluggable:** `CLAUDE_REPO_MEM_EMBED=openai:text-embedding-3-small` or `voyage:voyage-3` swaps in API embeddings. Behind a `Embedder` interface; one method, `embed(texts) -> vectors`.
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

### 10.2 User overrides — `.claude-repo-mem/scopes.yml`

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

## 11. Behavioral Steering

Two complementary mechanisms shape how Claude actually uses claude-repo-mem. Skills teach *how*; the MCP handshake teaches *when to trust*.

### 11.1 MCP `initialize` instructions

The MCP protocol's `serverInfo.instructions` field is shown to Claude on session handshake and meaningfully shapes which tools it reaches for. claude-repo-mem ships a short, strongly-worded instruction block declaring its scope of authority. Approximate v1 text (subject to tuning):

> **claude-repo-mem is the authoritative source for this repo's code structure, documentation, and accumulated decisions.** Before reading files with native `Read`/`Grep`, call `recall(query)` — it returns ranked, summarized, scoped results within a budget. Before tracing related code (callers, handlers, hooks, routes), call `trace(seed_handle)` — it returns full source for connected nodes in one shot. Reach for native file tools only when claude-repo-mem returns nothing useful, when working on files outside this repo, or when verifying a recent edit not yet reindexed. When you learn something durable (a decision, convention, or user preference), call `remember(fact, scope)`. For long or multi-part tasks, call `plan_task(intent)` before starting work.

This is the contract: claude-repo-mem promises to be the cheaper, faster path; Claude promises to try it first. The instruction text is versioned with the server binary and tuned based on observed fallback rates (visible in `stats()`).

### 11.2 Companion Skills (in `claude-full-stack-2.0`)

Four small skills, each a single markdown file under `skills/claude-repo-mem/`:

| Skill | Triggers on | Teaches |
|---|---|---|
| `claude-repo-mem-bootstrap` | First-time setup on a repo | Run `claude-repo-mem index`, derive scopes, verify `serve` is reachable |
| `claude-repo-mem-recall` | Start of any task, before reading files | When to `recall` vs work from existing context; how to interpret budget overflow and `tier_histogram` |
| `claude-repo-mem-trace` | Following code flow (callers, routes, handlers) | When to call `trace(seed)` instead of repeated `expand` or `Grep`; how to pick seeds; depth selection |
| `claude-repo-mem-task` | Long or multi-part task intent | When to `plan_task`; how to dispatch sub-tasks to subagents with bundles; how to write `decisions_made` back |
| `claude-repo-mem-handoff` | End of session, context bloat, task switch | When to `handoff()` and `resume(task_id)` |

The skills are the contract between Claude Code's behavior and the MCP server's capabilities. They are how we shape Claude's usage patterns toward small active context.

---

## 12. Build Plan (phased)

### Phase 1 — Substrate, retrieval, traversal (weeks 1–3)

- SQLite schema (unit + relation + FTS5 + sqlite-vec)
- Indexer for code (tree-sitter, Python + JS/TS) and docs
- T1 deterministic headers; embeddings via bge-small
- RRF + feature rerank ranking (§4.1)
- Budget-aware tiered fill (§4.2)
- **`recall`, `trace`, `expand`** MCP tools
- Imports synthesizer (cross-language) + at least one route synthesizer (Flask or FastAPI)
- MCP `initialize` instructions block (§11.1)
- `claude-repo-mem index` CLI
- **Exit criterion:** on a real repo, `recall("how does auth work")` returns ranked results within 3k tokens in <500ms; `trace` from an auth handler returns the route, the handler, and direct callees in one 8k-budget call.

### Phase 2 — Memory, tasks, synthesizer coverage (weeks 4–6)

- Memory layer schema and write path
- `remember`, `forget`, `scopes`, `stats` tools (with fallback-rate metric in `stats`)
- T2 LLM summaries via Claude Code auth
- `plan_task`, `tasks` tools
- Distillation CLI with user-confirm UX
- Remaining v1 synthesizers (Django, Express, React hooks)
- **Exit criterion:** a working session ends with a usable distilled memory set; `plan_task` produces sub-tasks with attached bundles a fresh session can pick up.

### Phase 3 — Handoff and integration (weeks 7–8)

- `handoff`, `resume` tools and markdown snapshot rendering
- File watcher daemon in `serve`
- Companion skills in parent plugin (incl. `claude-repo-mem-trace`)
- `claude-repo-mem doctor`, install-hooks
- **Exit criterion:** end-to-end demo — start task, decompose, work, handoff, resume in fresh session — all within budget and with fallback-to-native rate below a threshold to be set in Phase 2.

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
- Sound program analysis. Type inference, full dataflow, and complete call graphs remain out. **In their place**, claude-repo-mem ships targeted *heuristic synthesizers* (§7.3) that emit framework-aware edges (route → handler, hook → consumer, etc.) good enough to keep Claude off `grep`. The bar is "useful," not "sound."

---

## 14. Success Metrics

Local, observable, no telemetry:

- **Token reduction ratio:** baseline token usage on a representative task with naive context loading, vs. with claude-repo-mem. Target: ≥ 60% reduction for typical "implement feature X" tasks on a 50k-LOC repo.
- **Retrieval latency:** p50 < 200ms, p95 < 500ms for `recall` on a 50k-LOC repo.
- **Reindex cost:** full reindex of a 50k-LOC repo completes in < 5 minutes on CPU; incremental reindex of one changed file < 2 seconds.
- **Handoff fidelity:** a task handed off and resumed in a fresh session can be continued without the user re-explaining state. Measured by user survey on first 10 dogfood sessions.

---

## 15. Open Questions (to resolve during implementation, not now)

1. RRF `k`, feature multiplier defaults, `TOP_PROMOTE` / `T0_SINGLE_CAP` (§4.1, §4.2), and per-tool default budgets (§5) need real-workload calibration. Stats output (`stats()`) should expose fallback-to-native-tool rate so initialize-instruction text (§11.1) can be tuned against observed behavior.
6. Synthesizer coverage at v1 launch (§7.3): the table lists 7 synthesizers across Python and JS/TS. Which are critical-path for the first dogfood repo vs. nice-to-have? Pick during Phase 1 scoping.
7. `trace` relation-kind weighting (§5.1): is `route_to` more important than `imports`? Heuristic-tunable, validate on real traces.
2. Subagent dispatch UX: should `plan_task` optionally spawn subagents directly, or always return a tree for Claude to dispatch?
3. Memory `confidence` semantics: numeric (0–1), categorical (high/med/low), or both?
4. Whether `forget` should support time-window queries ("forget anything I said about X this week").
5. Whether `.claude-repo-mem/memory/` markdown should be the source of truth (regenerable into SQLite) or a snapshot (SQLite is truth, markdown is exported). Default current choice: markdown is truth, SQLite is derived.

---
