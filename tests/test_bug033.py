import pytest
import re
from server import _clean_dsml_wait, _STRIP_TAGS, _has_unclosed_tool_call


def test_clean_dsml_wait_removes_full_blocks():
    raw = "<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>"
    cleaned = _clean_dsml_wait(raw)
    assert cleaned == ""


def test_clean_dsml_wait_removes_repeated_blocks():
    raw = "<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>" * 4
    cleaned = _clean_dsml_wait(raw)
    assert cleaned.strip() == ""


def test_clean_dsml_wait_preserves_surrounding_text():
    raw = "Oto moja analiza:\n1. Punkt pierwszy.\n<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>\n2. Punkt drugi."
    cleaned = _clean_dsml_wait(raw)
    assert "Oto moja analiza:" in cleaned
    assert "1. Punkt pierwszy." in cleaned
    assert "2. Punkt drugi." in cleaned
    assert "_wait" not in cleaned
    assert "—brak" not in cleaned


def test_strip_tags_removes_dsml_wait_body():
    raw = "Tekst<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>"
    cleaned = _STRIP_TAGS.sub("", raw)
    assert cleaned == "Tekst"
    assert "—brak" not in cleaned


def test_tail_check_unblocks_streaming_on_dsml_wait():
    tool_regex = re.compile(
        r'</?\s*(?:[|\uff5c\u2502\s]*DSML|tool_call|invoke|_call|user_input|parameter|参数|參數|pattern|path|file_path|command|glob|grep|read|write|task|skill)\b',
        re.IGNORECASE
    )
    tail = "<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>"
    assert tool_regex.search(tail) is not None
    tail_check = _clean_dsml_wait(tail)
    assert tool_regex.search(tail_check) is None


def test_trailing_text_flushed_when_stream_ends_with_wait():
    tool_regex = re.compile(
        r'<\s*(?:[|\uff5c\u2502\s]*DSML|tool_call|invoke|_call|user_input|parameter|参数|參數|pattern|path)',
        re.IGNORECASE
    )
    remaining = "Przepraszam — wcześniej emitowałem puste znaczniki.\n<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>"
    rem_check = _clean_dsml_wait(remaining)
    
    assert not _has_unclosed_tool_call(rem_check)
    assert not tool_regex.search(rem_check)
    
    clean_rem = _STRIP_TAGS.sub("", rem_check)
    assert clean_rem.strip() == "Przepraszam — wcześniej emitowałem puste znaczniki."


def test_empty_full_with_only_wait_detects_empty_and_wait():
    full = "<\uff5c\uff5cDSML\uff5c\uff5c_wait>—brak</\uff5c\uff5cDSML\uff5c\uff5c_wait>" * 4
    clean_full = _clean_dsml_wait(full)
    clean_full = _STRIP_TAGS.sub("", clean_full).strip()
    
    assert not clean_full
    assert "_wait" in full.lower()


def test_coordinator_prompt_allows_direct_reading():
    with open("server.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "DO NOT use Read/Glob/Grep/SearchCodebase yourself if a subagent can do it" not in content
    assert "You CAN and SHOULD use Read/Write/Edit/SearchReplace directly when inspecting or modifying specific target files" in content
