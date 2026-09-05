import pytest
from unittest.mock import MagicMock, patch
import server
from server import DeepSeek, AccountPool, Session

def test_strip_tags_removes_previous_calls_tag():
    """BUG-029: </previous_calls> and similar tags must be stripped and not leak to user."""
    cases = [
        ("\n</previous_calls>\n", "\n\n"),
        ("<previous_calls>some calls</previous_calls>", "some calls"),
        ("Hello </previous_call> world", "Hello  world"),
        ("Start <previous_tool_calls> End", "Start  End"),
        ("</previous_calls>", ""),
    ]
    for raw, expected in cases:
        assert server._STRIP_TAGS.sub("", raw).strip() == expected.strip()

def test_auto_continue_does_not_fire_on_complete_tool_call():
    """BUG-029: Complete tool call must mark finished_normally=True and never trigger auto-continue."""
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = 'fake-token'
    mock_ses.user_agent = 'Mozilla/5.0'
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **kw: fn(*a, **kw)
    ds._get_pow = lambda idx: 'pow-sol'

    # Mock response that produces a complete tool call and natural EOF
    lines_data = [
        b'data: {"response_message_id": 2}',
        b'data: {"v": {"response": {"fragments": [{"type": "RESPONSE", "content": "<tool_call name=\\"Read\\"><parameter name=\\"file_path\\">test.md</parameter></tool_call>"}]}}}',
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.side_effect = lambda: iter(lines_data)

    with patch('server.requests.post', return_value=mock_resp):
        with patch.object(ds, 'stream_completion', wraps=ds.stream_completion) as spy_stream:
            gen, meta = ds.stream_completion(0, "sess-1", "prompt", parent_message_id=1, _auto_continue_budget=2)
            out = list(gen) # consume generator

            # stream_completion should be called only ONCE, never recursively with 'kontynuuj'
            calls = spy_stream.call_args_list
            assert len(calls) == 1
            assert meta["finished_normally"] is True

def test_auto_continue_fires_on_unclosed_tool_call_and_stops():
    """BUG-029: Unclosed tool call triggers auto-continue exactly once when budget=2, passing _auto_continue_budget=0 to child."""
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = 'fake-token'
    mock_ses.user_agent = 'Mozilla/5.0'
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **kw: fn(*a, **kw)
    ds._get_pow = lambda idx: 'pow-sol'

    # Stream 1: truncated tool call
    lines_data_1 = [
        b'data: {"response_message_id": 2}',
        b'data: {"v": {"response": {"fragments": [{"type": "RESPONSE", "content": "<tool_call name=\\"Read\\"><parameter name=\\"file_path\\">test.md"}]}}}',
    ]
    # Stream 2 (continue): closing tags
    lines_data_2 = [
        b'data: {"response_message_id": 3}',
        b'data: {"v": {"response": {"fragments": [{"type": "RESPONSE", "content": "</parameter></tool_call>"}]}}}',
    ]

    mock_resp_1 = MagicMock()
    mock_resp_1.status_code = 200
    mock_resp_1.iter_lines.side_effect = lambda: iter(lines_data_1)

    mock_resp_2 = MagicMock()
    mock_resp_2.status_code = 200
    mock_resp_2.iter_lines.side_effect = lambda: iter(lines_data_2)

    responses = [mock_resp_1, mock_resp_2]

    with patch('server.requests.post', side_effect=responses):
        with patch.object(ds, 'stream_completion', wraps=ds.stream_completion) as spy_stream:
            gen, meta = ds.stream_completion(0, "sess-1", "prompt", parent_message_id=1, _auto_continue_budget=2)
            out = list(gen)

            assert len(spy_stream.call_args_list) == 2
            # Second call must have prompt='kontynuuj' and _auto_continue_budget=0
            second_call = spy_stream.call_args_list[1]
            assert second_call.args[2] == "kontynuuj"
            assert second_call.kwargs.get("_auto_continue_budget") == 0
            assert meta["finished_normally"] is True

def test_leak_detector_catches_previous_calls():
    """BUG-029: _LEAK_DETECTOR must match any variation of previous_calls tags."""
    assert server._LEAK_DETECTOR.search("Here is </previous_calls>") is not None
    assert server._LEAK_DETECTOR.search("<previous_calls>") is not None
    assert server._LEAK_DETECTOR.search("<previous_call>") is not None
    assert server._LEAK_DETECTOR.search("</previous_tool_calls>") is not None