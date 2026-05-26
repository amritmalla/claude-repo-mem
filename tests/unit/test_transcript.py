import json
from pathlib import Path
from claude_mem.distill.transcript import parse_transcript, find_latest_transcript


def test_parse_simple(tmp_path: Path):
    p = tmp_path / "session.jsonl"
    p.write_text(
        json.dumps({"message": {"role": "user", "content": "hello"}}) + "\n" +
        json.dumps({"message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}}) + "\n"
    )
    turns = parse_transcript(p)
    assert len(turns) == 2
    assert turns[0].role == "user" and turns[0].content == "hello"
    assert turns[1].role == "assistant" and turns[1].content == "hi"


def test_parse_skips_malformed(tmp_path: Path):
    p = tmp_path / "session.jsonl"
    p.write_text("not json\n" + json.dumps({"message": {"role": "user", "content": "ok"}}) + "\n")
    turns = parse_transcript(p)
    assert len(turns) == 1


def test_find_latest_with_override(tmp_path: Path):
    fake = tmp_path / "x.jsonl"
    fake.write_text("")
    assert find_latest_transcript(tmp_path, override=fake) == fake
