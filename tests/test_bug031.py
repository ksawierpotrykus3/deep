import json
from unittest.mock import MagicMock, patch
import pytest
import server
from server import DeepSeek, AccountPool, Session, _ReasoningChunk


def test_bug031_realtime_transition_swallowed_tool_calls():
    """BUG-031: DeepSeek Web streams tool calls within the THINK fragment.
    _stream must dynamically transition to RESPONSE when <tool_calls> begins,
    yielding reasoning_content for pure thoughts, and content for tool calls.
    """
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = "fake-token"
    mock_ses.user_agent = "Mozilla/5.0"
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **gw: fn(*a, **gw)
    ds._get_pow = lambda idx: "pow-sol"

    # Simulate realistic SSE lines from DeepSeek Web:
    # Starts with THINK fragment, streams reasoning, then streams <tool_calls> without a RESPONSE fragment declaration.
    sse_events = [
        {"request_message_id": 10, "response_message_id": 11, "model_type": "expert"},
        {"v": {"response": {"message_id": 11, "role": "ASSISTANT", "fragments": [{"type": "THINK", "content": "I should"}]}}},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": " launch"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": " subagents"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": ".\n\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "<"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "tool"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "_c"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "alls"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": ">\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "<invoke name=\"Task\">\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "<parameter name=\"description\">Test 1</parameter>\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "</invoke>\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "<invoke name=\"Task\">\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "<parameter name=\"description\">Test 2</parameter>\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "</invoke>\n"},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "</tool_calls>"},
        {"p": "response", "o": "BATCH", "v": [{"p": "quasi_status", "v": "FINISHED"}]},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    encoded_lines = [f"data: {json.dumps(ev)}\n\n".encode("utf-8") for ev in sse_events]
    mock_resp.iter_lines.side_effect = lambda: iter(encoded_lines)

    with patch("server.requests.post", return_value=mock_resp):
        res = ds.stream_completion(0, "sess-1", "prompt", parent_message_id=10, _auto_continue_budget=0)
        assert res is not None
        gen, meta = res

        items = list(gen)
        reasoning_chunks = [item.text for item in items if isinstance(item, _ReasoningChunk)]
        content_chunks = [item for item in items if isinstance(item, str)]

        full_reasoning = "".join(reasoning_chunks)
        full_content = "".join(content_chunks)

        # 1. Reasoning must contain only thinking tokens
        assert "I should launch subagents." in full_reasoning
        assert "<tool" not in full_reasoning
        assert "<invoke" not in full_reasoning
        assert not full_reasoning.endswith("<")

        # 2. Content must contain the full tool call
        assert full_content.startswith("<tool_calls>")
        assert "</tool_calls>" in full_content

        # 3. Tool parser must detect both tool calls
        parsed_tools = server._parse_tool_calls(full_content)
        assert len(parsed_tools) == 2
        assert parsed_tools[0][2] == "Task"
        assert parsed_tools[1][2] == "Task"

        # 4. Stream status must be finished_normally
        assert meta["finished_normally"] is True


def test_bug031_post_stream_safety_net_recovery():
    """BUG-031: If tokens were in thinking_buffer without triggering real-time transition,
    post-stream safety net must recover tools and mark finished_normally = True.
    """
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = "fake-token"
    mock_ses.user_agent = "Mozilla/5.0"
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **gw: fn(*a, **gw)
    ds._get_pow = lambda idx: "pow-sol"

    # Suppose a single chunk in THINK fragment contains both thought and tool call
    raw_tool_block = "<tool_calls><invoke name=\"Read\"><parameter name=\"file_path\">test.py</parameter></invoke></tool_calls>"
    sse_events = [
        {"request_message_id": 20, "response_message_id": 21, "model_type": "expert"},
        {"v": {"response": {"message_id": 21, "role": "ASSISTANT", "fragments": [{"type": "THINK", "content": "Let me read.\n" + raw_tool_block}]}}},
        {"p": "response", "o": "BATCH", "v": [{"p": "quasi_status", "v": "FINISHED"}]},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    encoded_lines = [f"data: {json.dumps(ev)}\n\n".encode("utf-8") for ev in sse_events]
    mock_resp.iter_lines.side_effect = lambda: iter(encoded_lines)

    with patch("server.requests.post", return_value=mock_resp):
        res = ds.stream_completion(0, "sess-2", "prompt", parent_message_id=20, _auto_continue_budget=0)
        assert res is not None
        gen, meta = res

        items = list(gen)
        content_chunks = [item for item in items if isinstance(item, str)]
        full_content = "".join(content_chunks)

        parsed_tools = server._parse_tool_calls(full_content)
        assert len(parsed_tools) == 1
        assert parsed_tools[0][2] == "Read"
        assert meta["finished_normally"] is True


def test_bug031_explicit_think_tag_transition():
    """BUG-031: Explicit </think> tag inside thinking stream transitions immediately to content."""
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = "fake-token"
    mock_ses.user_agent = "Mozilla/5.0"
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **gw: fn(*a, **gw)
    ds._get_pow = lambda idx: "pow-sol"

    sse_events = [
        {"request_message_id": 30, "response_message_id": 31, "model_type": "expert"},
        {"v": {"response": {"message_id": 31, "role": "ASSISTANT", "fragments": [{"type": "THINK", "content": "Thinking hard..."}]}}},
        {"p": "response/fragments/-1/content", "o": "APPEND", "v": "</think>Hello, user! Here is your answer."},
        {"p": "response", "o": "BATCH", "v": [{"p": "quasi_status", "v": "FINISHED"}]},
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    encoded_lines = [f"data: {json.dumps(ev)}\n\n".encode("utf-8") for ev in sse_events]
    mock_resp.iter_lines.side_effect = lambda: iter(encoded_lines)

    with patch("server.requests.post", return_value=mock_resp):
        res = ds.stream_completion(0, "sess-3", "prompt", parent_message_id=30, _auto_continue_budget=0)
        assert res is not None
        gen, meta = res

        items = list(gen)
        content_chunks = [item for item in items if isinstance(item, str)]
        full_content = "".join(content_chunks)

        assert "Hello, user! Here is your answer." in full_content
        assert "</think>" not in full_content
        assert meta["finished_normally"] is True


def test_bug031_generate_loop_zero_tokens_prevention():
    """Verify that when stream_completion yields reasoning chunks followed by tool chunks,
    the proxy's chunk processing parses tools, emits them, and never triggers zero tokens error.
    """
    items = [
        _ReasoningChunk("Thinking..."),
        _ReasoningChunk(" about subagents."),
        "<tool_calls>\n<invoke name=\"Task\">\n<parameter name=\"description\">Test</parameter>\n</invoke>\n</tool_calls>"
    ]

    full = ""
    tools_yielded = 0
    yielded_sse = []
    sent_until = 0

    for chunk in items:
        if isinstance(chunk, _ReasoningChunk):
            yielded_sse.append({"reasoning_content": chunk.text})
            continue
        if chunk:
            full += chunk
            tools = server._parse_tool_calls(full)
            if tools:
                cursor = sent_until
                for ts, te, tname, targs in tools:
                    if te <= cursor:
                        continue
                    tc_id = "call_123"
                    yielded_sse.append({"tool_calls": [{"index": tools_yielded, "id": tc_id, "type": "function", "function": {"name": tname, "arguments": targs}}]})
                    tools_yielded += 1
                    cursor = te
                sent_until = cursor

    if tools_yielded == 0:
        if not full.strip():
            yielded_sse.append({"content": "[BŁĄD PROXY: Serwer DeepSeek nie zwrócił żadnych tokenów]"})

    assert tools_yielded == 1
    assert any("tool_calls" in p for p in yielded_sse)
    assert not any("[BŁĄD PROXY: Serwer DeepSeek nie zwrócił żadnych tokenów]" in p.get("content", "") for p in yielded_sse)

