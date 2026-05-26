"""DDL for claude-mem.

Schema mirrors §3.1 of the design spec.
"""

DDL = [
    # Schema version marker (used for future migrations).
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    """,
    "INSERT OR IGNORE INTO schema_version(version) VALUES (1);",
    # Core unit table.
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
    # FTS5 mirror of t1_header + t2_summary.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts USING fts5(
        id UNINDEXED,
        t1_header,
        t2_summary,
        tokenize = 'unicode61'
    );
    """,
    # Vector store via sqlite-vec. Dimension 384 = bge-small.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS unit_vec USING vec0(
        id TEXT PRIMARY KEY,
        embedding FLOAT[384]
    );
    """,
    # Relations.
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
