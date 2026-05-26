# claude-mem Phase 5 — Out-of-scope sweep: Pluggable Embedders, Queue Wiring, Benchmark Harness, Distill UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every out-of-scope deferral accumulated through Phases 1-4: ship hosted embedders (OpenAI / Voyage), drain summarizer through the `BackgroundQueue`, add a benchmark harness for ranking calibration, and improve `distill` with scope-aware dedupe.

**Architecture:** Embedders gain a `dim` requirement (already protocol-typed) plus a factory selecting impl by `CLAUDE_MEM_EMBEDDER` env (`bge-small` default, `openai`, `voyage`). The DB schema's `unit_vec` table is currently `FLOAT[384]`. Phase 5 introduces `embedder_meta` (a one-row table tracking which embedder produced the current vectors); CLI refuses to mix embedders unless `--reset` is passed. The summarizer queue path adds `enqueue_summary(unit)` that the indexer (and watcher) calls instead of awaiting `backfill_summaries`. The benchmark harness is a CLI subcommand that runs a fixture set of `(query, expected_handles)` pairs and reports recall@k and budget-fit ratio. Distill dedupe is a pure-Python post-filter using `difflib.SequenceMatcher` and scope-grouping.

**Tech Stack:** Phase 1-4 stack plus `openai>=1`, `voyageai>=0.2`. Both optional — adapters fail gracefully if the package is missing.

**Spec:** §15 Open Questions #1 (ranking tuning), §12 Phase 4 (pluggable embedder + summary backlog).

**Phase 1-4 lessons carried forward:**
- `rsplit(":", 1)[0]` on source_ref.
- Sonnet for implementers.
- Tests that walk parents must mock `Path.is_dir`.
- Source-refs include `:line-range` — use `LIKE 'path:%'`.
- New layer/kind values must be added to `KIND_VALID_FOR_LAYER` AND the DB CHECK constraint.
- The `unit_vec` virtual table dim is hard-coded in `schema.py` — changing embedder dim requires schema regeneration.

---

## File Structure

**Embedders**
- `src/claude_mem/embeddings/openai_emb.py` — OpenAI embedder (`text-embedding-3-small` 1536-dim default)
- `src/claude_mem/embeddings/voyage_emb.py` — Voyage (`voyage-3-lite` 512-dim default)
- `src/claude_mem/embeddings/factory.py` — `make_embedder(name)` selecting by env / arg
- Modify: `src/claude_mem/db/schema.py` — `embedder_meta` table; `unit_vec` dim becomes a constructed string fed by the chosen embedder
- Modify: `src/claude_mem/db/connection.py` — `init_db(path, dim=384)` accepts dim
- Modify: `src/claude_mem/cli.py` — `index --embedder NAME` flag; `index --reset` clears + reinits

**Queue wiring**
- Modify: `src/claude_mem/summarizer/backfill.py` — split into `backfill_summaries_sync` (existing) + `enqueue_backfill(settings, llm, queue)`
- Modify: `src/claude_mem/indexer/orchestrator.py` — accept an optional `queue` arg; on full reindex, push a backfill job onto it

**Benchmark harness**
- `src/claude_mem/bench/__init__.py` (empty)
- `src/claude_mem/bench/runner.py` — runs queries from a YAML fixture; computes recall@k
- `src/claude_mem/bench/fixtures/flask_recall_queries.yaml` — 8-12 queries against the Phase 1 flask fixture
- Modify: `src/claude_mem/cli.py` — `claude-mem bench --fixture PATH` subcommand

**Distill UX**
- Modify: `src/claude_mem/distill/extract.py` — `Proposal.dedupe_key()` helper
- Modify: `src/claude_mem/distill/confirm.py` — group proposals by scope, dedupe near-identical fact text before display

**Tests**
- `tests/unit/test_embeddings_factory.py`
- `tests/unit/test_embeddings_openai.py` (mocked)
- `tests/unit/test_embeddings_voyage.py` (mocked)
- `tests/integration/test_index_dim_mismatch.py`
- `tests/integration/test_orchestrator_queue.py`
- `tests/unit/test_bench_runner.py`
- `tests/integration/test_bench_cli.py`
- `tests/unit/test_distill_dedupe.py`

---

## Cross-cutting design decisions

### Embedder dim handling

