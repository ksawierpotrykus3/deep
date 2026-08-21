"""Tests for CloudflareBypasser timeout/retry logic and DeepSeekPOW concurrency & WASM memory deallocation."""
import time
import json
import base64
import threading
from unittest.mock import MagicMock
import pytest

from CloudflareBypasser import CloudflareBypasser
from pow import DeepSeekPOW, DeepSeekHash, WASM_PATH, _GLOBAL_ENGINE, _GLOBAL_MODULE


@pytest.mark.parametrize("title,expected", [
    ("", False),
    (None, False),
    ("   ", False),
    ("Just a moment...", False),
    ("JUST A MOMENT", False),
    ("Attention Required! | Cloudflare", False),
    ("Security Check Required", False),
    ("Cloudflare Ray ID: 12345", False),
    ("Turnstile verification", False),
    ("Chwileczkę...", False),
    ("CHWILECZKĘ", False),
    ("DeepSeek - Into the Unknown", True),
    ("Chat | DeepSeek", True),
    ("Login to DeepSeek", True),
])
def test_cloudflare_is_bypassed(title, expected):
    mock_driver = MagicMock()
    mock_driver.title = title
    bypasser = CloudflareBypasser(mock_driver, log=False)
    assert bypasser.is_bypassed() is expected


def test_cloudflare_is_bypassed_exception_handling():
    mock_driver = MagicMock()
    type(mock_driver).title = property(lambda self: (_ for _ in ()).throw(RuntimeError("Browser disconnected")))
    bypasser = CloudflareBypasser(mock_driver, log=False)
    assert bypasser.is_bypassed() is False


def test_cloudflare_bypasser_max_retries_termination(monkeypatch):
    """Weryfikuje, że pętla bypass() przerywa działanie po osiągnięciu max_retries i zwraca False."""
    mock_driver = MagicMock()
    mock_driver.title = "Just a moment..."
    
    monkeypatch.setattr(time, "sleep", lambda s: None)
    
    bypasser = CloudflareBypasser(mock_driver, max_retries=3, log=False)
    bypasser.click_verification_button = MagicMock()
    
    result = bypasser.bypass()
    
    assert result is False
    assert bypasser.click_verification_button.call_count == 3
    assert not bypasser.is_bypassed()


def test_cloudflare_bypasser_success():
    """Weryfikuje, że bypass() zwraca True, gdy strona nie jest zablokowana."""
    mock_driver = MagicMock()
    mock_driver.title = "DeepSeek"
    
    bypasser = CloudflareBypasser(mock_driver, log=False)
    bypasser.click_verification_button = MagicMock()
    
    result = bypasser.bypass()
    
    assert result is True
    assert bypasser.click_verification_button.call_count == 0


def test_cloudflare_bypasser_timeout_termination(monkeypatch):
    """Weryfikuje, że globalny timeout czasowy w bypass() przerywa pętlę i zwraca False."""
    mock_driver = MagicMock()
    mock_driver.title = "Just a moment..."
    
    monkeypatch.setattr(time, "sleep", lambda s: None)
    
    current_fake_time = [1000.0]
    def fake_time():
        t = current_fake_time[0]
        current_fake_time[0] += 30.0  # Każde sprawdzenie przesuwa zegar o 30s
        return t
        
    monkeypatch.setattr(time, "time", fake_time)
    
    bypasser = CloudflareBypasser(mock_driver, max_retries=0, log=False, timeout=120)
    assert bypasser.timeout == 120
    bypasser.click_verification_button = MagicMock()
    
    result = bypasser.bypass()
    
    # 0s (start=1000) -> 30s (t=1030, loop 1) -> 60s (t=1060, loop 2) -> 90s (t=1090, loop 3) -> 120s (t=1120, loop 4) -> 150s (t=1150 > 120 timeout, break)
    assert result is False
    assert not bypasser.is_bypassed()
    assert bypasser.click_verification_button.call_count == 4


def test_pow_wasm_singleton_module():
    """Weryfikuje, że singleton silnika i modułu WASM jest zainicjalizowany."""
    assert _GLOBAL_ENGINE is not None
    assert _GLOBAL_MODULE is not None
    
    hasher1 = DeepSeekHash().init(WASM_PATH)
    hasher2 = DeepSeekHash().init(WASM_PATH)
    assert hasher1.store is not hasher2.store  # Każda instancja ma swój lekki Store
    assert hasher1.instance is not hasher2.instance


def test_pow_wasm_memory_free_and_hash():
    """Weryfikuje poprawne obliczenie hasha PoW oraz brak błędów w bloku finally zwalniającym pamięć."""
    hasher = DeepSeekHash().init(WASM_PATH)
    
    config = {
        'algorithm': 'DeepSeekHashV1',
        'challenge': '281bd27e7cc70d5db64c3925a9aef489cbdaf3364e9b14ce0fb386e92ee81b84',
        'salt': '1aeac2ba2e6be2c048ca',
        'difficulty': 144000,
        'expire_at': 1787079523755
    }
    
    # Wielokrotne wywołanie calculate_hash — weryfikuje deterministyczny wynik i brak memory leaków
    for _ in range(5):
        answer = hasher.calculate_hash(
            config['algorithm'],
            config['challenge'],
            config['salt'],
            config['difficulty'],
            config['expire_at']
        )
        assert answer == 48634


def test_pow_thread_local_concurrency():
    """Weryfikuje równoległe rozwiązywanie wyzwań PoW przez wiele wątków z użyciem threading.local()."""
    pow_solver = DeepSeekPOW()
    
    config = {
        'algorithm': 'DeepSeekHashV1',
        'challenge': '281bd27e7cc70d5db64c3925a9aef489cbdaf3364e9b14ce0fb386e92ee81b84',
        'salt': '1aeac2ba2e6be2c048ca',
        'signature': '52b43869ab26f4c875ae14826caba08d81586c4856bccd2921d7b25666f77c0a',
        'difficulty': 144000,
        'expire_at': 1787079523755,
        'target_path': '/api/v0/chat/completion'
    }
    
    results = {}
    threads = []
    
    def worker(idx):
        encoded = pow_solver.solve_challenge(config)
        raw = base64.b64decode(encoded).decode()
        data = json.loads(raw)
        results[idx] = data
        
    for i in range(4):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join(timeout=10)
        
    assert len(results) == 4
    for i in range(4):
        assert results[i]['answer'] == 48634
        assert results[i]['algorithm'] == config['algorithm']
