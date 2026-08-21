"""Master Fixtures Configuration for Pytest (OpenAI & DeepSeek Web Test Suite).

Provides deterministic fixtures for:
1. IDE Requests (OpenAI-compatible / Trae IDE format)
2. Model Responses (DeepSeek Web raw outputs in 10+ real-world scenarios)
3. SSE Validation, Chunk Parsing & Schema Invariant Verifiers
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple

import pytest

# Ensure server module is importable
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import server  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 1. REQUEST FIXTURES (IDE / OpenAI Compatible)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def trae_10_tools_schemas() -> List[Dict[str, Any]]:
    """Full set of 10 Trae IDE tool definitions (~6 500 characters of JSON Schema)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read file contents with line numbers and line range slicing",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to the file to read"},
                        "start_line": {"type": "integer", "description": "1-based starting line number"},
                        "end_line": {"type": "integer", "description": "1-based ending line number"}
                    },
                    "required": ["file_path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Write",
                "description": "Write or overwrite content to a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "New content for the file"}
                    },
                    "required": ["file_path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Edit",
                "description": "Replace targeted chunk of text in an existing file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Target file path"},
                        "old_string": {"type": "string", "description": "Exact text to replace"},
                        "new_string": {"type": "string", "description": "Replacement text"}
                    },
                    "required": ["file_path", "old_string", "new_string"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Grep",
                "description": "Search pattern in codebase using ripgrep syntax",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search pattern"},
                        "path": {"type": "string", "description": "Search root directory"},
                        "case_sensitive": {"type": "boolean", "description": "Perform case sensitive search"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Glob",
                "description": "Find files matching wildcard glob pattern",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"},
                        "path": {"type": "string", "description": "Base directory"}
                    },
                    "required": ["pattern"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "LS",
                "description": "List directory contents recursively",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory to list"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Task",
                "description": "Launch specialized subagent for background execution",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "Short 2-5 word job description"},
                        "query": {"type": "string", "description": "Detailed multi-line instructions for subagent"},
                        "subagent_type": {"type": "string", "enum": ["search", "general_purpose_task", "writer"]},
                        "response_language": {"type": "string", "description": "Target language for output"}
                    },
                    "required": ["description", "query", "subagent_type", "response_language"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "RunCommand",
                "description": "Execute shell command on local system",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "CLI command line string"},
                        "cwd": {"type": "string", "description": "Working directory path"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "Browser",
                "description": "Interact with headless browser for web research",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"},
                        "action": {"type": "string", "enum": ["navigate", "screenshot", "click", "fill"]}
                    },
                    "required": ["url"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "DiffPreview",
                "description": "Generate visual diff preview before applying patch",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file"},
                        "diff": {"type": "string", "description": "Unified diff block"}
                    },
                    "required": ["file_path", "diff"]
                }
            }
        }
    ]


@pytest.fixture
def ide_standard_chat_request() -> Dict[str, Any]:
    """Standard OpenAI Chat Completion request from IDE without tool calls."""
    return {
        "model": "deepseek-chat",
        "stream": True,
        "messages": [
            {"role": "system", "content": "You are an expert software engineer."},
            {"role": "user", "content": "Explain how Dijkstra shortest path algorithm works in Python."}
        ]
    }


@pytest.fixture
def ide_subagent_task_request(trae_10_tools_schemas) -> Dict[str, Any]:
    """Trae Coordinator request instructing the model to launch parallel subagents."""
    return {
        "model": "deepseek-reasoner",
        "stream": True,
        "tools": trae_10_tools_schemas,
        "messages": [
            {"role": "system", "content": "You are a master coordinator running in Trae IDE. Use Task tool for subagents."},
            {"role": "user", "content": "Przeanalizuj 4 projekty w folderze c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_autorskie i stwórz dla nich skróty."}
        ]
    }


@pytest.fixture
def ide_multiturn_heavy_history_request(trae_10_tools_schemas) -> Dict[str, Any]:
    """Multi-turn conversation containing heavy tool results (>80k characters raw)."""
    large_file_content = "\n".join(f"{i:4d}: def function_handler_{i}(arg_{i}: int) -> str:\n    return f'res_{i}'" for i in range(1, 400))
    large_grep_content = "\n".join(f"server.py:{i}: match found for pattern in cluster node {i*7}" for i in range(1, 300))
    
    return {
        "model": "deepseek-chat",
        "stream": True,
        "tools": trae_10_tools_schemas,
        "messages": [
            {"role": "system", "content": "You are an AI coding assistant."},
            {"role": "user", "content": "Read server.py and search for route handlers."},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "server.py"}'}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "Read", "content": large_file_content},
            {"role": "assistant", "content": "I have read server.py. Now searching with Grep.", "tool_calls": [{"id": "call_2", "type": "function", "function": {"name": "Grep", "arguments": '{"query": "route_handler"}'}}]},
            {"role": "tool", "tool_call_id": "call_2", "name": "Grep", "content": large_grep_content},
            {"role": "user", "content": "Now write a summary report based on all gathered data."}
        ]
    }