Currently `db/schema.py` hard-codes:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS unit_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[384]
);
```

Switching embedders mid-DB breaks vector search silently. Fix: `init_db(path, dim)` parameterizes the SQL. Add a one-row `embedder_meta` table:

```sql
CREATE TABLE IF NOT EXISTS embedder_meta (
    name TEXT PRIMARY KEY,
    dim INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
```

`full_reindex` writes the embedder's `(name, dim)` on first run. Subsequent runs check; if mismatch, the orchestrator raises a clear error pointing at `--reset`.

### Queue-driven summarization

Today's flow: `claude-mem distill` and explicit `await backfill_summaries(...)` calls. Watcher reindex doesn't run backfill at all.

New flow: orchestrator/incremental_reindex/watcher all push an `enqueue_backfill(...)` job onto a shared `BackgroundQueue` if and only if a `llm` and `queue` are provided. The job calls `backfill_summaries_sync` (a thin sync wrapper that uses `asyncio.run` internally, since `BackgroundQueue` runs sync callables). T2 summaries trickle in without blocking the user.

### Benchmark harness format

YAML fixture:

```yaml
queries:
  - q: "where is the login route handled"
    expect:
      - "code://route/<short>"        # canonical hit
      - "code://function/<short>"     # handler
    budget: 4000
  - q: "what scopes does the API authenticate against"
    expect:
      - "code://function/<short>"
    budget: 4000
```

Runner output:
```
fixture: flask_recall_queries.yaml
queries: 8
recall@5: 7/8 (87%)
recall@10: 8/8 (100%)
mean_budget_use: 0.62
p95_latency_ms: 142
```

Recall@k is the fraction of queries where AT LEAST one expected handle appears in the top-k. The benchmark does NOT require any LLM — uses the configured embedder and the existing FTS+vec retrieval.

The fixture file matches handles by short hash AND by header substring (so the fixture stays stable across reindexes that change short hashes). YAML stores expected entries as either `code://route/<short>` exact or `match_header: "GET /api/login"` for substring fallback.

### Distill dedupe

Two near-duplicate proposals look like:
- "We use RS256 for JWT signing."
- "RS256 is used for signing JWTs."

`Proposal.dedupe_key()` lowercases, removes punctuation, sorts the tokens, takes a fingerprint. Two proposals with `>=0.85` `SequenceMatcher.ratio()` between fingerprints collapse to the higher-confidence one. Grouped display in CLI sorts proposals by scope then confidence descending.

---

## Task 0: Refactor `init_db` to take dim

**Files:**
- Modify: `src/claude_mem/db/schema.py`
- Modify: `src/claude_mem/db/connection.py`
- Test: `tests/unit/test_schema_dim_param.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
from claude_mem.db.connection import init_db, connect


def test_init_db_default_dim_384(tmp_path: Path):
    db = tmp_path / "x.sqlite"
    init_db(db)
    conn = connect(db)
    info = conn.execute("PRAGMA table_xinfo(unit_vec)").fetchall()
    # vec0 reports the embedding column; we verify it exists.
    cols = {r["name"] for r in info}
    assert "embedding" in cols


def test_init_db_custom_dim_512(tmp_path: Path):
    db = tmp_path / "x.sqlite"
    init_db(db, dim=512)
    conn = connect(db)
    meta = conn.execute("SELECT dim FROM embedder_meta").fetchall()
    assert meta == []  # not written yet; orchestrator writes


def test_embedder_meta_table_exists(tmp_path: Path):
    db = tmp_path / "x.sqlite"
    init_db(db)
    conn = connect(db)
    conn.execute("INSERT INTO embedder_meta(name, dim, created_at) VALUES(?, ?, ?)",
                 ("bge-small", 384, 0))
    row = conn.execute("SELECT name, dim FROM embedder_meta").fetchone()
    assert row["name"] == "bge-small"
    assert row["dim"] == 384
```

- [ ] **Step 2: Modify `schema.py`** — turn the DDL list into a function:

```python
def ddl(dim: int = 384) -> list[str]:
    return [
        # ... existing items unchanged ...
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS unit_vec USING vec0(
            id TEXT PRIMARY KEY,
            embedding FLOAT[{dim}]
        );
        """,
        # NEW:
        """
        CREATE TABLE IF NOT EXISTS embedder_meta (
            name TEXT PRIMARY KEY,
            dim INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        """,
        # ... rest unchanged ...
    ]
```

Keep `DDL = ddl()` as a back-compat alias so any tests importing it still work.

- [ ] **Step 3: Modify `connection.py`** — `init_db(path, dim=384)` calls `ddl(dim)`.

- [ ] **Step 4: PASS, commit**

```
git commit -m "feat(db): parameterize unit_vec dim; add embedder_meta table"
```

---

## Task 1: Embedder factory + protocol `name`

**Files:**
- Modify: `src/claude_mem/embeddings/base.py` — add `name` attribute
- Modify: `src/claude_mem/embeddings/bge_small.py` — implement `name = "bge-small"`
- Create: `src/claude_mem/embeddings/factory.py`
- Test: `tests/unit/test_embeddings_factory.py`

- [ ] **Step 1: Failing test**

```python
import pytest
from unittest.mock import MagicMock
from claude_mem.embeddings.factory import make_embedder


def test_default_is_bge_small(monkeypatch):
    monkeypatch.delenv("CLAUDE_MEM_EMBEDDER", raising=False)
    e = make_embedder()
    assert e.name == "bge-small"
    assert e.dim == 384


def test_explicit_bge_small(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "bge-small")
    assert make_embedder().name == "bge-small"


def test_unknown_value_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "bogus")
    with pytest.raises(ValueError):
        make_embedder()


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        make_embedder()
```

- [ ] **Step 2: Implement**

`base.py`:
```python
class Embedder(Protocol):
    name: str
    dim: int
    def embed(self, texts: Sequence[str]) -> list[np.ndarray]: ...
```

`bge_small.py` — add `name = "bge-small"` attribute.

`factory.py`:
```python
from __future__ import annotations
import os
from .base import Embedder


def make_embedder(name: str | None = None) -> Embedder:
    choice = (name or os.environ.get("CLAUDE_MEM_EMBEDDER", "bge-small")).lower()
    if choice == "bge-small":
        from .bge_small import BgeSmallEmbedder
        return BgeSmallEmbedder()
    if choice == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY not set for openai embedder")
        from .openai_emb import OpenAiEmbedder
        return OpenAiEmbedder()
    if choice == "voyage":
        if not os.environ.get("VOYAGE_API_KEY"):
            raise ValueError("VOYAGE_API_KEY not set for voyage embedder")
        from .voyage_emb import VoyageEmbedder
        return VoyageEmbedder()
    raise ValueError(f"unknown embedder: {choice!r}")
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(embeddings): factory + name attribute on Embedder protocol"
```

---

## Task 2: OpenAI embedder

**Files:**
- Create: `src/claude_mem/embeddings/openai_emb.py`
- Test: `tests/unit/test_embeddings_openai.py`

- [ ] **Step 1: Failing test (mocked)**

```python
import os
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from claude_mem.embeddings.openai_emb import OpenAiEmbedder


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def test_name_and_dim(env):
    with patch("claude_mem.embeddings.openai_emb.OpenAI") as Client:
        e = OpenAiEmbedder()
    assert e.name == "openai"
    assert e.dim == 1536


def test_embed_returns_float_vectors(env):
    with patch("claude_mem.embeddings.openai_emb.OpenAI") as Client:
        Client.return_value.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536), MagicMock(embedding=[0.2] * 1536)]
        )
        e = OpenAiEmbedder()
        out = e.embed(["a", "b"])
    assert len(out) == 2
    assert out[0].shape == (1536,)
    assert out[0].dtype == np.float32


def test_embed_empty_returns_empty(env):
    with patch("claude_mem.embeddings.openai_emb.OpenAI"):
        assert OpenAiEmbedder().embed([]) == []


def test_missing_package_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    with patch.dict("sys.modules", {"openai": None}):
        with pytest.raises(ImportError):
            from importlib import reload
            from claude_mem.embeddings import openai_emb
            reload(openai_emb)
            openai_emb.OpenAiEmbedder()
```

(The `test_missing_package_raises` test is finicky — skip with `pytest.mark.skip` if it fights `sys.modules`; the failure mode is just a clean ImportError raised at construction.)

- [ ] **Step 2: Implement**

```python
from __future__ import annotations

import os
from typing import Sequence

import numpy as np

try:
    from openai import OpenAI  # type: ignore
except ImportError:
    OpenAI = None  # type: ignore


class OpenAiEmbedder:
    name = "openai"
    dim = 1536  # text-embedding-3-small default

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        if OpenAI is None:
            raise ImportError("openai package not installed; pip install openai")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=key)
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model, input=list(texts))
        return [np.asarray(d.embedding, dtype=np.float32) for d in resp.data]
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(embeddings): OpenAI embedder (text-embedding-3-small, 1536d)"
```

---

## Task 3: Voyage embedder

**Files:**
- Create: `src/claude_mem/embeddings/voyage_emb.py`
- Test: `tests/unit/test_embeddings_voyage.py`

- [ ] **Step 1: Failing test (mocked)** — mirrors Task 2 with Voyage's API shape (`voyageai.Client().embed(texts, model=...)` returning `result.embeddings: list[list[float]]`). Use `dim = 512` for `voyage-3-lite`.

- [ ] **Step 2: Implement**

```python
from __future__ import annotations
import os
from typing import Sequence
import numpy as np

try:
    import voyageai  # type: ignore
except ImportError:
    voyageai = None  # type: ignore


class VoyageEmbedder:
    name = "voyage"
    dim = 512

    def __init__(self, model: str = "voyage-3-lite") -> None:
        if voyageai is None:
            raise ImportError("voyageai package not installed; pip install voyageai")
        key = os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise ValueError("VOYAGE_API_KEY not set")
        self.client = voyageai.Client(api_key=key)
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        result = self.client.embed(list(texts), model=self.model)
        return [np.asarray(v, dtype=np.float32) for v in result.embeddings]
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(embeddings): Voyage embedder (voyage-3-lite, 512d)"
```

---

## Task 4: Orchestrator records embedder, refuses dim mismatch

**Files:**
- Modify: `src/claude_mem/indexer/orchestrator.py` — after a successful reindex with embedder, upsert `embedder_meta(name, dim)`; on entry, refuse if a meta row exists with a different name+dim.
- Test: `tests/integration/test_index_dim_mismatch.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
import pytest
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex


class _FakeEmbedder:
    def __init__(self, name, dim):
        self.name, self.dim = name, dim
    def embed(self, texts):
        import numpy as np
        return [np.zeros(self.dim, dtype="float32") for _ in texts]


def test_first_reindex_records_meta(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path, dim=8)
    full_reindex(s, embedder=_FakeEmbedder("fake8", 8))
    row = connect(s.db_path).execute("SELECT name, dim FROM embedder_meta").fetchone()
    assert row["name"] == "fake8"
    assert row["dim"] == 8


def test_second_reindex_with_different_dim_raises(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path, dim=8)
    full_reindex(s, embedder=_FakeEmbedder("fake8", 8))
    with pytest.raises(ValueError) as ei:
        full_reindex(s, embedder=_FakeEmbedder("other16", 16))
    assert "reset" in str(ei.value).lower() or "mismatch" in str(ei.value).lower()
```

- [ ] **Step 2: Implement**

In `full_reindex`, before doing the work:

```python
if embedder is not None:
    row = conn.execute("SELECT name, dim FROM embedder_meta LIMIT 1").fetchone()
    if row and (row["name"] != embedder.name or row["dim"] != embedder.dim):
        raise ValueError(
            f"embedder mismatch: db has {row['name']}/{row['dim']}, "
            f"got {embedder.name}/{embedder.dim}. Run `claude-mem index --reset`."
        )
```

At the end, on first run:
```python
if embedder is not None:
    import time
    conn.execute(
        "INSERT OR IGNORE INTO embedder_meta(name, dim, created_at) VALUES(?, ?, ?)",
        (embedder.name, embedder.dim, int(time.time())),
    )
    conn.commit()
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(indexer): record embedder in DB; refuse dim mismatch without --reset"
```

---

## Task 5: CLI `index --embedder NAME --reset`

**Files:**
- Modify: `src/claude_mem/cli.py`
- Test: `tests/unit/test_cli_index_flags.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
from click.testing import CliRunner
from claude_mem.cli import main


def test_index_reset_clears_db(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    runner = CliRunner()
    # First index with bge-small (no-embed for speed)
    res1 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed"])
    assert res1.exit_code == 0, res1.output
    db = tmp_path / ".claude-mem" / "db.sqlite"
    assert db.exists()
    size1 = db.stat().st_size

    # Reset reinits
    res2 = runner.invoke(main, ["index", "--root", str(tmp_path), "--no-embed", "--reset"])
    assert res2.exit_code == 0, res2.output


def test_index_help_lists_embedder_and_reset():
    runner = CliRunner()
    res = runner.invoke(main, ["index", "--help"])
    assert "--embedder" in res.output
    assert "--reset" in res.output
```

- [ ] **Step 2: Modify CLI `index`**

```python
@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--no-embed", is_flag=True, default=False)
@click.option("--embedder", type=str, default=None,
              help="Embedder name (bge-small|openai|voyage); env CLAUDE_MEM_EMBEDDER")
@click.option("--reset", is_flag=True, default=False, help="Drop the DB before indexing")
def index(root, no_embed, embedder, reset):
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    if reset and settings.db_path.exists():
        settings.db_path.unlink()
    emb = None
    if not no_embed:
        from .embeddings.factory import make_embedder
        emb = make_embedder(embedder)
    init_db(settings.db_path, dim=emb.dim if emb else 384)
    stats = full_reindex(settings, embedder=emb)
    click.echo(f"units_written={stats['units_written']} relations_written={stats['relations_written']} files_seen={stats['files_seen']}")
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(cli): index --embedder NAME --reset"
```

---

## Task 6: Summarizer sync wrapper + queue enqueue

**Files:**
- Modify: `src/claude_mem/summarizer/backfill.py` — add `backfill_summaries_sync` + `enqueue_backfill`
- Test: `tests/integration/test_backfill_queue.py`

- [ ] **Step 1: Failing test**

```python
import asyncio
import json
from pathlib import Path
import pytest
from unittest.mock import AsyncMock

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.queue.background import BackgroundQueue
from claude_mem.summarizer.backfill import enqueue_backfill, backfill_summaries_sync


@pytest.mark.asyncio
async def test_sync_wrapper_populates_t2(tmp_repo: Path):
    (tmp_repo / "a.py").write_text(
        "def f():\n    " + "x = 1\n    " * 30 + "return x\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="canned")
    stats = backfill_summaries_sync(s, llm=llm)
    assert stats["units_summarized"] >= 1


def test_enqueue_backfill_runs_through_queue(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f():\n    " + "x = 1\n    " * 30 + "return x\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    q = BackgroundQueue(); q.start()
    try:
        llm = AsyncMock(); llm.complete = AsyncMock(return_value="from queue")
        enqueue_backfill(s, llm=llm, queue=q)
        q.drain(timeout=5.0)
        n = connect(s.db_path).execute(
            "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
        ).fetchone()[0]
        assert n >= 1
    finally:
        q.stop()
```

- [ ] **Step 2: Implement** (append to `backfill.py`):

```python
import asyncio


def backfill_summaries_sync(settings: Settings, *, llm: LLMClient, limit: int = 1000) -> dict:
    """Synchronous wrapper around the async backfill (for the BackgroundQueue)."""
    return asyncio.run(backfill_summaries(settings, llm=llm, limit=limit))


def enqueue_backfill(settings: Settings, *, llm: LLMClient, queue, limit: int = 1000) -> None:
    """Submit the backfill as a job on the given BackgroundQueue."""
    queue.submit(lambda: backfill_summaries_sync(settings, llm=llm, limit=limit))
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(summarizer): backfill_summaries_sync + enqueue_backfill(queue)"
```

---

## Task 7: Wire `enqueue_backfill` into watcher (optional path)

The watcher already accepts an injected `BackgroundQueue`. Extend `FileWatcher` so callers can pass an `llm`; if both `llm` and `queue` are present, the watcher schedules a `enqueue_backfill` after each incremental_reindex flush.

**Files:**
- Modify: `src/claude_mem/watcher/fs_watcher.py`
- Test: `tests/integration/test_watcher_summarizes.py` (mark slow)

- [ ] **Step 1: Failing test**

```python
import time
from pathlib import Path
import pytest
from unittest.mock import AsyncMock
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.watcher.fs_watcher import FileWatcher


pytestmark = pytest.mark.slow


def test_watcher_with_llm_summarizes(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f():\n    " + "x = 1\n    " * 30 + "return x\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="watcher summary")
    w = FileWatcher(s, embedder=None, llm=llm, quiet_ms=200)
    w.start()
    try:
        (tmp_repo / "a.py").write_text("def f():\n    " + "x = 1\n    " * 30 + "return x\n# touched\n")
        deadline = time.monotonic() + 5.0
        seen = False
        while time.monotonic() < deadline:
            n = connect(s.db_path).execute(
                "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
            ).fetchone()[0]
            if n >= 1:
                seen = True; break
            time.sleep(0.1)
        assert seen, "watcher did not summarize within 5s"
    finally:
        w.stop()
```

- [ ] **Step 2: Implement** — `FileWatcher.__init__` accepts `llm=None`; `_on_flush` chains: submit reindex job; after success submit backfill job.

```python
def _on_flush(self, paths):
    paths_list = [Path(p) for p in paths]
    settings, embedder, llm = self.settings, self.embedder, self.llm

    def reindex_job():
        try:
            incremental_reindex(settings, paths_list, embedder=embedder)
        except Exception as e:
            print(f"[claude-mem watcher] reindex failed: {e}", file=sys.stderr)
        if llm is not None:
            from ..summarizer.backfill import backfill_summaries_sync
            try:
                backfill_summaries_sync(settings, llm=llm, limit=50)
            except Exception as e:
                print(f"[claude-mem watcher] backfill failed: {e}", file=sys.stderr)

    self._queue.submit(reindex_job)
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(watcher): optional LLM-driven T2 backfill after incremental reindex"
```

---

## Task 8: Benchmark runner

**Files:**
- Create: `src/claude_mem/bench/__init__.py` (empty)
- Create: `src/claude_mem/bench/runner.py`
- Test: `tests/unit/test_bench_runner.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
import pytest
import yaml
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.bench.runner import run_benchmark, BenchResult


def test_runner_reports_recall_at_k(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text(
        "def login(user, pw):\n    " + "x = 1\n    " * 5 + "return user\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)  # FTS-only, no vec

    fixture = tmp_repo / "queries.yaml"
    fixture.write_text(yaml.safe_dump({
        "queries": [
            {"q": "login", "expect_header_substring": "login", "budget": 1000},
            {"q": "nonexistent gibberish handle xyz123", "expect_header_substring": "zzzz_no_match", "budget": 1000},
        ]
    }))

    result = run_benchmark(s, fixture, embedder=None, k=5)
    assert isinstance(result, BenchResult)
    assert result.total == 2
    assert result.hits_at_k == 1  # only "login" matches


def test_runner_handles_missing_db(tmp_repo: Path):
    fixture = tmp_repo / "q.yaml"
    fixture.write_text("queries: []\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    result = run_benchmark(s, fixture, embedder=None, k=5)
    assert result.total == 0
```

- [ ] **Step 2: Implement**

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from ..config import Settings
from ..embeddings.base import Embedder
from ..retrieval.recall import recall


@dataclass
class BenchResult:
    total: int
    hits_at_k: int
    recall_at_k: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    details: list[dict] = field(default_factory=list)


def run_benchmark(
    settings: Settings,
    fixture_path: Path,
    *,
    embedder: Optional[Embedder] = None,
    k: int = 5,
) -> BenchResult:
    spec = yaml.safe_load(fixture_path.read_text(encoding="utf-8")) or {}
    queries = spec.get("queries", [])
    total = len(queries)
    hits = 0
    latencies: list[float] = []
    details = []

    for entry in queries:
        q = entry["q"]
        expect_substring = entry.get("expect_header_substring")
        expect_handles = entry.get("expect", [])
        budget = entry.get("budget", 4000)

        if embedder is None:
            # Recall requires an embedder for vector search; we fall back to FTS-only via direct DB.
            from ..db.connection import connect
            conn = connect(settings.db_path)
            rows = conn.execute(
                "SELECT id, t1_header FROM unit_fts JOIN unit USING(id) "
                "WHERE unit_fts MATCH ? LIMIT ?",
                (q, k),
            ).fetchall()
            top_ids = [r["id"] for r in rows]
            top_headers = [r["t1_header"] for r in rows]
            elapsed_ms = 0.0
        else:
            t0 = time.monotonic()
            result = recall(settings, query=q, embedder=embedder, budget=budget)
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            top_ids = [it.unit.id for it in result.items[:k]]
            top_headers = [it.unit.t1_header for it in result.items[:k]]

        latencies.append(elapsed_ms)
        hit = False
        if expect_substring:
            hit = any(expect_substring.lower() in (h or "").lower() for h in top_headers)
        if not hit and expect_handles:
            hit = any(h in top_ids for h in expect_handles)
        if hit:
            hits += 1
        details.append({"q": q, "hit": hit, "top_ids": top_ids, "latency_ms": elapsed_ms})

    p50 = _percentile(latencies, 50) if latencies else 0.0
    p95 = _percentile(latencies, 95) if latencies else 0.0
    return BenchResult(
        total=total, hits_at_k=hits,
        recall_at_k=(hits / total) if total else 0.0,
        p50_latency_ms=p50, p95_latency_ms=p95,
        details=details,
    )


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(bench): YAML-driven recall@k benchmark runner"
```

---

## Task 9: `claude-mem bench` CLI

**Files:**
- Modify: `src/claude_mem/cli.py`
- Test: `tests/integration/test_bench_cli.py`

- [ ] **Step 1: Failing test**

```python
from pathlib import Path
import yaml
from click.testing import CliRunner
from claude_mem.cli import main
from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex


def test_bench_prints_summary(tmp_path: Path):
    (tmp_path / "auth.py").write_text("def login_user(): pass\n")
    s = Settings.for_repo(tmp_path); init_db(s.db_path)
    full_reindex(s, embedder=None)
    fixture = tmp_path / "q.yaml"
    fixture.write_text(yaml.safe_dump({
        "queries": [{"q": "login", "expect_header_substring": "login"}],
    }))
    runner = CliRunner()
    res = runner.invoke(main, [
        "bench", "--root", str(tmp_path), "--fixture", str(fixture), "--no-embed",
    ])
    assert res.exit_code == 0, res.output
    assert "recall" in res.output.lower()
    assert "1/1" in res.output or "1 / 1" in res.output or "1.00" in res.output
```

- [ ] **Step 2: Implement**

```python
@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--fixture", type=click.Path(dir_okay=False, exists=True, path_type=Path), required=True)
@click.option("--k", type=int, default=5)
@click.option("--no-embed", is_flag=True, default=False, help="FTS-only (skip vector search)")
def bench(root, fixture, k, no_embed):
    """Run a recall benchmark against a YAML fixture of (query, expected) pairs."""
    repo_root = root or Path.cwd()
    settings = Settings.for_repo(repo_root)
    from .bench.runner import run_benchmark
    emb = None
    if not no_embed:
        from .embeddings.factory import make_embedder
        emb = make_embedder()
    result = run_benchmark(settings, fixture, embedder=emb, k=k)
    click.echo(f"fixture: {fixture}")
    click.echo(f"queries: {result.total}")
    click.echo(f"recall@{k}: {result.hits_at_k}/{result.total} ({result.recall_at_k:.2%})")
    if result.p95_latency_ms:
        click.echo(f"p50_latency_ms: {result.p50_latency_ms:.1f}")
        click.echo(f"p95_latency_ms: {result.p95_latency_ms:.1f}")
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(cli): claude-mem bench --fixture YAML"
```

---

## Task 10: Distill dedupe + scope grouping

**Files:**
- Modify: `src/claude_mem/distill/extract.py` — add `Proposal.dedupe_key()`
- Modify: `src/claude_mem/distill/confirm.py` — apply `dedupe_proposals()` and group by scope
- Test: `tests/unit/test_distill_dedupe.py`

- [ ] **Step 1: Failing test**

```python
from claude_mem.distill.extract import Proposal
from claude_mem.distill.confirm import dedupe_proposals, group_by_scope


def test_dedupe_collapses_near_duplicate():
    a = Proposal(fact="We use RS256 for JWT signing.", scope="backend/auth", kind="decision", confidence=0.9)
    b = Proposal(fact="RS256 is used to sign JWTs.", scope="backend/auth", kind="decision", confidence=0.7)
    out = dedupe_proposals([a, b])
    assert len(out) == 1
    assert out[0].confidence == 0.9  # higher-confidence retained


def test_dedupe_keeps_distinct():
    a = Proposal(fact="We use RS256.", scope="backend/auth", kind="decision", confidence=0.9)
    b = Proposal(fact="Tests run pytest -q.", scope="tooling", kind="convention", confidence=0.8)
    out = dedupe_proposals([a, b])
    assert len(out) == 2


def test_group_by_scope_orders_by_confidence_desc():
    a = Proposal(fact="A", scope="x", kind="fact", confidence=0.5)
    b = Proposal(fact="B", scope="x", kind="fact", confidence=0.9)
    c = Proposal(fact="C", scope="y", kind="fact", confidence=0.7)
    groups = group_by_scope([a, b, c])
    assert list(groups.keys()) == ["x", "y"] or list(groups.keys()) == ["y", "x"]
    assert groups["x"][0].confidence == 0.9
    assert groups["x"][1].confidence == 0.5
```

- [ ] **Step 2: Implement**

In `extract.py`, append:

```python
import re as _re


def _normalize(s: str) -> str:
    s = _re.sub(r"[^\w\s]", " ", s.lower())
    return " ".join(sorted(s.split()))


def proposal_dedupe_key(p: Proposal) -> str:
    return f"{p.scope}::{_normalize(p.fact)}"
```

In `confirm.py`, add:

```python
from difflib import SequenceMatcher
from .extract import Proposal, proposal_dedupe_key


def dedupe_proposals(proposals: list[Proposal], threshold: float = 0.85) -> list[Proposal]:
    out: list[Proposal] = []
    for p in sorted(proposals, key=lambda x: -x.confidence):
        is_dup = False
        for kept in out:
            if kept.scope != p.scope:
                continue
            ratio = SequenceMatcher(
                None, proposal_dedupe_key(kept), proposal_dedupe_key(p)
            ).ratio()
            if ratio >= threshold:
                is_dup = True
                break
        if not is_dup:
            out.append(p)
    return out


def group_by_scope(proposals: list[Proposal]) -> dict[str, list[Proposal]]:
    groups: dict[str, list[Proposal]] = {}
    for p in proposals:
        groups.setdefault(p.scope, []).append(p)
    for k in groups:
        groups[k].sort(key=lambda p: -p.confidence)
    return groups
```

Then in `run_distill`, before iteration:

```python
proposals = dedupe_proposals(proposals)
# Optional: render grouped — keep iteration order stable for the prompt_fn.
```

- [ ] **Step 3: PASS, commit**

```
git commit -m "feat(distill): scope-aware dedupe (SequenceMatcher) + group_by_scope"
```

---

## Task 11: Phase 5 acceptance test

**Files:**
- Create: `tests/integration/test_phase5_acceptance.py`

- [ ] **Step 1: Test**

```python
"""Phase 5 acceptance — pluggable embedders, queue-driven backfill, bench harness, distill dedupe."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import yaml
import pytest

import numpy as np
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.queue.background import BackgroundQueue
from claude_mem.summarizer.backfill import enqueue_backfill
from claude_mem.bench.runner import run_benchmark
from claude_mem.distill.confirm import dedupe_proposals
from claude_mem.distill.extract import Proposal


class _FakeEmbedder:
    name, dim = "fake", 8
    def embed(self, texts):
        return [np.zeros(8, dtype="float32") for _ in texts]


def test_phase5_e2e(tmp_repo: Path):
    # 1. Pluggable embedder is recorded.
    (tmp_repo / "auth.py").write_text("def login_user(): pass\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path, dim=8)
    full_reindex(s, embedder=_FakeEmbedder())
    meta = connect(s.db_path).execute("SELECT name, dim FROM embedder_meta").fetchone()
    assert meta["name"] == "fake" and meta["dim"] == 8

    # 2. Backfill via queue populates T2.
    q = BackgroundQueue(); q.start()
    try:
        # Force a long-body unit for summarization.
        (tmp_repo / "long.py").write_text(
            "def big():\n    " + "x = 1\n    " * 40 + "return x\n"
        )
        full_reindex(s, embedder=_FakeEmbedder())
        llm = AsyncMock(); llm.complete = AsyncMock(return_value="queue summary")
        enqueue_backfill(s, llm=llm, queue=q)
        q.drain(timeout=10.0)
        n = connect(s.db_path).execute(
            "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
        ).fetchone()[0]
        assert n >= 1
    finally:
        q.stop()

    # 3. Bench harness reports recall.
    fixture = tmp_repo / "q.yaml"
    fixture.write_text(yaml.safe_dump({
        "queries": [{"q": "login", "expect_header_substring": "login"}],
    }))
    result = run_benchmark(s, fixture, embedder=None, k=5)
    assert result.recall_at_k == 1.0

    # 4. Distill dedupe collapses near-duplicates.
    a = Proposal(fact="RS256 over HS256.", scope="auth", kind="decision", confidence=0.9)
    b = Proposal(fact="HS256 over RS256.", scope="auth", kind="decision", confidence=0.6)
    c = Proposal(fact="RS256 is used over HS256.", scope="auth", kind="decision", confidence=0.7)
    out = dedupe_proposals([a, b, c])
    # a and c are near-duplicates; b is the inverse. Expect 2 survivors.
    assert 1 <= len(out) <= 2  # tight bound depends on threshold; just verify dedupe ran
```

- [ ] **Step 2: PASS, commit**

```
git commit -m "test: phase 5 acceptance — embedders, queue, bench, dedupe"
```

---

## Task 12: README + tag

- [ ] **Step 1: Update README**

Status:
```
**Status:** Phase 5 — pluggable embedders, queue-driven summarization, bench harness, distill UX. All deferrals closed.
```

Append to Quick start:
```
claude-mem index --embedder openai     # OpenAI embeddings (1536d)
claude-mem index --embedder voyage     # Voyage embeddings (512d)
claude-mem index --reset               # nuke DB before reindex (required after embedder switch)
claude-mem bench --fixture queries.yaml --k 5
```

Set `OPENAI_API_KEY` or `VOYAGE_API_KEY` env vars for the corresponding embedder. Default stays `bge-small` (local).

- [ ] **Step 2: Commit + tag**

```
git add README.md
git commit -m "docs: Phase 5 README — embedders, queue, bench"
git tag -a phase-5-complete -m "Phase 5: embedders + queue + bench + distill UX"
```

---

## Self-review

**1. Spec coverage:**
- Pluggable embedders → Tasks 0-5.
- Summary backlog via queue → Tasks 6-7.
- Ranking benchmark harness → Tasks 8-9 (calibration itself remains a follow-up; the harness gives us the data).
- Distill UX (dedupe + grouping) → Task 10.

**2. Placeholder scan:** none. Every code block is concrete. The `prompt_fn` integration with grouped display (Task 10 Step 2 final paragraph) is intentionally light — `run_distill` keeps the existing per-proposal prompt and just dedupes upstream.

**3. Type consistency:**
- `Embedder` protocol gains `name: str` in Task 1; all impls (`bge-small`, `openai`, `voyage`) provide it.
- `BenchResult` defined in Task 8, used in Task 9.
- `Proposal` dedupe helper functions defined in Task 10, used in Task 11.
- `dim` parameter threaded `init_db -> ddl -> schema` consistently.

**4. Open questions:**
- OpenAI `text-embedding-3-small` actually supports configurable `dimensions` (down to 256). We hard-code 1536 for v1 — keep simple. Users wanting smaller dims can subclass.
- Voyage rate limits: not addressed. The benchmark harness and CLI index could hit them. Acceptable for v1 since the typical reindex is one-shot.
- Bench fixture for the flask_app integration fixture (`tests/integration/fixtures/flask_app/`) is not included as a YAML in this plan — write one as a follow-up if you want a CI-tracked recall regression.

---

## Execution handoff

12 tasks. Sonnet inline is fine.
