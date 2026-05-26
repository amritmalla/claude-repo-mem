from claude_mem.watcher.debounce import PathDebouncer


def test_collects_paths_until_flush():
    fired: list[set] = []
    d = PathDebouncer(on_flush=lambda paths: fired.append(set(paths)))
    d.add("a.py")
    d.add("b.py")
    d.add("a.py")
    assert not fired
    d.flush()
    assert fired == [{"a.py", "b.py"}]


def test_flush_with_no_changes_is_noop():
    fired: list[set] = []
    PathDebouncer(on_flush=lambda paths: fired.append(set(paths))).flush()
    assert not fired


def test_flush_clears_buffer():
    fired: list[set] = []
    d = PathDebouncer(on_flush=lambda paths: fired.append(set(paths)))
    d.add("a.py")
    d.flush()
    d.flush()
    assert fired == [{"a.py"}]


def test_due_at_advances_after_add():
    fake_now = [100.0]
    d = PathDebouncer(on_flush=lambda paths: None, quiet_ms=500, now_fn=lambda: fake_now[0])
    d.add("a.py")
    assert not d.is_due()
    fake_now[0] += 0.4
    assert not d.is_due()
    fake_now[0] += 0.2
    assert d.is_due()


def test_due_resets_on_subsequent_add():
    fake_now = [100.0]
    d = PathDebouncer(on_flush=lambda paths: None, quiet_ms=500, now_fn=lambda: fake_now[0])
    d.add("a.py")
    fake_now[0] += 0.4
    d.add("b.py")
    fake_now[0] += 0.4
    assert not d.is_due()
    fake_now[0] += 0.2
    assert d.is_due()
