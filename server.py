import json, time, uuid, re, hashlib, threading, os, base64, random, sys, io
from pathlib import Path

# Ensure UTF-8 stdout/stderr on Windows to avoid UnicodeEncodeError crashes safely in-place
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from curl_cffi import requests
from dataclasses import dataclass
from pow import DeepSeekPOW
from debounce import (
    record_tool_call,
    deduplicate_tool_results_in_prompt, extract_goals_from_messages, format_goals_context,
)
from official_api import official_api
from subagent_isolation import (
    record_subagent_start, record_subagent_done, get_subagent_stats,
)
from conversation_tracker import (
    build_conversation_summary, get_rotation_warning,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

CONV_STATE_FILE = Path(__file__).parent / "conv_state.json"
MAX_ACCOUNTS = 100
MAX_CONV_ENTRIES = 25
MODE_FILE = Path(__file__).parent / "data" / "proxy_mode.txt"
PROMPT2_FILE = Path(__file__).parent / "prompt2.txt"
PROMPT3_FILE = Path(__file__).parent / "prompt3.txt"

# ==============================================================================
#                     USTAWIENIA TRYBÓW PROXY (DLA UŻYTKOWNIKA)
#  Tutaj możesz zmienić True / False dla domyślnego zachowania proxy:
# ==============================================================================

# --- 1. TRYB SZYBKI [⚡ Szybki] (DeepSeek-V4-Flash) ---
SZYBKI_MYSLEKIE   = True    # True = włącz głębokie myślenie [⚛️], False = szybka odpowiedź bez myślenia
SZYBKI_SZUKANIE   = False   # True = włącz wyszukiwanie w necie [🌐], False = wyłącz

# --- 2. TRYB EKSPERT [💎 Ekspert] (DeepSeek-V4-Pro) ---
EKSPERT_MYSLEKIE  = True    # True = włącz głębokie myślenie [⚛️] (zalecane do kodowania)
EKSPERT_SZUKANIE  = False   # True = włącz wyszukiwanie w necie, False = wyłącz

# --- 3. TRYB WIZJA [🖼️ Wizja] (DeepSeek-Vision) ---
WIZJA_MYSLEKIE    = False   # True = myślenie przy analizie obrazów, False = szybka analiza
# ==============================================================================


def _get_mode() -> str:
    """Returns 'auto', 'web', 'free', 'biedny', or 'free_first'."""
    try:
        if MODE_FILE.exists():
            mode = MODE_FILE.read_text().strip().lower()
            if mode in ("auto", "web", "free", "biedny", "free_first"):
                return mode
    except Exception:
        pass
    return "auto"


def _set_mode(mode: str):
    """Set proxy mode. Valid values: auto, web, free, biedny, free_first."""
    mode = mode.lower().strip()
    if mode not in ("auto", "web", "free", "biedny", "free_first"):
        raise ValueError(f"Invalid mode: {mode}. Use auto, web, free, biedny, or free_first.")
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODE_FILE.write_text(mode)
    print(f"[MODE] Switched to '{mode}'", flush=True)


def _clean_mode_enabled() -> bool:
    """True gdy tryb czysty wlaczony przy starcie (--clean lub env)."""
    return os.environ.get("DEEPSEEK_PROXY_CLEAN") == "1" or "--clean" in sys.argv


def _get_clean_prompt() -> str:
    """Czyta prompt2.txt — wlasny prompt uzytkownika dla trybu czystego (moze byc pusty)."""
    try:
        if PROMPT2_FILE.exists():
            return PROMPT2_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _get_search_vision_prompt() -> str:
    """Czyta prompt3.txt — wlasny prompt uzytkownika dla trybow Search i Vision (moze byc pusty)."""
    try:
        if PROMPT3_FILE.exists():
            return PROMPT3_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


@dataclass
class Session:
    auth_token: str
    cookies: dict
    user_agent: str = ""
    created_at: float = 0.0
    last_validated_at: float = 0.0


class AccountPool:
    def __init__(self):
        self.slots: list[Session | None] = [None] * MAX_ACCOUNTS
        self._migrate_old_session()
        self._load_all()

    def _slot_path(self, idx: int) -> Path:
        return Path(__file__).parent / f"session_{idx}.json"

    def _migrate_old_session(self):
        old = Path(__file__).parent / "session.json"
        if old.exists() and not self._slot_path(0).exists():
            try:
                old.rename(self._slot_path(0))
                print("[MIGRATE] session.json -> session_0.json", flush=True)
            except Exception:
                pass

    def _load_all(self):
        for i in range(MAX_ACCOUNTS):
            try:
                p = self._slot_path(i)
                if p.exists():
                    self.slots[i] = Session(**json.loads(p.read_text()))
            except Exception:
                pass

    def save(self, idx: int):
        s = self.slots[idx]
        if s:
            self._slot_path(idx).write_text(json.dumps({
                "auth_token": s.auth_token, "cookies": s.cookies,
                "user_agent": s.user_agent, "created_at": s.created_at,
                "last_validated_at": s.last_validated_at,
            }, indent=2))

    def is_valid(self, idx: int) -> bool:
        if 0 <= idx < MAX_ACCOUNTS and self.slots[idx] is None:
            p = self._slot_path(idx)
            if p.exists():
                try:
                    self.slots[idx] = Session(**json.loads(p.read_text()))
                except Exception:
                    pass
        return self.slots[idx] is not None and bool(self.slots[idx].auth_token)

    def any_valid(self) -> bool:
        return any(self.is_valid(i) for i in range(MAX_ACCOUNTS))

    def open_slot(self) -> int | None:
        for i in range(MAX_ACCOUNTS):
            if self.slots[i] is None:
                return i
        return None

    def pick_for_conv(self, conv_key: str | None = None, is_subagent: bool = False) -> int:
        """Pick least-loaded account for a new conversation, prioritizing non-busy slots."""
        now = time.time()
        counts = [0] * MAX_ACCOUNTS
        with _conv_lock:
            for v in _conv_state.values():
                a = v.get("account", -1)
                if 0 <= a < MAX_ACCOUNTS:
                    counts[a] += 1
        valid = [i for i in range(MAX_ACCOUNTS) if self.is_valid(i) and now >= _rate_limited_until[i]]
        if not valid:
            valid = [i for i in range(MAX_ACCOUNTS) if self.is_valid(i)]
        if not valid:
            valid = [i for i in range(MAX_ACCOUNTS) if self.slots[i] is not None]
        if not valid:
            valid = list(range(MAX_ACCOUNTS))

        # Priorytet dla slotów, które NIE są aktualnie zajęte strumieniowaniem
        try:
            with _slot_busy_lock:
                free_valid = [i for i in valid if not _slot_busy[i]]
        except Exception:
            free_valid = []

        if free_valid:
            return min(free_valid, key=lambda i: counts[i])
        return min(valid, key=lambda i: counts[i])

    def reset_slot(self, idx: int):
        self.slots[idx] = None
        p = self._slot_path(idx)
        if p.exists():
            p.unlink()

    def clear_conv_state(self):
        global _conv_state
        # Backup before clearing (zabezpieczenie przed przypadkową utratą stanu)
        if _conv_state:
            try:
                backup_path = CONV_STATE_FILE.with_suffix(".backup.json")
                import shutil
                if CONV_STATE_FILE.exists():
                    shutil.copy2(CONV_STATE_FILE, backup_path)
                    print(f"[CONV] Backup saved to {backup_path}", flush=True)
            except Exception as e:
                print(f"[CONV] Backup failed: {e}", flush=True)
        _conv_state.clear()
        try:
            CONV_STATE_FILE.write_text("{}")
        except Exception:
            pass


def _detect_loop(content_buffer: str, min_len: int = 500, window: int = 1500) -> bool:
    """Wykrywa wyłącznie rzeczywiste, patologiczne zapętlenia całych zdań/linii generowanych pod rząd (consecutive loops).
    NIGDY nie fałszuje alarmu przy równoległych wywołaniach wielu narzędzi o zbliżonych ścieżkach katalogowych.
    """
    if len(content_buffer) < min_len:
        return False
    tail = content_buffer[-window:]
    for chunk_size in range(10, 201):
        if len(tail) < chunk_size * 3:
            continue
        c1 = tail[-chunk_size:]
        c2 = tail[-2*chunk_size:-chunk_size]
        c3 = tail[-3*chunk_size:-2*chunk_size]
        if c1 == c2 == c3 and len(c1.strip()) > 3:
            print(f"[LOOP GUARD] Detected exact repeating chunk ({len(c1)} chars) -> aborting", flush=True)
            return True
    return False


_HEARTBEAT_SENTINEL = object()


def _heartbeat_iter(gen, interval: float = 15.0):
    """Bug 26: utrzymuje zywe polaczenie SSE z Trae podczas dlugiego myslenia.

    Generator `gen` (strumien chunkow tekstu z DeepSeeka) jest czytany w tle.
    Gdy przez `interval` sekund nie przyjdzie zaden chunk, zwraca sentinel
    _HEARTBEAT_SENTINEL, zeby warstwa wyzsza wyslala pusty komentarz SSE
    ': keep-alive' (ignorowany przez klientow, ale nie pozwala posrednim
    warstwom/Trae zerwac bezczynnego polaczenia). Chunki przechodza 1:1,
    wyjatki z `gen` sa propagowane.
    """
    import queue as _queue
    import threading as _threading

    q = _queue.Queue()

    def reader():
        try:
            for item in gen:
                q.put(("data", item))
            q.put(("end", None))
        except Exception as e:
            q.put(("error", e))

    _threading.Thread(target=reader, daemon=True).start()
    while True:
        try:
            kind, val = q.get(timeout=interval)
        except _queue.Empty:
            yield _HEARTBEAT_SENTINEL
            continue
        if kind == "data":
            yield val
        elif kind == "end":
            break
        elif kind == "error":
            raise val


def _has_unclosed_tool_call(text: str) -> bool:
    """Deterministycznie sprawdza, czy w buforze znajduje się otwarty, ale niedomknięty tag narzędzia.
    NIGDY nie fałszuje alarmu, gdy model domknął wszystkie wewnętrzne <invoke>...</invoke>, ale pominął zewnętrzny <tool_calls>.
    """
    if not text:
        return False

    # 1. Rzeczywiste tagi wywołania pojedynczego narzędzia (invoke / tool_call / call)
    open_invokes = len(re.findall(r'<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)?(?:tool_call|invoke|tool_capability|_call|call)\b[^>]*>', text, re.IGNORECASE))
    close_invokes = len(re.findall(r'</\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)?(?:tool_call|invoke|tool_capability|_call|call)\s*>', text, re.IGNORECASE))
    if open_invokes > close_invokes:
        return True

    # 2. Rzeczywiste tagi parametrów pojedynczego narzędzia
    open_params = len(re.findall(r'<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)?parameter\b[^>]*>', text, re.IGNORECASE))
    close_params = len(re.findall(r'</\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)?parameter\s*>', text, re.IGNORECASE))
    if open_params > close_params:
        return True

    # 3. Format natywny DeepSeek (<｜tool call begin｜> ... <｜tool call end｜>)
    native_opens = len(re.findall(r'<[|｜\uff5c\s]*tool\s*call\s*begin[|｜\uff5c\s]*>', text, re.IGNORECASE))
    native_closes = len(re.findall(r'<[|｜\uff5c\s]*tool\s*call\s*end[|｜\uff5c\s]*>', text, re.IGNORECASE))
    if native_opens > native_closes:
        return True

    # 4. Urwany znacznik na samym końcu bufora (np. "<｜｜DSML｜｜inv")
    tail = text[-100:]
    if re.search(r'<\s*(?:[|\uff5c\u2502\s]*DSML|[|\uff5c\u2502\s]*tool|\w+:\w+)[^>]*$', tail, re.IGNORECASE):
        return True

    return False


class DeepSeek:
    # Klasy błędów sieciowych do retry (importowane dynamicznie dla izolacji)
    _NETWORK_ERRORS = None

    @classmethod
    def _get_network_errors(cls):
        if cls._NETWORK_ERRORS is None:
            from curl_cffi.requests.exceptions import (
                ConnectionError as CurlConnectionError,
                DNSError, ProxyError, SSLError, Timeout,
            )
            cls._NETWORK_ERRORS = (CurlConnectionError, DNSError, ProxyError, SSLError, Timeout)
        return cls._NETWORK_ERRORS

    def _retry_on_network(self, fn, *args, max_retries=3, **kwargs):
        """Wywołaj fn() z retry na błędach sieciowych (DNS, timeout, connection)."""
        import time as _time
        last_err = None
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except self._get_network_errors() as e:
                last_err = e
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 3  # 3s, 6s, 9s
                    print(f"[NET RETRY] {type(e).__name__}: {e} — waiting {wait}s (attempt {attempt+1}/{max_retries})", flush=True)
                    _time.sleep(wait)
                else:
                    raise
        raise last_err  # never reached

    def __init__(self, ap: AccountPool):
        self.ap = ap
        self.pow = DeepSeekPOW()
        self._cached_pow: dict[int, str] = {}
        self._pow_expires: dict[int, float] = {}
        self._pow_lock = threading.Lock()
        self._http = requests.Session()
        self._http.headers.update({"accept": "*/*", "content-type": "application/json", "origin": "https://chat.deepseek.com", "referer": "https://chat.deepseek.com/", "x-client-bundle-id": "com.deepseek.chat", "x-client-locale": "pl", "x-client-platform": "web", "x-client-timezone-offset": "7200", "x-client-version": "2.3.0"})

    def _ses(self, idx: int) -> Session:
        s = self.ap.slots[idx]
        if s is None:
            raise RuntimeError(f"Account slot {idx} not logged in")
        return s

    def _headers(self, account_idx: int, pow_resp: str | None = None) -> dict:
        s = self._ses(account_idx)
        h = {
            "accept": "*/*",
            "authorization": f"Bearer {s.auth_token}",
            "content-type": "application/json",
            "origin": "https://chat.deepseek.com",
            "referer": "https://chat.deepseek.com/",
            "user-agent": s.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "pl",
            "x-client-platform": "web",
            "x-client-timezone-offset": "7200",
            "x-client-version": "2.3.0",
        }
        if pow_resp:
            h["x-ds-pow-response"] = pow_resp
        return h

    def _get_challenge(self, account_idx: int) -> dict:
        s = self._ses(account_idx)
        r = self._http.post(
            "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
            headers=self._headers(account_idx),
            json={"target_path": "/api/v0/chat/completion"},
            cookies=s.cookies,
            impersonate="chrome120",
            timeout=30,
        )
        return r.json()["data"]["biz_data"]["challenge"]

    def _get_pow(self, account_idx: int) -> str:
        now = time.time()
        with self._pow_lock:
            cached = self._cached_pow.get(account_idx)
            if cached and now < self._pow_expires.get(account_idx, 0):
                return cached
        challenge = self._get_challenge(account_idx)
        t0 = time.time()
        pow_resp = self.pow.solve_challenge(challenge)
        elapsed = time.time() - t0
        print(f"[POW] account={account_idx} solved in {elapsed:.1f}s (difficulty={challenge.get('difficulty')})", flush=True)
        with self._pow_lock:
            self._cached_pow[account_idx] = pow_resp
            self._pow_expires[account_idx] = challenge.get("expire_at", 0) / 1000  # DeepSeek returns ms
        # Pre-fetch next PoW in background for future retries
        threading.Thread(target=self._prefetch_pow, args=(account_idx,), daemon=True).start()
        return pow_resp

    def _get_upload_pow(self, account_idx: int) -> str:
        s = self._ses(account_idx)
        r = self._http.post(
            "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
            headers=self._headers(account_idx),
            json={"target_path": "/api/v0/file/upload_file"},
            cookies=s.cookies,
            impersonate="chrome120",
            timeout=30,
        )
        challenge = r.json()["data"]["biz_data"]["challenge"]
        return self.pow.solve_challenge(challenge)

    def upload_file(self, account_idx: int, file_data: bytes, filename: str, mime_type: str = "image/png") -> str:
        """Upload an image file to DeepSeek and return the file_id."""
        from curl_cffi import CurlMime
        pow_resp = self._get_upload_pow(account_idx)
        mp = CurlMime.from_list([
            {
                "name": "file",
                "content_type": mime_type,
                "filename": filename,
                "data": file_data,
            }
        ])
        try:
            h = self._headers(account_idx)
            h.pop("content-type", None)
            h["x-ds-pow-response"] = pow_resp
            r = requests.post(
                "https://chat.deepseek.com/api/v0/file/upload_file",
                headers=h,
                multipart=mp,
                cookies=self._ses(account_idx).cookies,
                impersonate="chrome120",
                timeout=60,
            )
        finally:
            mp.close()
        raw = r.text[:1000]
        if r.status_code != 200:
            raise Exception(f"DeepSeek file upload error {r.status_code}: {raw}")
        if not raw.strip():
            raise Exception("DeepSeek file upload returned empty response (status 200)")
        try:
            data = r.json()
        except Exception:
            raise Exception(f"DeepSeek file upload non-JSON response (status 200): {raw}")
        if data.get("code") != 0:
            raise Exception(f"DeepSeek file upload returned error code: {raw}")
        file_id = (
            data.get("data", {}).get("biz_data", {}).get("id")
            or data.get("data", {}).get("id")
            or data.get("data", {}).get("file_id")
            or data.get("id")
        )
        if not file_id:
            raise Exception(f"DeepSeek file upload missing id: {raw}")
        file_id = str(file_id)

        # Wait for file parsing to complete (status == 'SUCCESS')
        s = self._ses(account_idx)
        for _ in range(15):
            try:
                r_info = requests.get(
                    f"https://chat.deepseek.com/api/v0/file/fetch_files?file_ids={file_id}",
                    headers=self._headers(account_idx),
                    cookies=s.cookies,
                    impersonate="chrome120",
                    timeout=15,
                )
                if r_info.status_code == 200:
                    files = r_info.json().get("data", {}).get("biz_data", {}).get("files", [])
                    if files:
                        st = files[0].get("status")
                        if st == "SUCCESS":
                            print(f"[VISION] File {file_id} parsed successfully (SUCCESS)", flush=True)
                            break
                        elif st == "FAILED":
                            print(f"[VISION] Warning: file {file_id} status FAILED", flush=True)
                            break
            except Exception:
                pass
            time.sleep(1)
        return file_id

    def _prefetch_pow(self, account_idx: int):
        """Solve a fresh PoW challenge in the background and cache it."""
        try:
            challenge = self._get_challenge(account_idx)
            pow_resp = self.pow.solve_challenge(challenge)
            expiry_s = challenge.get("expire_at", 0) / 1000  # DeepSeek returns ms
            if expiry_s > time.time() + 5:  # only cache if it'll still be valid
                with self._pow_lock:
                    self._cached_pow[account_idx] = pow_resp
                    self._pow_expires[account_idx] = expiry_s
                print(f"[POW] prefetched for account={account_idx} (expires in {int(expiry_s-time.time())}s)", flush=True)
        except Exception as e:
            print(f"[POW] prefetch failed for account={account_idx}: {e}", flush=True)

    def create_session(self, account_idx: int) -> str:
        s = self._ses(account_idx)
        def _do():
            return self._http.post(
                "https://chat.deepseek.com/api/v0/chat_session/create",
                headers=self._headers(account_idx),
                json={"character_id": None},
                cookies=s.cookies,
                impersonate="chrome120",
                timeout=30,
            )
        r = self._retry_on_network(_do, max_retries=3)
        resp_json = r.json()
        print(f"[CREATE SESSION] account={account_idx} status={r.status_code} response={json.dumps(resp_json, ensure_ascii=False)[:500]}", flush=True)
        data = resp_json.get("data")
        if data is None:
            raise RuntimeError(f"Create session failed: {json.dumps(resp_json, ensure_ascii=False)[:300]}")
        return data["biz_data"]["chat_session"]["id"]

    def stream_completion(self, account_idx: int, chat_session_id: str, prompt: str,
                          parent_message_id: int | None = None,
                          max_tokens: int = 8192, temperature: float = 1.0, top_p: float = 1.0,
                          model_type: str = "expert", ref_file_ids: list[str] | None = None,
                          thinking_enabled: bool = True, search_enabled: bool = False,
                          _retry: int = 0, _auto_continue_budget: int = 2):
        if _retry > 0:
            print(f"[RETRY] Attempt {_retry} for session={chat_session_id[:12]}...", flush=True)
        from curl_cffi.requests.exceptions import RequestException as CurlError
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                pow_resp = self._get_pow(account_idx)
                s = self._ses(account_idx)

                r = requests.post(
                    "https://chat.deepseek.com/api/v0/chat/completion",
                    headers=self._headers(account_idx, pow_resp),
                    json={
                        "chat_session_id": chat_session_id,
                        "parent_message_id": parent_message_id,
                        "model_type": model_type,
                        "prompt": prompt,
                        "ref_file_ids": ref_file_ids or [],
                        "thinking_enabled": thinking_enabled,
                        "search_enabled": search_enabled,
                        "action": None,
                        "preempt": False,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "top_p": top_p,
                    },
                    cookies=s.cookies,
                    impersonate="chrome120",
                    stream=True,
                    timeout=300,
                )
                break
            except CurlError as e:
                if attempt < max_retries:
                    print(f"[RETRY] curl error (attempt {attempt+1}/{max_retries}): {e}", flush=True)
                    time.sleep(5)
                    continue
                raise

        if r.status_code == 401:
            return None
        if r.status_code != 200:
            error_text = next(r.iter_lines(), b"").decode("utf-8", "ignore")
            raise Exception(f"DeepSeek API error {r.status_code}: {error_text}")

        it = r.iter_lines()

        # ── Moduł 1: Watchdog bezczynności (definicja PRZED preambułą) ──
        def _iter_lines_with_watchdog(generator, timeout_sec=180.0):
            import queue
            import threading
            q = queue.Queue()
            stop_ev = threading.Event()

            def reader():
                try:
                    for item in generator:
                        if stop_ev.is_set():
                            break
                        q.put(("data", item))
                    q.put(("end", None))
                except Exception as e:
                    q.put(("error", e))

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            while True:
                try:
                    kind, val = q.get(timeout=timeout_sec)
                    if kind == "data":
                        yield val
                    elif kind == "end":
                        break
                    elif kind == "error":
                        raise val
                except queue.Empty:
                    print(f"[WATCHDOG] Inactivity timeout ({timeout_sec}s) on account={account_idx} -> terminating stalled stream gracefully", flush=True)
                    stop_ev.set()
                    break

        # Preambuła objęta watchdogiem: zero danych przez 180s kończy czekanie zamiast
        # wisieć do 300s (LOW_SPEED_TIME curl_cffi = timeout=300) na martwym sockecie.
        watchdog_it = _iter_lines_with_watchdog(it, timeout_sec=180.0)
        resp_msg_id: str | int | None = ""
        pre_lines: list[bytes] = []
        rate_limit_detected = False
        preamble_data_count = 0
        for line in watchdog_it:
            pre_lines.append(line)
            if not line:
                continue
            decoded = line.decode("utf-8", "ignore")
            if decoded.startswith("data: "):
                preamble_data_count += 1
                try:
                    d = json.loads(decoded[6:])
                    if d.get("type") == "error":
                        err = d.get("content", "Unknown error")
                        print(f"[ERROR] DeepSeek error: {err}", flush=True)
                        if "length limit" in err.lower() or "start a new chat" in err.lower() or "context_length" in err.lower() or "content is too long" in err.lower() or "input_exceeds_limit" in err.lower():
                            raise RuntimeError(f"DeepSeek error: {err}")
                        rate_limit_detected = True
                        break
                    rid = d.get("response_message_id")
                    if rid is not None:
                        resp_msg_id = str(rid)
                        break
                except json.JSONDecodeError:
                    pass
        if preamble_data_count == 0 and pre_lines:
            raw_body = b"".join(pre_lines).decode("utf-8", "ignore")
            if "INVALID_POW_RESPONSE" in raw_body:
                print(f"[POW] INVALID_POW_RESPONSE (attempt {_retry+1}) â€“ clearing PoW cache and retrying...", flush=True)
                with self._pow_lock:
                    self._cached_pow.pop(account_idx, None)
                    self._pow_expires.pop(account_idx, 0)
                return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1)

        if rate_limit_detected:
            _rate_limited_until[account_idx] = time.time() + 120
            if _retry >= 1:
                print(f"[RETRY] Preamble rate-limited on account={account_idx}, giving up fast to migrate", flush=True)
                raise RuntimeError(f"DeepSeek busy after {_retry+1} retries: preamble rate-limited")
            wait = 60 + random.randint(-10, 15)
            _rate_limited_until[account_idx] = time.time() + wait + 10
            print(f"[RETRY] Preamble rate-limited (attempt {_retry+1}), waiting {wait}s...", flush=True)
            time.sleep(wait)
            return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1)
        resp_msg_id = int(resp_msg_id) if resp_msg_id else None
        if preamble_data_count == 0:
            print(f"[WARN] No data lines from DeepSeek for session={chat_session_id} parent={parent_message_id}", flush=True)
        elif resp_msg_id is None:
            print(f"[WARN] No response_message_id in {preamble_data_count} data lines for session={chat_session_id}", flush=True)

        from itertools import chain
        remaining_it = watchdog_it  # wznowienie po preambule (watchdog już aktywny)
        result_meta: dict = {"resp_msg_id": resp_msg_id}

        def _stream():
            nonlocal resp_msg_id
            nonlocal _auto_continue_budget
            content_buffer = ""   # wyłącznie faza RESPONSE — to, co idzie do Trae
            thinking_buffer = ""  # wyłącznie faza THINK — reasoning, NIE idzie do Trae
            response_started = False
            thinking_active = False   # True gdy DeepSeek zadeklarował fragment THINK (myślenie)
            prev_yielded = 0
            raw_count = 0
            finished_normally = False

            def _route_token(text):
                """Kieruje token treści do właściwego bufora na podstawie fazy.
                Zwraca treść do yieldowania (tylko faza RESPONSE) lub ''."""
                nonlocal content_buffer, thinking_buffer, response_started, thinking_active, prev_yielded
                if not text:
                    return ""
                if not response_started and not thinking_active:
                    # Brak deklaracji fazy = tryb bez myślenia (lub starszy format):
                    # bare tokeny to RESPONSE. Myślenie jest tłumione TYLKO gdy
                    # DeepSeek jawnie zadeklarował fragment THINK przed tokenami.
                    response_started = True
                if response_started:
                    content_buffer += text
                    inc = content_buffer[prev_yielded:]
                    if inc:
                        prev_yielded = len(content_buffer)
                        return inc
                    return ""
                # Faza THINK — reasoning nie wycieka do Trae.
                thinking_buffer += text
                return ""

            def _begin_phase(ftype, fcontent):
                """Obsługuje deklarację fragmentu THINK/RESPONSE: ustawia fazę i emituje
                początkowy fragment treści. Zwraca treść do yieldowania lub ''."""
                nonlocal response_started, thinking_active, content_buffer, thinking_buffer, prev_yielded
                if ftype == "THINK":
                    thinking_active = True
                    response_started = False
                    if fcontent:
                        thinking_buffer += fcontent
                    return ""
                if ftype == "RESPONSE":
                    thinking_active = False
                    response_started = True
                    if fcontent:
                        content_buffer += fcontent
                        inc = content_buffer[prev_yielded:]
                        if inc:
                            prev_yielded = len(content_buffer)
                            return inc
                    return ""
                return ""
            # Diagnostyka: świeży plik z SUROWYM strumieniem DeepSeek (pełne linie JSON,
            # bez obcinania do 200 znaków). Nadpisywany przy każdym strumieniu, więc po
            # następnej reprodukcji błędu zobaczymy dokładny format thinking/response/tools.
            _raw_capture = os.path.join(DATA_DIR, "raw_stream_capture.jsonl")
            try:
                open(_raw_capture, "w", encoding="utf-8").close()
            except Exception:
                _raw_capture = None
            for line in _iter_lines_with_watchdog(chain(pre_lines, remaining_it), timeout_sec=180.0):
                if not line:
                    continue
                decoded = line.decode("utf-8", "ignore")
                if not decoded.startswith("data: "):
                    continue
                payload = decoded[6:]
                raw_count += 1
                if raw_count <= 3:
                    print(f"[RAW] {payload[:200]}", flush=True)
                if _raw_capture:
                    try:
                        with open(_raw_capture, "a", encoding="utf-8") as _rf:
                            _rf.write(payload + "\n")
                    except Exception:
                        pass
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "error":
                    err_msg = data.get("content", "Unknown error")
                    print(f"[ERROR] DeepSeek error: {err_msg}", flush=True)
                    fr_raw = str(data.get("finish_reason") or "")
                    err_lower = err_msg.lower()
                    if ("too frequent" in err_lower or "server is busy" in err_lower or "serwer jest zajęty" in err_lower
                        or "zajęty" in err_lower or "zajety" in err_lower
                        or "message is being generated" in err_lower or "parallel_chat_limit" in fr_raw or "busy" in fr_raw.lower()):
                        if _retry >= 1:
                            _rate_limited_until[account_idx] = time.time() + 120
                            print(f"[RETRY] Giving up fast on account={account_idx} after {_retry+1} attempts to trigger migration", flush=True)
                            raise RuntimeError(f"DeepSeek busy after {_retry+1} retries: {err_msg}")
                        wait = 60 + random.randint(-10, 15)
                        _rate_limited_until[account_idx] = time.time() + wait + 10
                        print(f"[RETRY] Rate-limited (attempt {_retry+1}, reason={fr_raw}), waiting {wait}s...", flush=True)
                        time.sleep(wait)
                        retry_result = self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1)
                        if retry_result is None:
                            raise RuntimeError("Session expired during retry")
                        new_gen, retry_meta = retry_result
                        if retry_meta.get("resp_msg_id") is not None:
                            resp_msg_id = retry_meta["resp_msg_id"]
                        # PrzekaĹĽ finished_normally z retry do zewnętrznego result_meta
                        result_meta["resp_msg_id"] = resp_msg_id
                        result_meta["finished_normally"] = retry_meta.get("finished_normally", False)
                        yield from new_gen
                        return
                    raise RuntimeError(f"DeepSeek error: {err_msg}")
                # v.response moĹĽe zawierać sygnał zakoĹ„czenia — sprawdź przed skipnięciem
                _v = data.get("v")
                if isinstance(_v, dict) and "response" in _v:
                    _inner = _v["response"]
                    if isinstance(_inner, dict):
                        # Fragmenty ustawiają fazę (THINK/RESPONSE) — nie wolno ich pomijać,
                        # inaczej gubimy fazę i pierwszy token, a myślenie wycieka do klienta.
                        _frags = _inner.get("fragments")
                        if isinstance(_frags, list):
                            for _frag in _frags:
                                if isinstance(_frag, dict):
                                    _tok = _begin_phase(_frag.get("type"), _frag.get("content") or "")
                                    if _tok:
                                        yield _tok
                        _inner_status = str(_inner.get("status", _inner.get("state", ""))).upper()
                        if "FINISHED" in _inner_status or "COMPLETED" in _inner_status or "DONE" in _inner_status:
                            finished_normally = True
                            break
                    continue
                if data.get("o") == "BATCH" and isinstance(data.get("v"), list):
                    for item in data["v"]:
                        if isinstance(item, dict) and item.get("p") == "quasi_status" and item.get("v") == "FINISHED":
                            finished_normally = True
                            break
                    if finished_normally:
                        break
                path = data.get("p", "")
                val = data.get("v")
                rid = data.get("response_message_id")
                if rid is not None:
                    try:
                        resp_msg_id = int(rid)
                    except (ValueError, TypeError):
                        pass
                if path == "response/status" and data.get("o") == "SET" and val == "FINISHED":
                    finished_normally = True
                    break
                # Tokeny treści przychodzą dwiema ścieżkami: response/fragments/-1/content
                # ORAZ pustą ścieżką (p=""). Obie są deltami bieżącej fazy (THINK lub RESPONSE).
                if path == "response/fragments/-1/content" and isinstance(val, str) and val:
                    _tok = _route_token(val)
                    if _tok:
                        yield _tok
                    if _detect_loop(content_buffer):
                        finished_normally = True
                        break
                    continue
                if not path and isinstance(val, str) and val:
                    _tok = _route_token(val)
                    if _tok:
                        yield _tok
                    # Anti-loop guard: przetnij petle tokenow (finished_normally=True)
                    if _detect_loop(content_buffer):
                        finished_normally = True
                        break
                    continue
                if path == "response/fragments" and isinstance(val, list):
                    for fragment in val:
                        if isinstance(fragment, dict):
                            _tok = _begin_phase(fragment.get("type"), fragment.get("content") or "")
                            if _tok:
                                yield _tok
                    # Anti-loop guard: przetnij petle tokenow (finished_normally=True)
                    if _detect_loop(content_buffer):
                        finished_normally = True
                        break
                    continue
            if not response_started:
                # Faza RESPONSE nigdy nie wystartowała — reasoning (THINK) NIE może wyciec
                # do Trae. content_buffer trzyma wyłącznie treść RESPONSE (więc jest pusty),
                # a myślenie celowo siedzi w thinking_buffer i nie jest yieldowane.
                if thinking_buffer:
                    print(f"[THINK] captured {len(thinking_buffer)} chars of reasoning (suppressed, not leaked)", flush=True)

            # ── Moduł 2: Transparentny Auto-Continue ──
            # Stream uciety (watchdog 60s / koniec bez FINISHED / urwany tag narzedzia)
            # -> proxy NIE zamyka odpowiedzi do Trae, tylko wysyla "KONTYNUUJ" w tej samej
            # sesji DeepSeeka (parent = ostatnie resp_msg_id) i dokleja nowe tokeny do
            # biezacego strumienia SSE. Tylko gdy mamy juz tresc i nie wyczerpano budzetu.
            auto_continue_count = 0
            # Auto-continue ma sie odpalic tez, gdy strumien zakonczyl sie "normalnie"
            # (FINISHED), ale zostal niedomkniety tag narzedzia — inaczej uciety tag
            # wycieknie jako tekst i narzedzie nie zostanie wykonane.
            while ((not finished_normally or _has_unclosed_tool_call(content_buffer)) and _auto_continue_budget > 0 and content_buffer.strip()):
                _auto_continue_budget -= 1
                auto_continue_count += 1
                print(f"[AUTO-CONTINUE] attempt {auto_continue_count}, budget left={_auto_continue_budget}, parent={resp_msg_id} (so far {len(content_buffer)} chars)", flush=True)
                try:
                    cont_res = self.stream_completion(
                        account_idx, chat_session_id, "KONTYNUUJ", resp_msg_id,
                        max_tokens=max_tokens, temperature=temperature, top_p=top_p,
                        model_type=model_type, ref_file_ids=ref_file_ids,
                        thinking_enabled=thinking_enabled, search_enabled=search_enabled,
                        _auto_continue_budget=_auto_continue_budget)
                except Exception as ce:
                    print(f"[AUTO-CONTINUE] Request failed: {ce}", flush=True)
                    break
                if cont_res is None:
                    print(f"[AUTO-CONTINUE] Session expired during continue", flush=True)
                    break
                cont_gen, cont_meta = cont_res
                if cont_meta.get("resp_msg_id") is not None:
                    resp_msg_id = cont_meta["resp_msg_id"]
                cont_yielded = False
                try:
                    for tok in cont_gen:
                        if tok:
                            cont_yielded = True
                            content_buffer += tok
                            yield tok
                except Exception as ce:
                    print(f"[AUTO-CONTINUE] Continue stream error: {ce}", flush=True)
                    break
                # finished_normally jest ustawiane DOPIERO po pelnym skonsumowaniu
                # cont_gen (wewnatrz _stream), wiec czytaj je PO petli, nie przed.
                cont_finished = cont_meta.get("finished_normally", False)
                if cont_finished or cont_yielded:
                    finished_normally = True
                    print(f"[AUTO-CONTINUE] attempt {auto_continue_count} OK (yielded={cont_yielded}, finished={cont_finished})", flush=True)
                else:
                    print(f"[AUTO-CONTINUE] attempt {auto_continue_count} produced nothing - retrying", flush=True)
            if auto_continue_count and not finished_normally:
                result_meta["auto_continue_failed"] = True

            result_meta["resp_msg_id"] = resp_msg_id
            result_meta["finished_normally"] = finished_normally
            if not finished_normally:
                print(f"[STREAM] Incomplete — returning partial content ({len(content_buffer)} chars). Next RESUME will continue.", flush=True)
            print(f"[TIMING] DS stream done, resp_id={resp_msg_id} finished={finished_normally}", flush=True)

        return _stream(), result_meta

    def ingest_chunk_fast(self, account_idx: int, chat_session_id: str, prompt: str, parent_message_id: int | None = None, thinking_enabled: bool = False) -> int | None:
        """Wysyła paczkę danych do DeepSeek Web i natychmiast zamyka generator po odebraniu resp_msg_id."""
        stream_res = self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id=parent_message_id, thinking_enabled=thinking_enabled, _auto_continue_budget=0)
        if not stream_res:
            return None
        gen, meta = stream_res
        try:
            for _ in gen:
                break
        finally:
            gen.close()
        return meta.get("resp_msg_id")


