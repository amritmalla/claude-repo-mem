from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.db.repository import Repository
from claude_mem.indexer.orchestrator import full_reindex


@pytest.fixture
def flask_fixture(tmp_repo: Path) -> Path:
    (tmp_repo / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/login', methods=['POST'])\n"
        "def login():\n"
        "    return 'ok'\n"
    )
    (tmp_repo / "utils.py").write_text(
        "def helper():\n    return 1\n"
    )
    (tmp_repo / "README.md").write_text("# App\n\nA tiny Flask app.\n")
    return tmp_repo


def test_full_reindex_creates_units(flask_fixture: Path):
    settings = Settings.for_repo(flask_fixture)
    init_db(settings.db_path)
    stats = full_reindex(settings, embedder=None)
    assert stats["units_written"] > 0
    repo = Repository(connect(settings.db_path))
    units = repo.conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    assert units >= 4   # at least: login fn, helper fn, README section, route unit


def test_full_reindex_emits_route_edge(flask_fixture: Path):
    settings = Settings.for_repo(flask_fixture)
    init_db(settings.db_path)
    full_reindex(settings, embedder=None)
    repo = Repository(connect(settings.db_path))
    rels = repo.conn.execute("SELECT COUNT(*) FROM relation WHERE kind='route_to'").fetchone()[0]
    assert rels == 1


def test_full_reindex_idempotent(flask_fixture: Path):
    settings = Settings.for_repo(flask_fixture)
    init_db(settings.db_path)
    s1 = full_reindex(settings, embedder=None)
    s2 = full_reindex(settings, embedder=None)
    repo = Repository(connect(settings.db_path))
    units = repo.conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    assert units == s1["units_written"]
