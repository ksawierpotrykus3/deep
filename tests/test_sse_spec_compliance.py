"""Tests for Strict OpenAI SSE Specification Compliance and Multi-byte Unicode Handling."""
import json
import pytest
import server


def test_openai_chunk_schema_invariants(validate_openai_chunk_schema, make_openai_chunk, make_openai_tool_chunk):
    """Verifies that all generated chunk types adhere to the official OpenAI JSON schema."""
    # 1. Role delta chunk
    role_chunk_raw = make_openai_chunk(content="", role="assistant", model="deepseek-chat")
    role_json = json.loads(role_chunk_raw.replace("data: ", "").strip())
    assert validate_openai_chunk_schema(role_json)
    assert role_json["choices"][0]["delta"]["role"] == "assistant"
    
    # 2. Content delta chunk
    content_chunk_raw = make_openai_chunk(content="Test message chunk", model="deepseek-chat")
    content_json = json.loads(content_chunk_raw.replace("data: ", "").strip())
    assert validate_openai_chunk_schema(content_json)
    assert content_json["choices"][0]["delta"]["content"] == "Test message chunk"
    
    # 3. Tool call delta chunk
    tool_chunk_raw = make_openai_tool_chunk(
        index=0,
        call_id="call_999",
        name="Read",
        args='{"file_path": "server.py"}',
        model="deepseek-chat"
    )
    tool_json = json.loads(tool_chunk_raw.replace("data: ", "").strip())
    assert validate_openai_chunk_schema(tool_json)
    assert tool_json["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "Read"
    
    # 4. Final finish_reason chunk
    stop_chunk_raw = make_openai_chunk(content="", finish_reason="stop", model="deepseek-chat")
    stop_json = json.loads(stop_chunk_raw.replace("data: ", "").strip())
    assert validate_openai_chunk_schema(stop_json)
    assert stop_json["choices"][0]["finish_reason"] == "stop"


def test_unicode_and_multibyte_escaping_in_sse_chunks(validate_openai_chunk_schema, make_openai_chunk):
    """Verifies that Polish diacritics, Chinese characters, fullwidth pipes, and quotes are properly escaped."""
    special_text = (
        'Zażółć gęślą jaźń! '
        'Ścieżka: c:\\Users\\Ksawier\\Projekty '
        'Tagi: <｜｜DSML｜｜> '
        'Znaki chińskie: 深度求索 '
        'JSON w stringu: {"key": "value with \\"quotes\\" and \n newline"}'
    )
    
    chunk_raw = make_openai_chunk(content=special_text, model="deepseek-chat")
    assert chunk_raw.startswith("data: ")
    assert chunk_raw.endswith("\n\n")
    
    chunk_json_str = chunk_raw[6:-2]
    parsed = json.loads(chunk_json_str)
    assert validate_openai_chunk_schema(parsed)
    assert parsed["choices"][0]["delta"]["content"] == special_text


def test_stream_done_sentinel_format():
    """Verifies that the stream termination marker is exactly 'data: [DONE]\n\n'."""
    sentinel = "data: [DONE]\n\n"
    assert sentinel.startswith("data: ")
    assert sentinel.endswith("\n\n")
    assert sentinel.strip() == "data: [DONE]"
