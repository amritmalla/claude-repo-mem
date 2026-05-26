import json
import pytest
from claude_mem.tasks.model import TaskView, task_to_unit_metadata, unit_metadata_to_task
from claude_mem.units.model import Unit


def test_default_fields():
    t = TaskView(handle="task://task/a", title="Add X", intent="do it")
    assert t.status == "pending"
    assert t.acceptance == []


def test_invalid_status_raises():
    with pytest.raises(ValueError):
        TaskView(handle="task://task/a", title="t", intent="i", status="weird")


def test_round_trip():
    t = TaskView(
        handle="task://task/a", title="T", intent="I", status="active",
        acceptance=["a1", "a2"], context_handles=["code://function/x"],
    )
    meta = task_to_unit_metadata(t)
    u = Unit(
        id="task://task/a", layer="task", kind="task", scope="root",
        source_ref=None, content_hash="h", t1_header="t",
        created_at=0, last_seen_at=0,
        metadata=json.dumps(meta),
    )
    t2 = unit_metadata_to_task(u)
    assert t2.title == "T"
    assert t2.status == "active"
    assert t2.acceptance == ["a1", "a2"]
    assert t2.context_handles == ["code://function/x"]
