from claude_mem.units.ids import make_handle, parse_handle, HandleParts


def test_make_handle_is_deterministic():
    h1 = make_handle("code", "function", "auth.login", "def login(): pass")
    h2 = make_handle("code", "function", "auth.login", "def login(): pass")
    assert h1 == h2


def test_make_handle_changes_with_content():
    h1 = make_handle("code", "function", "auth.login", "def login(): pass")
    h2 = make_handle("code", "function", "auth.login", "def login(): return 1")
    assert h1 != h2


def test_make_handle_format():
    h = make_handle("code", "function", "auth.login", "def login(): pass")
    assert h.startswith("code://function/")
    parts = h.split("/")
    assert len(parts[-1]) == 12  # 12-char short hash


def test_parse_handle_roundtrip():
    h = make_handle("memory", "decision", "auth/use-jwt", "We use JWT.")
    p = parse_handle(h)
    assert p == HandleParts(layer="memory", kind="decision", short_hash=h.split("/")[-1])


def test_parse_handle_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        parse_handle("not-a-handle")
    with pytest.raises(ValueError):
        parse_handle("http://example.com/foo")
