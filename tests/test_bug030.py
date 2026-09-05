import pytest
from unittest.mock import MagicMock, patch
import server
from server import DeepSeek, AccountPool, Session, _build_prompt

def test_stream_completion_retries_and_raises_on_0_data_lines():
    """BUG-030: 0 data lines received must retry and raise RuntimeError,"""
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = 'fake-token'
    mock_ses.user_agent = 'Mozilla/5.0'
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **gw: fn(*a, **gw)
    ds._get_pow = lambda idx: 'pow-sol'

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.side_effect = lambda: iter([])

    with patch('server.requests.post', return_value=mock_resp):
        with patch('time.sleep'):
            with pytest.raises(RuntimeError, match='DeepSeek empty stream'):
                ds.stream_completion(0, 'sess-1', 'prompt', parent_message_id=1, _auto_continue_budget=0)


def test_tool_deduplication_in_current_turn():
    """BUG-030: Multiple reads of the same file in current turn must keep first and deuplicate rest."""
    large_file_content = "1-> line 1\n2-> line 2\n" * 200
    messages = [
        {'role': 'user', 'content': 'Please read this'},
        {'role': 'assistant', 'content': '<tool_call name="Read">...</tool_call>'},
        {'role': 'tool', 'content': large_file_content},
        {'role': 'tool', 'content': large_file_content},
        {'role': 'tool', 'content': large_file_content},
    ]
    prompt = _build_prompt(messages)
    assert prompt.count('Zduplikowany wynik narzędzia') == 2
    assert len(prompt) < 10000
