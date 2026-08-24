"""Regression tests for tool-call parsing, unclosed-tag detection, and state-bump logic fixes."""
import json

import server


def _parse_one(text):
    tools = server._parse_tool_calls(text)
    if not tools:
        return None
    _, _, name, args = tools[0]
    return name, json.loads(args)


def test_glob_lowercase_tag():
    """<glob> (lowercase, positional pattern) must be recognized as Glob with pattern and path separated."""
    r = _parse_one("<glob> **/*.py c:/Users/Ksawier/test </glob>")
    assert r is not None
    name, args = r
    assert name == "Glob"
    assert args["pattern"] == "**/*.py"
    assert args["path"] == "c:/Users/Ksawier/test"


def test_runcommand_lowercase_tag_with_nested_command():
    """<runcommand> with nested <command> must be recognized as RunCommand."""
    r = _parse_one("<runcommand> <command>git status</command> </runcommand>")
    assert r is not None
    name, args = r
    assert name == "RunCommand"
    assert args["command"] == "git status"


def test_read_tag_with_positional_offset_limit():
    """<Read> path 120 50 </Read> without nested tags must parse file_path/offset/limit."""
    r = _parse_one("<Read> path/file.py 120 50 </Read>")
    assert r is not None
    name, args = r
    assert name == "Read"
    assert args["file_path"] == "path/file.py"
    assert args["offset"] == 120
    assert args["limit"] == 50


def test_bare_path_with_offset_limit_becomes_read():
    """Bare 'path/file.py 120 50' without XML must be recognized as Read, not leaked."""
    r = _parse_one("c:/Users/Ksawier/server.py 120 50")
    assert r is not None
    name, args = r
    assert name == "Read"
    assert args["file_path"] == "c:/Users/Ksawier/server.py"
    assert args["offset"] == 120
    assert args["limit"] == 50


def test_unclosed_tool_calls_plural_detected():
    """<tool_calls> (plural) must be detected as unclosed — regression for the \b bug."""
    assert server._has_unclosed_tool_call("<tool_calls>") is True
    assert server._has_unclosed_tool_call("<tool_call>") is True
    assert server._has_unclosed_tool_call("<invoke>") is True
    assert server._has_unclosed_tool_call("<read>") is True


def test_state_bump_logic_respects_loop_aborted():
    """loop_aborted must block state bump even with preambula text."""
    meta_loop = {"finished_normally": False, "loop_aborted": True}
    meta_norm = {"finished_normally": True, "loop_aborted": False}
    meta_empty = {"finished_normally": False, "loop_aborted": False}

    assert server._should_bump_state(0, meta_loop) is False
    assert server._should_bump_state(0, meta_norm) is True
    assert server._should_bump_state(0, meta_empty) is False
    # Real tool work is success regardless of loop flag
    assert server._should_bump_state(1, meta_loop) is True


def test_map_positional_does_not_glue_numbers_to_path():
    """_map_positional must split trailing offset/limit from the file path."""
    assert server._map_positional("Read", "c:/test/server.py 1220 200") == {
        "file_path": "c:/test/server.py",
        "offset": 1220,
        "limit": 200,
    }
    assert server._map_positional("Read", "c:/test/server.py 1220") == {
        "file_path": "c:/test/server.py",
        "offset": 1220,
    }
    assert server._map_positional("Read", "c:/test/server.py") == {
        "file_path": "c:/test/server.py",
    }


def test_chunk_threshold_is_at_least_95k():
    """CHUNK_THRESHOLD must be at least 95000 to prevent breaking new chats on tool injection."""
    assert server.CHUNK_THRESHOLD >= 95000


def test_unclosed_tool_call_not_flushed_as_plain_content():
    """An unclosed tool call must not leak into displayed text."""
    partial = 'Intro text\n<invoke name="Write"><parameter name="content">import os\ncode...'
    assert server._has_unclosed_tool_call(partial) is True


def test_map_positional_glob_and_grep():
    """_map_positional must handle Glob and Grep parameter combinations correctly."""
    assert server._map_positional("Glob", "* c:/test/dir") == {
        "path": "c:/test/dir",
        "pattern": "*",
    }
    assert server._map_positional("Glob", "c:/test/dir *.md") == {
        "path": "c:/test/dir",
        "pattern": "*.md",
    }
    assert server._map_positional("Grep", "OLX|olx c:/test/dir files_with_matches 300") == {
        "pattern": "OLX|olx",
        "path": "c:/test/dir",
        "output_mode": "files_with_matches",
        "head_limit": 300,
    }


def test_parse_tool_calls_handles_shorthand_stacked_tags():
    """_parse_tool_calls must extract multiple consecutive shorthand tool tags without crashing."""
    raw = (
        '<glob> * c:/proj <glob> **/*.md c:/proj/docs '
        '<grep> token c:/proj files_with_matches 50 '
        '<read> c:/proj/file.py 10 20 '
        '</glob></glob></grep></read>'
    )
    calls = server._parse_tool_calls(raw, known_tools=["Glob", "Grep", "Read"])
    assert len(calls) == 4
    names = [c[2] for c in calls]
    assert names == ["Glob", "Glob", "Grep", "Read"]


def test_strip_tags_removes_cascading_closed_tags():
    """_STRIP_TAGS must remove cascading tags like </glob></glob></grep></read>."""
    raw = "Some text </glob></glob></grep></read>"
    cleaned = server._clean_text(raw)
    assert "</glob>" not in cleaned
    assert "</grep>" not in cleaned
    assert "</read>" not in cleaned
    assert cleaned == "Some text"


def test_parse_tool_calls_chinese_parameters():
    """_parse_tool_calls must extract parameters written with Chinese tags (<参数>)."""
    raw = (
        '<参数 name="description">Wyodrębnij specyfikację</参数> '
        '<参数 name="query">Przeczytaj pliki</参数> '
        '<参数 name="subagent_type">search</参数>'
    )
    calls = server._parse_tool_calls(raw)
    assert len(calls) == 1
    start, end, name, args_json = calls[0]
    assert name == "Task"
    parsed = json.loads(args_json)
    assert parsed["description"] == "Wyodrębnij specyfikację"
    assert parsed["query"] == "Przeczytaj pliki"
    assert parsed["subagent_type"] == "search"


def test_parse_tool_calls_orphaned_pattern_tags():
    """_parse_tool_calls must extract direct <pattern>...</pattern><path>...</path> tags as Grep."""
    raw = (
        '<pattern>[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]</pattern>\n'
        '<path>c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT</path>\n\n'
        '<pattern>^\\s*(#|;|::|rem\\s)</pattern>\n'
        '<path>c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT</path>'
    )
    calls = server._parse_tool_calls(raw)
    assert len(calls) == 2
    assert calls[0][2] == "Grep"
    assert json.loads(calls[0][3])["pattern"] == "[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]"
    assert json.loads(calls[0][3])["path"] == "c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_zlecenia\\Last_Z_BOT"
    assert calls[1][2] == "Grep"
    assert json.loads(calls[1][3])["pattern"] == "^\\s*(#|;|::|rem\\s)"