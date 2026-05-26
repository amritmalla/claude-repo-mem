import pytest
from claude_mem.units.model import Unit
from claude_mem.units.typed import metadata_json, with_metadata, KIND_VALID_FOR_LAYER


def _u(**overrides) -> Unit:
    base = dict(
        id="mem://decision/a", layer="memory", kind="decision", scope="x",
        source_ref=None, content_hash="h", t1_header="header",
        created_at=0, last_seen_at=0,
    )
    base.update(overrides)
    return Unit(**base)


def test_metadata_json_parses_string():
    u = _u(metadata='{"a": 1, "b": "two"}')
    assert metadata_json(u) == {"a": 1, "b": "two"}


def test_metadata_json_none_returns_empty_dict():
    u = _u(metadata=None)
    assert metadata_json(u) == {}


def test_metadata_json_invalid_returns_empty():
    u = _u(metadata="not json")
    assert metadata_json(u) == {}


def test_with_metadata_serializes():
    u = _u()
    u2 = with_metadata(u, {"hello": "world"})
    assert u2.metadata == '{"hello": "world"}'
    assert u2.id == u.id


def test_kind_valid_for_layer_constants():
    assert "decision" in KIND_VALID_FOR_LAYER["memory"]
    assert "task" in KIND_VALID_FOR_LAYER["task"]
    assert "section" in KIND_VALID_FOR_LAYER["docs"]
    assert "function" in KIND_VALID_FOR_LAYER["code"]


def test_task_snapshot_kind_valid():
    assert "task_snapshot" in KIND_VALID_FOR_LAYER["task"]
