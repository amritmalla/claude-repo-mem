from claude_mem.llm.base import LLMClient, LLMError


def test_protocol_has_complete():
    assert hasattr(LLMClient, "complete")


def test_llm_error_is_exception():
    e = LLMError("oops")
    assert isinstance(e, Exception)
    assert "oops" in str(e)