def _write_crash_dump(conv_key="", session_id="", account_idx=-1, messages=None,
                      state=None, partial_content="", reason="", error=""):
    """Moduł 3: awaryjny zrzut stanu czatu (po nieudanym auto-continue / błędzie strumienia).

    Zapisuje crash_{ts}_{conv_key[:12]}_{session_id[:8]}.json i .md do data/crashed_chats/
    i loguje dokładną ścieżkę w proxy_output.log. Zwraca ścieżkę lub None.
    """
    try:
        dump_dir = Path(__file__).resolve().parent / "data" / "crashed_chats"
        dump_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        conv_slug = str(conv_key or "")[:12]
        sess_slug = str(session_id or "")[:8]
        base = dump_dir / f"crash_{ts}_{conv_slug}_{sess_slug}"
        partial_content = partial_content or ""
        messages = messages or []
        payload = {
            "timestamp": time.time(),
            "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "conv_key": conv_key,
            "session_id": session_id,
            "account_idx": account_idx,
            "reason": reason,
            "error": str(error),
            "state": state or {},
            "partial_content_chars": len(partial_content),
            "partial_content": partial_content,
            "messages": messages,
        }
        jpath = base.with_suffix(".json")
        jpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_lines = [
            f"# Crash dump {ts}", "",
            f"- conv_key: {conv_key}", f"- session_id: {session_id}",
            f"- account_idx: {account_idx}", f"- reason: {reason}", f"- error: {error}", "",
            "## Partial content", "", "```",
            partial_content[:20000], "```", "",
            f"## Messages ({len(messages)})", "",
        ]
        for i, m in enumerate(messages):
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            md_lines.append(f"### {i} {m.get('role')} ({len(str(c))} chars)")
            md_lines.append(f"```\n{str(c)[:4000]}\n```")
        mdpath = base.with_suffix(".md")
        mdpath.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"[CRASH DUMP] Saved: {jpath}", flush=True)
        return str(jpath)
    except Exception as e:
        print(f"[CRASH DUMP] Failed to write dump: {e}", flush=True)
        return None


