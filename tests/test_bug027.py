import pytest
from unittest.mock import MagicMock, patch
import server
from server import DeepSeek, AccountPool, Session

class DummyResponse:
    def __init__(self, status_code=200, content=b'', json_data=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode('utf-8', errors='replace')
        self._json_data = json_data

    def json(self):
        if not self.content or not self.content.strip():
            import orjson
            raise orjson.JSONDecodeError('Input is a zero-length, empty document', 'doc', 0)
        if self._json_data is not None:
            return self._json_data
        import json
        return json.loads(self.content)

def test_create_session_retries_on_empty_response():
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = 'fake-token'
    mock_ses.user_agent = 'Mozilla/5.0'
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **kw: fn(*a, **kw)

    call_count = 0
    def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return DummyResponse(status_code=200, content=b'')
        return DummyResponse(
            status_code=200,
            content=b'{"data":{"biz_data":{"chat_session":{"id":"sess-123"}}}}',
            json_data={"data": {"biz_data": {"chat_session": {"id": "sess-123"}}}}
        )

    with patch.object(ds._http, 'post', side_effect=mock_post):
        with patch('time.sleep', return_value=None):
            sess_id = ds.create_session(0)
            assert sess_id == 'sess-123'
            assert call_count == 2

def test_create_session_raises_on_persistent_empty_body():
    mock_ap = MagicMock(spec=AccountPool)
    mock_ses = MagicMock(spec=Session)
    mock_ses.cookies = {}
    mock_ses.auth_token = 'fake-token'
    mock_ses.user_agent = 'Mozilla/5.0'
    mock_ap.slots = [mock_ses]

    ds = DeepSeek(mock_ap)
    ds._retry_on_network = lambda fn, *a, max_retries=3, **kw: fn(*a, **kw)

    with patch.object(ds._http, 'post', return_value=DummyResponse(status_code=200, content=b'')):
        with patch('time.sleep', return_value=None):
            with pytest.raises(RuntimeError, match='Empty response body'):
                ds.create_session(0)

def test_create_session_with_fallback_switches_account():
    mock_ap = MagicMock(spec=AccountPool)
    mock_ap.is_valid.side_effect = lambda idx: idx in (0, 1)

    ds = DeepSeek(mock_ap)

    def mock_create(account_idx):
        if account_idx == 0:
            raise RuntimeError('Account 0 failed: Empty response body')
        return 'sess-from-account-1'

    with patch.object(ds, 'create_session', side_effect=mock_create):
        sid, actual_idx = ds.create_session_with_fallback(0)
        assert sid == 'sess-from-account-1'
        assert actual_idx == 1

def test_create_session_with_fallback_all_fail():
    mock_ap = MagicMock(spec=AccountPool)
    mock_ap.is_valid.side_effect = lambda idx: idx in (0, 1)

    ds = DeepSeek(mock_ap)

    with patch.object(ds, 'create_session', side_effect=RuntimeError('Service unavailable')):
        with pytest.raises(RuntimeError, match='All accounts failed'):
            ds.create_session_with_fallback(0)

@pytest.mark.asyncio
async def test_generate_stream_does_not_raise_unbound_local_error():
    '''Verify that generate() can start and access account_idx without UnboundLocalError.'''
    from starlette.requests import Request
    from server import ChatRequest, _chat_completions_impl

    scope = {
        'type': 'http',
        'method': 'POST',
        'headers': [(b'content-type', b'application/json')],
    }
    raw_req = Request(scope)
    raw_req._body = b'{}'
    req = ChatRequest(
        model='deepseek-chat',
        messages=[{'role': 'user', 'content': 'ping'}],
        stream=True
    )

    with patch('server.ds.create_session_with_fallback', return_value=('test-sess', 0)):
        with patch('server.ds.stream_completion', return_value=(iter([]), {'resp_msg_id': 1})):
            with patch('server._ensure_slot'):
                resp = _chat_completions_impl(req, raw_req)
                gen = resp.body_iterator
                first_chunk = await anext(gen)
                assert 'role' in first_chunk

