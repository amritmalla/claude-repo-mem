from pathlib import Path
from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex


def test_react_self_loop_on_setter_use(tmp_repo: Path):
    (tmp_repo / "Comp.jsx").write_text(
        "function Comp() {\n"
        "  const [n, setN] = useState(0);\n"
        "  const onClick = () => setN(n + 1);\n"
        "  return null;\n"
        "}\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    rels = conn.execute(
        "SELECT src_id, dst_id FROM relation WHERE kind='mutates_state_of'"
    ).fetchall()
    assert len(rels) >= 1
    assert rels[0]["src_id"] == rels[0]["dst_id"]


def test_no_state_relation_when_setter_unused(tmp_repo: Path):
    (tmp_repo / "Comp.jsx").write_text(
        "function Comp() {\n"
        "  const [n, setN] = useState(0);\n"
        "  return null;\n"
        "}\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path)
    full_reindex(s, embedder=None)
    conn = connect(s.db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM relation WHERE kind='mutates_state_of'"
    ).fetchone()[0]
    assert n == 0
