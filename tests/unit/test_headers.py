from claude_repo_mem.units.headers import t1_header


def test_t1_for_python_function():
    h = t1_header(
        layer="code", kind="function", lang="python",
        name="login", signature="(user: str, pw: str) -> Token",
        first_line="def login(user: str, pw: str) -> Token:",
    )
    assert h == "python login(user: str, pw: str) -> Token"


def test_t1_for_python_class():
    h = t1_header(
        layer="code", kind="class", lang="python",
        name="AuthService", signature="(BaseService)",
        first_line="class AuthService(BaseService):",
        docstring_first_line="Handles login and token refresh.",
    )
    assert h == "python class AuthService(BaseService): Handles login and token refresh."


def test_t1_for_doc_section():
    h = t1_header(
        layer="docs", kind="section",
        heading_path=["Auth", "JWT", "Refresh"],
    )
    assert h == "# Auth > JWT > Refresh"


def test_t1_for_memory_fact():
    h = t1_header(
        layer="memory", kind="fact",
        text="We chose RS256 because the gateway needs to verify without the signing key.",
    )
    assert h.startswith("[fact] We chose RS256 because the gateway needs to verify")
    assert len(h) <= 90  # 80 chars + "[fact] " prefix


def test_t1_for_memory_decision_truncates_long():
    long = "x" * 500
    h = t1_header(layer="memory", kind="decision", text=long)
    assert h.startswith("[decision] ")
    # 80 chars of body + the prefix
    assert len(h) == len("[decision] ") + 80
