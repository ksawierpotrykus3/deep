import pytest
import json
import server

def test_normal_chat_response_not_broken():
    """Verify standard text with no tool tags is completely untouched."""
    text = "Oto podsumowanie analizy:\n1. Plik `main.py` wymaga poprawki.\n2. Wszystko działa poprawnie."
    tools = server._parse_tool_calls(text)
    assert tools == []
    cleaned = server._clean_text(text)
    assert cleaned == text

def test_code_block_with_xml_like_syntax():
    """Verify python code with angle brackets in markdown is not corrupted."""
    text = "```python\nif a < b and c > d:\n    print('<test>')\n```"
    tools = server._parse_tool_calls(text)
    assert tools == []
    cleaned = server._clean_text(text)
    assert "if a < b and c > d:" in cleaned

def test_standard_invoke_tool_call_takes_precedence():
    """Verify standard <invoke name='Read'> is parsed normally and not affected by fallback parsers."""
    text = '<invoke name="Read"><parameter name="file_path">c:/test/file.py</parameter></invoke>'
    tools = server._parse_tool_calls(text)
    assert len(tools) == 1
    assert tools[0][2] == "Read"
    assert json.loads(tools[0][3]) == {"file_path": "c:/test/file.py"}

def test_native_deepseek_tool_call_intact():
    """Verify DeepSeek native tool call format is not affected."""
    text = '<｜tool call begin｜>function<｜tool sep｜>Read\n```json\n{"file_path": "c:/test/app.py"}\n```\n<｜tool call end｜>'
    tools = server._parse_tool_calls(text)
    assert len(tools) == 1
    assert tools[0][2] == "Read"
    assert json.loads(tools[0][3]) == {"file_path": "c:/test/app.py"}

def test_regular_dsml_tool_call_intact():
    """Verify standard DSML tool call format works as expected."""
    text = '< | | DSML | | name="Glob"><parameter name="pattern">*.py</parameter><parameter name="path">c:/src</parameter></ | | DSML | | >'
    tools = server._parse_tool_calls(text)
    assert len(tools) == 1
    assert tools[0][2] == "Glob"
    assert json.loads(tools[0][3]) == {"pattern": "*.py", "path": "c:/src"}
