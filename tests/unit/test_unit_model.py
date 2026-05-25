import time
from claude_mem.units.model import Unit, Relation


def test_unit_minimal_fields():
    u = Unit(
        id="code://function/abc",
        layer="code",
        kind="function",
        scope="backend/auth",
        source_ref="src/auth.py:10-25",
        content_hash="deadbeef",
        t1_header="def login(user, pw) -> Token",
        created_at=1_700_000_000,
        last_seen_at=1_700_000_000,
    )
    assert u.t2_summary is None
    assert u.parent_id is None
    assert u.layer == "code"


def test_unit_rejects_invalid_layer():
    import pytest
    with pytest.raises(ValueError):
        Unit(
            id="x://y/z",
            layer="invalid",
            kind="function",
            scope="x",
            source_ref=None,
            content_hash="h",
            t1_header="h",
            created_at=0,
            last_seen_at=0,
        )


def test_relation_equality():
    r1 = Relation(src_id="a", dst_id="b", kind="imports")
    r2 = Relation(src_id="a", dst_id="b", kind="imports")
    assert r1 == r2
