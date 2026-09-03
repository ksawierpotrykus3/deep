import os
import server

def test_annotate_read_tool_result_partial():
    mock_content = "10→import sys\n11→import os"
    result = server._annotate_read_tool_result(mock_content, "server.py")
    assert "[FILE METADATA: server.py | STATUS: PARTIAL SNIPPET" in result
    assert "SearchReplace" in result
    assert "Write" in result
    assert "10→import sys" in result

def test_annotate_read_tool_result_full(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    mock_content = "1→line1\n2→line2\n3→line3"
    result = server._annotate_read_tool_result(mock_content, str(f))
    assert "[FILE METADATA: sample.py | STATUS: FULL FILE" in result
    assert "Do NOT re-read this file" in result
    assert "1→line1" in result

def test_annotate_read_tool_result_no_duplicate():
    mock_content = "[FILE METADATA: sample.py | STATUS: FULL FILE]\ncode"
    result = server._annotate_read_tool_result(mock_content, "sample.py")
    assert result == mock_content
