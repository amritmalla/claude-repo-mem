from claude_repo_mem.tokens import count_tokens


def test_empty_string():
    assert count_tokens("") == 0


def test_simple_text_nonzero():
    assert count_tokens("hello world") > 0


def test_longer_is_longer():
    short = count_tokens("hi")
    long = count_tokens("hi " * 100)
    assert long > short


def test_idempotent():
    s = "def login(user, pw):\n    return Token()"
    assert count_tokens(s) == count_tokens(s)
