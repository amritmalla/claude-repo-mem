from claude_repo_mem.handoff.render import render_handoff_markdown, HandoffPayload
from claude_repo_mem.tasks.model import TaskView


def _task(**overrides) -> TaskView:
    base = dict(
        handle="task://task/abc123def456",
        title="Add token refresh endpoint",
        intent="POST /auth/refresh issues new tokens and invalidates the previous one.",
        status="active",
        scope="backend/auth",
        acceptance=["POST /auth/refresh returns new pair", "Old refresh token invalidated"],
        context_handles=["code://function/4a7b8c9d", "docs://section/5c6d7e8f"],
        open_questions=["Should tokens be per-device revocable?"],
        decisions_made=["memory://decision/abc12345"],
        parent="task://task/parent789",
    )
    base.update(overrides)
    return TaskView(**base)


def test_frontmatter_has_required_fields():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert md.startswith("---\n")
    assert "task_id: task://task/abc123def456" in md
    assert "status: active" in md
    assert "scope: backend/auth" in md


def test_body_includes_intent_and_acceptance():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert "# Handoff: Add token refresh endpoint" in md
    assert "POST /auth/refresh issues new tokens" in md
    assert "- [ ] POST /auth/refresh returns new pair" in md


def test_context_handles_section_lists_each_handle():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert "## Context handles" in md
    assert "code://function/4a7b8c9d" in md
    assert "docs://section/5c6d7e8f" in md


def test_recent_memories_rendered_when_present():
    md = render_handoff_markdown(HandoffPayload(
        task=_task(),
        recent_memories=[
            ("memory://decision/abc12345", "We chose RS256 over HS256."),
            ("memory://convention/9z8y7x", "Tests run with pytest -q on Windows."),
        ],
    ))
    assert "## Recent memory writes" in md
    assert "We chose RS256 over HS256." in md
    assert "memory://decision/abc12345" in md


def test_empty_sections_omitted():
    bare = _task(acceptance=[], open_questions=[], context_handles=[], decisions_made=[])
    md = render_handoff_markdown(HandoffPayload(task=bare, recent_memories=[]))
    assert "## Acceptance" not in md
    assert "## Open questions" not in md
    assert "## Context handles" not in md
    assert "## Recent memory writes" not in md


def test_open_questions_rendered():
    md = render_handoff_markdown(HandoffPayload(task=_task(), recent_memories=[]))
    assert "## Open questions" in md
    assert "Should tokens be per-device revocable?" in md