@pytest.fixture
def ide_monolith_user_request(trae_10_tools_schemas) -> Dict[str, Any]:
    """Request with single 100k monolith user message."""
    monolith = "USER_MASSIVE_LOG_DATA\n" + ("LOG_ENTRY_TIMESTAMP_PAYLOAD_VALUE_X\n" * 3000) + "END_LOG"
    return {
        "model": "deepseek-chat",
        "stream": True,
        "tools": trae_10_tools_schemas,
        "messages": [
            {"role": "system", "content": "Analyze logs."},
            {"role": "user", "content": monolith}
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. RESPONSE FIXTURES (DeepSeek Web Model Outputs in Various Scenarios)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def ds_raw_dsml_task_response() -> str:
    """Exact DSML Task payload from Request #448 (deeo.txt)."""
    deeo_path = BASE_DIR.parent / "deeo.txt"
    if not deeo_path.exists():
        deeo_path = BASE_DIR / "deeo.txt"
    if deeo_path.exists():
        with open(deeo_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[743:784])
    return """<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="Task">
<｜｜DSML｜｜parameter name="description" string="true">Analiza projektu deepseek-proxy-clean</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="query" string="true">1. Przejrzyj pliki w c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_autorskie\\deepseek-proxy-clean
2. Zidentyfikuj kluczowe moduły i mechanizmy
3. Utwórz plik podsumowania markdown</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="response_language" string="true">pl</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="subagent_type" string="true">general_purpose_task</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""


@pytest.fixture
def ds_raw_xml_read_response() -> str:
    """Standard XML <tool_call name="Read">."""
    return """Jasne, sprawdzam zawartość pliku server.py:

<tool_call name="Read">
<parameter name="file_path">c:\\Users\\Ksawier\\Pictures\\Screenshots\\Projekty_autorskie\\deepseek-proxy-clean\\server.py</parameter>
<parameter name="start_line">1</parameter>
<parameter name="end_line">100</parameter>
</tool_call>"""


@pytest.fixture
def ds_raw_short_xml_edit_response() -> str:
    """Skrócony format <_call name="Edit">."""
    return """<_call name="Edit">
<parameter name="file_path">server.py</parameter>
<parameter name="old_string">MAX_PROMPT_LEN = 75000</parameter>
<parameter name="new_string">MAX_PROMPT_LEN = 35000</parameter>
</_call>"""


@pytest.fixture
def ds_raw_native_deepseek_response() -> str:
    """Natywny format DeepSeek <｜tool call begin｜>."""
    return """<｜tool call begin｜>function<｜tool sep｜>Grep
```json
{"query": "_detect_loop", "path": "server.py"}
```<｜tool call end｜>"""


@pytest.fixture
def ds_raw_markdown_json_response() -> str:
    """Wywołanie narzędzia w bloku Markdown ```json."""
    return """```json
{
  "tool": "LS",
  "parameters": {
    "path": "c:\\\\Users\\\\Ksawier\\\\Pictures\\\\Screenshots\\\\Projekty_autorskie"
  }
}
```"""


@pytest.fixture
def ds_raw_multi_tool_response() -> str:
    """Multiple tool calls emitted in a single turn."""
    return """Wykonuję operację odczytu oraz listowania katalogu:

<tool_call name="Read">
<parameter name="file_path">server.py</parameter>
</tool_call>

<tool_call name="LS">
<parameter name="path">data</parameter>
</tool_call>"""


@pytest.fixture
def ds_raw_truncated_dsml_response(ds_raw_dsml_task_response) -> str:
    """Truncated DSML payload cut in the middle of query parameter."""
    return ds_raw_dsml_task_response[:300]


@pytest.fixture
def ds_raw_thinking_stream_frames() -> List[str]:
    """Exact raw SSE frame sequence simulating THINK phase -> RESPONSE phase (Rekurencja)."""
    return [
        json.dumps({"v": {"response": {"message_id": 2, "parent_id": 1, "fragments": [{"type": "THINK", "content": "Rozważam definicję pojęcia rekurencji w informatyce..."}]}}}),
        json.dumps({"p": "response/fragments/-1/content", "o": "APPEND", "v": " Użytkownik pyta o prosty przykład."}),
        json.dumps({"p": "response/fragments", "o": "APPEND", "v": [{"type": "RESPONSE", "content": "R"}]}),
        json.dumps({"p": "response/fragments/-1/content", "v": "ek"}),
        json.dumps({"v": "uren"}),
        json.dumps({"v": "cja"}),
        json.dumps({"v": " to metoda rozwiązywania problemów."}),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 3. UTILITY & ASSERTION FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def parse_sse_stream():
    """Parses raw SSE string into a list of events: {'type': 'data'|'comment', 'json': dict|None, 'raw': str}."""
    def _parse(raw_sse: str) -> List[Dict[str, Any]]:
        events = []
        lines = raw_sse.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith(":"):
                events.append({"type": "comment", "comment": line[1:].strip(), "raw": line})
            elif line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    events.append({"type": "done", "raw": line})
                else:
                    try:
                        parsed_json = json.loads(data_str)
                        events.append({"type": "data", "json": parsed_json, "raw": line})
                    except Exception as e:
                        events.append({"type": "invalid_json", "error": str(e), "raw": line})
        return events
    return _parse


@pytest.fixture
def validate_openai_chunk_schema():
    """Validates that a parsed SSE JSON object complies 100% with OpenAI Chat Completion Chunk Schema."""
    def _validate(chunk: Dict[str, Any]):
        assert "id" in chunk, f"Chunk missing 'id': {chunk}"
        assert chunk.get("object") == "chat.completion.chunk", f"Invalid object: {chunk}"
        assert "created" in chunk and isinstance(chunk["created"], int), f"Invalid created: {chunk}"
        assert "model" in chunk, f"Chunk missing 'model': {chunk}"
        assert "choices" in chunk and isinstance(chunk["choices"], list) and len(chunk["choices"]) > 0, f"Invalid choices: {chunk}"
        
        choice = chunk["choices"][0]
        assert "index" in choice and choice["index"] == 0, f"Invalid choice index: {choice}"
        assert "delta" in choice and isinstance(choice["delta"], dict), f"Invalid delta: {choice}"
        
        delta = choice["delta"]
        # Delta can contain role, content, or tool_calls
        if "tool_calls" in delta:
            assert isinstance(delta["tool_calls"], list), f"tool_calls must be list: {delta}"
            for tc in delta["tool_calls"]:
                assert "index" in tc, f"tool_call missing index: {tc}"
                assert "function" in tc, f"tool_call missing function: {tc}"
                fn = tc["function"]
                if "name" in fn:
                    assert isinstance(fn["name"], str), f"function name must be string: {fn}"
                if "arguments" in fn:
                    assert isinstance(fn["arguments"], str), f"function arguments must be string: {fn}"
                    
        if "finish_reason" in choice and choice["finish_reason"] is not None:
            assert choice["finish_reason"] in ("stop", "tool_calls", "length", "content_filter"), f"Invalid finish_reason: {choice}"
            
        return True
    return _validate


@pytest.fixture
def accumulate_stream_content_and_tools():
    """Accumulates deltas across all chunks and reconstructs full text content and parsed tool calls."""
    def _accumulate(events: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]], str | None]:
        full_content = ""
        tools_dict = {}
        final_finish_reason = None
        
        for ev in events:
            if ev["type"] != "data":
                continue
            chunk = ev["json"]
            choice = chunk["choices"][0]
            if choice.get("finish_reason"):
                final_finish_reason = choice["finish_reason"]
                
            delta = choice.get("delta", {})
            if "content" in delta and delta["content"]:
                full_content += delta["content"]
                
            if "tool_calls" in delta:
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tools_dict:
                        tools_dict[idx] = {
                            "id": tc.get("id", f"call_{idx}"),
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        }
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tools_dict[idx]["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        tools_dict[idx]["function"]["arguments"] += fn["arguments"]
                        
        tools_list = [tools_dict[i] for i in sorted(tools_dict.keys())]
        return full_content, tools_list, final_finish_reason
    return _accumulate


@pytest.fixture
def make_openai_chunk():
    """Generates an OpenAI SSE chunk line for testing."""
    def _make(content: str = "", role: str | None = None, finish_reason: str | None = None, model: str = "deepseek-chat") -> str:
        delta = {}
        if role:
            delta["role"] = role
        if content:
            delta["content"] = content
        c = {
            "id": "chatcmpl-test-chunk-123456",
            "object": "chat.completion.chunk",
            "created": 1786872000,
            "model": model,
            "system_fingerprint": "fp_deepseek_proxy_v1",
            "choices": [{"index": 0, "delta": delta}]
        }
        if finish_reason is not None:
            c["choices"][0]["finish_reason"] = finish_reason
        return f"data: {json.dumps(c)}\n\n"
    return _make


@pytest.fixture
def make_openai_tool_chunk():
    """Generates an OpenAI SSE tool_calls chunk line for testing."""
    def _make(index: int = 0, call_id: str = "call_123", name: str = "", args: str = "", model: str = "deepseek-chat") -> str:
        tc = {"index": index, "id": call_id, "type": "function", "function": {}}
        if name:
            tc["function"]["name"] = name
        if args:
            tc["function"]["arguments"] = args
        c = {
            "id": "chatcmpl-test-chunk-123456",
            "object": "chat.completion.chunk",
            "created": 1786872000,
            "model": model,
            "system_fingerprint": "fp_deepseek_proxy_v1",
            "choices": [{"index": 0, "delta": {"tool_calls": [tc]}}]
        }
        return f"data: {json.dumps(c)}\n\n"
    return _make
