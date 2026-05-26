---
name: claude-repo-mem-trace
description: Use AFTER recall when you have a seed handle and need to see callers, callees, routes, hooks, or other connected code in a single round-trip. Returns full source for connected nodes within a budget. Triggers on "what calls X", "what handlers does this route hit", "what uses this hook".
---

# claude-repo-mem-trace

Once you have a handle from `recall`, use `trace(seed_handle, depth=2, budget=8000)`
to fetch the connected subgraph (callers, callees, routes, imports, hooks) with
full source. One call replaces N grep+read pairs.

## When to call trace
- "What calls `issue_token`?" — `trace(seed_handle="code://function/abc", depth=2)`
- "What handler does POST /login map to?" — `trace(seed_handle="code://route/xyz")`
- "Who consumes this React state?" — `trace(seed_handle="code://function/...")`

## When NOT to call trace
- You have no seed handle — call `recall` first.
- You only need one item — call `expand(handle, tier="t0")` instead.