def authenticate_via_playwright(ap: AccountPool, slot: int, clean_profile: bool = False) -> str:
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        raise Exception("DrissionPage not installed. Run:  pip install DrissionPage")

    from CloudflareBypasser import CloudflareBypasser
    from DrissionPage.errors import PageDisconnectedError

    import os
    import shutil

    data_dir = os.path.join(os.path.dirname(__file__), ".chrome_slot", f"slot_{slot}")
    # Force-clean profile for fresh login (prevents same-account-on-two-slots bug)
    if clean_profile and os.path.exists(data_dir):
        try:
            shutil.rmtree(data_dir)
            print(f"[AUTH] slot={slot} Cleaned Chrome profile: {data_dir}", flush=True)
        except Exception as e:
            print(f"[AUTH] slot={slot} Could not clean profile: {e}", flush=True)
    os.makedirs(data_dir, exist_ok=True)
    chrome_opt = ChromiumOptions()
    chrome_opt.set_user_data_path(data_dir)
    chrome_opt.set_argument("--no-first-run")
    chrome_opt.set_argument("--no-default-browser-check")
    # Anti-detection: ukryj automatyzację przed DeepSeek
    chrome_opt.set_argument("--disable-blink-features=AutomationControlled")
    chrome_opt.set_argument("--disable-features=IsolateOrigins,site-per-process")
    chrome_opt.set_argument("--disable-infobars")
    # Ustaw realistyczny rozmiar okna
    chrome_opt.set_argument("--window-size=1280,800")
    chrome_opt.auto_port()
    driver = ChromiumPage(chrome_opt)
    try:
        driver.get("https://chat.deepseek.com/sign_in")
        # Anti-detection: usuĹ„ flagę webdriver po załadowaniu strony
        driver.run_cdp("Page.addScriptToEvaluateOnNewDocument", source="""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
        """)

        cf = CloudflareBypasser(driver, max_retries=10, log=True)
        cf.bypass()

        print(f"[AUTH] slot={slot} Waiting for user to sign in... (DO NOT close Chrome)", flush=True)
        disconnect_streak = 0
        token = None
        while True:
            try:
                # 1. Sprawdz czy token jest juz w localStorage
                try:
                    token = driver.run_js("try { return JSON.parse(localStorage.getItem('userToken')).value } catch(e) { return null }")
                except Exception:
                    token = None

                if token and isinstance(token, str) and len(token) > 10:
                    print(f"[AUTH] slot={slot} Detected active userToken! Login successful.", flush=True)
                    break

                # 2. Sprawdz URL jako fallback
                try:
                    url = driver.url
                    if "/a/chat" in url or (url.rstrip("/") == "https://chat.deepseek.com" and "/sign_in" not in url):
                        time.sleep(1)
                        try:
                            token = driver.run_js("try { return JSON.parse(localStorage.getItem('userToken')).value } catch(e) { return null }")
                        except Exception:
                            pass
                        if token and isinstance(token, str) and len(token) > 10:
                            break
                except Exception:
                    pass

                disconnect_streak = 0
            except PageDisconnectedError:
                disconnect_streak += 1
                if disconnect_streak >= 6:
                    raise Exception("Browser was closed before sign-in completed. Run login_slot.bat again.")
                print(f"[AUTH] slot={slot} Browser briefly disconnected, retrying ({disconnect_streak}/6)...", flush=True)
                time.sleep(3)
            except Exception as e:
                time.sleep(1)
            time.sleep(1.5)

        if not token:
            try:
                token = driver.run_js("try { return JSON.parse(localStorage.getItem('userToken')).value } catch(e) { return null }")
            except Exception:
                token = None
        cookies = {c["name"]: c["value"] for c in driver.cookies()}
        user_agent = driver.user_agent
        driver.quit()

        ap.slots[slot] = Session(
            auth_token=token, cookies=cookies, user_agent=user_agent,
            created_at=time.time(), last_validated_at=time.time(),
        )
        ap.save(slot)
        # NIE czyść stanu konwersacji przy logowaniu — to powoduje utratę kontekstu!
        # W razie potrzeby uĹĽytkownik moĹĽe wywołać ręcznie przez dedykowany endpoint.
        # ap.clear_conv_state()  # ZAKOMENTOWANE — powód: utrata kontekstu między restartami
        # Properly reset PoW cache (fix: was setting dict to None)
        ds._cached_pow.clear()
        ds._pow_expires.clear()
        return f"Slot {slot} authenticated successfully"
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            driver.quit()
        except Exception:
            pass
        raise


# â”€â”€â”€ FastAPI App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

app = FastAPI(title="DeepSeek V4-Pro Proxy")

# â”€â”€ Lokalne ścieĹĽki danych (zamiast F:/PROJEKTY/...) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
_TOOLS_CACHE = os.path.join(DATA_DIR, "tools_cache.json")
SERVER_LOG = os.path.join(DATA_DIR, "server_errors.log")
DIAG_LOG = os.path.join(DATA_DIR, "diag_headers.jsonl")
FP_LOG = os.path.join(DATA_DIR, "user_fp_log.txt")
TOKEN_LOG = os.path.join(DATA_DIR, "token_fields.txt")
MSG_LOG = os.path.join(DATA_DIR, "msg_structure.txt")
LEGID_LOG = os.path.join(DATA_DIR, "legid_log.txt")
SYS_PROMPT_LOG = os.path.join(DATA_DIR, "system_prompt.txt")
PROXY_LOG = os.path.join(SCRIPT_DIR, "proxy_output.log")

# â”€â”€ Logowanie stdout/stderr do pliku â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import sys as _sys
_STDOUT_SAVED = _sys.__stdout__
_STDERR_SAVED = _sys.__stderr__
class _TeeLogger:
    def __init__(self, filepath, original):
        self.terminal = original
        self.log = open(filepath, "a", encoding="utf-8", buffering=1)
        self.encoding = getattr(original, "encoding", "utf-8") or "utf-8"
        self.errors = getattr(original, "errors", "replace") or "replace"
    def write(self, message):
        try:
            self.terminal.write(message)
        except UnicodeEncodeError:
            try:
                enc = self.terminal.encoding or "utf-8"
                self.terminal.write(message.encode(enc, errors="replace").decode(enc, errors="replace"))
            except Exception:
                pass
        except Exception:
            pass
        try:
            self.log.write(message)
        except Exception:
            pass
    def flush(self):
        try:
            self.terminal.flush()
        except Exception:
            pass
        try:
            self.log.flush()
        except Exception:
            pass
    def isatty(self):
        return getattr(self.terminal, "isatty", lambda: False)()
    def fileno(self):
        return getattr(self.terminal, "fileno", lambda: 1)()
    def close(self):
        try:
            self.log.close()
        except Exception:
            pass
_sys.stdout = _TeeLogger(PROXY_LOG, _STDOUT_SAVED)
_sys.stderr = _TeeLogger(PROXY_LOG, _STDERR_SAVED)

# â”€â”€ Global error logger â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import traceback as _tb

@app.middleware("http")
async def _log_errors_middleware(request, call_next):
    import time
    t0 = time.time()
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        body = f"[{time.strftime('%H:%M:%S')}] {request.method} {request.url.path}\n{_tb.format_exc()}\n"
        try:
            with open(SERVER_LOG, "a", encoding="utf-8") as f:
                f.write(body)
        except:
            pass
        print(body, flush=True)
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- multi-account pool ---
ap = AccountPool()
ds = DeepSeek(ap)


MAX_PROMPT_LEN = 35000
ENABLE_ACCOUNT_MIGRATION = False  # Gdy False: wyłącza automatyczną migrację konwersacji na inne sloty/konta przy błędach busy/rate-limit (zostaje na tym samym koncie)

def _compress_tool_results(messages: list[dict], threshold: int = 1500) -> list[dict]:
    """Aggressively compress all large tool results to summaries.
    Threshold: 1500 chars (by default). Handles both Read-like (line-numbered) and other tool outputs.
    Adds a marker so the AI knows content was truncated and can re-read via tools."""
    result = []
    for msg in messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) < threshold:
            result.append(msg)
            continue
        char_count = len(content)
        # Read-like content (starts with line numbers like "  1->")
        if re.match(r'^\s*\d+[\u2192\->]', content):
            lines = content.split('\n')
            numbered = [l for l in lines if re.match(r'\s*\d+[\u2192\->]', l)]
            total_lines = len(numbered)
            preview_lines = numbered[:3]
            preview = '\n'.join(preview_lines)
            omitted = total_lines - len(preview_lines)
            compressed = (
                f"[Tool result: {total_lines} lines, {char_count} chars — "
                f"full content available via Read/Glob/Grep tools if needed]\n"
                f"{preview}\n"
                f"[... {omitted} more lines omitted ...]"
            )
        else:
            # Non-Read tool result — keep first 500 chars as preview
            preview = content[:500]
            compressed = (
                f"[Tool result: {char_count} chars — "
                f"full content available via tools if needed]\n"
                f"{preview}\n"
                f"[... {char_count - 500} more chars omitted ...]"
            )
        result.append(dict(msg, content=compressed))
    return result


def _clean_system_reminders(text: str) -> str:
    """Usuwa tagi <system-reminder>...</system-reminder>, <critical_directive>, <previous_tool_call> oraz odpakowuje <user_input>...<user_input>."""
    if not isinstance(text, str):
        return text
    text = re.sub(r'<critical_directive>[\s\S]*?</critical_directive>', '', text).strip()
    text = re.sub(r'<system-reminder>[\s\S]*?</system-reminder>', '', text).strip()
    text = re.sub(r'</?system-reminder[^>]*>', '', text).strip()
    text = re.sub(r'</?previous_tool_call[^>]*>', '', text).strip()
    text = re.sub(r'-reminder>[^\n]*', '', text).strip()
    if "<user_input>" in text:
        m = re.search(r'<user_input>\s*([\s\S]*?)\s*</user_input>', text)
        if m:
            text = m.group(1).strip()
    return text


def _format_msgs(msgs: list[dict], keep_images: bool = False, strip_reminders: bool = False) -> list[str]:
    parts = []
    for msg in msgs:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        tc = msg.get("tool_calls", [])
        if isinstance(content, list):
            texts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text" and part.get("text"):
                        txt = part["text"]
                        if "<system-reminder>" in txt or "<user_input>" in txt or strip_reminders:
                            txt = _clean_system_reminders(txt)
                        if txt:
                            texts.append(txt)
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            texts.append("[Image]")
                        elif url:
                            texts.append(f"[Image: {url}]")
                elif isinstance(part, str):
                    txt = part
                    if "<system-reminder>" in txt or "<user_input>" in txt or strip_reminders:
                        txt = _clean_system_reminders(txt)
                    if txt:
                        texts.append(txt)
            content = " ".join(texts).strip()
        elif isinstance(content, str):
            if "<system-reminder>" in content or "<user_input>" in content or "<critical_directive>" in content or strip_reminders:
                content = _clean_system_reminders(content)

        if isinstance(content, str) and content.strip():
            if role == "system":
                parts.append(f"[System]: {content.strip()}")
            elif role == "user":
                parts.append(f"[User]: {content.strip()}")
            elif role == "assistant":
                parts.append(f"[Assistant]: {content.strip()}")
            elif role == "tool":
                tid = msg.get('tool_call_id', msg.get('name', 'tool'))
                parts.append(f"<tool_result id=\"{tid}\">\n{content.strip()}\n</tool_result>")
        if tc:
            for call in tc:
                fn = call.get("function", {})
                name = fn.get("name", "tool")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
                parts.append(f"<tool_call name=\"{name}\">" +
                             "".join(f"<parameter name=\"{k}\">{_format_value(v)}</parameter>" for k, v in args.items()) +
                             f"</tool_call>")
    return parts

def _format_value(v):
    """Format a parameter value for XML: strings as-is, others as JSON."""
    if isinstance(v, str):
        return v
    return json.dumps(v) if v is not None else ""

def _compress_image(img_b64: str, mime_type: str = "image/png", max_px: int = 1024, quality: int = 75) -> tuple[str, str]:
    """Compress image: resize to max_px on longest side, convert to JPEG, return (b64, mime_type)."""
    try:
        from PIL import Image
        from io import BytesIO
        img_bytes = base64.b64decode(img_b64)
        buf = BytesIO(img_bytes)
        img = Image.open(buf)
        # Convert RGBA to RGB (white background) for JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        # Resize if larger than max_px on longest side
        w, h = img.size
        if max(w, h) > max_px:
            ratio = max_px / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        # Save as JPEG with given quality; if still >200KB, reduce quality
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality)
        if out.tell() > 200 * 1024:
            out.seek(0)
            out.truncate(0)
            img.save(out, format="JPEG", quality=60)
        out.seek(0)
        compressed_b64 = base64.b64encode(out.read()).decode("ascii")
        return compressed_b64, "image/jpeg"
    except Exception as e:
        print(f"[COMPRESS] Failed, using original: {e}", flush=True)
        return img_b64, mime_type

def _crush_tool_results(messages: list[dict]) -> list[dict]:
    """For WEB CHAT recovery: compress ALL tool results to tiny summaries.
    Unlike _compress_tool_results (which only compresses above threshold=1500 chars), this crushes ALL tools > 200 chars.
    Used when Content is too long or Trae trimmed — we can't re-send raw results."""
    result = []
    for msg in messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            result.append(msg)
            continue
        char_count = len(content)
        if char_count < 200:
            result.append(msg)
            continue
        # Read-like (line-numbered output)
        if re.match(r'^\s*\d+→', content):
            lines = content.split('\n')
            numbered = [l for l in lines if re.match(r'\s*\d+→', l)]
            total_lines = len(numbered)
            preview = numbered[0].strip() if numbered else ""
            crushed = f"[Read result: {total_lines} lines, already processed] {preview}"
        # Grep/Glob-like (multi-line listings)
        elif '\n' in content[:500] and len(content.split('\n')) > 5:
            first_line = content.split('\n')[0].strip()[:200]
            crushed = f"[Listing result: {char_count} chars, already processed] {first_line}"
        else:
            preview = content[:150].replace('\n', ' ').strip()
            crushed = f"[Tool result: {char_count} chars, already processed] {preview}"
        result.append(dict(msg, content=crushed))
    return result


def _strip_dead_system_sections(msg: dict) -> dict:
    """Usuwa martwe sekcje z system promptu Trae (np. Image Guidelines z URL do coresg)."""
    content = msg.get("content", "")
    if not isinstance(content, str):
        return msg
    # Sekcja Image Guidelines jest na sztywno podpięta pod wewnętrzny URL Trae
    # (coresg-normal.trae.ai) i w tym proxy nigdy nie jest używana.
    idx = content.find("\n# Image Guidelines")
    if idx != -1:
        content = content[:idx].rstrip()
    return {**msg, "content": content}


def _build_prompt(messages: list[dict], tools: list[dict] | None = None, images: list[dict] | None = None, embed_images: bool = True, state: dict | None = None) -> str:
    msgs = list(messages)
    system = []
    rest = msgs
    if msgs and msgs[0].get("role") == "system":
        system = [_strip_dead_system_sections(msgs[0])]
        rest = msgs[1:]
    # if len(rest) > 60:
    #     rest = rest[-60:]
    # Compress tool results: history gets aggressive compression,
    # CURRENT turn's results stay INTACT so DeepSeek can actually READ the files.
    # Without this, the AI works blind — fabricating file contents because it only
    # sees 500-char previews. This was THE reason the proxy DeepSeek hallucinated
    # while the paid DeepSeek (same model!) was accurate.
    tool_indices = [i for i, m in enumerate(rest) if m.get("role") == "tool"]
    if tool_indices:
        # Znajdź początek bieżącej tury narzędzi (wszystkie narzędzia po ostatniej wiadomości user/assistant)
        # Dzięki temu przy równoległym odczycie wielu plików WSZYSTKIE pliki z bieżącej tury zostają pełne,
        # zamiast ucinania pierwszych N-1 plików do 3-liniowych podglądów (co wywoływało pętlę ponownego czytania).
        last_non_tool = -1
        for i in range(len(rest) - 1, -1, -1):
            if rest[i].get("role") != "tool":
                last_non_tool = i
                break
        keep_from = (last_non_tool + 1) if last_non_tool != -1 else 0

        # Compress OLD history (before current turn)
        compressed_history = _compress_tool_results(rest[:keep_from])
        # Keep CURRENT turn intact — DO NOT compress unless individually massive (>25000 chars)
        current_turn = rest[keep_from:]
        safe_current = []
        for msg in current_turn:
            # Pojedynczy odczyt powyżej 25k znaków skracamy, aby nie przebić limitu 35k
            if msg.get("role") == "tool" and isinstance(msg.get("content", ""), str) and len(msg["content"]) > 25000:
                safe_current.append(_compress_tool_results([msg])[0])
            else:
                safe_current.append(msg)
        rest = compressed_history + safe_current
    # â”€â”€ DebounceHook v2: persystentny sliding-window bloker duplikatów â”€â”€
    # Ĺšledzi w conv_state jakie narzędzia były wywołane i blokuje przy 2+ w oknie 3 tur.
    # Zastępuje wyniki duplikatów w prompcie krótką wiadomością BLOCKED.
    # DISABLED: deduplicate_tool_results_in_prompt has a bug — it blocks ALL read-like
    # tool results if ANY hash has >=2 entries, not just the actual duplicate.
    # This causes every subsequent Read to return "BLOCKED" for different files too.
    # rest = deduplicate_tool_results_in_prompt(rest, state or {})
    # Inject compressed images as data URIs for vision model (only when embed_images=True)
    if images and embed_images:
        img_uris = []
        for idx, img in enumerate(images):
            if img.get("base64"):
                b64, mime = _compress_image(img["base64"], img.get("mime_type", "image/png"))
                orig_kb = len(img["base64"]) * 3 // 4 // 1024
                new_kb = len(b64) * 3 // 4 // 1024
                print(f"[COMPRESS] Image {idx+1}: {orig_kb}KB -> {new_kb}KB ({mime})", flush=True)
                img_uris.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": img.get("detail", "auto")}})
            elif img.get("url"):
                img_uris.append({"type": "image_url", "image_url": {"url": img["url"], "detail": img.get("detail", "auto")}})
        if img_uris:
            # Find last user message and attach images as vision content blocks
            for i in range(len(rest)-1, -1, -1):
                if rest[i].get("role") == "user":
                    old_content = rest[i].get("content", "")
                    rest[i] = dict(rest[i])
                    if isinstance(old_content, list):
                        # Already a vision content list - extract text, preserve existing images
                        text_parts = []
                        existing_images = []
                        for p in old_content:
                            if isinstance(p, dict) and p.get("type") == "text":
                                text_parts.append(p.get("text", ""))
                            elif isinstance(p, dict) and p.get("type") == "image_url":
                                existing_images.append(p)
                        new_text = " ".join(text_parts).strip()
                        rest[i]["content"] = [{"type": "text", "text": new_text}] + existing_images + img_uris
                    else:
                        rest[i]["content"] = [{"type": "text", "text": old_content}] + img_uris
                    break
    # ── Tool Schemas & Instructions Suffix ──
    tools_suffix = ""
    if tools:
        tools_suffix += "\n\n# Available Tool Schemas\n"
        for t in tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function", t)
            name = fn.get("name", "?")
            desc = fn.get("description", "")
            params = fn.get("parameters", {})
            tools_suffix += f"\n## {name}\n"
            if desc:
                tools_suffix += f"{desc}\n"
            if isinstance(params, dict):
                props = params.get("properties", {})
                required = params.get("required", [])
                if props:
                    tools_suffix += "Parameters:\n"
                    for pname, pdef in props.items():
                        ptype = pdef.get("type", "any")
                        req = " (required)" if pname in required else ""
                        pdesc = pdef.get("description", "")
                        enum = pdef.get("enum", [])
                        extra = f" [{', '.join(enum)}]" if enum else ""
                        items = pdef.get("items", {})
                        if items:
                            tools_suffix += f"  - `{pname}` ({ptype}{extra}){req}"
                            if pdesc:
                                tools_suffix += f": {pdesc}"
                            tools_suffix += "\n"
                            # Show nested properties for array items
                            iprops = items.get("properties", {})
                            ireq = items.get("required", [])
                            for ipn, ipd in iprops.items():
                                ipt = ipd.get("type", "any")
                                ir = " (required)" if ipn in ireq else ""
                                tools_suffix += f"      - `{ipn}` ({ipt}){ir}\n"
                        else:
                            tools_suffix += f"  - `{pname}` ({ptype}{extra}){req}"
                            if pdesc:
                                tools_suffix += f": {pdesc}"
                            tools_suffix += "\n"
        tools_suffix += """

# Tool Call Format
When you need to call a tool, ALWAYS use this exact XML format:

<tool_call name="ToolName">
  <parameter name="param1">value1</parameter>
  <parameter name="param2">value2</parameter>
</tool_call>

Rules:
- Put <tool_call> directly in your response (NOT inside markdown code blocks, do NOT use DSML markers)
- Use the exact tool name and parameter names as shown in the # Available Tool Schemas above (if provided)
- For tools without parameters: <tool_call name="ToolName"></tool_call>
- Text before tool calls is displayed to user; tool calls are intercepted and executed
- CRITICAL: When you say you will check, read, edit, or search files, you MUST emit the <tool_call> block immediately in the same message. NEVER output promises or plain text parameter lists like 'Grep pattern: ...' without the actual <tool_call> XML block!"""

    # Obliczamy dynamiczny budżet na wiadomości po odliczeniu schematów narzędzi
    msgs_budget = max(5000, MAX_PROMPT_LEN - len(tools_suffix))
    strip_reminders = (tools is None or _clean_mode_enabled())
    parts = _format_msgs(system + rest, keep_images=bool(images), strip_reminders=strip_reminders)
    prompt = "\n\n".join(parts)

    # Progresywne przycinanie historii do budżetu wiadomości
    if len(prompt) > msgs_budget and rest:
        for keep_n in (10, 5, 2, 1):
            if len(prompt) <= msgs_budget:
                break
            parts = _format_msgs(system + rest[-keep_n:], keep_images=bool(images), strip_reminders=strip_reminders)
            prompt = "\n\n".join(parts)

    # Ostateczny hard-cap na pojedynczą wiadomość użytkownika
    if len(prompt) > msgs_budget:
        allowed = msgs_budget - 200
        prompt = prompt[:allowed] + "\n[... Prompt truncated to 35k limit to prevent backend drop ...]"

    # Doklejenie schematów narzędzi
    prompt += tools_suffix

    # Ostateczny absolutny invariant na łączny prompt
    if len(prompt) > MAX_PROMPT_LEN:
        allowed = MAX_PROMPT_LEN - 200
        prompt = prompt[:allowed] + "\n[... Prompt hard-capped to 35k limit ...]"

    return prompt


