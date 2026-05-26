from pathlib import Path
import pytest
import numpy as np
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex


class _FakeEmbedder:
    def __init__(self, name, dim):
        self.name, self.dim = name, dim
    def embed(self, texts):
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
    msg = str(ei.value).lower()
    assert "reset" in msg or "mismatch" in msg


def test_no_embedder_no_meta_required(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    rows = connect(s.db_path).execute("SELECT * FROM embedder_meta").fetchall()
    assert rows == []
