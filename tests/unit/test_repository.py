import time
import numpy as np
import pytest
from pathlib import Path

from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.units.model import Unit, Relation


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