CHUNK_THRESHOLD = 50000


def _chunk_oversized_prompt(prompt: str, max_chunk_size: int = CHUNK_THRESHOLD) -> list[str]:
    """
    Dzieli duży prompt (> 50k znaków) na listę mniejszych części (<= max_chunk_size),
    respektując granice wiadomości ([User]:, [Assistant]:, [System]:, <tool_result)
    oraz akapitów (\\n\\n), aby nie uszkodzić żadnego bloku kodu ani tagu XML.
    """
    if len(prompt) <= max_chunk_size:
        return [prompt]

    # Szukamy granic wiadomości: \n\n[User]: , \n\n[Assistant]: , \n\n[System]: , \n\n<tool_result , \n\n# Available Tool Schemas
    split_pattern = r"(?=\n\n(?:\[(?:User|Assistant|System|Tool)\]:|<tool_result\b|# Available Tool Schemas))"
    raw_sections = [s for s in re.split(split_pattern, prompt) if s.strip()]
    if not raw_sections:
        raw_sections = [prompt]

    chunks = []
    current_chunk = ""

    for sec in raw_sections:
        # Jeśli pojedyncza sekcja (np. gigantyczny odczyt pliku) sama przekracza max_chunk_size:
        if len(sec) > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            sub_parts = re.split(r"(?<=\n\n)", sec)
            sub_chunk = ""
            for sp in sub_parts:
                if len(sub_chunk) + len(sp) > max_chunk_size and sub_chunk:
                    chunks.append(sub_chunk.strip())
                    sub_chunk = ""
                if len(sp) > max_chunk_size:
                    line_parts = re.split(r"(?<=\n)", sp)
                    for lp in line_parts:
                        if len(sub_chunk) + len(lp) > max_chunk_size and sub_chunk:
                            chunks.append(sub_chunk.strip())
                            sub_chunk = ""
                        sub_chunk += lp
                else:
                    sub_chunk += sp
            if sub_chunk:
                chunks.append(sub_chunk.strip())
        else:
            if len(current_chunk) + len(sec) > max_chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sec
            else:
                current_chunk += ("\n\n" + sec if current_chunk else sec)

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [prompt]


def _safe_json_loads(s: str) -> dict | list | str | None:
    """Robust JSON parser that repairs common LLM mistakes (unescaped backslashes, trailing commas)."""
    if not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    repaired = re.sub(r'\\(?!(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))', r'\\\\', s)
    try:
        return json.loads(repaired)
    except Exception:
        pass
    repaired2 = re.sub(r',\s*([}\]])', r'\1', repaired)
    try:
        return json.loads(repaired2)
    except Exception:
        pass
    repaired3 = s.replace('\\', '\\\\')
    repaired3 = re.sub(r'\\\\{2,}', r'\\\\', repaired3)
    repaired3 = re.sub(r',\s*([}\]])', r'\1', repaired3)
    try:
        return json.loads(repaired3)
    except Exception:
        pass
    return None


def _parse_param_value(raw: str):
    """Try to parse a tool param value as JSON; fall back to raw string."""
    s = raw.strip()
    if not s:
        return s
    parsed = _safe_json_loads(s)
    if parsed is not None:
        if isinstance(parsed, str):
            parsed2 = _safe_json_loads(parsed)
            if parsed2 is not None:
                return parsed2
        return parsed
    return s


# Klucze, które jednoznacznie należą do konkretnego narzędzia — niezależnie od tego,
# jaki tag model wymyśli. Format tagów jest niestabilny, schematy narzędzi są stałe,
# więc ufamy kluczom, a nie nazwie w tagu.
_TASK_ONLY_KEYS = {"subagent_type", "response_language"}
_RUNCOMMAND_ONLY_KEYS = {"command", "command_type", "blocking", "target_terminal",
                        "wait_ms_before_async", "requires_approval"}


def _repair_tool_call(name: str, params: dict) -> tuple[str, dict]:
    """Napraw nazwę narzędzia na podstawie kluczy parametrów.

    Model potrafi wypluć np. <tool_call name="RunCommand"> z parametrami Taska w środku
    (query, subagent_type, response_language). Wtedy cały call jest realnie Taskiem.
    Zamiast dodawać kolejny regex, sprawdzamy klucze i poprawiamy nazwę.
    """
    keys = set(params or {})
    if _TASK_ONLY_KEYS & keys:
        # To naprawdę Task — odrzuć klucze RunCommanda, które tam nie pasują.
        params = {k: v for k, v in (params or {}).items() if k not in _RUNCOMMAND_ONLY_KEYS}
        return "Task", params
    return name, params


def _parse_tool_calls(text: str) -> list[tuple[int, int, str, str]]:
    """Parse all tool call formats. Returns [(start, end, name, args_json), ...]"""
    results = []

    # 1. Standard XML or DSML-wrapped invoke:
    # Matches <invoke name="...">, <tool_call name="...">, <_call name="...">, <call name="...">, <tool name="...">, and DSML variants
    tool_pat = re.compile(
        r'''(?:<\s*(?:[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?tool\s+)?'''
        r'''<\s*(?:[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?(?:tool_call|invoke|tool_capability|_call|call|tool)\s*name=(["'])([^"']*?)\1[^>]*>'''
        r'''(.*?)'''
        r'''</\s*(?:[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?(?:tool_call|invoke|tool_capability|_call|call|tool)s?>''',
        re.DOTALL | re.IGNORECASE
    )
    for m in tool_pat.finditer(text):
        name = m.group(2)
        body = m.group(3).strip()
        params = {}
        param_pat = re.compile(
            r'''<\s*(?:[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?parameter\s*name=(["'])([^"']+?)\1[^>]*>(.*?)</\s*(?:[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?parameter>''',
            re.DOTALL | re.IGNORECASE
        )
        for pm in param_pat.finditer(body):
            params[pm.group(2)] = _parse_param_value(pm.group(3))
        if not params:
            jm = re.search(r'\{.*\}', body, re.DOTALL)
            if jm:
                parsed_jm = _safe_json_loads(jm.group(0))
                if isinstance(parsed_jm, dict):
                    params = parsed_jm
        results.append((m.start(), m.end(), name, json.dumps(params) if params else "{}"))

    # 2. DSML variant: < | | DSML | | name="ToolName"> ... </ | | DSML | | > or <DSML name="...">
    for m in re.finditer(r'''<(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?DSML(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?\s*name=(["'])([^"']*?)\1>(.*?)</(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?DSML(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?>''', text, re.DOTALL | re.IGNORECASE):
        name = m.group(2)
        body = m.group(3).strip()
        params = {}
        for pm in re.finditer(r'''<parameter\s*name=(["'])([^"']+?)\1[^>]*>(.*?)</parameter>''', body, re.DOTALL | re.IGNORECASE):
            params[pm.group(2)] = _parse_param_value(pm.group(3))
        if not params:
            jm = re.search(r'\{.*\}', body, re.DOTALL)
            if jm:
                parsed_jm = _safe_json_loads(jm.group(0))
                if isinstance(parsed_jm, dict):
                    params = parsed_jm
        results.append((m.start(), m.end(), name, json.dumps(params) if params else "{}"))

    # 2b. Loose DSML without outer angle brackets: | | DSML | | name="ToolName"> ... / | | DSML | | >
    for m in re.finditer(r'''(?:<)?\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*name=(["'])([^"']*?)\1\s*>(.*?)(?:(?:</?\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*>)|(?:/\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*>))''', text, re.DOTALL | re.IGNORECASE):
        name = m.group(2)
        body = m.group(3).strip()
        params = {}
        for pm in re.finditer(r'''<parameter\s*name=(["'])([^"']+?)\1[^>]*>(.*?)</parameter>''', body, re.DOTALL | re.IGNORECASE):
            params[pm.group(2)] = _parse_param_value(pm.group(3))
        if not params:
            pm2 = re.search(r'''name=(["'])([^"']+?)\1\s*>\s*(.*?)(?:</parameter>|/parameter>|$)''', body, re.DOTALL | re.IGNORECASE)
            if pm2:
                params[pm2.group(2)] = _parse_param_value(pm2.group(3))
        results.append((m.start(), m.end(), name, json.dumps(params) if params else "{}"))

    # 3. DeepSeek native: <｜tool call begin｜>function<｜tool sep｜>name\n```json\n{...}\n```<｜tool call end｜>
    for m in re.finditer(r'''<[|｜\s]*tool\s*call\s*begin[|｜\s]*>(?:function)?(?:\s*<[|｜\s]*tool\s*sep[|｜\s]*>|\s*[|｜]?\s*tool\s*sep[|｜]?\s*)?([a-zA-Z0-9_-]+)\s*(?:```(?:json)?\s*)?(\{.*?\})(?:\s*```)?\s*<[|｜\s]*tool\s*call\s*end[|｜\s]*>''', text, re.DOTALL | re.IGNORECASE):
        name = m.group(1).strip()
        parsed_body = _safe_json_loads(m.group(2).strip())
        if parsed_body is not None and isinstance(parsed_body, (dict, list)):
            args = json.dumps(parsed_body)
        else:
            args = m.group(2).strip()
        results.append((m.start(), m.end(), name, args))

    # 4. MCP file system
    for m in re.finditer(r"<mcp_file_system>(.*?)</mcp_file_system>", text, re.DOTALL):
        tn = re.search(r"<tool_name>(.*?)</tool_name>", m.group(1), re.DOTALL)
        tp = re.search(r"<tool_parameters>(.*?)</tool_parameters>", m.group(1), re.DOTALL)
        results.append((m.start(), m.end(), tn.group(1).strip() if tn else "mcp_tool", tp.group(1).strip() if tp else "{}"))

    # 5. DeepSeek native format: <tool_use_json>{"tool_name":"...","arguments":{...}}</tool_use_json>
    for m in re.finditer(r"<tool_use_json>(.*?)</tool_use_json>", text, re.DOTALL | re.IGNORECASE):
        try:
            payload = json.loads(m.group(1))
            if isinstance(payload, dict):
                name = payload.get("tool_name", "unknown")
                args = json.dumps(payload.get("arguments", {}))
                results.append((m.start(), m.end(), name, args))
        except json.JSONDecodeError:
            pass

    # 6. Specific Tool Name tags e.g. <Read><file_path>...</file_path></Read>
    for m in re.finditer(r"<([A-Z][a-zA-Z0-9_]+)>(.*?)</\1>", text, re.DOTALL):
        params = {}
        for pm in re.finditer(r"<([a-zA-Z_]\w*)>(.*?)</\1>", m.group(2), re.DOTALL):
            params[pm.group(1)] = _parse_param_value(pm.group(2))
        if params:
            results.append((m.start(), m.end(), m.group(1), json.dumps(params)))

    # 7. Pattern: [调用ToolName]{json} or [调用 ToolName]{json}
    for m in re.finditer(rf"\[{_CALL_MARKER}\s*(\w+)\]\s*(\{{)", text):
        brace_start = m.start(2)
        depth = 0
        i = brace_start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    body = text[brace_start:i+1]
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict):
                            results.append((m.start(), i+1, m.group(1), body))
                    except:
                        pass
                    break
            i += 1

    # 8. CLI/Text style tool invocation: ToolName param1: val1 param2: val2
    # e.g. Grep pattern: 4570|... path: ... output_mode: content -n: true
    known_tools = {"Read", "Write", "Edit", "SearchReplace", "Grep", "Glob", "LS", "RunCommand", "Task", "CheckCommandStatus", "DeleteFile", "TodoWrite"}
    for tn in known_tools:
        for m in re.finditer(rf"(?:^|\n)\s*({tn})\s+([a-zA-Z_-]+:\s*[^\n]+)", text):
            # FIX: wcześniej było tu `raw_args` (niezdefiniowane) -> NameError przy każdym
            # dopasowaniu formatu CLI, co udawało "przerwany strumień DeepSeeka".
            pairs = re.findall(r'([a-zA-Z_-]+):\s*([a-zA-Z]:[^\s:]*(?:\s+[^\s:]+)*|[^\s:]+(?:\s+[^\s:]+)*)(?=\s+[a-zA-Z_-]+:|$)', m.group(2))
            if pairs:
                params = {}
                for k, v in pairs:
                    clean_k = k.lstrip("-")
                    params[clean_k] = _parse_param_value(v.strip())
                results.append((m.start(), m.end(), tn, json.dumps(params)))

    # 9. Top-level JSON tool call: ```json {"tool": "LS", "args": {...}} ``` or raw {"tool": "...", "args": ...}
    i = 0
    while i < len(text):
        if text[i] == '{':
            start = i
            depth = 0
            in_str = False
            escape = False
            j = i
            while j < len(text):
                c = text[j]
                if escape:
                    escape = False
                elif c == '\\':
                    escape = True
                elif c == '"':
                    in_str = not in_str
                elif not in_str:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            raw = text[start:j+1]
                            m_start = start
                            m_end = j + 1
                            before = text[:start].rstrip()
                            if before.endswith('```json') or before.endswith('```'):
                                m_start = text.rfind('```', 0, start)
                            after = text[j+1:].lstrip()
                            if after.startswith('```'):
                                m_end = j + 1 + text[j+1:].find('```') + 3
                            
                            payload = _safe_json_loads(raw)
                            if isinstance(payload, dict):
                                tname = payload.get("tool") or payload.get("tool_name") or payload.get("name") or payload.get("action") or payload.get("function")
                                if isinstance(tname, str):
                                    match_name = next((kt for kt in known_tools if kt.lower() == tname.lower()), None)
                                    if match_name:
                                        targs = payload.get("args") or payload.get("arguments") or payload.get("parameters") or payload.get("input") or payload.get("params") or {}
                                        if isinstance(targs, str):
                                            targs_parsed = _safe_json_loads(targs)
                                            targs = targs_parsed if isinstance(targs_parsed, dict) else {"query": targs}
                                        if not isinstance(targs, dict):
                                            targs = {"value": targs}
                                        results.append((m_start, m_end, match_name, json.dumps(targs)))
                            i = j
                            break
                j += 1
        i += 1

    # Napraw nazwy narzędzi na podstawie kluczy parametrów (np. RunCommand z parametrami
    # Taska → realnie Task). Format tagów modelu jest niestabilny, schematy stałe.
    repaired = []
    for start, end, name, args_json in results:
        try:
            params = json.loads(args_json) if isinstance(args_json, str) else (args_json or {})
        except Exception:
            params = {}
        if isinstance(params, dict):
            fixed_name, fixed_params = _repair_tool_call(name, params)
            name = fixed_name
            args_json = json.dumps(fixed_params)
        repaired.append((start, end, name, args_json))
    results = repaired

    results.sort(key=lambda x: x[0])
    unique = []
    for r in results:
        if not unique or r[0] >= unique[-1][1]:
            unique.append(r)
    return unique


# Tags that should be stripped from displayed text (not parsed as tool calls)
_CALL_MARKER = "\u8c03\u7528"
_STRIP_TAGS = re.compile(
    r"</?system-reminder[^>]*>|</?-reminder[^>]*>|"
    r"-reminder>[^\n]*|"
    r"<critical_directive>[\s\S]*?</critical_directive>|"
    r"</?previous_tool_call[^>]*>|"
    r"</?(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*|tool_calls?|tool_capability|invoke|_calls?|call|tools?|center)[^>]*>|"
    r"<tool_result[^>]*>.*?</tool_result>|</?tool_result[^>]*>|"
    r"<result[^>]*>|</result>|<status[^>]*>.*?</status>|"
    r"</?thinking[^>]*>|<tool_use_json[^>]*>.*?</tool_use_json>|"
    r"</?parameter[^>]*>|"
    r"<[|\uff5c\u2502\s]*tool\s*call\s*begin[|\uff5c\u2502\s]*>.*?<[|\uff5c\u2502\s]*tool\s*call\s*end[|\uff5c\u2502\s]*>|"
    r"</?[|\uff5c\u2502\s]*tool[_\s]*calls?\s*(?:begin|end)?[|\uff5c\u2502\s]*>|"
    r"<tool_call[^>]*>.*?</tool_calls?>|" + rf"\[{_CALL_MARKER}\s*\w+\]",
    re.DOTALL | re.IGNORECASE
)


def _clean_text(text: str) -> str:
    """Remove known XML wrapper/control tags from displayed text."""
    return _STRIP_TAGS.sub("", text).strip()


def _extract_images(messages: list[dict]) -> list[dict]:
    """Extract all image_url content blocks from ALL user messages.
    Returns list of dicts with base64, mime_type, url, and detail keys.
    Supports both data: URIs and http/https URLs."""
    results = []
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                detail = part.get("image_url", {}).get("detail", "auto")
                result = {"url": url, "detail": detail, "base64": None, "mime_type": None}
                if url.startswith("data:"):
                    header, base64_data = url.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                    result["base64"] = base64_data
                    result["mime_type"] = mime_type
                elif url.startswith("http://") or url.startswith("https://"):
                    result["url"] = url
                    # Keep mime_type unknown — will be detected from response headers or defaults to png
                results.append(result)
    return results


class ChatRequest(BaseModel):
    model: str = "deepseek-v4-pro"
    messages: list[dict]
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    stream: bool = True
    max_tokens: int = 8192
    max_completion_tokens: int | None = None
    temperature: float = 1.0
    top_p: float = 1.0



_slot_locks = [threading.Lock() for _ in range(MAX_ACCOUNTS)]
_slot_in_progress = [False] * MAX_ACCOUNTS
_slot_busy = [False] * MAX_ACCOUNTS
_slot_busy_lock = threading.Lock()
_conv_lock = threading.Lock()
_rate_limited_until: list[float] = [0.0] * MAX_ACCOUNTS

