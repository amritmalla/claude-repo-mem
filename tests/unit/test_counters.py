from claude_repo_mem.observability.counters import reset_counters, get_counters


def test_default_zero():
    reset_counters()
    c = get_counters()
    assert c.recall_calls == 0
    assert c.trace_calls == 0
    assert c.expand_calls == 0
    assert c.remember_calls == 0


def test_increment():
    reset_counters()
    c = get_counters()
    c.recall_calls += 1
    c.recall_calls += 1
    assert get_counters().recall_calls == 2
