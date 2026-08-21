"""End-to-End Tests for OpenAI-Compatible SSE Streaming and Chunk Analysis."""
import json
import time
import pytest
from unittest.mock import MagicMock
import server


def test_e2e_text_streaming_chunk_sequence(parse_sse_stream, validate_openai_chunk_schema, accumulate_stream_content_and_tools, make_openai_chunk):
    """Verifies complete SSE stream for standard text conversation."""
    raw_tokens = ["Oto ", "odpowiedź ", "na ", "Twoje ", "pytanie ", "o ", "algorytmy."]
    
    stream_output = ""
    for i, tok in enumerate(raw_tokens):
        chunk_str = make_openai_chunk(content=tok, model="deepseek-chat")
        stream_output += chunk_str
        
    final_chunk = make_openai_chunk(content="", finish_reason="stop", model="deepseek-chat")
    stream_output += final_chunk
    stream_output += "data: [DONE]\n\n"
    
    events = parse_sse_stream(stream_output)
    assert len(events) == len(raw_tokens) + 2  # tokens + final chunk + [DONE]
    
    # Validate each data chunk against OpenAI schema
    for ev in events:
        if ev["type"] == "data":
            validate_openai_chunk_schema(ev["json"])
            
    assert events[-1]["type"] == "done"
    
    content, tools, finish_reason = accumulate_stream_content_and_tools(events)
    assert content == "Oto odpowiedź na Twoje pytanie o algorytmy."
    assert tools == []
    assert finish_reason == "stop"


def test_e2e_dsml_tool_calling_chunk_sequence(ds_raw_dsml_task_response, parse_sse_stream, validate_openai_chunk_schema, accumulate_stream_content_and_tools, make_openai_chunk, make_openai_tool_chunk):
    """Verifies that DSML Task call from DeepSeek Web is translated into OpenAI SSE tool_calls chunks."""
    parsed_tools = server._parse_tool_calls(ds_raw_dsml_task_response)
    assert len(parsed_tools) == 1
    
    stream_output = ""
    for idx, (match_str, tool_type, name, args_json) in enumerate(parsed_tools):
        chunk_str = make_openai_tool_chunk(
            index=idx,
            call_id=f"call_{idx}_{int(time.time())}",
            name=name,
            args=args_json,
            model="deepseek-chat"
        )
        stream_output += chunk_str
        
    final_chunk = make_openai_chunk(content="", finish_reason="tool_calls", model="deepseek-chat")
    stream_output += final_chunk
    stream_output += "data: [DONE]\n\n"
    
    events = parse_sse_stream(stream_output)
    for ev in events:
        if ev["type"] == "data":
            validate_openai_chunk_schema(ev["json"])
            
    assert events[-1]["type"] == "done"
    
    content, tools, finish_reason = accumulate_stream_content_and_tools(events)
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "Task"
    assert finish_reason == "tool_calls"
    
    # Verify that reconstructed arguments can be cleanly parsed as JSON
    parsed_args = json.loads(tools[0]["function"]["arguments"])
    assert parsed_args["subagent_type"] in ("search", "general_purpose_task")
    assert parsed_args["response_language"] in ("Polish", "pl")


def test_e2e_multi_tool_calling_chunk_sequence(ds_raw_multi_tool_response, parse_sse_stream, validate_openai_chunk_schema, accumulate_stream_content_and_tools, make_openai_chunk, make_openai_tool_chunk):
    """Verifies that multiple tools in a single turn receive separate incremental indexes in delta.tool_calls."""
    parsed_tools = server._parse_tool_calls(ds_raw_multi_tool_response)
    assert len(parsed_tools) == 2
    
    stream_output = ""
    for idx, (match_str, tool_type, name, args_json) in enumerate(parsed_tools):
        chunk_str = make_openai_tool_chunk(
            index=idx,
            call_id=f"call_{idx}_{int(time.time())}",
            name=name,
            args=args_json,
            model="deepseek-chat"
        )
        stream_output += chunk_str
        
    final_chunk = make_openai_chunk(content="", finish_reason="tool_calls", model="deepseek-chat")
    stream_output += final_chunk
    stream_output += "data: [DONE]\n\n"
    
    events = parse_sse_stream(stream_output)
    content, tools, finish_reason = accumulate_stream_content_and_tools(events)
    
    assert len(tools) == 2
    assert tools[0]["function"]["name"] == "Read"
    assert tools[1]["function"]["name"] == "LS"
    assert finish_reason == "tool_calls"


def test_e2e_heartbeat_sse_keepalive_interspersed(parse_sse_stream, validate_openai_chunk_schema, make_openai_chunk):
    """Verifies that : keep-alive comments do not disrupt the JSON stream."""
    stream_output = (
        make_openai_chunk(content="First chunk", model="deepseek-chat")
        + ": keep-alive\n\n"
        + ": keep-alive\n\n"
        + make_openai_chunk(content=" Second chunk", model="deepseek-chat")
        + make_openai_chunk(content="", finish_reason="stop", model="deepseek-chat")
        + "data: [DONE]\n\n"
    )
    
    events = parse_sse_stream(stream_output)
    comments = [ev for ev in events if ev["type"] == "comment"]
    data_events = [ev for ev in events if ev["type"] == "data"]
    
    assert len(comments) == 2
    assert all(c["comment"] == "keep-alive" for c in comments)
    assert len(data_events) == 3
    for ev in data_events:
        validate_openai_chunk_schema(ev["json"])