def _ensure_slot(slot: int, clean: bool = False):
    global _slot_in_progress
    print(f"[DEBUG] _ensure_slot(slot={slot}) called, current in_progress={_slot_in_progress[slot]}", flush=True)
    with _slot_locks[slot]:
        valid = ap.is_valid(slot)
        print(f"[DEBUG] ap.is_valid({slot}) = {valid}, slots[{slot}] = {ap.slots[slot]}", flush=True)
        if _slot_in_progress[slot]:
            raise HTTPException(401, f"Slot {slot} login in progress â€“ complete sign-in in Chrome, then retry")
        if valid and not clean:
            return
        if valid and clean:
            ap.slots[slot] = None
        _slot_in_progress[slot] = True

    def _bg():
        global _slot_in_progress
        try:
            authenticate_via_playwright(ap, slot, clean_profile=clean)
        finally:
            _slot_in_progress[slot] = False

    t = threading.Thread(target=_bg, daemon=True)
    t.start()
    raise HTTPException(401, f"Slot {slot} not authenticated â€“ Chrome opened. Sign in and retry.")


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{
            "id": "deepseek-v4-pro",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-v4-flash",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-v4-flash-search",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-v4-flash-nothink",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-vision",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-fast",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-fast-search",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-fast-nothink",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }, {
            "id": "deepseek-expert",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }]
    }


@app.post("/v1/login")
def login(slot: int = 0, clean: bool = False):
    if slot < 0 or slot >= MAX_ACCOUNTS:
        raise HTTPException(400, f"Slot must be 0-{MAX_ACCOUNTS-1}")
    # clean=True -> force fresh Chrome profile (prevents same-account-on-two-slots bug)
    _ensure_slot(slot, clean=clean)
    return {"status": "pending", "message": f"Chrome opened for slot {slot}. Sign in and retry the request."}


@app.get("/v1/accounts")
def list_accounts():
    counts = [0] * MAX_ACCOUNTS
    for v in _conv_state.values():
        a = v.get("account", -1)
        if 0 <= a < MAX_ACCOUNTS:
            counts[a] += 1
    accts = []
    for i in range(MAX_ACCOUNTS):
        s = ap.slots[i]
        accts.append({
            "slot": i,
            "logged_in": ap.is_valid(i),
            "conversations": counts[i],
            "age_hours": round((time.time() - s.created_at) / 3600, 1) if s and s.created_at else None,
        })
    return {"accounts": accts}


# Per-conversation state: maps sys_prompt_hash -> {ds_session, parent_id, msgs_len, tools}

def _save_conv_state():
    try:
        import shutil
        # Backup co 10 zapisów (rotacyjnie, ĹĽeby nie zalewać dysku)
        if not hasattr(_save_conv_state, '_counter'):
            _save_conv_state._counter = 0
        _save_conv_state._counter += 1
        if _save_conv_state._counter % 10 == 0 and CONV_STATE_FILE.exists():
            backup_path = CONV_STATE_FILE.with_suffix(".auto.backup.json")
            try:
                shutil.copy2(CONV_STATE_FILE, backup_path)
            except Exception:
                pass
        # Timestamp entries for pruning
        now_ts = time.time()
        for v in _conv_state.values():
            if isinstance(v, dict) and "_ts" not in v:
                v["_ts"] = now_ts
        # Prune oldest entries if over limit
        if len(_conv_state) > MAX_CONV_ENTRIES:
            sorted_keys = sorted(
                [k for k in _conv_state.keys()],
                key=lambda k: _conv_state[k].get("_ts", 0) if isinstance(_conv_state[k], dict) else 0,
                reverse=True,
            )
            for k in sorted_keys[MAX_CONV_ENTRIES:]:
                del _conv_state[k]
            print(f"[CONV] Pruned {len(sorted_keys) - MAX_CONV_ENTRIES} old entries, keeping {len(_conv_state)}", flush=True)
        tmp = CONV_STATE_FILE.with_suffix(".tmp")
        # Explicit UTF-8 open to avoid Windows cp1250 encoding bug with -> (U+2192)
        with open(str(tmp), "w", encoding="utf-8") as f:
            json.dump(_conv_state, f, indent=2, ensure_ascii=False)
        tmp.replace(CONV_STATE_FILE)
    except Exception as e:
        print(f"[CONV SAVE ERROR] {e}", flush=True)

