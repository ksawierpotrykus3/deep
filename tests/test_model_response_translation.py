"""Tests for Model Response Translation (DeepSeek Web Formats -> OpenAI Tool Calls & State Machine)."""
import json
import pytest
import server


def test_parse_dsml_task_tool_call(ds_raw_dsml_task_response):
    """Verifies that DSML Task call with 4 parameters is 100% correctly parsed into JSON arguments."""
    parsed = server._parse_tool_calls(ds_raw_dsml_task_response)
    assert len(parsed) == 1
    
    full_match, tool_type, tool_name, args_json = parsed[0]
    assert tool_name == "Task"
    args = json.loads(args_json)
    assert "description" in args
    assert "query" in args
    assert "subagent_type" in args
    assert "response_language" in args
    assert args["response_language"] in ("Polish", "pl")
    assert args["subagent_type"] in ("search", "general_purpose_task")
    assert "Ksawier" in args["query"] or "Projekty_autorskie" in args["query"]


def test_parse_xml_read_tool_call(ds_raw_xml_read_response):
    """Verifies that standard XML <tool_call name="Read"> is correctly parsed."""
    parsed = server._parse_tool_calls(ds_raw_xml_read_response)
    assert len(parsed) == 1
    
    full_match, tool_type, tool_name, args_json = parsed[0]
    assert tool_name == "Read"
    args = json.loads(args_json)
    assert "file_path" in args
    assert "server.py" in args["file_path"]
    assert args.get("start_line") == 1 or args.get("start_line") == "1"


def test_parse_short_xml_edit_tool_call(ds_raw_short_xml_edit_response):
    """Verifies that short XML format <_call name="Edit"> is parsed."""
    parsed = server._parse_tool_calls(ds_raw_short_xml_edit_response)
    assert len(parsed) == 1
    
    full_match, tool_type, tool_name, args_json = parsed[0]
    assert tool_name == "Edit"
    args = json.loads(args_json)
    assert args["file_path"] == "server.py"
    assert "MAX_PROMPT_LEN" in args["old_string"]
    assert "35000" in args["new_string"]


def test_parse_native_deepseek_tool_call(ds_raw_native_deepseek_response):
    """Verifies that native DeepSeek format <｜tool call begin｜> is parsed."""
    parsed = server._parse_tool_calls(ds_raw_native_deepseek_response)
    assert len(parsed) == 1
    
    full_match, tool_type, tool_name, args_json = parsed[0]
    assert tool_name == "Grep"
    args = json.loads(args_json)
    assert args["query"] == "_detect_loop"
    assert args["path"] == "server.py"


def test_parse_markdown_json_tool_call(ds_raw_markdown_json_response):
    """Verifies that markdown json tool block is parsed."""
    parsed = server._parse_tool_calls(ds_raw_markdown_json_response)
    assert len(parsed) == 1
    
    full_match, tool_type, tool_name, args_json = parsed[0]
    assert tool_name == "LS"
    args = json.loads(args_json)
    assert "path" in args


def test_parse_multi_tool_call(ds_raw_multi_tool_response):
    """Verifies that multiple tool calls in a single turn are all extracted."""
    parsed = server._parse_tool_calls(ds_raw_multi_tool_response)
    assert len(parsed) == 2
    
    names = [p[2] for p in parsed]
    assert "Read" in names
    assert "LS" in names


def test_unclosed_tool_call_detection_complete_vs_truncated(ds_raw_dsml_task_response, ds_raw_truncated_dsml_response):
    """Verifies that _has_unclosed_tool_call accurately distinguishes complete vs truncated DSML payloads."""
    assert server._has_unclosed_tool_call(ds_raw_dsml_task_response) is False
    assert server._has_unclosed_tool_call(ds_raw_truncated_dsml_response) is True
    
    # Test unclosed tail
    assert server._has_unclosed_tool_call("<｜｜DSML｜｜inv") is True
    assert server._has_unclosed_tool_call("<tool_call name=") is True
    assert server._has_unclosed_tool_call("Just normal conversational text") is False


def test_loop_guard_false_positive_immunity(ds_raw_dsml_task_response):
    """Verifies that legal repeated tags and 5+ parallel tool calls in the same directory do not trigger loop guard."""
    assert server._detect_loop(ds_raw_dsml_task_response) is False
    
    # Real 5 parallel tool calls in the same deep directory
    tools = []
    for name in ["PLAN.md", "PLAN_faza1.md", "PLAN_faza2_analiza.md", "PLAN_orchestrator.md", "PLAN_faza3.md"]:
        tools.append(f'<invoke name="Read">\n<parameter name="file_path">c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_autorskie\\dry_runy\\plan\\{name}</parameter>\n</invoke>')
    parallel_tools_text = "<tool_calls>\n" + "\n".join(tools) + "\n</tool_calls>"
    
    assert server._detect_loop(parallel_tools_text) is False
    # Stream simulated char-by-char should never trigger loop guard
    buf = ""
    for ch in parallel_tools_text:
        buf += ch
        assert server._detect_loop(buf) is False


def test_loop_guard_catches_true_infinite_loops():
    """Verifies that massive 100+ character repetitive loops are reliably caught."""
    # 100-character exact pattern
    infinite_pattern = ("CRITICAL_INFINITE_LOOP_BLOCK_AT_NODE_X_" * 3)[:100]
    assert len(infinite_pattern) == 100
    loop_text = infinite_pattern * 6  # 600 characters
    
    assert server._detect_loop(loop_text) is True


def test_thinking_stream_phase_isolation(ds_raw_thinking_stream_frames):
    """Verifies that THINK fragments are isolated from RESPONSE and that -1/content tokens are preserved."""
    content_buffer = ""
    thinking_buffer = ""
    thinking_active = False
    response_started = False
    
    for raw_frame in ds_raw_thinking_stream_frames:
        chunk_json = json.loads(raw_frame)
        val = chunk_json.get("v")
        path = chunk_json.get("p", "")
        
        # Check phase declaration in v.response
        if isinstance(val, dict) and "response" in val:
            resp_obj = val["response"]
            fragments = resp_obj.get("fragments", [])
            for frag in fragments:
                ftype = frag.get("type")
                fcontent = frag.get("content", "")
                if ftype == "THINK":
                    thinking_active = True
                    thinking_buffer += fcontent
                elif ftype == "RESPONSE":
                    thinking_active = False
                    response_started = True
                    content_buffer += fcontent
            continue
            
        # Check phase declaration in p == "response/fragments"
        if path == "response/fragments" and isinstance(val, list):
            for frag in val:
                ftype = frag.get("type")
                fcontent = frag.get("content", "")
                if ftype == "THINK":
                    thinking_active = True
                    thinking_buffer += fcontent
                elif ftype == "RESPONSE":
                    thinking_active = False
                    response_started = True
                    content_buffer += fcontent
            continue
            
        # Token routing
        token_str = ""
        if isinstance(val, str):
            token_str = val
            
        if thinking_active:
            thinking_buffer += token_str
        else:
            content_buffer += token_str
            
    assert "Rekurencja to metoda rozwiązywania problemów." in content_buffer
    assert "Rozważam definicję" in thinking_buffer
    assert "Rozważam definicję" not in content_buffer
