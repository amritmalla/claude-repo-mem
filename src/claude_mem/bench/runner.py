from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder


@dataclass
class BenchResult:
    total: int
    hits_at_k: int
    recall_at_k: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    details: List[dict] = field(default_factory=list)


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
    details: list[dict] = []

    for entry in queries:
        q = entry["q"]
        expect_substring = entry.get("expect_header_substring")
        expect_handles = entry.get("expect", [])
        budget = entry.get("budget", 4000)

        t0 = time.monotonic()
        if embedder is None:
            top_ids, top_headers = _fts_only(settings, q, k)
        else:
            top_ids, top_headers = _recall_top_k(settings, embedder, q, budget, k)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
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


def _fts_only(settings: Settings, q: str, k: int) -> tuple[list[str], list[str]]:
    conn = connect(settings.db_path)
    try:
        rows = conn.execute(
            "SELECT unit_fts.id AS id, unit.t1_header AS hdr "
            "FROM unit_fts JOIN unit ON unit.id = unit_fts.id "
            "WHERE unit_fts MATCH ? LIMIT ?",
            (q, k),
        ).fetchall()
        return [r["id"] for r in rows], [r["hdr"] for r in rows]
    finally:
        conn.close()


def _recall_top_k(settings, embedder, q, budget, k):
    from ..retrieval.recall import recall
    result = recall(settings, query=q, embedder=embedder, budget=budget)
    top = result.items[:k]
    ids = [it.handle for it in top]
    conn = connect(settings.db_path)
    try:
        repo = Repository(conn)
        headers: list[str] = []
        for h in ids:
            u = repo.get_unit(h)
            headers.append(u.t1_header if u else "")
    finally:
        conn.close()
    return ids, headers


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]