def _load_conv_state() -> dict:
    try:
        if CONV_STATE_FILE.exists():
            with open(str(CONV_STATE_FILE), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
    except Exception as e:
        print(f"[CONV LOAD ERROR] {e}", flush=True)
    return {}

_conv_state: dict = _load_conv_state()
# Migrate old entries without account field -> account 0
for _v in _conv_state.values():
    if isinstance(_v, dict) and "account" not in _v:
        _v["account"] = 0
if _conv_state:
    _save_conv_state()

def _save_tools(sys_hash: str, tools: list[dict]):
    try:
        cache = {}
        if os.path.exists(_TOOLS_CACHE):
            with open(_TOOLS_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        cache[sys_hash] = tools
        with open(_TOOLS_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[TOOLS CACHE WRITE ERROR] {e}", flush=True)

def _load_tools(sys_hash: str) -> list[dict] | None:
    try:
        if os.path.exists(_TOOLS_CACHE):
            with open(_TOOLS_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            return cache.get(sys_hash)
    except Exception as e:
        print(f"[TOOLS CACHE READ ERROR] {e}", flush=True)
    return None

# â”€â”€â”€ Watermarking (stabilne mapowanie rozmów) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
WM_PATTERN = re.compile(r"<!--\s*PROXY_SID:\s*([a-f0-9]{32})\s*-->")

def _extract_watermark(messages: list[dict]) -> str | None:
    """Scan messages from newest to oldest for a watermark comment."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            m = WM_PATTERN.search(content)
            if m:
                return m.group(1)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    m = WM_PATTERN.search(block.get("text", ""))
                    if m:
                        return m.group(1)
    return None


def _is_actual_subagent(messages: list[dict]) -> bool:
    """True tylko gdy request to faktycznie oddelegowany subagent (nie pierwszy turn głównego agenta)."""
    if len(messages) != 2:
        return False
    sys_content = messages[0].get("content", "") if messages else ""
    if isinstance(sys_content, list):
        sys_content = " ".join(p.get("text", "") for p in sys_content if isinstance(p, dict) and p.get("type") == "text")
    # Główny agent Trae zawiera pełny prompt interaktywny z "# Doing tasks" i "TraeCode"
    if "You are an interactive agent in TraeCode" in sys_content or "# Doing tasks" in sys_content or "TraeCode" in sys_content:
        return False
    return True


# â”€â”€â”€ Sonda diagnostyczna (zbiera WSZYSTKIE headery + ACL) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _dump_request_diagnostics(raw_request: Request, acl_payload: dict | None, body_str: str):
    """Log all headers, ACL fields, and body fields for correlation analysis."""
    import socket
    fp = DIAG_LOG
    entry = {
        "ts": time.time(),
        "hostname": socket.gethostname(),
        "headers": dict(raw_request.headers),
        "acl_payload": acl_payload,
        "body_fields": list(json.loads(body_str).keys()) if body_str else [],
    }
    try:
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[DIAG] write error: {e}", flush=True)


def _get_sys_hash(messages: list[dict]) -> str:
    """Compute a hash from the system prompt (if any)."""
    for m in messages:
        if m.get("role") == "system":
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return hashlib.md5(c.encode()).hexdigest()
    return ""

def _get_first_user_prompt_text(messages: list[dict]) -> str:
    """Find the FIRST user message in the history and return its plain text content."""
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                parts = [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
                text = " ".join(parts).strip()
            elif isinstance(c, str):
                text = c.strip()
            else:
                text = str(c).strip()
            
            if text:
                m_tag = re.search(r'<user_input>\s*(.*?)\s*</user_input>', text, re.DOTALL)
                if m_tag:
                    return m_tag.group(1).strip()
                return text
    return ""


def _get_user_fp(messages: list[dict]) -> str:
    """Hash the FIRST user prompt to give every new conversation topic a distinct key."""
    first_text = _get_first_user_prompt_text(messages)
    if first_text:
        fp = hashlib.md5(first_text.encode("utf-8")).hexdigest()[:8]
        return fp
    return ""

# â”€â”€â”€ Silent rotation dla limitu 200 wiadomości DeepSeek â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _handle_silent_rotation(conv_key: str, messages: list, conv_state: dict, ds_client, account_idx: int) -> bool:
    """
    Sprawdza czy sesja DeepSeek zbliĹĽa się do limitu ~200 wiadomości.
    Jeśli tak, tworzy nową sesję i przepina stan.
    Returns True jeśli wykonano rotację (full prompt needed).
    """
    state = conv_state.get(conv_key)
    if not state:
        return False
    # ROTACJA WYŁĄCZONA (2026-08-15) na życzenie użytkownika: rozmowa DeepSeek trwa do
    # momentu, aż użytkownik sam zacznie nową rozmowę w Trae (nowy conv_key).
    return False
    # Skip if using official API (no turn limit)
    if state.get("api") == "official":
        return False
    ds_session = state.get("ds_session")
    if not ds_session:
        return False

    print(f"[ROTATION] conv={conv_key[:20]}... msgs={msgs_len} >= 200, rotating session...", flush=True)
    try:
        new_session_id = ds_client.create_session(account_idx)
        print(f"[ROTATION] New DS session: {new_session_id}", flush=True)
        state["ds_session"] = new_session_id
        state["parent_id"] = None
        state["msgs_len"] = len(messages)
        # Invalidate PoW cache for this account
        if hasattr(ds_client, '_cached_pow'):
            ds_client._cached_pow.pop(account_idx, None)
            ds_client._pow_expires.pop(account_idx, 0)
        conv_state[conv_key] = state
        _save_conv_state()
        return True
    except Exception as e:
        print(f"[ROTATION] Failed: {e}", flush=True)
        return False


def _get_conv_key(messages: list[dict], acl_payload: dict | None = None, chat_id: str | None = None) -> str:
    """
    Unique key per conversation.
    
    Priority:
      1. Watermark w odpowiedzi asystenta (odporny na trimowanie)
      2. chat_id od Trae (jeśli kiedyś zaczną wysyłać)
      3. JWT identity + user fingerprint
      4. System prompt + user fingerprint
    """
    # â”€â”€ PRIORYTET 1: Watermark (najstabilniejszy) â”€â”€
    wm_id = _extract_watermark(messages)
    if wm_id:
        print(f"[CONV_KEY] watermark found: {wm_id[:12]}...", flush=True)
        return f"wm_{wm_id}"

    # â”€â”€ PRIORYTET 2: chat_id z Trae â”€â”€
    if chat_id:
        return f"trae_{chat_id}"

    # â”€â”€ PRIORYTET 3: JWT + fingerprint â”€â”€
    user_fp = _get_user_fp(messages)
    if acl_payload:
        # Sprawdź legid jako potencjalny klucz zakładki
        legid = acl_payload.get("legid")
        if isinstance(legid, dict):
            stable_id = legid.get("user") or legid.get("sub") or ""
        elif legid:
            stable_id = str(legid)
        else:
            stable_id = ""
        if stable_id and user_fp:
            return f"jwt_leg_{stable_id}_{user_fp}"
        if stable_id:
            return f"jwt_leg_{stable_id}"
        jwt_id = acl_payload.get("sub") or acl_payload.get("session") or ""
        if jwt_id:
            jwt_hash = hashlib.md5(jwt_id.encode()).hexdigest()[:8]
            if user_fp:
                return f"jwt_{jwt_hash}_{user_fp}"
            return f"jwt_{jwt_hash}"

    # â”€â”€ PRIORYTET 4: Sys hash + user fp (obecna logika, podatna na trim) â”€â”€
    sys_hash = _get_sys_hash(messages)
    if user_fp:
        return f"{sys_hash}_{user_fp}" if sys_hash else user_fp
    return sys_hash


def _handle_official_api_chat(
    req: ChatRequest, conv_key: str, watermark_uuid: str,
    state: dict | None, tools: list[dict] | None, sys_hash: str,
    is_subagent: bool, t0: float,
):
    """
    Handle chat completion via official DeepSeek API (api.deepseek.com).
    Used for MAIN AGENT only. Subagents continue using web chat.
    
    Advantages: no 50-60 turn limit, no Cloudflare/PoW, native JSON tool calls,
    stateless (no session management). Cost: ~$0.015 per conversation.
    """
    # Prepare messages for official API
    api_messages = []
    for m in req.messages:
        role = m.get("role")
        content = m.get("content", "")
        
        if role == "tool":
            # Compress large tool results
            if isinstance(content, str) and len(content) > 500000:
                content = f"[Tool result: {len(content)} chars — compressed for context limits]"
            api_messages.append({"role": "tool", "content": content,
                                "tool_call_id": m.get("tool_call_id", "")})
        elif role == "system":
            # Main agent: prepend subagent emphasis + goals
            if not is_subagent:
                # Strip any XML tool call format instructions from Trae's prompt
                # to prevent contradictory signals: native JSON tools vs XML tool calls
                clean_content = re.sub(
                    r'# Tool Call Format.*?(?=\n#|\Z)',
                    '',
                    content,
                    flags=re.DOTALL
                )
                clean_content = re.sub(
                    r'<tool_call[^>]*>.*?</tool_call>',
                    '[use native JSON tool_calls instead of XML]',
                    clean_content,
                    flags=re.DOTALL
                )
                _prepend = (
                    "## đź‘” HIERARCHY: USER (CEO) -> YOU (MANAGER) -> INTERNS (FREE WORKERS)\n\n"
                    "The USER is the CEO. They give orders. You are the MANAGER.\n"
                    "Interns (Task subagents) are your unlimited FREE workforce. They cost NOTHING.\n"
                    "âš ď¸Ź The CEO works on MANY things — code, documents, analysis, research, business,\n"
                    "   planning, creative writing, data work, automation, and more. Adapt to whatever\n"
                    "   the CEO brings. Don't assume it's about code — ask if unsure.\n\n"
                    "YOUR ROLE AS MANAGER:\n"
                    "- Understand the CEO's vision. Read their words carefully. Think before acting.\n"
                    "- Identify WHAT kind of work this is. Is it code? Documents? Research? Planning?\n"
                    "- Plan the work: break the CEO's goal into specific intern-sized tasks.\n"
                    "- Delegate EVERYTHING to interns. Reading files, searching, analyzing, auditing,\n"
                    "  researching, planning, reviewing, writing — all intern work. You assign and review.\n"
                    "- Review intern reports critically. Verify with another intern if needed.\n"
                    "- Synthesize findings into clear answers for the CEO. Make decisions.\n"
                    "- Edit/create files only based on intern evidence (code, docs, configs, any format).\n\n"
                    "CREATIVE INTERN DEPLOYMENT:\n"
                    "- Don't just give interns boring tasks. Use them CREATIVELY.\n"
                    "- Launch parallel teams: intern-1 checks X, intern-2 checks Y, intern-3 compares them.\n"
                    "- Use interns for ANY kind of analysis: code review, document audit, data analysis,\n"
                    "  business research, writing reviews, architecture evaluation, anything.\n"
                    "- Interns can plan, research, compare, critique, suggest, summarize, rewrite.\n"
                    "- If the CEO gives a vague goal, launch interns to explore and report options.\n"
                    "- One intern finds problems, another proposes solutions, a third evaluates them.\n"
                    "- Be clever. The more creative your delegation, the more value the CEO gets.\n\n"
                    "WHAT YOU DO YOURSELF vs WHAT YOU DELEGATE:\n"
                    "- Simple, targeted reads (one known file, one specific search) — do them directly.\n"
                    "- Broad exploration, multi-file research, audits — delegate to interns (Task).\n"
                    "- When in doubt, delegate. MANAGEMENT is your default, not your limit.\n\n"
                    "TALKING TO THE CEO:\n"
                    "- The CEO talks to YOU, not to interns. You are the face of the operation.\n"
                    "- Never say 'let me read that file'. Say 'let me have interns investigate'.\n"
                    "- Explain what interns found in your own words. Add YOUR judgment.\n"
                    "- Ask the CEO questions when the direction or task type is unclear.\n"
                    "- If interns disagree, tell the CEO and explain both sides.\n\n"
                    "COST: You cost money (~$0.01/response). Interns are FREE ($0).\n"
                    "The CEO pays you to THINK, not to READ. Use interns for everything else.\n\n"
                    "TOOL CALL FORMAT:\n"
                    "- Use NATIVE JSON tool_calls to invoke tools (not XML).\n"
                    "- The system provides tool schemas via the 'tools' parameter.\n"
                    "- Call them directly as JSON function calls, NOT as XML tags.\n\n"
                )
                # Extract goals
                goals = extract_goals_from_messages(req.messages)
                if goals:
                    goals_text = format_goals_context(goals)
                    _prepend = goals_text + "\n\n" + _prepend
                api_messages.append({"role": "system", "content": _prepend + clean_content})
            else:
                # Subagent: use minimal prompt (shouldn't normally reach here, but just in case)
                api_messages.append({"role": "system", "content": (
                    "You are a coding subagent. Execute the task using the provided tools. "
                    "Be thorough. Return ALL requested information. Do not chat — just do the task."
                )})
        elif role == "user":
            if isinstance(content, list):
                text_parts = []
                has_images = False
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        text_parts.append(p.get("text", ""))
                    elif isinstance(p, dict) and p.get("type") == "image_url":
                        has_images = True
                content = " ".join(text_parts).strip()
                if has_images:
                    content = "[Images: see conversation above]\n" + content
            api_messages.append({"role": "user", "content": content})
        elif role == "assistant":
            tc = m.get("tool_calls", [])
            if tc:
                api_messages.append({
                    "role": "assistant",
                    "content": m.get("content"),
                    "tool_calls": [{
                        "id": c.get("id", f"call_{uuid.uuid4().hex[:12]}"),
                        "type": "function",
                        "function": {
                            "name": c.get("function", {}).get("name", ""),
                            "arguments": c.get("function", {}).get("arguments", "{}"),
                        }
                    } for c in tc]
                })
            else:
                api_messages.append({"role": "assistant", "content": content or ""})
    
    # DISABLED: debounce dedup has a bug — blocks ALL read-like results, not just duplicates
    # api_messages = deduplicate_tool_results_in_prompt(api_messages, state or {})
    
    # Keep at most 500 messages (practically unlimited per user request)
    if len(api_messages) > 500:
        # Keep system + last 499
        system_msgs = [m for m in api_messages if m.get("role") == "system"]
        non_system = [m for m in api_messages if m.get("role") != "system"][-499:]
        api_messages = system_msgs + non_system
    
    total_chars = sum(len(str(m.get("content", ""))) for m in api_messages)
    print(f"[OFFICIAL API] {len(api_messages)} msgs, ~{total_chars} chars total", flush=True)
    
    # Call official API
    try:
        resp = official_api.chat_completion(
            messages=api_messages,
            model="deepseek-chat",
            tools=tools,
            stream=True,
            max_tokens=req.max_completion_tokens or req.max_tokens,
            temperature=req.temperature,
        )
    except Exception as e:
        print(f"[OFFICIAL API] Failed, falling back to web chat: {e}", flush=True)
        # Fall back — the calling code will handle this by not returning early
        raise HTTPException(502, f"Official API error: {e}")
    
    # Save state with goal
    goal = extract_goals_from_messages(req.messages)
    if state:
        state.update({"msgs_len": len(req.messages), "tools": tools, "original_task_goal": goal,
                      "_ts": time.time(), "incomplete_count": 0, "api": "official"})
    else:
        state = {"ds_session": None, "parent_id": None, "msgs_len": len(req.messages),
                 "tools": tools, "account": 0, "_ts": time.time(), "original_task_goal": goal,
                 "incomplete_count": 0, "api": "official"}
    with _conv_lock:
        _conv_state[conv_key] = state
        _save_conv_state()
    
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    _created = int(time.time())
    _model = req.model
    
    def _chunk(delta: dict, fr: str | None = None) -> str:
        c = {"id": completion_id, "object": "chat.completion.chunk", "created": _created,
             "model": _model, "system_fingerprint": "fp_deepseek_official",
             "choices": [{"index": 0, "delta": delta}]}
        if fr is not None:
            c["choices"][0]["finish_reason"] = fr
        return f"data: {json.dumps(c)}\n\n"
    
    def generate_official():
        full_content = ""
        tools_yielded = 0
        tc_dict: dict[int, dict] = {}
        tc_emitted: set[int] = set()
        
        def _emit_tool_call(idx: int):
            nonlocal tools_yielded
            if idx in tc_emitted or idx not in tc_dict:
                return []
            tcd = tc_dict[idx]
            chunks = []
            chunks.append(_chunk({"tool_calls": [{
                "index": tools_yielded,
                "id": tcd.get("id", ""),
                "type": "function",
                "function": tcd.get("function", {"name": "", "arguments": ""})
            }]}))
            tools_yielded += 1
            tc_emitted.add(idx)
            # â”€â”€ DebounceHook: zapisz wywołanie narzędzia â”€â”€
            try:
                fn = tcd.get("function", {})
                record_tool_call(state or {}, fn.get("name", ""), fn.get("arguments", ""), len(req.messages))
            except Exception:
                pass
            return chunks

        try:
            for chunk in official_api.stream_sse(resp):
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")
                
                # Handle content
                content = delta.get("content", "")
                if content:
                    full_content += content
                    yield _chunk({"content": content})
                
                # Handle tool calls (native JSON format from official API)
                tool_deltas = delta.get("tool_calls", [])
                for tc in tool_deltas:
                    idx = tc.get("index", 0)
                    if idx not in tc_dict:
                        tc_dict[idx] = {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        }
                    else:
                        if tc.get("id"):
                            tc_dict[idx]["id"] = tc["id"]
                    
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tc_dict[idx]["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        tc_dict[idx]["function"]["arguments"] += fn["arguments"]
                
                if finish_reason == "tool_calls":
                    for idx in sorted(tc_dict.keys()):
                        for c in _emit_tool_call(idx):
                            yield c
                
                if finish_reason:
                    break
            
            # Emit any remaining un-emitted tool call buffers
            for idx in sorted(tc_dict.keys()):
                for c in _emit_tool_call(idx):
                    yield c
            
            fr = "tool_calls" if tools_yielded > 0 else "stop"
            yield _chunk({}, fr)
            yield "data: [DONE]\n\n"
            
            print(f"[OFFICIAL API] Done: {len(full_content)} chars, {tools_yielded} tools ({time.time()-t0:.1f}s)", flush=True)
            
            # Update state
            with _conv_lock:
                s = _conv_state.get(conv_key)
                if s:
                    s["msgs_len"] = len(req.messages)
                    s["incomplete_count"] = 0
                    _save_conv_state()
                    
        except GeneratorExit:
            print(f"[OFFICIAL API] Client disconnected", flush=True)
        except Exception as e:
            print(f"[OFFICIAL API] Stream error: {e}", flush=True)
            yield _chunk({"content": f"\n\n*Oficjalne API DeepSeek: stream error — {e}*"})
            yield _chunk({}, "error")
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate_official(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, raw_request: Request):
    t0 = time.time()
    # Log raw request body to see EVERYTHING Trae sends
    body_bytes = await raw_request.body()
    body_str = body_bytes.decode("utf-8", "ignore")
    try:
        raw_json = json.loads(body_str)
        print(f"[RAW REQUEST BODY]", flush=True)
        print(f"  fields: {list(raw_json.keys())}", flush=True)
        for k, v in raw_json.items():
            if k == "messages":
                print(f"  messages: {len(v)} items", flush=True)
            elif k == "tools":
                print(f"  tools: {len(v)} items", flush=True)
                for t in v:
                    fn = t.get("function", t)
                    print(f"    - {fn.get('name', '?')}: params={list(fn.get('parameters', {}).get('properties', {}).keys())}", flush=True)
            elif k == "stream":
                print(f"  stream: {v}", flush=True)
            else:
                vs = json.dumps(v, ensure_ascii=False)
                print(f"  {k}: {vs[:200]}", flush=True)

    except Exception as e:
        print(f"[RAW REQUEST PARSE ERROR] {e}", flush=True)
    # Extract acl-token payload for conv_key
    acl_payload = None
    tools = None  # initialize to avoid UnboundLocalError
    acl_token = raw_request.headers.get("acl-token", "")
    if acl_token and acl_token.count(".") == 2:
        try:
            payload_b64 = acl_token.split(".")[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            acl_payload = json.loads(base64.b64decode(payload_b64))
            print(f"[ACL TOKEN] payload keys: {list(acl_payload.keys())}", flush=True)
            for pk in ["sub", "session", "conv", "chat", "jid", "sid", "legid"]:
                if pk in acl_payload:
                    val = acl_payload[pk]
                    val_str = str(val)[:200]
                    print(f"[ACL TOKEN] {pk}: {val_str}", flush=True)
                    with open(TOKEN_LOG, "a", encoding="utf-8") as tf:
                        tf.write(f"{pk}: {val_str}\n")
        except Exception as e:
            print(f"[ACL TOKEN] decode error: {e}", flush=True)
    # â”€â”€ Sonda diagnostyczna â”€â”€
    try:
        _dump_request_diagnostics(raw_request, acl_payload, body_str)
    except Exception as e:
        print(f"[DIAG] error: {e}", flush=True)

    roles = {m.get("role") for m in req.messages}
    tcs = sum(1 for m in req.messages if m.get("tool_calls"))
    print(f"[REQUEST] roles={roles} tools={tcs} msgs={len(req.messages)}", flush=True)
    # Log all messages structure for debugging
    with open(MSG_LOG, "a", encoding="utf-8") as mf:
        mf.write(f"\n--- {time.time():.0f} msgs={len(req.messages)} ---\n")
        for mi, m in enumerate(req.messages):
            c = m.get("content", "")
            role = m.get("role", "?")
            if isinstance(c, list):
                mf.write(f"  msg[{mi}] role={role} {len(c)} parts\n")
                for pi, p in enumerate(c):
                    if isinstance(p, dict) and p.get("type") == "text":
                        t = p.get("text", "")
                        tag = "<user_input>" if "<user_input>" in t else ("<system-reminder>" if "<system-reminder>" in t else "other")
                        mf.write(f"    part[{pi}] {tag}: {t[:100]}\n")
            else:
                mf.write(f"  msg[{mi}] role={role} content={str(c)[:120]}\n")
    # Log full system prompt (once per conversation)
    sys_hash = _get_sys_hash(req.messages)
    conv_key = _get_conv_key(req.messages, acl_payload, raw_json.get("chat_id"))

    # â”€â”€ Watermark UUID: wyciągnij z conv_key lub wygeneruj nowy â”€â”€
    if conv_key.startswith("wm_"):
        watermark_uuid = conv_key[3:]  # already has UUID
    else:
        watermark_uuid = uuid.uuid4().hex  # fresh UUID for new conversations

    if acl_payload:
        raw_legid = acl_payload.get("legid", "?")
        print(f"[CONV_KEY] legid={raw_legid} conv_key={conv_key}", flush=True)
        with open(LEGID_LOG, "a", encoding="utf-8") as lf:
            lf.write(f"{time.time():.0f} conv_key={conv_key} legid={raw_legid}\n")
    for i, m in enumerate(req.messages):
        if m.get("role") == "system":
            c = m.get("content", "")
            with open(SYS_PROMPT_LOG, "w", encoding="utf-8") as f:
                f.write(c if isinstance(c, str) else json.dumps(c, indent=2))
            break
    # Log last user/tool messages for debugging
    for m in list(req.messages)[-5:]:
        if m.get("role") in ("tool", "user"):
            c = m.get("content", "")
            tid = m.get("tool_call_id", "")
            print(f"  [{m['role']}] {'id='+tid if tid else ''} content={len(c)} chars: {repr(c[:120])}", flush=True)

    # Decide whether to resume or start a new DeepSeek conversation
    with _conv_lock:
        state = _conv_state.get(conv_key)
    if state:
        print(f"[DEBUG] state: parent_id={state.get('parent_id')!r} msgs_len={state.get('msgs_len')} req_len={len(req.messages)} resume_cond={'parent_is_not_none' if state.get('parent_id') is not None else 'parent_is_none'} {'len_ok' if len(req.messages) > state.get('msgs_len', 0) else 'len_not_ok'}", flush=True)
    else:
        print(f"[DEBUG] no state for conv_key={conv_key[:24]}...", flush=True)
    # Check for explicit [new chat] or [reset session] marker ONLY in the latest user message
    last_user_msg = None
    for m in reversed(req.messages):
        if m.get("role") == "user":
            last_user_msg = m
            break
    if last_user_msg:
        u_content = last_user_msg.get("content", "")
        if isinstance(u_content, list):
            u_content = " ".join(p.get("text", "") for p in u_content if isinstance(p, dict) and p.get("type") == "text")
        if isinstance(u_content, str):
            clean_u = _clean_system_reminders(u_content).strip()
            if re.fullmatch(r'\[(?:new\s+chat|reset\s+session|nowy\s+czat|nowa\s+sesja)\]', clean_u, re.IGNORECASE):
                print(f"[NEW CHAT] explicit reset marker detected in latest user message, clearing conv state for {conv_key[:24]}...", flush=True)
                with _conv_lock:
                    _conv_state.pop(conv_key, None)
                    _save_conv_state()
                state = None
    # â”€â”€ Silent rotation â”€â”€
    # (przeniesione poniĹĽej po definicji account_idx)

    # Initialize tools from request
    tools = req.tools

    # Detect if request is from subagent
    is_subagent = _is_actual_subagent(req.messages)

    # Detect model type and configuration from requested model name or default config
    req_model_lower = (req.model or "").lower()
    is_vision = "vision" in req_model_lower
    image_files = []
    if is_vision:
        image_files = _extract_images(req.messages)
        print(f"[VISION] Found {len(image_files)} image(s) in request", flush=True)

    # Rozpoznanie profilu (Szybki / Ekspert / Wizja / Subagent)
    if is_vision:
        model_type = "vision"
        thinking_enabled = WIZJA_MYSLEKIE or ("think" in req_model_lower)
        search_enabled = False
    elif is_subagent:
        # SUBAGENT: profil Expert (model_type='expert'). Myślenie zostaje WŁĄCZONE
        # (jak użytkownik zawsze miał) — problem nie leży w samym myśleniu, tylko w tym,
        # że proxy nie oddziela CoT (thinking) od odpowiedzi. To naprawiamy w parserze
        # strumienia, a nie przez wyłączanie myślenia.
        model_type = "expert"
        thinking_enabled = EKSPERT_MYSLEKIE
        search_enabled = EKSPERT_SZUKANIE or ("search" in req_model_lower)
        print(f"[SUBAGENT] Expert profile (model_type='expert', thinking={thinking_enabled}, search={search_enabled})", flush=True)
    elif "fast" in req_model_lower or "flash" in req_model_lower:
        # Pełne usunięcie profilu Flash: modele "fast/flash" traktowane jak Expert
        model_type = "expert"
        if "nothink" in req_model_lower or "no_think" in req_model_lower:
            thinking_enabled = False
        else:
            thinking_enabled = EKSPERT_MYSLEKIE
        search_enabled = "search" in req_model_lower or EKSPERT_SZUKANIE
    else:
        # Domyślnie tryb Ekspert (deepseek-v4-pro / deepseek-expert)
        model_type = "expert"
        if "nothink" in req_model_lower or "no_think" in req_model_lower:
            thinking_enabled = False
        else:
            thinking_enabled = EKSPERT_MYSLEKIE
        search_enabled = "search" in req_model_lower or EKSPERT_SZUKANIE

    print(f"[ROUTER] Model '{req.model}' -> model_type='{model_type}', thinking={thinking_enabled}, search={search_enabled}", flush=True)

    # Disable Trae XML tools for search and vision to allow native DeepSeek operation
    if search_enabled or is_vision:
        tools = None
        print(f"[TOOLS] Disabled for search/vision model '{req.model}'", flush=True)

    # Handle tool_choice
    if req.tool_choice:
        if req.tool_choice == "none":
            tools = None
            print(f"[TOOL_CHOICE] 'none' — tools disabled", flush=True)
        elif req.tool_choice == "required":
            print(f"[TOOL_CHOICE] 'required' — will append instruction to prompt", flush=True)
        elif isinstance(req.tool_choice, dict) and tools:
            fn_name = req.tool_choice.get("function", {}).get("name", "")
            if fn_name:
                tools = [t for t in tools if t.get("function", {}).get("name") == fn_name]
                print(f"[TOOL_CHOICE] filtered to '{fn_name}' — {len(tools)} tool(s) remaining", flush=True)

    # ── New conversation vs Resume detection ──
    first_user_prompt = _get_first_user_prompt_text(req.messages)
    has_assistant_messages = any(m.get("role") == "assistant" for m in req.messages)
    is_new_conversation = False

    if state:
        prev_first_prompt = state.get("first_user_prompt")
        prev_msgs_len = state.get("msgs_len", 0)
        curr_msgs_len = len(req.messages)

        # Invariant 1: Jeśli stan ma parent_id (asystent już wcześniej odpowiadał), ale w requeście NIE MA żadnej wiadomości asystenta,
        # to bez względu na treść promptu (nawet jeśli to 'hej' po 'hej') jest to NOWY CZAT.
        if state.get("parent_id") is not None and not has_assistant_messages:
            print(f"[NEW CHAT] No assistant messages in request while state has parent_id -> Forcing fresh DeepSeek session", flush=True)
            is_new_conversation = True

        # Invariant 2: Treść pierwszej wiadomości użytkownika uległa zmianie
        elif prev_first_prompt and first_user_prompt and prev_first_prompt != first_user_prompt:
            print(f"[NEW CHAT] First prompt changed from '{prev_first_prompt[:30]}...' to '{first_user_prompt[:30]}...' -> Forcing fresh DeepSeek session", flush=True)
            is_new_conversation = True

        # Invariant 3: Liczba wiadomości drastycznie spadła (np. z 8+ do <= 4), co oznacza kliknięcie 'New Chat' w Trae
        elif curr_msgs_len <= 4 and prev_msgs_len >= 8:
            print(f"[NEW CHAT] Message count dropped ({curr_msgs_len} <= 4 vs previous {prev_msgs_len}) -> Forcing fresh DeepSeek session", flush=True)
            is_new_conversation = True

    if is_new_conversation:
        state["parent_id"] = None
        state["first_user_prompt"] = first_user_prompt
        resume = False
    else:
        resume = state and state.get("parent_id") is not None

    if is_vision:
        resume = False  # vision always creates a new session (images must be uploaded each time)
    elif state and (state.get("is_vision") or (state.get("model_type") and state.get("model_type") != model_type)):
        print(f"[MODEL CHANGE] Model switched from {state.get('model_type')} (vision={state.get('is_vision')}) to {model_type} (vision={is_vision}) -> forcing fresh session", flush=True)
        state["parent_id"] = None
        resume = False
    ref_file_ids = []

    # Pick account for this conversation
    if state and "account" in state:
        account_idx = state["account"]
        if is_subagent:
            with _slot_busy_lock:
                is_curr_busy = _slot_busy[account_idx]
            if is_curr_busy:
                free_acc = ap.pick_for_conv(conv_key, is_subagent=True)
                if free_acc != account_idx:
                    print(f"[SUBAGENT] Slot {account_idx} busy -> reassigning to free slot {free_acc}", flush=True)
                    account_idx = free_acc
    else:
        account_idx = ap.pick_for_conv(conv_key, is_subagent=is_subagent)
    # Fall back to valid slot if selected one is invalid
    if not ap.is_valid(account_idx):
        valid = [i for i in range(MAX_ACCOUNTS) if ap.is_valid(i)]
        if valid:
            account_idx = valid[0]
            print(f"[ACCOUNT] fallback to valid slot {account_idx}", flush=True)
        else:
            # Bez zalogowanych kont NIE otwieramy Chrome automatycznie.
            # Zwracamy czytelny blad z instrukcja - klient musi uruchomic login_slot.bat 0
            raise HTTPException(503,
                "Brak zalogowanych kont DeepSeek. Otworz DRUGIE okno CMD w tym folderze "
                "i uruchom: login_slot.bat 0   (zaloguj sie, potem zamknij przegladarke) "
                "i powtorz zapytanie.")
    print(f"[ACCOUNT] conv_key={conv_key[:24]}... account_idx={account_idx}", flush=True)

    # CRITICAL: Jeśli konto uległo zmianie względem zapisanego stanu,
    # stary ds_session NIE ISTNIEJE na nowym koncie! Wymuszamy nową sesję.
    if state and state.get("account") is not None and state.get("account") != account_idx:
        print(f"[ACCOUNT CHANGE] Account switched from {state.get('account')} to {account_idx} -> forcing fresh session", flush=True)
        state["parent_id"] = None
        state["account"] = account_idx
        resume = False

    _ensure_slot(account_idx)

    # â”€â”€ Silent rotation: jeśli sesja DeepSeek ma >= 190 wiadomości â”€â”€
    if state:
        needs_full_prompt = _handle_silent_rotation(conv_key, req.messages, _conv_state, ds, account_idx)
        if needs_full_prompt:
            state = _conv_state.get(conv_key)
            print(f"[ROTATION] Session rotated (parent cleared -> forced NEW SESSION below)", flush=True)

    # Resolve tools: use from request, or from cache/persisted state
    if not search_enabled and not is_vision:
        if not tools and state:
            tools = state.get("tools")
        if not tools and not state:
            tools = _load_tools(sys_hash)
    else:
        tools = None

    # ── Tryb czysty: odciąż kontekst — zostaw tylko narzędzia do przeglądania plików ──
    if _clean_mode_enabled() and tools:
        _keep = {"Read", "Glob", "Grep", "LS", "SearchCodebase"}
        _filtered = []
        for _t in tools:
            if isinstance(_t, dict):
                _fn = _t.get("function", _t)
                if isinstance(_fn, dict) and _fn.get("name") in _keep:
                    _filtered.append(_t)
        print(f"[CLEAN] Tools filtered: {len(tools)} -> {len(_filtered)} (read-only file browsing)", flush=True)
        tools = _filtered

    # â”€â”€ HYBRID ARCHITECTURE ROUTING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Main agent (3+ msgs) -> official DeepSeek API ($0.015/konwersację)
    # Subagents (exactly 2 msgs: system+task) -> free web chat
    # Vision -> web chat (official API image support varies)
    # Detection proven from logs: subagent requests always have exactly 2 msgs.
    proxy_mode = _get_mode()
    is_subagent = _is_actual_subagent(req.messages)
    _clean_enabled = _clean_mode_enabled()
    if proxy_mode in ("web", "free", "biedny", "free_first") or _clean_enabled or is_vision or model_type != "expert":
        use_official_api = False
    else:  # auto
        use_official_api = (not is_subagent and not is_vision and official_api.available)
    
    if use_official_api:
        print(f"[HYBRID] Main agent detected ({len(req.messages)} msgs) -> routing to official API (mode={proxy_mode})", flush=True)
        return _handle_official_api_chat(
            req, conv_key, watermark_uuid, state, tools, sys_hash,
            is_subagent, t0
        )
    elif is_subagent:
        print(f"[HYBRID] Subagent detected (2 msgs) -> routing to web chat", flush=True)
    else:
        reason = "resume" if resume else ("vision" if is_vision else f"mode={proxy_mode}")
        print(f"[HYBRID] Using web chat ({reason}, msgs={len(req.messages)})", flush=True)

    resume_did_full_prompt = False  # Flaga: w RESUME zbudowano juĹĽ full prompt (np. przy trimowaniu)
    if resume:
        chat_id = state["ds_session"]
        parent_id = state["parent_id"]
        # ROTACJA WYŁĄCZONA (2026-08-15): kontynuujemy ZAWSZE w tej samej sesji DeepSeek.
        # Nowa sesja powstaje TYLKO gdy użytkownik zacznie nową rozmowę w Trae (nowy conv_key).
        # Duży prompt (system + schematy narzędzi) wysyłamy tylko na starcie; tu wysyłamy
        # wyłącznie nowe wiadomości (user + wyniki tooli) — bez schematów, bez celu.
        if len(req.messages) == state["msgs_len"]:
            # RETRY / kontynuacja po niepełnym strumieniu: wyślij tylko ostatnią wiadomość
            new_msgs = [m for m in req.messages[-1:] if m.get("role") != "system"]
            print(f"[RESUME] RETRY/continue (same msgs_len={state['msgs_len']}), last msg only", flush=True)
            prompt = _build_prompt(new_msgs, tools=None, state=state)
        elif len(req.messages) > state["msgs_len"]:
            # Normalny resume: tylko nowe wiadomości (bez system, bez schematów narzędzi)
            new_msgs = [m for m in req.messages[state["msgs_len"]:] if m.get("role") != "system"]
            existing_goal = state.get("original_task_goal", "")
            if not existing_goal:
                new_goal = extract_goals_from_messages(new_msgs)
                if new_goal:
                    state["original_task_goal"] = new_goal
                    print(f"[GOAL] RESUME: set goal from new msgs", flush=True)
            print(f"[RESUME] ds_session={chat_id} account={account_idx} parent={parent_id} skip={state['msgs_len']} send={len(new_msgs)} new msgs (no schemas re-injected)", flush=True)
            prompt = _build_prompt(new_msgs, tools=None, state=state)
        else:
            # Trae przyciął wiadomości — NIE rotujemy. Kontynuujemy w tej samej sesji,
            # wysyłając tylko ostatnią wiadomość (DeepSeek ma już pełny kontekst po swojej stronie).
            new_msgs = [m for m in req.messages[-1:] if m.get("role") != "system"]
            print(f"[RESUME] Trae trimmed ({len(req.messages)} < {state['msgs_len']}) — continue same session, last msg only", flush=True)
            prompt = _build_prompt(new_msgs, tools=None, state=state)
    if not resume and not resume_did_full_prompt:
        if state:
            print(f"[NEW TURN] conv_key={conv_key[:24]}... old_msgs={state['msgs_len']} cur_msgs={len(req.messages)}", flush=True)
        if tools:
            print(f"[TOOLS] {len(tools)} tool schemas", flush=True)
            for t in tools:
                fn = t.get("function", t)
                print(f"  - {fn.get('name', '?')}", flush=True)
        else:
            print(f"[TOOLS] none available", flush=True)
        if req.tools:
            _save_tools(sys_hash, req.tools)
        # Build prompt with uploaded images for vision model
        ref_file_ids = []
        chat_id = ds.create_session(account_idx)
        parent_id = None
        clean_msgs = []
        for m in req.messages:
            if m.get("role") == "tool":
                m2 = dict(m)
                clean_msgs.append(m2)
            elif is_vision and isinstance(m.get("content"), list):
                # Strip image_url blocks, keep only text for prompt
                m2 = dict(m)
                text_parts = []
                for p in m["content"]:
                    if isinstance(p, dict) and p.get("type") == "text":
                        text_parts.append(p.get("text", ""))
                m2["content"] = " ".join(text_parts).strip()
                clean_msgs.append(m2)
            else:
                clean_msgs.append(m)
        if is_vision and image_files:
            print(f"[VISION] Uploading {len(image_files)} image(s) to DeepSeek...", flush=True)
            # #region debug-point B
            try:
                _ur.urlopen(_ur.Request("http://127.0.0.1:7777/event",
                    data=_js.dumps({"sessionId":"vision-image-not-passed","runId":"pre","hypothesisId":"B","location":"server.py:1445","msg":"[DEBUG] before_upload","data":{"image_count":len(image_files),"images":[{"type":"base64" if "base64" in f else "url","size":len(f.get("base64","")) if "base64" in f else 0} for f in image_files[:3]]}}).encode(),
                    headers={"Content-Type":"application/json"})).read()
            except: pass
            # #endregion
            for idx, img in enumerate(image_files):
                try:
                    if img.get("base64"):
                        b64, mime = _compress_image(img["base64"], img.get("mime_type", "image/png"))
                        file_data = base64.b64decode(b64)
                        ext = mime.split("/")[-1] if "/" in mime else "png"
                        file_id = ds.upload_file(account_idx, file_data, f"image_{idx+1}.{ext}", mime)
                        ref_file_ids.append(file_id)
                        print(f"[VISION] Uploaded image {idx+1}: {file_id}", flush=True)
                    elif img.get("url"):
                        import requests as req_lib
                        resp = req_lib.get(img["url"], timeout=30)
                        if resp.status_code == 200:
                            mime = resp.headers.get("content-type", "image/png")
                            ext = mime.split("/")[-1] if "/" in mime else "png"
                            file_id = ds.upload_file(account_idx, resp.content, f"image_{idx+1}.{ext}", mime)
                            ref_file_ids.append(file_id)
                            print(f"[VISION] Uploaded image {idx+1} from URL: {file_id}", flush=True)
                except Exception as e:
                    print(f"[VISION] Failed to upload image {idx+1}: {e}", flush=True)
        # ── Prompt engineering: search/vision, clean mode, subagents, main agent ──
        if clean_msgs and clean_msgs[0].get("role") == "system":
            if search_enabled or is_vision:
                _sv_prompt = _get_search_vision_prompt()
                clean_msgs[0] = dict(clean_msgs[0], content=_sv_prompt)
                print(f"[SEARCH/VISION] Model='{req.model}' — system prompt replaced by prompt3.txt ({len(_sv_prompt)} chars)", flush=True)
            elif _clean_mode_enabled():
                orig_sys = clean_msgs[0].get("content", "")
                if not orig_sys or "TraeCode" in orig_sys or "interactive agent" in orig_sys or "# Doing tasks" in orig_sys:
                    clean_msgs[0] = dict(clean_msgs[0], content=_get_clean_prompt())
                    print(f"[CLEAN] Mode=clean — Trae prompt replaced by prompt2.txt ({len(clean_msgs[0]['content'])} chars)", flush=True)
                else:
                    print(f"[CLEAN] Preserved explicit custom system prompt ({len(orig_sys)} chars)", flush=True)
            elif is_subagent:
                # SUBAGENT for coding: replace 15KB Trae prompt with minimal task-focused version
                _orig_len = len(clean_msgs[0]["content"])
                clean_msgs[0] = dict(clean_msgs[0], content=(
                    "You are a subagent. Execute the task below using the provided tools.\n"
                    "Be thorough and complete. Return ALL requested information.\n"
                    "Do not chat, explain, or ask questions — just do the task and report results.\n"
                    "Use tools aggressively. Read files, search code, analyze data — whatever it takes."
                ))
                print(f"[SUBAGENT] Real subagent detected. Prompt: {_orig_len}→{len(clean_msgs[0]['content'])} chars (saved {_orig_len - len(clean_msgs[0]['content'])})", flush=True)
            else:
                # MAIN AGENT for coding: different prompt depending on mode
                _mode = _get_mode()
                if _mode == "free":
                    _prepend = (
                        "## 💥 YOU ARE A VERSATILE ASSISTANT\n\n"
                        "You help the user with ANYTHING that is NOT programming. The user does\n"
                        "many different things — adapt to whatever they bring. Do NOT assume it's code.\n\n"
                        "YOUR ROLE:\n"
                        "- Understand the user's goal. Clarify if needed. Be helpful.\n"
                        "- For simple tasks: answer directly with your own knowledge.\n"
                        "- For tasks involving files: use subagents (Task tool) to read and search.\n"
                        "- Launch subagents in PARALLEL when checking multiple files.\n"
                        "- Review subagent findings, then present clear results to the user.\n"
                        "- Edit/create files when needed (any format: txt, md, csv, json, config, etc.).\n\n"
                        "HOW YOU WORK:\n"
                        "- Think first. Plan your approach. Then act.\n"
                        "- For file-heavy tasks: delegate reading to subagents — keeps your context clean.\n"
                        "- For non-file tasks: answer directly. You have knowledge, use it.\n"
                        "- Be concise but thorough. Quality over quantity.\n"
                        "- Ask clarifying questions when the request is vague.\n"
                        "- If the user mentions files, launch subagents to read them proactively.\n"
                        "- You can do ANYTHING that isn't coding: writing, analysis, research,\n"
                        "  planning, calculations, translations, summaries, brainstorming, editing,\n"
                        "  formatting, comparing, organizing, explaining, teaching — anything.\n\n"
                        "NOTE: You run on FREE web chat. Be efficient with context (~32K limit).\n"
                        "Use subagents for heavy reading. Keep responses focused.\n\n"
                    )
                else:
                    _prepend = (
                        "## ⚠️ CRITICAL — USE SUBAGENTS FOR EVERYTHING NON-TRIVIAL\n"
                        "You are a COORDINATOR, not a worker. Your role:\n"
                        "- Talk to the user, ask questions, explain results\n"
                        "- Launch subagents (Task tool) for ALL reading, searching, analyzing, auditing\n"
                        "- Launch subagents in PARALLEL for independent work — multiple at once\n"
                        "- After subagents finish, summarize and present results to user\n"
                        "- Write final code/document changes based on subagent findings\n"
                        "WHY: Every file you Read() fills your context window. Subagents use their OWN context.\n"
                        "Delegating reads/searches keeps YOUR context free for thinking and coordinating.\n"
                        "DO NOT use Read/Glob/Grep/SearchCodebase yourself if a subagent can do it.\n"
                        "DO NOT read files one-by-one — launch parallel subagents instead.\n\n"
                    )
                    if _mode == "web":
                        _prepend += (
                            "## NOTE: You are running on the FREE web chat (limited context ~32K).\n"
                            "Be efficient. Avoid huge tool results. Use subagents aggressively.\n\n"
                        )
                clean_msgs[0] = dict(clean_msgs[0], content=_prepend + clean_msgs[0]["content"])
                print(f"[MAIN] Mode={_mode} — prepended prompt (+{len(_prepend)} chars). Total: {len(clean_msgs[0]['content'])} chars", flush=True)
        # ── Persistent Goal Injection: wyciągnij cele ze wszystkich wiadomości użytkownika ──
        # Tryb czysty: bez wstrzykiwania <critical_directive> / ORIGINAL GOAL — czysty kontekst.
        goals = extract_goals_from_messages(req.messages) if (not search_enabled and not is_vision and not _clean_mode_enabled()) else ""
        # ── Semantic summary + proactive rotation warning (web chat only) ──
        conv_summary = ""
        rotation_warning = ""
        if not is_subagent and not search_enabled and not is_vision:
            # For web chat, check if we need proactive rotation warning
            if state and state.get("msgs_len", 0) >= 45:
                rotation_warning = get_rotation_warning(state["msgs_len"])
            conv_summary = build_conversation_summary(req.messages) if len(req.messages) > 10 else ""
        
        prefix_parts = []
        if goals:
            prefix_parts.append(format_goals_context(goals))
            print(f"[GOALS] Extracted goals from {len(req.messages)} msgs, injecting into prompt", flush=True)
        if rotation_warning:
            prefix_parts.append(rotation_warning)
        if conv_summary:
            prefix_parts.append(conv_summary)
        
        base_prompt = _build_prompt(clean_msgs, tools=tools, images=None if (search_enabled or is_vision) else image_files)
        if prefix_parts:
            prompt = "\n\n".join(prefix_parts) + "\n\n" + base_prompt
        else:
            prompt = base_prompt
        state = {"ds_session": chat_id, "parent_id": None, "msgs_len": len(req.messages), "tools": tools,
                 "account": account_idx, "_ts": time.time(), "original_task_goal": goals, "incomplete_count": 0,
                 "model_type": model_type, "is_vision": is_vision, "first_user_prompt": first_user_prompt}
        with _conv_lock:
            _conv_state[conv_key] = state
            _save_conv_state()
        print(f"[NEW SESSION] account={account_idx} {chat_id} prompt={len(prompt)} chars msgs={len(req.messages)} ({time.time()-t0:.1f}s)", flush=True)

    print(f"[TIMING] PoW+solve+stream setup...", flush=True)
    max_tok = req.max_completion_tokens or req.max_tokens
    # #region debug-point C
    try:
        _ur.urlopen(_ur.Request("http://127.0.0.1:7777/event",
            data=_js.dumps({"sessionId":"vision-image-not-passed","runId":"pre","hypothesisId":"C","location":"server.py:1608","msg":"[DEBUG] before_api_call","data":{"model_type":model_type,"prompt_len":len(prompt),"has_image_tag":"<image>" in prompt,"ref_file_ids":ref_file_ids[:5],"prompt_tail":prompt[-300:]}}).encode(),
            headers={"Content-Type":"application/json"})).read()
    except: pass
    # #endregion

    result = None
    migrated = False
    # ── Subagent Circuit Breaker timing ──
    subagent_timing_key = record_subagent_start() if is_subagent else None
    subagent_stream_start = time.time() if is_subagent else 0
    for attempt in range(2):  # max 1 migration
        try:
            # ── Chunked Ingestion with Immediate Abort dla dużych promptów (> 50k znaków) ──
            # Wewnątrz pętli attempt, żeby błędy ingestii (rate-limit, "Server is busy")
            # trafiały do tej samej obsługi migracji co błędy streamu — zamiast 500.
            # Idempotentne: po reaktywnym chunkowaniu (30k) prompt jest mały i blok się pomija.
            if len(prompt) > CHUNK_THRESHOLD:
                chunks = _chunk_oversized_prompt(prompt, CHUNK_THRESHOLD)
                if len(chunks) > 1:
                    if not chat_id:
                        chat_id = ds.create_session(account_idx)
                    print(f"[CHUNKED INGESTION] Prompt ({len(prompt)} chars) > {CHUNK_THRESHOLD} -> split into {len(chunks)} chunks for session {chat_id}", flush=True)
                    current_parent = parent_id
                    for c_idx, c_text in enumerate(chunks[:-1]):
                        t_c0 = time.time()
                        print(f"[CHUNKED INGESTION] Ingesting chunk {c_idx+1}/{len(chunks)} ({len(c_text)} chars) with parent_id={current_parent}...", flush=True)
                        new_pid = ds.ingest_chunk_fast(account_idx, chat_id, c_text, parent_message_id=current_parent, thinking_enabled=False)
                        if new_pid is not None:
                            current_parent = new_pid
                            print(f"[CHUNKED INGESTION] Chunk {c_idx+1} ingested in {time.time()-t_c0:.2f}s -> parent_id={current_parent}", flush=True)
                        else:
                            print(f"[CHUNKED INGESTION] Warning: chunk {c_idx+1} returned None parent_id", flush=True)
                    parent_id = current_parent
                    prompt = chunks[-1]
                    if state:
                        state["ds_session"] = chat_id
                        state["parent_id"] = parent_id
                        with _conv_lock:
                            _conv_state[conv_key] = state
                            _save_conv_state()
                    print(f"[CHUNKED INGESTION] Ingestion complete. Final chunk {len(chunks)} ({len(prompt)} chars) ready for stream (parent_id={parent_id})", flush=True)
            result = ds.stream_completion(account_idx, chat_id, prompt, parent_id, max_tok, req.temperature, req.top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled)
            break
        except Exception as e:
            err_str = str(e).lower()
            if not migrated and ("content is too long" in err_str or "input_exceeds_limit" in err_str):
                # Poziom 2: Reaktywny podział na mniejsze paczki (30k) w nowej sesji
                smaller_chunks = _chunk_oversized_prompt(prompt, 30000)
                if len(smaller_chunks) > 1:
                    print(f"[REACTIVE CHUNKING] Splitting prompt into {len(smaller_chunks)} smaller 30k chunks in fresh session...", flush=True)
                    chat_id = ds.create_session(account_idx)
                    cur_p = None
                    for sc_idx, sc_text in enumerate(smaller_chunks[:-1]):
                        new_p = ds.ingest_chunk_fast(account_idx, chat_id, sc_text, parent_message_id=cur_p, thinking_enabled=False)
                        if new_p is not None:
                            cur_p = new_p
                        else:
                            print(f"[REACTIVE CHUNKING] Warning: chunk {sc_idx+1} returned None parent_id", flush=True)
                    parent_id = cur_p
                    prompt = smaller_chunks[-1]
                    if state:
                        state["ds_session"] = chat_id
                        state["parent_id"] = parent_id
                        with _conv_lock:
                            _conv_state[conv_key] = state
                            _save_conv_state()
                    migrated = True
                    continue

                proxy_mode_now = _get_mode()
                # free_first mode: fall back to official API with FULL context instead of crushing
                if proxy_mode_now == "free_first" and official_api.available and not is_subagent and not _clean_enabled:
                    print(f"[FREEFIRST] Content too long → switching to official API with full context", flush=True)
                    # Clear web chat state so next request doesn't try to resume dead session
                    with _conv_lock:
                        _conv_state.pop(conv_key, None)
                        _save_conv_state()
                    return _handle_official_api_chat(
                        req, conv_key, watermark_uuid, None, tools, sys_hash,
                        is_subagent, t0
                    )
                print(f"[CONTEXT-OVERFLOW] DS context exceeded, crushing tool results for web chat...", flush=True)
                # Clear old state and build a heavily compressed full-prompt for new session
                with _conv_lock:
                    _conv_state.pop(conv_key, None)
                    _save_conv_state()
                chat_id = ds.create_session(account_idx)
                parent_id = None
                # Crush ALL tool results — web chat can't handle raw results on rebuild
                crushed_msgs = _crush_tool_results(req.messages)
                prompt = _build_prompt(crushed_msgs, tools=tools, images=image_files, state=state)
                saved_goal = state.get("original_task_goal", "") if state else (goals if isinstance(goals, str) else "")
                prompt = "## NOTE: Tool results above are summaries. ACT now, don't re-read.\n\n" + prompt
                is_vision = model_type == "vision"
                print(f"[CONTEXT-OVERFLOW] New session {chat_id}, crushed={len(prompt)} chars (was {len(req.messages)} msgs)", flush=True)
                state = {"ds_session": chat_id, "parent_id": None, "msgs_len": len(req.messages), "tools": tools, "account": account_idx, "_ts": time.time(), "original_task_goal": saved_goal, "incomplete_count": 0, "model_type": model_type, "is_vision": is_vision}
                with _conv_lock:
                    _conv_state[conv_key] = state
                    _save_conv_state()
                migrated = True  # block further migration attempts
                continue  # retry the attempt loop
            if not ENABLE_ACCOUNT_MIGRATION or migrated or ("busy after" not in err_str and "rate_limit" not in err_str.lower()):
                print(f"[ERROR] stream_completion failed: {e}", flush=True)
                raise HTTPException(502, f"Upstream error: {e}")
            print(f"[MIGRATE] Account {account_idx} exhausted, looking for alternative...", flush=True)
            now_migrate = time.time()
            alt = [i for i in range(MAX_ACCOUNTS) if i != account_idx and ap.is_valid(i) and now_migrate >= _rate_limited_until[i]]
            if not alt:
                alt = [i for i in range(MAX_ACCOUNTS) if i != account_idx and ap.is_valid(i)]
            if not alt:
                print(f"[MIGRATE] No alternative account available, giving up", flush=True)
                raise HTTPException(502, f"Upstream error: {e}")
            new_idx = ap.pick_for_conv(conv_key)
            if new_idx == account_idx:
                new_idx = alt[0]
            print(f"[MIGRATE] Moving conv {conv_key[:24]}... from account {account_idx} to {new_idx}", flush=True)
            account_idx = new_idx
            _ensure_slot(account_idx)
            chat_id = ds.create_session(account_idx)
            parent_id = None
            clean_msgs = []
            for m in req.messages:
                if m.get("role") == "tool":
                    m2 = dict(m)
                    clean_msgs.append(m2)
                elif is_vision and isinstance(m.get("content"), list):
                    m2 = dict(m)
                    text_parts = []
                    for p in m["content"]:
                        if isinstance(p, dict) and p.get("type") == "text":
                            text_parts.append(p.get("text", ""))
                    m2["content"] = " ".join(text_parts).strip()
                    clean_msgs.append(m2)
                else:
                    clean_msgs.append(m)
            if is_vision and image_files and not ref_file_ids:
                print(f"[VISION] Re-uploading {len(image_files)} image(s) for migration...", flush=True)
                for idx, img in enumerate(image_files):
                    try:
                        if img.get("base64"):
                            b64, mime = _compress_image(img["base64"], img.get("mime_type", "image/png"))
                            file_data = base64.b64decode(b64)
                            ext = mime.split("/")[-1] if "/" in mime else "png"
                            file_id = ds.upload_file(account_idx, file_data, f"image_{idx+1}.{ext}", mime)
                            ref_file_ids.append(file_id)
                            print(f"[VISION] Re-uploaded image {idx+1}: {file_id}", flush=True)
                        elif img.get("url"):
                            import requests as req_lib
                            resp = req_lib.get(img["url"], timeout=30)
                            if resp.status_code == 200:
                                mime = resp.headers.get("content-type", "image/png")
                                ext = mime.split("/")[-1] if "/" in mime else "png"
                                file_id = ds.upload_file(account_idx, resp.content, f"image_{idx+1}.{ext}", mime)
                                ref_file_ids.append(file_id)
                                print(f"[VISION] Re-uploaded image {idx+1} from URL: {file_id}", flush=True)
                    except Exception as e:
                        print(f"[VISION] Failed to re-upload image {idx+1}: {e}", flush=True)
            saved_goal = state.get("original_task_goal", "") if state else (goals if isinstance(goals, str) else "")
            prompt = _build_prompt(clean_msgs, tools=tools or state.get("tools") if state else None, images=image_files, state=state)
            state = {"ds_session": chat_id, "parent_id": None, "msgs_len": len(req.messages), "tools": tools or state.get("tools") if state else tools, "account": account_idx, "_ts": time.time(), "original_task_goal": saved_goal, "incomplete_count": 0, "model_type": model_type, "is_vision": is_vision}
            with _conv_lock:
                _conv_state[conv_key] = state
                _save_conv_state()
            print(f"[MIGRATE] New session on account {new_idx}: {chat_id}, retrying ({len(prompt)} chars)", flush=True)
            migrated = True
    if result is None:
        ap.reset_slot(account_idx)
        raise HTTPException(401, f"Account {account_idx} session expired. Use POST /v1/login?slot={account_idx}")

    if not isinstance(result, tuple) or len(result) != 2:
        print(f"[ERROR] stream_completion returned: {type(result).__name__} {repr(result)[:200]}", flush=True)
        raise HTTPException(502, "Upstream error")

    stream, result_meta = result
    resp_msg_id = result_meta.get("resp_msg_id")
    # State NOT saved yet — defer until streaming completes successfully
    # to avoid bumping msgs_len on an error that Trae will discard and retry
    print(f"[TIMING] Stream ready ({time.time()-t0:.1f}s, resp_id={resp_msg_id})", flush=True)

    if not req.stream:
        full_text = ""
        with _slot_busy_lock:
            _slot_busy[account_idx] = True
        try:
            for chunk in stream:
                if chunk:
                    full_text += chunk
        except Exception as e:
            raise HTTPException(502, f"Upstream error: {str(e)}")
        finally:
            with _slot_busy_lock:
                _slot_busy[account_idx] = False
        tools = _parse_tool_calls(full_text)
        clean_text = full_text
        if tools:
            for ts, te, _, _ in sorted(tools, key=lambda x: -x[1]):
                clean_text = clean_text[:ts] + clean_text[te:]
            clean_text = clean_text.strip()
        clean_text = _clean_text(clean_text)
        print(f"[TIMING] Response ready ({time.time()-t0:.1f}s)", flush=True)
        msg = {"role": "assistant", "content": clean_text or None}
        if tools:
            msg["tool_calls"] = [
                {"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
                 "function": {"name": name, "arguments": args}}
                for _, _, name, args in tools
            ]
        new_parent = result_meta.get("resp_msg_id") or state.get("parent_id")
        with _conv_lock:
            state["parent_id"] = new_parent
            if tools or full_text.strip():
                state["msgs_len"] = len(req.messages)
            _save_conv_state()
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "system_fingerprint": "fp_deepseek_proxy_v1",
            "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tools else "stop"}],
            "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": max(1, len(full_text) // 4), "total_tokens": (len(prompt) + len(full_text)) // 4},
        }

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    _created = int(time.time())
    _model = req.model

    _stream_usage = {"prompt_tokens": len(prompt) // 4, "completion_tokens": 0, "total_tokens": len(prompt) // 4}

    def _chunk(delta: dict, fr: str | None = None) -> str:
        c = {"id": completion_id, "object": "chat.completion.chunk", "created": _created, "model": _model,
             "system_fingerprint": "fp_deepseek_proxy_v1",
             "choices": [{"index": 0, "delta": delta}]}
        if fr is not None:
            c["choices"][0]["finish_reason"] = fr
            c["usage"] = _stream_usage
        return f"data: {json.dumps(c)}\n\n"

    def generate():
        with _slot_busy_lock:
            _slot_busy[account_idx] = True
        try:
            full = ""
            sent_until = 0
            tools_yielded = 0

            try:
                yield _chunk({"role": "assistant"})
            except GeneratorExit:
                print(f"[DISCONNECT] Client disconnected before stream", flush=True)
                return
            success = False
            try:
                for chunk in _heartbeat_iter(stream):
                    if chunk is _HEARTBEAT_SENTINEL:
                        # Bug 26: podtrzymuj polaczenie SSE podczas ciszy (myslenie/CoT)
                        yield ": keep-alive\n\n"
                        continue
                    if chunk:
                        full += chunk
                        tools = _parse_tool_calls(full)
                        if tools:
                            cursor = sent_until
                            for ts, te, tname, targs in tools:
                                if te <= cursor:
                                    continue
                                if ts > cursor:
                                    text = _STRIP_TAGS.sub("", full[cursor:ts])
                                    print(f"[YIELD] text[{cursor}:{ts}] -> {repr(text[:100])}", flush=True)
                                    yield _chunk({"content": text})
                                print(f"[TC] {tname}({targs[:80]})  span=({ts},{te})", flush=True)
                                # Debug: verify targs deserializes correctly
                                try:
                                    j = json.loads(targs)
                                    for pk, pv in j.items():
                                        print(f"[TC]  param '{pk}': {type(pv).__name__} = {repr(pv)[:100]}", flush=True)
                                except Exception as e:
                                    print(f"[TC]  WARNING targs not valid JSON: {e}", flush=True)
                                tc_id = f"call_{uuid.uuid4().hex[:12]}"
                                yield _chunk({"tool_calls": [{"index": tools_yielded, "id": tc_id, "type": "function", "function": {"name": tname, "arguments": targs}}]})
                                tools_yielded += 1
                                # — DebounceHook: zapisz wywołanie narzędzia w conv_state —
                                try:
                                    targs_dict = json.loads(targs) if isinstance(targs, str) else targs
                                    record_tool_call(state or {}, tname, targs_dict, len(req.messages))
                                except Exception:
                                    pass
                                cursor = te
                            sent_until = cursor
                        else:
                            delta = full[sent_until:]
                            lt = delta.find('<')
                            lb = delta.find('[')
                            cand_pos = [p for p in (lt, lb) if p != -1]
                            first_delim = min(cand_pos) if cand_pos else -1

                            if first_delim != -1:
                                safe = delta[:first_delim]
                                clean = _STRIP_TAGS.sub("", safe)
                                if clean:
                                    print(f"[YIELD] text before delimiter: {repr(clean[:100])}", flush=True)
                                    yield _chunk({"content": clean})
                                if first_delim > 0:
                                    sent_until = sent_until + first_delim
                                else:
                                    delim_char = delta[0]
                                    if delim_char == '<':
                                        gt = delta.find('>')
                                        if gt != -1:
                                            tag = delta[:gt+1]
                                            # If it's a tool call tag or system reminder, don't advance – let _parse_tool_calls or _STRIP_TAGS handle it when complete
                                            if re.match(r'</?\s*(?:tool_call|tool_calls|tool_capability|invoke|_call|_calls|call|calls|tool|tools|tool_use_json|parameter|system-reminder|-reminder|[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*DSML|\?\?DSML\?\?|DSML|[|\uff5c\u2502]\s*tool)\b', tag, re.IGNORECASE):
                                                pass
                                            else:
                                                clean_tag = _STRIP_TAGS.sub("", tag)
                                                if clean_tag:
                                                    yield _chunk({"content": clean_tag})
                                                sent_until += gt + 1
                                        else:
                                            # Partial tag, no '>' yet – wait if it looks like a tag start
                                            if delta == '<' or re.match(r'</?[\s|\uff5c\u2502a-zA-Z]', delta):
                                                pass  # Any potential tag, wait for completion
                                            else:
                                                yield _chunk({"content": "<"})
                                                sent_until = sent_until + 1
                                    elif delim_char == '[':
                                        rb = delta.find(']')
                                        if rb != -1:
                                            bracket_tag = delta[:rb+1]
                                            if re.match(rf'\[\s*(?:{_CALL_MARKER}|tool_call|Task|Read|Write|Grep|Glob|LS)\b', bracket_tag, re.IGNORECASE):
                                                pass  # Tool marker, wait for complete tool call parse
                                            else:
                                                clean_bracket = _STRIP_TAGS.sub("", bracket_tag)
                                                if clean_bracket:
                                                    yield _chunk({"content": clean_bracket})
                                                sent_until += rb + 1
                                        else:
                                            # Partial bracket, no ']' yet – wait if it looks like a tool marker start
                                            if delta == '[' or re.match(rf'\[\s*(?:{_CALL_MARKER}|tool|[a-zA-Z])', delta):
                                                pass
                                            else:
                                                yield _chunk({"content": "["})
                                                sent_until = sent_until + 1
                            else:
                                clean = _STRIP_TAGS.sub("", delta)
                                if clean:
                                    print(f"[YIELD] text from delta: {repr(clean[:100])}", flush=True)
                                    yield _chunk({"content": clean})
                                sent_until = len(full)
                # Flush any held-back trailing text that never encountered a closing tag
                if sent_until < len(full):
                    remaining = full[sent_until:]
                    clean_rem = _STRIP_TAGS.sub("", remaining)
                    if clean_rem:
                        yield _chunk({"content": clean_rem})
                    sent_until = len(full)
                success = True
            except GeneratorExit:
                print(f"[DISCONNECT] Client disconnected", flush=True)
                return
            except Exception as e:
                err_str = str(e)
                elapsed = time.time() - t0
                print(f"[TIMING] Stream error at {elapsed:.1f}s: {e}", flush=True)
                # Save whatever content we got before the error
                if full.strip():
                    if state:
                        state["parent_id"] = result_meta.get("resp_msg_id") or state.get("parent_id")
                        state["msgs_len"] = len(req.messages)
                        _save_conv_state()
                        print(f"[STREAM ERROR] Partial content saved ({len(full)} chars) for {conv_key[:24]}", flush=True)
                    # Yield what we have so far + info message + [DONE]
                    remaining = full[sent_until:] if sent_until < len(full) else ""
                    remaining = _STRIP_TAGS.sub("", remaining)
                    remaining = re.sub(r"<[^>]*>", "", remaining).strip()
                    if remaining:
                        yield _chunk({"content": remaining})
                if "length limit" in err_str.lower() or "context_length" in err_str.lower() or "start a new chat" in err_str.lower() or "content is too long" in err_str.lower() or "input_exceeds_limit" in err_str.lower() or "too long" in err_str.lower():
                    # Zamiast czyścić stan, rotujemy sesję DS automatycznie
                    print(f"[CONTEXT LIMIT] Rotating DS session for {conv_key[:24]}... (prompt was {len(prompt)} chars)", flush=True)
                    if state:
                        try:
                            new_session_id = ds.create_session(account_idx)
                            state["ds_session"] = new_session_id
                            state["parent_id"] = None
                            state["msgs_len"] = len(req.messages)
                            with _conv_lock:
                                _conv_state[conv_key] = state
                                _save_conv_state()
                            print(f"[CONTEXT LIMIT] New DS session: {new_session_id}", flush=True)
                        except Exception as rot_err:
                            print(f"[CONTEXT LIMIT] Rotation failed: {rot_err}, clearing state", flush=True)
                            _conv_state.pop(conv_key, None)
                            _save_conv_state()
                    yield _chunk({"content": "\n\n*Kontekst został wyczerpany — sesja DeepSeek została zrotowana automatycznie. Wyślij 'kontynuuj' aby kontynuować.*"})
                    yield _chunk({}, "length")
                    yield "data: [DONE]\n\n"
                    return
                # Moduł 3: awaryjny zrzut stanu czatu, gdy auto-continue zawiódł
                if result_meta.get("auto_continue_failed"):
                    try:
                        _write_crash_dump(conv_key=conv_key, session_id=chat_id, account_idx=account_idx,
                                          messages=req.messages, state=state, partial_content=full,
                                          reason="auto-continue failed (2 attempts)", error=err_str)
                    except Exception:
                        pass
                yield _chunk({"content": "\n\n*Stream został przerwany przez DeepSeek. Wyślij 'kontynuuj' aby dokończyć — kontekst został zachowany.*"})
                yield "data: [DONE]\n\n"
                return
            if success:
                with _conv_lock:
                    if state:
                        old_parent = state.get("parent_id")
                        new_parent = result_meta.get("resp_msg_id") or old_parent
                        state["parent_id"] = new_parent
                        was_incomplete = not result_meta.get("finished_normally", True)
                        if was_incomplete:
                            # Moduł 3: awaryjny zrzut stanu czatu, gdy auto-continue zawiódł
                            # (typowa ścieżka: auto-continue nie rzuca wyjątku, tylko kończy strumień)
                            if result_meta.get("auto_continue_failed"):
                                try:
                                    _write_crash_dump(conv_key=conv_key, session_id=chat_id, account_idx=account_idx,
                                                      messages=req.messages, state=state, partial_content=full,
                                                      reason="auto-continue failed (2 attempts)", error="")
                                except Exception:
                                    pass
                            # Stream się nie dokończył — NIE bumpuj msgs_len.
                            # Następny RESUME wyśle te same wiadomości ponownie
                            # i DeepSeek naturalnie dokończy odpowiedź.
                            # Trackuj ile razy pod rząd — po 2 rotujemy sesję DS.
                            state["incomplete_count"] = state.get("incomplete_count", 0) + 1
                            print(f"[INCOMPLETE] Count={state['incomplete_count']}, not bumping msgs_len ({state['msgs_len']}), next RESUME will continue from partial response", flush=True)
                        elif tools_yielded > 0 or full.strip():
                            state["msgs_len"] = len(req.messages)
                            state["incomplete_count"] = 0  # Reset na sukces
                        elif old_parent and not result_meta.get("resp_msg_id"):
                            # Resume returned empty – session is dead, force new one
                            print(f"[EMPTY RESUME] Clearing conv state for {conv_key[:24]}...", flush=True)
                            _conv_state.pop(conv_key, None)
                        _save_conv_state()
            if is_subagent and subagent_timing_key:
                elapsed = time.time() - subagent_stream_start
                record_subagent_done(subagent_timing_key, elapsed, success)
            try:
                if tools_yielded == 0:
                    remaining = full[sent_until:] if sent_until < len(full) else ""
                    # JEŚLI bufor zawiera niedomknięty lub uszkodzony tag narzędzia -> ZAKAZ wypluwania do czatu!
                    if _has_unclosed_tool_call(full) or re.search(r'<\s*(?:[|\uff5c\u2502\s]*DSML|tool_call|invoke|_call)', remaining, re.IGNORECASE):
                        print(f"[STREAM] Suppressed unclosed tool call leakage ({len(remaining)} chars not sent to chat)", flush=True)
                        try:
                            _write_crash_dump(conv_key=conv_key, session_id=chat_id, account_idx=account_idx,
                                              messages=req.messages, state=state, partial_content=full,
                                              reason="unclosed tool call aborted before completion", error="")
                        except Exception:
                            pass
                    else:
                        remaining = _STRIP_TAGS.sub("", remaining)
                        remaining = re.sub(r"<[^>]*>", "", remaining).strip()
                        if remaining:
                            yield _chunk({"content": remaining})
                print(f"[TIMING] Stream done ({time.time()-t0:.1f}s, {tools_yielded} tools, wm={watermark_uuid[:12]}...)", flush=True)
                fr = "tool_calls" if tools_yielded > 0 else "stop"
                yield _chunk({}, fr)
                yield "data: [DONE]\n\n"
            except GeneratorExit:
                print(f"[DISCONNECT] Client disconnected at stream end", flush=True)
                return
        finally:
            with _slot_busy_lock:
                _slot_busy[account_idx] = False

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.get("/v1/mode")
def get_mode():
    """Sprawdź aktualny tryb proxy."""
    mode = _get_mode()
    return {
        "mode": mode,
        "official_api_available": official_api.available,
        "description": {
            "auto": "Glowny agent -> platne API. Subagenci -> darmowy web chat. (domyslne)",
            "free": "Wszystko przez darmowy web chat. Klucz API ignorowany.",
            "biedny": "Wszystko przez darmowy web chat (z promptem Managera).",
            "free_first": "WEB first: Glowny agent przez web chat. Przy Content is too long -> oficjalne API (pelny kontekst!). Subagenci zawsze web."
        }.get(mode, "")
    }


@app.post("/v1/mode")
def set_mode(mode: str):
    """Przelacz tryb proxy. Tryby: auto, free, biedny, free_first."""
    try:
        _set_mode(mode)
        return {"status": "ok", "mode": mode}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/health")
def health():
    slots = [ap.is_valid(i) for i in range(MAX_ACCOUNTS)]
    sub_stats = get_subagent_stats()
    return {"status": "ok", "slots": slots, "any_valid": any(slots),
            "subagents": sub_stats, "official_api": official_api.available}


if __name__ == "__main__":
    # â”€â”€ Log cleanup: zapobiega rozrastaniu się plików diagnostycznych â”€â”€
    def _truncate_log(path, max_kb):
        try:
            p = Path(path)
            if p.exists() and p.stat().st_size > max_kb * 1024:
                # Keep last ~half of max
                data = p.read_bytes()
                keep = max_kb * 512  # half
                p.write_bytes(data[-keep:])
                print(f"[STARTUP] Truncated {p.name} ({len(data)//1024}KB -> {keep//1024}KB)", flush=True)
        except Exception:
            pass
    for _log_path, _max_kb in [(MSG_LOG, 2048), (PROXY_LOG, 4096),
                                 (DIAG_LOG, 512), (FP_LOG, 256),
                                 (LEGID_LOG, 256), (TOKEN_LOG, 256)]:
        _truncate_log(_log_path, _max_kb)
    # Clean auto-backup if too large
    try:
        backup = CONV_STATE_FILE.with_suffix(".auto.backup.json")
        if backup.exists() and backup.stat().st_size > 256 * 1024:
            backup.unlink()
            print("[STARTUP] Removed oversized auto-backup", flush=True)
    except Exception:
        pass
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    valid_slots = [i for i in range(MAX_ACCOUNTS) if ap.is_valid(i)]
    if valid_slots:
        print(f"Active accounts: {len(valid_slots)} logged in (slots: {valid_slots}). Ready for requests.")
    else:
        print("No accounts found. Open a SECOND CMD in this folder and run:  login_slot.bat 0")
    print("Starting on http://localhost:4570")
    uvicorn.run(app, host="0.0.0.0", port=4570)
