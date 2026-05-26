"""DDL for claude-repo-mem.

Schema mirrors §3.1 of the design spec. `unit_vec` dim is parameterized so the
embedder can vary (bge-small=384, openai-3-small=1536, voyage-3-lite=512).
"""

from typing import List


def ddl(dim: int = 384) -> List[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        """,
        "INSERT OR IGNORE INTO schema_version(version) VALUES (1);",
        """
        CREATE TABLE IF NOT EXISTS unit (
            id              TEXT PRIMARY KEY,
            layer           TEXT NOT NULL CHECK (layer IN ('memory','docs','code','task')),
            kind            TEXT NOT NULL,
            scope           TEXT NOT NULL,
            source_ref      TEXT,
            content_hash    TEXT NOT NULL,
            t1_header       TEXT NOT NULL,
            t2_summary      TEXT,
            parent_id       TEXT REFERENCES unit(id),
            superseded_by   TEXT REFERENCES unit(id),
            confidence      REAL,
            created_at      INTEGER NOT NULL,
            last_seen_at    INTEGER NOT NULL,
            metadata        TEXT
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_unit_scope ON unit(scope);",
        "CREATE INDEX IF NOT EXISTS idx_unit_layer ON unit(layer);",
        "CREATE INDEX IF NOT EXISTS idx_unit_parent ON unit(parent_id);",
        "CREATE INDEX IF NOT EXISTS idx_unit_super ON unit(superseded_by);",
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts USING fts5(
            id UNINDEXED,
            t1_header,
            t2_summary,
            tokenize = 'unicode61'
        );
        """,
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS unit_vec USING vec0(
            id TEXT PRIMARY KEY,
            embedding FLOAT[{dim}]
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS embedder_meta (
            name TEXT PRIMARY KEY,
            dim INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS relation (
            src_id TEXT NOT NULL REFERENCES unit(id) ON DELETE CASCADE,
            dst_id TEXT NOT NULL REFERENCES unit(id) ON DELETE CASCADE,
            kind   TEXT NOT NULL,
            PRIMARY KEY (src_id, dst_id, kind)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_relation_dst ON relation(dst_id, kind);",
    ]


# Back-compat: default-dim DDL list.
DDL = ddl()
