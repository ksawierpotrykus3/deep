import json, time, uuid, re, hashlib, threading, os, base64, random, sys, io
from collections import deque
from datetime import datetime
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
import monitor
import doctor
from cloud_shield import cloud_shield
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

CONV_STATE_FILE = Path(__file__).parent / "data" / "conv_state.json"
_old_conv_state = Path(__file__).parent / "conv_state.json"
if _old_conv_state.exists() and not CONV_STATE_FILE.exists():
    try:
        import shutil as _shutil
        CONV_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _shutil.move(str(_old_conv_state), str(CONV_STATE_FILE))
        print(f"[MIGRATE] conv_state.json -> {CONV_STATE_FILE}", flush=True)
    except Exception:
        pass
_old_conv_backup = Path(__file__).parent / "conv_state.auto.backup.json"
if _old_conv_backup.exists() and not (CONV_STATE_FILE.parent / "conv_state.auto.backup.json").exists():
    try:
        import shutil as _shutil
        _shutil.move(str(_old_conv_backup), str(CONV_STATE_FILE.parent / "conv_state.auto.backup.json"))
    except Exception:
        pass

MAX_ACCOUNTS = 100
MAX_CONV_ENTRIES = 500
MODE_FILE = Path(__file__).parent / "data" / "proxy_mode.txt"
LEAKS_LOG_FILE = Path(__file__).parent / "data" / "leaks.log"
WORKSPACE_LEAKS_LOG = Path(__file__).parent / "leaks.log"
PROMPT2_FILE = Path(__file__).parent / "prompt2.txt"
PROMPT3_FILE = Path(__file__).parent / "prompt3.txt"

# ==============================================================================
#                     USTAWIENIA TRYBÓW PROXY (DLA UŻYTKOWNIKA)
# ==============================================================================
# Głębokie myślenie (DeepThink / R1) i Wyszukiwanie (Search) dla nowego,
# zunifikowanego modelu DeepSeek (łączącego Szybki, Ekspert i Wizja w jeden silnik).
DEFAULT_THINKING  = True    # True = włącz głębokie myślenie [⚛️] (zalecane do kodowania/architektury)
DEFAULT_SEARCH    = False   # False = wyłącz wyszukiwanie w necie dla kodowania (stabilniejsze i szybsze)
VISION_THINKING   = True    # True = myślenie przy analizie obrazów [🖼️], False = szybka analiza

# Zachowanie pełnej zgodności wstecznej dla starszych skryptów i wywołań:
SZYBKI_MYSLEKIE   = DEFAULT_THINKING
SZYBKI_SZUKANIE   = DEFAULT_SEARCH
EKSPERT_MYSLEKIE  = DEFAULT_THINKING
EKSPERT_SZUKANIE  = DEFAULT_SEARCH
WIZJA_MYSLEKIE    = VISION_THINKING
# ==============================================================================


def _get_mode() -> str:
    """Returns 'auto', 'web', 'free', 'biedny', or 'free_first'."""
    try:
        if MODE_FILE.exists():
            mode = MODE_FILE.read_text(encoding="utf-8").strip().lower()
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
    MODE_FILE.write_text(mode, encoding="utf-8")
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
    email: str = ""



_slot_locks = [threading.Lock() for _ in range(MAX_ACCOUNTS)]
_slot_in_progress = [False] * MAX_ACCOUNTS
_slot_busy = [False] * MAX_ACCOUNTS
_slot_busy_lock = threading.RLock()
_conv_lock = threading.Lock()
_rate_limited_until: list[float] = [0.0] * MAX_ACCOUNTS
# Sloty, których token DeepSeek został odrzucony (40003 Authorization Failed) w TYM uruchomieniu.
# `is_valid()` sprawdza tylko lokalny plik sesji i nie ma jak wiedzieć, że token wygasł po stronie
# serwera — dlatego wygasłe konto było wybierane raz po raz, a jego awarie wyglądały w logach jak
# rate-limit. Efekt: proxy mieliło żądania na jednym żywym koncie (S3), co dawało generation_err,
# puste tury i "przerwane strumienie". Teraz takie sloty są jawnie oznaczone i pomijane.
MUTED_SLOTS_FILE = Path(__file__).parent / "data" / "muted_slots.json"

def _load_muted_slots() -> dict[int, float]:
    if MUTED_SLOTS_FILE.exists():
        try:
            d = json.loads(MUTED_SLOTS_FILE.read_text(encoding="utf-8"))
            now_ts = time.time()
            return {int(k): float(v) for k, v in d.items() if float(v) > now_ts}
        except Exception:
            pass
    return {}

def _save_muted_slots():
    try:
        MUTED_SLOTS_FILE.write_text(json.dumps({str(k): v for k, v in _muted_slots_until.items()}, indent=2), encoding="utf-8")
    except Exception:
        pass

_auth_expired_slots: set[int] = set()
_muted_slots_until: dict[int, float] = _load_muted_slots()
_last_global_completion_time: float = 0.0
_global_pacing_lock = threading.Lock()
_last_search_completion_time: float = 0.0
_search_pacing_lock = threading.Lock()
_auto_login_lock = threading.Lock()

def try_auto_login(slot_idx: int, ap_instance=None) -> bool:
    """Automatycznie odnawia sesje dla wygaslego slotu uzywajac auto_login.py i data/accounts.json."""
    with _auto_login_lock:
        try:
            import auto_login
            accounts = auto_login.load_accounts()
            acc = accounts.get(slot_idx)
            if not acc:
                print(f"[AUTO-LOGIN] Slot {slot_idx}: brak danych logowania w data/accounts.json", flush=True)
                return False
            print(f"[AUTO-LOGIN] Proba automatycznego logowania slotu {slot_idx} ({acc['email']})...", flush=True)
            ok = auto_login.login_slot(slot_idx, acc["email"], acc["password"])
            if ok:
                print(f"[AUTO-LOGIN] Sukces logowania slotu {slot_idx}! Przywracam slot do puli.", flush=True)
                _auth_expired_slots.discard(slot_idx)
                _rate_limited_until[slot_idx] = 0.0
                if ap_instance is not None:
                    ap_instance.reload_slot(slot_idx)
                elif 'ap' in globals() and globals()['ap'] is not None:
                    globals()['ap'].reload_slot(slot_idx)
                return True
            else:
                print(f"[AUTO-LOGIN] Logowanie slotu {slot_idx} nie powiodlo sie.", flush=True)
                return False
        except Exception as e:
            print(f"[AUTO-LOGIN] Wyjatek podczas auto-login slotu {slot_idx}: {e}", flush=True)
            return False

# Maksymalny ŁĄCZNY czas oczekiwania na anty-spam DeepSeeka w ramach JEDNEGO żądania.
# DeepSeek odpowiada wtedy "Zbyt częste wiadomości. Spróbuj ponownie później." i trzeba
# odczekać. Kluczowe: budżet jest wspólny dla całej rekurencji, więc kolejne próby nie
# mnożą pauz. 240 s wystarcza na typowe okno anty-spamu, a jednocześnie nie pozwala
# żądaniu wisieć w nieskończoność (wcześniej bywało 600 s i zero treści na koniec).
MAX_SPAM_WAIT_S = 240.0
ACCOUNT_USAGE_FILE = Path(__file__).parent / "data" / "account_usage.json"

def _create_empty_slot_stat() -> dict:
    return {
        "total_requests": 0,
        "main_requests": 0,
        "subagent_requests": 0,
        "last_used": 0.0,
        "last_finished": 0.0,
        "last_role": "NONE",
        "last_status": "IDLE",
        "consecutive_rate_limits": 0,
    }

def _load_account_stats() -> list[dict]:
    stats = [_create_empty_slot_stat() for _ in range(MAX_ACCOUNTS)]
    try:
        if ACCOUNT_USAGE_FILE.exists():
            data = json.loads(ACCOUNT_USAGE_FILE.read_text(encoding="utf-8"))
            raw_stats = data.get("stats", {})
            for k, v in raw_stats.items():
                idx = int(k)
                if 0 <= idx < MAX_ACCOUNTS and isinstance(v, dict):
                    stats[idx].update(v)
            for k, v in data.get("last_used", {}).items():
                idx = int(k)
                if 0 <= idx < MAX_ACCOUNTS:
                    ts = float(v)
                    if ts > stats[idx]["last_used"]:
                        stats[idx]["last_used"] = ts
            for k, v in data.get("last_finished", {}).items():
                idx = int(k)
                if 0 <= idx < MAX_ACCOUNTS:
                    stats[idx]["last_finished"] = float(v)
    except Exception as e:
        print(f"[ACCOUNT_STATS] Load failed: {e}", flush=True)
    return stats

_account_stats: list[dict] = _load_account_stats()
_last_account_completion_time: list[float] = [float(st.get("last_used", 0.0)) for st in _account_stats]
_last_account_finish_time: list[float] = [float(st.get("last_finished", st.get("last_used", 0.0))) for st in _account_stats]

def _save_account_usage():
    try:
        ACCOUNT_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_used": {str(i): _last_account_completion_time[i] for i in range(MAX_ACCOUNTS)},
            "last_finished": {str(i): _last_account_finish_time[i] for i in range(MAX_ACCOUNTS)},
            "stats": {str(i): _account_stats[i] for i in range(MAX_ACCOUNTS)}
        }
        tmp = ACCOUNT_USAGE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(ACCOUNT_USAGE_FILE)
    except Exception:
        pass

def _record_account_used(idx: int, is_subagent: bool = False, role: str | None = None):
    """Zapisuje timestamp i szczegółowe statystyki użycia konta na dysku."""
    if 0 <= idx < MAX_ACCOUNTS:
        now = time.time()
        _last_account_completion_time[idx] = now
        st = _account_stats[idx]
        st["total_requests"] = int(st.get("total_requests", 0)) + 1
        st["last_used"] = now
        resolved_role = role or ("SUBAGENT" if is_subagent else "MAIN")
        st["last_role"] = resolved_role
        st["last_status"] = "BUSY"
        if resolved_role == "SUBAGENT":
            st["subagent_requests"] = int(st.get("subagent_requests", 0)) + 1
        else:
            st["main_requests"] = int(st.get("main_requests", 0)) + 1
        _save_account_usage()

def _record_account_finished(idx: int, status: str = "OK"):
    if 0 <= idx < MAX_ACCOUNTS:
        now = time.time()
        _last_account_finish_time[idx] = now
        st = _account_stats[idx]
        st["last_status"] = status
        st["last_finished"] = now
        if status == "OK":
            st["consecutive_rate_limits"] = 0
        elif status == "RATE_LIMITED":
            st["consecutive_rate_limits"] = int(st.get("consecutive_rate_limits", 0)) + 1
        _save_account_usage()

# ── ADAPTACYJNY SENSOR OBCIĄŻENIA KLASTRA (TTFT & Congestion Circuit Breaker) ──
_recent_ttfts: deque = deque(maxlen=15)
_last_busy_error_time: float = 0.0

def _record_ttft(ttft_sec: float):
    global _recent_ttfts
    if 0.05 <= ttft_sec <= 180.0:
        _recent_ttfts.append(ttft_sec)

def _record_cluster_busy():
    global _last_busy_error_time
    _last_busy_error_time = time.time()

def _get_cluster_congestion_factor() -> tuple[float, str]:
    """
    Zwraca mnożnik pacingu (1.0x - 2.0x) oraz opis stanu obciążenia klastra DeepSeek.
    Wyliczany na podstawie ruchomej średniej TTFT (Time to First Token)
    oraz świeżości błędów przeciążenia serwera ('server is busy' / 'parallel_chat_limit').
    """
    now = time.time()
    reasons = []
    multiplier = 1.0

    # 1. Sprawdź błędy przeciążenia z ostatnich 4 minut
    busy_age = now - _last_busy_error_time
    if _last_busy_error_time > 0 and busy_age < 240.0:
        multiplier = max(multiplier, 1.5)
        reasons.append(f"błąd przeciążenia {busy_age:.0f}s temu")

    # 2. Sprawdź ruchomą średnią TTFT
    if len(_recent_ttfts) >= 2:
        avg_ttft = sum(_recent_ttfts) / len(_recent_ttfts)
        if avg_ttft >= 8.0:
            multiplier = max(multiplier, 1.8)
            reasons.append(f"krytyczny TTFT: {avg_ttft:.1f}s")
        elif avg_ttft >= 5.0:
            multiplier = max(multiplier, 1.35)
            reasons.append(f"podwyższony TTFT: {avg_ttft:.1f}s")

    desc = ", ".join(reasons) if reasons else "klaster stabilny"
    return multiplier, desc

IDLE_RESET_SECONDS = 1800.0  # 30 minut bezczynności = automatyczny reset liczników poola

def _check_idle_reset() -> bool:
    """Automatyczny reset statusu poola po 30 minutach bezczynności.
    1. Jeśli cały pool nie był używany przez >= 30 minut, zeruje liczniki żądań dla wszystkich kont.
    2. Jeśli pojedynczy slot nie był używany przez >= 30 minut, zeruje jego liczniki.
    3. Czyści przeterminowane znaczniki rate limitu.
    """
    now = time.time()
    modified = False

    # Sprawdź czy CAŁY POOL był bezczynny przez >= 30 minut
    pool_last_used = max((float(st.get("last_used", 0.0)) for st in _account_stats), default=0.0)
    if pool_last_used > 0 and (now - pool_last_used) >= IDLE_RESET_SECONDS:
        for i in range(MAX_ACCOUNTS):
            st = _account_stats[i]
            if st.get("total_requests", 0) > 0 or st.get("consecutive_rate_limits", 0) > 0:
                st["total_requests"] = 0
                st["main_requests"] = 0
                st["subagent_requests"] = 0
                st["consecutive_rate_limits"] = 0
                st["last_role"] = "NONE"
                st["last_status"] = "IDLE"
                modified = True
            if _rate_limited_until[i] > 0 and now >= _rate_limited_until[i]:
                _rate_limited_until[i] = 0.0
        if modified:
            print(f"[POOL RESET] Cały pool był bezczynny przez {(now - pool_last_used)/60:.1f} min (>= 30 min) — zresetowano liczniki żądań.", flush=True)
            _save_account_usage()
        return modified

    # Sprawdź poszczególne sloty (cooldown >= 30 minut dla danego slotu)
    reset_slots = []
    for i in range(MAX_ACCOUNTS):
        st = _account_stats[i]
        last_u = float(st.get("last_used", 0.0))
        if last_u > 0 and (now - last_u) >= IDLE_RESET_SECONDS:
            if st.get("total_requests", 0) > 0 or st.get("consecutive_rate_limits", 0) > 0:
                st["total_requests"] = 0
                st["main_requests"] = 0
                st["subagent_requests"] = 0
                st["consecutive_rate_limits"] = 0
                st["last_role"] = "NONE"
                st["last_status"] = "IDLE"
                reset_slots.append(i)
                modified = True
            if _rate_limited_until[i] > 0 and now >= _rate_limited_until[i]:
                _rate_limited_until[i] = 0.0

    if modified:
        print(f"[SLOT RESET] Sloty {reset_slots} były bezczynne >= 30 min — zresetowano liczniki.", flush=True)
        _save_account_usage()

    return modified

# Inicjalne sprawdzenie przy starcie proxy (zeruje stare statystyki z poprzednich dni)
_check_idle_reset()

def _format_pool_status() -> str:
    _check_idle_reset()
    parts = []
    disabled = _get_disabled_slots()
    for i in range(MAX_ACCOUNTS):
        if i in disabled:
            continue
        p = Path(__file__).parent / f"session_{i}.json"
        if not p.exists():
            continue
        st = _account_stats[i]
        tot = st.get("total_requests", 0)
        now = time.time()
        if i in _auth_expired_slots:
            # Wygasły token NIE jest limitem — wyglądał jak limit i maskował prawdziwą
            # przyczynę awarii (realnie pracowało tylko jedno konto).
            status_str = "EXPIRED(relogin!)"
        elif now < _rate_limited_until[i]:
            remain = int(_rate_limited_until[i] - now)
            status_str = f"LIMIT({remain}s)"
        elif _slot_busy[i]:
            role = st.get("last_role", "BUSY")
            role_short = "SUB" if "SUB" in role else "MAIN"
            status_str = f"BUSY[{role_short}]"
        else:
            status_str = "IDLE"
        parts.append(f"S{i}:{status_str}({tot}x)")
    return " | ".join(parts)

DISABLED_SLOTS_FILE = Path(__file__).parent / "data" / "disabled_slots.txt"


def _get_disabled_slots() -> set[int]:
    """Zwraca zbiór wyłączonych indeksów slotów (konfigurowalne przez data/disabled_slots.txt)."""
    disabled = set()
    try:
        if DISABLED_SLOTS_FILE.exists():
            for line in DISABLED_SLOTS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    for part in line.replace(",", " ").split():
                        try:
                            disabled.add(int(part))
                        except ValueError:
                            pass
    except Exception:
        pass
    return disabled


class AccountPool:
    def __init__(self):
        self.slots: list[Session | None] = [None] * MAX_ACCOUNTS
        self._rr_index = 0
        self._pool_lock = _slot_busy_lock
        self._slot_conditions = [threading.Condition(self._pool_lock) for _ in range(MAX_ACCOUNTS)]
        self._any_free_cond = threading.Condition(self._pool_lock)
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
        disabled = _get_disabled_slots()
        for i in range(MAX_ACCOUNTS):
            if i in disabled:
                continue
            try:
                p = self._slot_path(i)
                if p.exists():
                    self.slots[i] = Session(**json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self, idx: int):
        s = self.slots[idx]
        if s:
            self._slot_path(idx).write_text(json.dumps({
                "auth_token": s.auth_token, "cookies": s.cookies,
                "user_agent": s.user_agent, "created_at": s.created_at,
                "last_validated_at": s.last_validated_at,
            }, indent=2), encoding="utf-8")

    def reload_slot(self, idx: int):
        p = self._slot_path(idx)
        if p.exists():
            try:
                self.slots[idx] = Session(**json.loads(p.read_text(encoding="utf-8")))
                print(f"[ACCOUNT POOL] Odswiezono dane sesji slotu {idx} w pamieci proxy", flush=True)
            except Exception as e:
                print(f"[ACCOUNT POOL] Blad ladowania odswiezonego slotu {idx}: {e}", flush=True)

    def is_muted(self, idx: int) -> bool:
        now_ts = time.time()
        mute_until = _muted_slots_until.get(idx, 0.0)
        if mute_until > now_ts:
            return True
        elif mute_until > 0.0 and now_ts >= mute_until:
            _muted_slots_until.pop(idx, None)
            _save_muted_slots()
            print(f"[BAN RECOVERY] Slot {idx}: Czas kary mute minal! Przywracam konto do puli roboczej.", flush=True)
            return False
        return False

    def is_valid(self, idx: int) -> bool:
        if idx in _get_disabled_slots():
            return False
        # Jesli konto jest zmutowane i czas bana jeszcze nie minal - chronimy je przed dobijaniem
        if self.is_muted(idx):
            return False

        # Token odrzucony przez DeepSeek w tym uruchomieniu -> konto wymaga ponownego
        # zalogowania.
        if idx in _auth_expired_slots:
            return False
        if 0 <= idx < MAX_ACCOUNTS and self.slots[idx] is None:
            p = self._slot_path(idx)
            if p.exists():
                try:
                    self.slots[idx] = Session(**json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    pass
        return self.slots[idx] is not None and bool(self.slots[idx].auth_token)

    def any_valid(self) -> bool:
        return any(self.is_valid(i) for i in range(MAX_ACCOUNTS))

    def open_slot(self) -> int | None:
        disabled = _get_disabled_slots()
        for i in range(MAX_ACCOUNTS):
            if i not in disabled and self.slots[i] is None:
                return i
        return None

    def pick_for_conv(self, conv_key: str | None = None, is_subagent: bool = False) -> int:
        """Wybiera wolny slot wg najmniejszego obciążenia (total_requests + LRU), omijając zajęte i rate-limited."""
        now = time.time()
        with self._pool_lock:
            _check_idle_reset()
            valid = [i for i in range(MAX_ACCOUNTS) if self.is_valid(i) and now >= _rate_limited_until[i]]
            if not valid:
                valid = [i for i in range(MAX_ACCOUNTS) if self.is_valid(i)]
            if not valid:
                valid = [i for i in range(MAX_ACCOUNTS) if self.slots[i] is not None]
            if not valid:
                valid = list(range(MAX_ACCOUNTS))

            free_valid = [i for i in valid if not _slot_busy[i]]
            candidates = free_valid if free_valid else valid
            candidates.sort(key=lambda i: (_last_account_finish_time[i], int(_account_stats[i].get("total_requests", 0))))
            return candidates[0]

    def acquire_slot(self, preferred_slot: int | None = None, timeout: float = 60.0, is_subagent: bool = False) -> int:
        """
        Atomowo rezerwuje slot dla zapytania (ustawia _slot_busy = True).
        - Jeśli preferred_slot jest podany i sprawny: czeka w kolejce na ten slot (zachowanie CoT i ciągłości czatu).
        - Jeśli brak preferencji (nowy czat / subagent):
          wybiera NAJMNIEJ OBCIĄŻONY slot (najmniej zapytań + LRU), omijając sloty zajęte i rate-limited.
        """
        role_label = "SUBAGENT" if is_subagent else "MAIN"
        deadline = time.time() + timeout
        with self._pool_lock:
            _check_idle_reset()
            # 1. Preferowany slot (kontynuacja trwającej rozmowy na danym koncie)
            #    POLITYKA "BEZ ROTACJI": gdy preferowany slot jest chwilowo rate-limited,
            #    CZEKAMY na niego, zamiast przełączać rozmowę na inne konto. Przełączenie
            #    konta = utrata sesji DeepSeek = ponowne wysłanie CAŁEGO kontekstu i pętla
            #    modelu na zduplikowanym prompcie. Inne konto bierzemy dopiero po wyczerpaniu
            #    timeoutu — świadoma ostateczność, głośno logowana.
            if preferred_slot is not None and 0 <= preferred_slot < MAX_ACCOUNTS and self.is_valid(preferred_slot):
                while True:
                    now = time.time()
                    if now >= _rate_limited_until[preferred_slot] and not _slot_busy[preferred_slot]:
                        _slot_busy[preferred_slot] = True
                        _record_account_used(preferred_slot, is_subagent=is_subagent)
                        tot = _account_stats[preferred_slot].get("total_requests", 0)
                        main_cnt = _account_stats[preferred_slot].get("main_requests", 0)
                        sub_cnt = _account_stats[preferred_slot].get("subagent_requests", 0)
                        idle_s = max(0.0, time.time() - _last_account_finish_time[preferred_slot]) if _last_account_finish_time[preferred_slot] > 0 else 0.0
                        print(f"[SLOT ACQUIRED] Slot {preferred_slot} (CONTINUE) | role={role_label} | Stats: total={tot} (main={main_cnt}, sub={sub_cnt}) | idle={idle_s:.1f}s", flush=True)
                        print(f"[POOL STATUS] {_format_pool_status()}", flush=True)
                        return preferred_slot
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        rl_left = max(0.0, _rate_limited_until[preferred_slot] - now)
                        print(f"[SLOT-QUEUE] Timeout ({timeout}s) — slot {preferred_slot} nadal "
                              f"(busy={_slot_busy[preferred_slot]}, rate-limited jeszcze {rl_left:.0f}s). "
                              f"OSTATECZNOŚĆ: inne konto = utrata sesji i ponowne wysłanie całego kontekstu.", flush=True)
                        break
                    self._slot_conditions[preferred_slot].wait(timeout=min(remaining, 1.0))

            # 2. Szukanie wolnego slotu wg obciążenia (najmniej zapytań + LRU) z kolejkowaniem
            while True:
                now = time.time()
                any_unmuted = [i for i in range(MAX_ACCOUNTS) if self.is_valid(i)]
                if not any_unmuted:
                    muted_times = {slot: until for slot, until in _muted_slots_until.items() if until > now}
                    if muted_times:
                        next_slot, next_until = min(muted_times.items(), key=lambda x: x[1])
                        diff_sec = max(0.0, next_until - now)
                        hours = int(diff_sec // 3600)
                        mins = int((diff_sec % 3600) // 60)
                        next_time_str = datetime.fromtimestamp(next_until).strftime("%H:%M:%S")
                        msg = (
                            f"Wszystkie konta DeepSeek są zmutowane ({len(muted_times)} kont). "
                            f"Najbliższe automatyczne odblokowanie: Slot {next_slot} o {next_time_str} CEST (za {hours}h {mins}m). "
                            f"Sweeper w tle przywróci konto natychmiast po wygaśnięciu kary bez potrzeby restartu proxy."
                        )
                    else:
                        msg = "Brak aktywnych lub zalogowanych kont DeepSeek w puli."
                    raise HTTPException(503, msg)

                valid = [i for i in any_unmuted if now >= _rate_limited_until[i]]
                if not valid:
                    # Wszystkie sprawne konta mają chwilowy rate-limit cooldown (np. 5-15s).
                    # Zamiast błędu 503 — czekamy w kolejce na najszybciej odblokowywany slot!
                    min_rl_remaining = min(max(0.0, _rate_limited_until[i] - now) for i in any_unmuted)
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise HTTPException(503, f"Wszystkie aktywne konta ({len(any_unmuted)}) są w trakcie rate-limit cooldown. Upłynął limit czasu oczekiwania ({timeout}s).")
                    sleep_time = min(min_rl_remaining, remaining, 1.0)
                    print(f"[RATE-LIMIT-QUEUE] Wszystkie aktywne sloty ({any_unmuted}) na cooldownie (najbliższy za {min_rl_remaining:.1f}s). Czekam...", flush=True)
                    self._any_free_cond.wait(timeout=max(0.1, sleep_time))
                    continue

                free_valid = [i for i in valid if not _slot_busy[i]]
                if free_valid:
                    # Sortowanie: 1) najdłużej odpoczywający (LRU wg _last_account_finish_time = rotacja po wszystkich kontach),
                    # 2) mniej zapytań w historii.
                    chosen = min(free_valid, key=lambda i: (
                        _last_account_finish_time[i],
                        int(_account_stats[i].get("total_requests", 0))
                    ))
                    self._rr_index = (chosen + 1) % MAX_ACCOUNTS
                    # idle liczymy PRZED _record_account_used
                    _now_idle = time.time()
                    idle_s = max(0.0, _now_idle - _last_account_finish_time[chosen]) if _last_account_finish_time[chosen] > 0 else 0.0
                    cands_summary = ", ".join(
                        f"S{i}:idle{max(0.0, _now_idle - _last_account_finish_time[i]) if _last_account_finish_time[i] > 0 else 0.0:.0f}s"
                        for i in sorted(free_valid, key=lambda x: _last_account_finish_time[x])
                    )
                    _slot_busy[chosen] = True
                    _record_account_used(chosen, is_subagent=is_subagent)
                    tot = _account_stats[chosen].get("total_requests", 0)
                    main_cnt = _account_stats[chosen].get("main_requests", 0)
                    sub_cnt = _account_stats[chosen].get("subagent_requests", 0)
                    print(f"[SLOT BALANCING] Candidates: [{cands_summary}] -> Picked Slot {chosen} (LRU rotation) | role={role_label}", flush=True)
                    print(f"[SLOT ACQUIRED] Slot {chosen} (NEW) | role={role_label} | Stats: total={tot} (main={main_cnt}, sub={sub_cnt}) | idle={idle_s:.1f}s", flush=True)
                    print(f"[POOL STATUS] {_format_pool_status()}", flush=True)
                    return chosen

                # Wszystkie sprawne sloty są zajęte — kolejkowanie żądania
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise HTTPException(503, f"Wszystkie sloty ({len(valid)}) są zajęte generowaniem. Upłynął limit czasu oczekiwania.")
                print(f"[SLOT-QUEUE] All {len(valid)} active slots busy [{_format_pool_status()}]. Waiting ({remaining:.1f}s left)...", flush=True)
                self._any_free_cond.wait(timeout=min(remaining, 1.0))

    def release_slot(self, slot_idx: int, status: str = "OK", duration: float = 0.0):
        """Zwalnia slot i natychmiast wybudza oczekujące żądania z kolejki."""
        with self._pool_lock:
            if 0 <= slot_idx < MAX_ACCOUNTS:
                if _slot_busy[slot_idx]:
                    _slot_busy[slot_idx] = False
                    _record_account_finished(slot_idx, status=status)
                    free_cnt = sum(1 for i in range(MAX_ACCOUNTS) if self.is_valid(i) and not _slot_busy[i])
                    total_valid = sum(1 for i in range(MAX_ACCOUNTS) if self.is_valid(i))
                    dur_str = f" | duration={duration:.1f}s" if duration > 0 else ""
                    print(f"[SLOT RELEASED] Slot {slot_idx}{dur_str} | status={status} | pool: {free_cnt}/{total_valid} free", flush=True)
                    print(f"[POOL STATUS] {_format_pool_status()}", flush=True)
                    self._slot_conditions[slot_idx].notify_all()
                    self._any_free_cond.notify()


    def reset_slot(self, idx: int):
        # Nigdy nie usuwamy pliku sesji z dysku (chroni przed utratą ciasteczek i tokenów przy błędach sieci)
        self.slots[idx] = None

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
            CONV_STATE_FILE.write_text("{}", encoding="utf-8")
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
            # BUG-025: Ignoruj linie dekoracyjne (np. =====, -----, *****, //////, ######)
            # chyba że powtórzenie jednolitego znaku osiągnie patologiczną długość (>= 250 znaków)
            if len(set(c1.strip())) <= 2 and chunk_size * 3 < 250:
                continue
            print(f"[LOOP GUARD] Detected exact repeating chunk ({len(c1)} chars) -> aborting", flush=True)
            return True
    return False


_HEARTBEAT_SENTINEL = object()

# ── KONTRAKT UKOŃCZENIA TURY (Turn Completion Contract) ──────────────────────
# Zasada: SUKCES TRZEBA UDOWODNIĆ. Wszystko, czego nie da się udowodnić, jest klasyfikowane
# jako "do ponowienia" i przechodzi przez drabinkę odzyskiwania. Dlatego NIE MA tu listy
# znanych błędów — jest jeden TOTALNY klasyfikator, którego gałęzią domyślną jest ponowienie.
#
# Dlaczego tak: wcześniej każdy warunek był TWIERDZĄCY ("tura jest sukcesem, CHYBA że złapie ją
# jedna z sześciu znanych sytuacji"). Wszystko, czego nie przewidzieliśmy w tych sześciu,
# przechodziło jako sukces i użytkownik dostawał pustą odpowiedź. Każdy nowy objaw wymagał
# kolejnej łatki. Odwrócenie logiki kończy ten proceder: nowy, nieprzewidziany scenariusz
# z DeepSeeka (inny sposób urwania strumienia, cicha pusta odpowiedź, nowy błąd biznesowy)
# wpada w domyślną gałąź ponowienia sam, bez pisania kolejnej łatki.
TURN_COMPLETE = "complete"
TURN_EMPTY = "empty"
TURN_ONLY_THINKING = "only_thinking"
TURN_UNCLOSED_TOOL = "unclosed_tool"
TURN_PROMISE = "promise"
TURN_PARTIAL = "partial"
TURN_ABORTED = "aborted"

# Drabinka odzyskiwania: outcome -> ((thinking_override, cooldown_s), ...)
# Każdy szczebel zużywa się RAZ, więc pętla jest z definicji skończona.
#   thinking_override: False = wyłącz myślenie (model MUSI wypluć treść albo narzędzie),
#                      True  = włącz myślenie, None = zostaw jak było.
# Brak wpisu dla danego outcome = nie ponawiamy (np. TURN_ABORTED = realna pętla: ogon sesji
# jest bezwartościowy, więc ponawianie w tym samym czacie tylko ją utrwala).
TURN_LADDER = {
    TURN_EMPTY:         ((False, 3.0),),
    TURN_ONLY_THINKING: ((False, 3.0),),
    TURN_UNCLOSED_TOOL: ((False, 3.0),),
    TURN_PROMISE:       ((False, 2.0),),
    TURN_PARTIAL:       ((None, 3.0),),
}

# Bodziec dobierany do wyniku klasyfikacji — profesjonalne dyrektywy systemowe zamiast prowokowania pętli 'kontynuuj'.
TURN_STIMULUS = {
    TURN_EMPTY: (
        "[System directive: Previous response yielded no content or tools. "
        "Please provide the final answer or invoke the appropriate tool now.]"
    ),
    TURN_ONLY_THINKING: (
        "[System directive: You finished reasoning but did not output a message or tool call. "
        "Please provide your response or invoke the appropriate tool now.]"
    ),
    TURN_UNCLOSED_TOOL: (
        "[System directive: Tool invocation was incomplete or truncated. "
        "Please provide a complete and valid tool call or final response.]"
    ),
    TURN_PROMISE: (
        "[System directive: Please proceed directly to invoke the required tool or output the final answer.]"
    ),
    TURN_PARTIAL: (
        "[System directive: Generation was cut off. Please continue from where you left off.]"
    ),
}


class _ReasoningChunk:
    """Chunk myślenia (reasoning) — oddzielony od treści, aby warstwa wyższa mogła go
    streamować do Trae jako delta.reasoning_content (BUG-004), zamiast zjadać w tle."""
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


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
    stop_ev = _threading.Event()

    def reader():
        try:
            for item in gen:
                if stop_ev.is_set():
                    break
                q.put(("data", item))
            q.put(("end", None))
        except Exception as e:
            q.put(("error", e))

    _threading.Thread(target=reader, daemon=True).start()
    try:
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
    finally:
        stop_ev.set()


# BUG-034: Wykrywanie realnego wywołania narzędzia w strumieniu myslenia.
# UWAGA: model w CoT potrafi CYT OWAC nazwe tagu w prozie (np. "I won't emit a
# <tool_call> block" albo "No tool call."). Samotne wystapienie stringu
# "tool_call"/"<tool_call>" BEZ atrybutu name=/id= oraz BEZ zamkniecia NIE jest
# wywolaniem narzedzia. Dlatego:
#   - usunieto gołe nazwy narzedzi (Read|Write|Edit|...), bo lapaly slowa z prozy,
#   - tag bloku narzedzia musi miec atrybut name=/id= albo byc jawnie domkniety.
_REAL_TOOL_TAG = re.compile(
    r'<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*(?:calls?|tool_calls?|invoke|tool_capability|_calls?|call|ask)\b)'
    r'(?=[^>]*(?:\bname\s*=|\bid\s*=))[^>]*>'
    r'|<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*calls?\b)[^>]*>'
    r'|<\s*(?:tool_calls?|invoke)\b(?=[^>]*(?:\bname\s*=|\bid\s*=))[^>]*>'
    r'|</\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*(?:calls?|tool_calls?|invoke|call|ask)?\b)\s*>'
    r'|</\s*(?:tool_calls?|invoke)\s*>'
    r'|<[|｜\uff5c\s]*tool\s*call\s*begin[|｜\uff5c\s]*>',
    re.IGNORECASE
)

_REASONING_LEAK_PAT = re.compile(
    r'<\s*(?=<\s*/?[|\uff5c\u2502\s]*DS)|'
    r'</?\s*[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*(?:calls?|tool_calls?|invoke|tool_capability|_calls?|call|ask|parameter|param)?\b[^>]*>|'
    r'<\s*(?:parameter|param|user_input)\b[^>]*>[\s\S]*?</\s*(?:parameter|param|user_input)\s*>|'
    r'</?\s*(?:tool_calls?|invoke|tool_capability|_call|call|tool|parameter|param|user_input)[^>]*>|'
    r'<\s*[|\uff5c\u2502\s]*/?\s*DS[a-zA-Z0-9_|\uff5c\u2502\s]*>?|'
    r'<[|｜\uff5c\s]*tool\s*call\s*(?:begin|end)?[|｜\uff5c\s]*>',
    re.IGNORECASE
)

def _clean_reasoning(text: str) -> str:
    if not text:
        return ""
    return _REASONING_LEAK_PAT.sub("", text)

_TAG_PREFIX_PAT = re.compile(r'<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*|[a-zA-Z_|｜\uff5c\-]+)?$', re.IGNORECASE)
# Model potrafi ZAPOWIEDZIEĆ akcję w samym tekście ("Let me read the file...", "Sprawdzam stan...")
# i nie wyemitować wywołania narzędzia. Tura kończy się wtedy samą zapowiedzią, Trae czeka
# w miejscu, a użytkownik musi ręcznie pisać "kontynuuj".
# Uwaga: celowo TYLKO czas teraźniejszy/przyszły (PL) — formy przeszłe ("sprawdziłem",
# "uruchomiłem") to sprawozdanie z wykonanej pracy, a nie zapowiedź, więc ich nie łapiemy.
_ACTION_PROMISE_RE = re.compile(
    r"(?:^|[.\n!?;:]\s+|\s[—–-]\s+)"
    r"(?:"
    r"let me|let's|i'll|i will|i'm going to|i am going to|now i'll|now i|"
    r"first,?\s+let me|next,?\s+let me|"
    r"sprawdzam|sprawdzę|sprawdzimy|sprawdzasz|czytam|przeczytam|czytamy|"
    r"zaczynam|zacznę|zaczynamy|zobaczę|zobaczymy|patrzę|popatrzę|"
    r"poszukam|szukam|szukamy|uruchamiam|uruchomię|uruchomimy|ustalam|ustalę|"
    r"otwieram|otworzę|wypisuję|wypiszę|liczę|policzę|zweryfikuję|"
    r"przeanalizuję|analizuję|sięgam|biorę|wezmę|muszę|trzeba"
    r")\b",
    re.IGNORECASE,
)

# Jednoznaczne formy 1. osoby czasu PRZYSZŁEGO (PL). Łapiemy je NIEZALE od pozycji w zdaniu,
# bo w polszczyźnie zapowiedź bardzo często stoi po spójniku, gdzie powyższy wzorzec (wymagający
# granicy zdania) jej nie widzi:
#   "… — doczytam resztę pliku i sprawdzę faktyczny stan projektu."
# Tutaj `sprawdzę` jest poprzedzone "i ", a `doczytam` w ogóle nie było na liście.
# Skutek: model zapowiadał pracę i kończył turę bez wywołania narzędzia, a Trae czekało w miejscu.
# Świadomie BEZ form przeszłych (sprawozdanie z pracy) i bez "dodam" ("dodam, że…" to wtrącenie).
_ACTION_FUTURE_RE = re.compile(
    r"(?<![\wąćęłńóśźż])"
    r"(?:doczytam|doczytamy|dopiszę|dokończę|dokończymy|naprawię|naprawimy|poprawię|poprawimy|"
    r"zmienię|zmienimy|usunę|usuniemy|przetestuję|przetestujemy|zaimplementuję|zaktualizuję|"
    r"nadpiszę|edytuję|sprawdzę|sprawdzimy|przeczytam|przeczytamy|uruchomię|uruchomimy|"
    r"ustalę|poszukam|zacznę|zobaczę|zobaczymy|popatrzę|przeanalizuję|zweryfikuję|"
    r"wykonam|wykonamy|sięgnę|wezmę)\b",
    re.IGNORECASE,
)


def _has_unclosed_tool_call(text: str) -> bool:
    """Deterministycznie sprawdza, czy w buforze znajduje się otwarty, ale niedomknięty tag narzędzia.
    NIGDY nie fałszuje alarmu, gdy model domknął wszystkie wewnętrzne <invoke>...</invoke>, ale pominął zewnętrzny <tool_calls>.

    BUG-034: Model w CoT potrafi CYT OWAC nazwe tagu w prozie (np. "I won't emit a
    <tool_call> block", "No tool call.", "let me write the response"). Takie wzmianki
    NIE sa wywolaniem narzedzia. Dlatego:
      - usunieto gołe nazwy narzedzi (read/write/edit/glob/...), bo lapaly slowa z prozy,
      - tag bloku narzedzia musi miec atrybut name=/id= (albo byc jawnie domkniety),
        inaczej jest traktowany jako wzmianka, a nie otwarte wywolanie.
    """
    if not text:
        return False

    # 1. Rzeczywiste tagi wywołania narzędzia (tool_call(s), invoke, call, chińskie 调用/工具/函数).
    # BUG-034: wymagany atrybut name=/id= dla tagow Otwierajacych, inaczej to tylko wzmianka w prozie.
    tool_names = r'(?:tool_calls?|invoke|tool_capability|_calls?|call|ask|调用|調用|工具|函数)'
    # BUG-024 & BUG-026 & BUG-034: open_invokes dopuszcza <｜｜DSML｜｜invoke name=...>, <tool_call name=...>,
    # ale NIE samotna wzmianke <tool_call> bez atrybutu (cytowana w CoT) ani parametry.
    open_invokes = len(re.findall(
        r'<\s*(?:'
        r'[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*(?:' + tool_names + r'\b|\s+name=)'
        r'(?=[^>]*(?:\bname\s*=|\bid\s*=))[^>]*>'
        r'|(?:' + tool_names + r')\b(?=[^>]*(?:\bname\s*=|\bid\s*=))[^>]*>'
        r'|[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*\s+name=[^>]*>'
        r')', text, re.IGNORECASE))
    # BUG-026 & BUG-034 & BUG-035: Zamknięcie invoke WYMAGA słowa kluczowego (invoke/tool_call/ask/tool itp.).
    # Nagi </||DSML||> zamyka parametr, a NIE invoke!
    dsml_close = r'(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*(?:ask|tool_calls?|invoke|tool_capability|_calls?|call|tool|action)|(?:ask|tool_calls?|invoke|tool_capability|_calls?|call|tool|action|调用|調用|工具|函数))'
    close_invokes = len(re.findall(rf'</\s*{dsml_close}\s*>', text, re.IGNORECASE))
    if open_invokes > close_invokes:
        return True

    # Jeśli wszystkie otwarte invoke zostały domknięte, to całe wywołanie jest kompletne
    if open_invokes > 0 and open_invokes == close_invokes:
        tail = text[-100:]
        if re.search(
            r'<\s*/?[|｜\uff5c\u2502\s]*(?:[a-zA-Z0-9_]{0,25})$|'
            r'\[\s*/?[|｜\uff5c\u2502\s]*(?:[a-zA-Z0-9_]{0,25})$|'
            r'<[|｜\uff5c\s]*tool\s*(?:call\s*(?:begin|end)?)?$|'
            r'<\s*(?:[|\uff5c\u2502\s]*DSML|[|\uff5c\u2502\s]*tool|\w+:\w+)[^>]*$',
            tail, re.IGNORECASE
        ):
            return True
        return False

    # 2. Samotne tagi parametrów poza invoke (w tym chińskie warianty 参数 / 參數 oraz nagi </||DSML||>)
    param_names = r'(?:parameter|参数|參數|pattern|file_path|command)'
    open_params = len(re.findall(r'<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)?' + param_names + r'\b[^>]*>', text, re.IGNORECASE))
    param_close = r'(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*(?:parameter|参数|參數)?|(?:parameter|参数|參數))'
    close_params = len(re.findall(rf'</\s*{param_close}\s*>', text, re.IGNORECASE))
    if open_params > close_params:
        return True

    # 3. Format natywny DeepSeek (<｜tool call begin｜> ... <｜tool call end｜>)
    native_opens = len(re.findall(r'<[|｜\uff5c\s]*tool\s*call\s*begin[|｜\uff5c\s]*>', text, re.IGNORECASE))
    native_closes = len(re.findall(r'<[|｜\uff5c\s]*tool\s*call\s*end[|｜\uff5c\s]*>', text, re.IGNORECASE))
    if native_opens > native_closes:
        return True

    # 4. Urwany znacznik na samym końcu bufora (np. "<", "<｜｜DS", "<｜｜DSML｜｜inv")
    tail = text[-100:]
    if re.search(
        r'<\s*/?[|｜\uff5c\u2502\s]*(?:[a-zA-Z0-9_]{0,25})$|'
        r'\[\s*/?[|｜\uff5c\u2502\s]*(?:[a-zA-Z0-9_]{0,25})$|'
        r'<[|｜\uff5c\s]*tool\s*(?:call\s*(?:begin|end)?)?$|'
        r'<\s*(?:[|\uff5c\u2502\s]*DSML|[|\uff5c\u2502\s]*tool|\w+:\w+)[^>]*$',
        tail, re.IGNORECASE
    ):
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
                err_str = str(e).lower()
                if "proxy" in err_str or "connect" in err_str:
                    cloud_shield.mark_proxy_unhealthy(str(e))
                    self._http.proxies = {}
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 3  # 3s, 6s, 9s
                    print(f"[NET RETRY] {type(e).__name__}: {e} — waiting {wait}s (attempt {attempt+1}/{max_retries})", flush=True)
                    _time.sleep(wait)
                else:
                    raise
        raise last_err  # never reached

    def _apply_proxy(self, account_idx: int | None = None) -> str | None:
        """Konfiguruje sesje HTTP do uzywania aktywnego proxy (lub polaczenia bezposredniego)."""
        proxy = cloud_shield.get_proxy(account_idx)
        if proxy:
            self._http.proxies = {"https": proxy, "http": proxy}
        else:
            self._http.proxies = {}
        return proxy

    def __init__(self, ap: AccountPool):
        self.ap = ap
        self.pow = DeepSeekPOW()
        self._cached_pow: dict[int, str] = {}
        self._pow_expires: dict[int, float] = {}
        self._pow_lock = threading.Lock()
        self._http = requests.Session()
        self._apply_proxy()
        self._http.headers.update({
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://chat.deepseek.com",
            "referer": "https://chat.deepseek.com/",
            "sec-ch-ua": '"Google Chrome";v="120", "Chromium";v="120", "Not=A?Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-app-version": "2.5.0",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "pl",
            "x-client-platform": "web",
            "x-client-timezone-offset": "7200",
            "x-client-version": "2.5.0",
        })

    def _ses(self, idx: int) -> Session:
        s = self.ap.slots[idx]
        if s is None:
            raise RuntimeError(f"Account slot {idx} not logged in")
        return s

    def _headers(self, account_idx: int, pow_resp: str | None = None) -> dict:
        s = self._ses(account_idx)
        ua = s.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        m = re.search(r'Chrome/(\d+)', ua)
        chrome_ver = m.group(1) if m else "120"
        h = {
            "accept": "*/*",
            "authorization": f"Bearer {s.auth_token}",
            "content-type": "application/json",
            "origin": "https://chat.deepseek.com",
            "referer": "https://chat.deepseek.com/",
            "sec-ch-ua": f'"Google Chrome";v="{chrome_ver}", "Chromium";v="{chrome_ver}", "Not=A?Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": ua,
            "x-app-version": "2.5.0",
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "pl",
            "x-client-platform": "web",
            "x-client-timezone-offset": "7200",
            "x-client-version": "2.5.0",
        }
        if pow_resp:
            h["x-ds-pow-response"] = pow_resp
        return h

    def _get_challenge(self, account_idx: int) -> dict:
        s = self._ses(account_idx)
        self._apply_proxy(account_idx)
        r = self._http.post(
            "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
            headers=self._headers(account_idx),
            json={"target_path": "/api/v0/chat/completion"},
            cookies=s.cookies,
            impersonate="chrome120",
            timeout=30,
        )
        resp_json = r.json()
        if not resp_json or resp_json.get("code") != 0 or not resp_json.get("data"):
            raise RuntimeError(f"PoW challenge failed for account {account_idx}: {r.text[:300]}")
        biz_data = resp_json["data"].get("biz_data")
        if not biz_data or "challenge" not in biz_data:
            raise RuntimeError(f"PoW challenge missing for account {account_idx}: {r.text[:300]}")
        return biz_data["challenge"]

    def _get_pow(self, account_idx: int) -> str:
        now = time.time()
        with self._pow_lock:
            cached = self._cached_pow.pop(account_idx, None)
            if cached and now < self._pow_expires.get(account_idx, 0):
                # Prefetch next PoW in background to replace the consumed one
                threading.Thread(target=self._prefetch_pow, args=(account_idx,), daemon=True).start()
                return cached
        challenge = self._get_challenge(account_idx)
        t0 = time.time()
        pow_resp = self.pow.solve_challenge(challenge)
        elapsed = time.time() - t0
        print(f"[POW] account={account_idx} solved in {elapsed:.1f}s (difficulty={challenge.get('difficulty')})", flush=True)
        # Pre-fetch next PoW in background for future requests (do not cache pow_resp as it is consumed now)
        threading.Thread(target=self._prefetch_pow, args=(account_idx,), daemon=True).start()
        return pow_resp

    def _get_upload_pow(self, account_idx: int) -> str:
        s = self._ses(account_idx)
        self._apply_proxy(account_idx)
        r = self._http.post(
            "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
            headers=self._headers(account_idx),
            json={"target_path": "/api/v0/file/upload_file"},
            cookies=s.cookies,
            impersonate="chrome120",
            timeout=30,
        )
        resp_json = r.json()
        if not resp_json or resp_json.get("code") != 0 or not resp_json.get("data"):
            raise RuntimeError(f"Upload PoW challenge failed for account {account_idx}: {r.text[:300]}")
        biz_data = resp_json["data"].get("biz_data")
        if not biz_data or "challenge" not in biz_data:
            raise RuntimeError(f"Upload PoW challenge missing for account {account_idx}: {r.text[:300]}")
        challenge = biz_data["challenge"]
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
            proxy_kwargs = cloud_shield.get_proxy_kwargs(account_idx)
            r = requests.post(
                "https://chat.deepseek.com/api/v0/file/upload_file",
                headers=h,
                multipart=mp,
                cookies=self._ses(account_idx).cookies,
                impersonate="chrome120",
                timeout=60,
                **proxy_kwargs,
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
                    **proxy_kwargs,
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

    def probe_auth(self, account_idx: int, allow_auto_login: bool = True) -> bool:
        """Sprawdza REALNIE, czy token konta jeszcze żyje (GET /users/current) oraz czy nie jest zbanowane."""
        # Jesli konto jest juz znane jako zbanowane/zmutowane - nie ma sensu odpytywac serwera ani robic auto-login
        now_ts = time.time()
        mute_until = _muted_slots_until.get(account_idx, 0.0)
        if mute_until > now_ts:
            return False
        try:
            s = self._ses(account_idx)
            self._apply_proxy(account_idx)
            r = self._http.get(
                "https://chat.deepseek.com/api/v0/users/current",
                headers=self._headers(account_idx),
                cookies=s.cookies,
                impersonate="chrome120",
                timeout=10,
            )
            data = r.json()
            code = data.get("code")
            if code == 40003 or "authorization failed" in data.get("msg", "").lower():
                if not allow_auto_login:
                    print(f"[AUTH PROBE] Slot {account_idx}: token WYGASL (40003) — pomijam szybki test startowy (brak blokowania).", flush=True)
                    return False
                print(f"[AUTH PROBE] Slot {account_idx}: token WYGASL (40003) — uruchamiam auto-logowanie...", flush=True)
                if try_auto_login(account_idx, self.ap):
                    print(f"[AUTH PROBE] Slot {account_idx}: odnowiono pomyslnie, sprawdzam ponownie...", flush=True)
                    return self.probe_auth(account_idx, allow_auto_login=False)
                return False
            if code != 0:
                return False
            biz = data.get("data", {}).get("biz_data", {})
            chat = biz.get("chat", {})
            if chat.get("is_muted", 0) == 1:
                mute_until = chat.get("mute_until")
                if mute_until:
                    _muted_slots_until[account_idx] = float(mute_until)
                    _save_muted_slots()
                import datetime
                until_s = datetime.datetime.fromtimestamp(mute_until).strftime("%Y-%m-%d %H:%M:%S") if mute_until else "?"
                print(f"[AUTH PROBE] Slot {account_idx}: KONTO ZMUTOWANE / ZBANOWANE do {until_s}!", flush=True)
                return False
            return True
        except Exception as e:
            print(f"[AUTH PROBE] Slot {account_idx}: blad sieci ({str(e)[:80]}) — nie wykluczam konta", flush=True)
            return True

    def create_session(self, account_idx: int) -> str:
        s = self._ses(account_idx)
        self._apply_proxy(account_idx)
        def _do():
            return self._http.post(
                "https://chat.deepseek.com/api/v0/chat_session/create",
                headers=self._headers(account_idx),
                json={"character_id": None},
                cookies=s.cookies,
                impersonate="chrome120",
                timeout=30,
            )
        last_exc = None
        for attempt in range(3):
            try:
                r = self._retry_on_network(_do, max_retries=2)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
                if not r.content or not r.content.strip():
                    raise RuntimeError(f"Empty response body (HTTP {r.status_code})")
                try:
                    resp_json = r.json()
                except Exception as e:
                    raise RuntimeError(f"Invalid JSON (HTTP {r.status_code}): {r.text[:300]}") from e
                print(f"[CREATE SESSION] account={account_idx} status={r.status_code} response={json.dumps(resp_json, ensure_ascii=False)[:500]}", flush=True)
                if resp_json.get("code") == 40003 or "authorization failed" in resp_json.get("msg", "").lower():
                    print(f"[AUTH EXPIRED] Slot {account_idx} token WYGASL (code: 40003) — uruchamiam natychmiastowe auto-logowanie...", flush=True)
                    if try_auto_login(account_idx, self.ap):
                        print(f"[AUTH RECOVERED] Slot {account_idx} pomyslnie zalogowany! Ponawiam tworzenie sesji...", flush=True)
                        return self.create_session(account_idx)
                    _auth_expired_slots.add(account_idx)
                    _rate_limited_until[account_idx] = time.time() + 86400
                    raise RuntimeError(f"Slot {account_idx} authorization expired: {resp_json.get('msg')}")
                data = resp_json.get("data")
                if data is None:
                    raise RuntimeError(f"Create session failed: {json.dumps(resp_json, ensure_ascii=False)[:300]}")
                return data["biz_data"]["chat_session"]["id"]
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    wait_s = (attempt + 1) * 1.0
                    print(f"[CREATE SESSION] account={account_idx} attempt {attempt+1}/3 failed: {e}. Retrying in {wait_s}s...", flush=True)
                    time.sleep(wait_s)
        raise RuntimeError(f"Create session failed for account {account_idx}: {last_exc}") from last_exc

    def create_session_with_fallback(self, preferred_idx: int) -> tuple[str, int]:
        """
        Tworzy sesję na koncie preferred_idx. Jeśli konto zwróci błąd (pusty dokument,
        błąd sieci, wygaśnięcie sesji), próbuje pozostałych kont w puli.
        Zwraca (session_id, account_idx_used).
        """
        candidates = [preferred_idx]
        for i in range(MAX_ACCOUNTS):
            if i != preferred_idx and self.ap.is_valid(i):
                candidates.append(i)

        last_err = None
        for idx in candidates:
            try:
                sid = self.create_session(idx)
                if idx != preferred_idx:
                    print(f"[CREATE SESSION FALLBACK] Preferred account {preferred_idx} failed, successfully created session on account {idx}: {sid}", flush=True)
                    with self.ap._pool_lock:
                        if 0 <= preferred_idx < MAX_ACCOUNTS and _slot_busy[preferred_idx]:
                            _slot_busy[preferred_idx] = False
                            self.ap._slot_conditions[preferred_idx].notify_all()
                        if 0 <= idx < MAX_ACCOUNTS:
                            _slot_busy[idx] = True
                return sid, idx
            except Exception as e:
                last_err = e
                print(f"[CREATE SESSION FALLBACK] Account {idx} failed: {e}", flush=True)

        raise RuntimeError(f"All accounts failed to create session (last error: {last_err})") from last_err

    def stop_completion(self, account_idx: int, chat_session_id: str):
        """Zatrzymuje generację wiadomości w toku na serwerze DeepSeek (anuluje stan WIP)."""
        try:
            s = self._ses(account_idx)
            self._apply_proxy(account_idx)
            self._http.post(
                "https://chat.deepseek.com/api/v0/chat/stop_completion",
                headers=self._headers(account_idx),
                json={"chat_session_id": chat_session_id},
                cookies=s.cookies,
                impersonate="chrome120",
                timeout=5
            )
            print(f"[STOP] Successfully requested stop_completion for session {chat_session_id}", flush=True)
        except Exception as e:
            print(f"[STOP] Stop completion request failed (non-fatal): {e}", flush=True)


    def stream_continue(self, account_idx: int, chat_session_id: str, message_id: int, **kwargs):
        """Wysyła żądanie kontynuacji do natywnego endpointu DeepSeek Web (/api/v0/chat/continue)."""
        return self.stream_completion(
            account_idx=account_idx,
            chat_session_id=chat_session_id,
            prompt="",
            parent_message_id=message_id,
            is_continue=True,
            **kwargs
        )

    def stream_completion(self, account_idx: int, chat_session_id: str, prompt: str = "",
                          parent_message_id: int | None = None,
                          max_tokens: int = 8192, temperature: float = 1.0, top_p: float = 1.0,
                          model_type: str = "expert", ref_file_ids: list[str] | None = None,
                          thinking_enabled: bool = True, search_enabled: bool = False,
                          _retry: int = 0, _auto_continue_budget: int = 2,
                          tools_available: bool = False,
                          watermark_uuid: str | None = None,
                          _spam_budget: list | None = None,
                          is_continue: bool = False):
        if _retry > 0:
            print(f"[RETRY] Attempt {_retry} for session={chat_session_id[:12]}...", flush=True)
        # WSPÓLNY budżet oczekiwania na anty-spam, przewlekany przez CAŁĄ rekurencję tego żądania.
        # Wcześniej każdy poziom rekurencji (preamble + in-stream) dokładał własne 3 × 60 s,
        # więc pojedyncze żądanie potrafiło wisieć 10 minut i kończyć się zerem treści.
        # Teraz oczekiwanie jest sumarycznie ograniczone — lepiej oddać jawny błąd niż wisieć.
        if _spam_budget is None:
            _spam_budget = [MAX_SPAM_WAIT_S]
        from curl_cffi.requests.exceptions import RequestException as CurlError
        max_retries = 3
        # 1. Global IP pacing: ochrona puli przed jednoczesnym zalewem zadan ze wszystkich kont naraz
        global _last_global_completion_time
        with _global_pacing_lock:
            g_elapsed = time.time() - _last_global_completion_time
            g_min = 3.5 + random.uniform(0.5, 1.5)  # 4.0 - 5.0s bufor pomiedzy zadaniami z tego samego IP
            if g_elapsed < g_min:
                time.sleep(g_min - g_elapsed)
            _last_global_completion_time = time.time()

        # 2. Bezpiecznik wyszukiwania sieciowego (search_enabled / model search)
        if search_enabled:
            global _last_search_completion_time
            with _search_pacing_lock:
                s_elapsed = time.time() - _last_search_completion_time
                s_min = 14.0 + random.uniform(1.0, 4.0)
                if s_elapsed < s_min:
                    s_sleep = s_min - s_elapsed
                    print(f"[SEARCH PACING] Bufor bezpieczenstwa dla wyszukiwarki: {s_sleep:.2f}s...", flush=True)
                    time.sleep(s_sleep)
                _last_search_completion_time = time.time()

        # 3. Dynamiczny antyspam pacing na koncie zależny od pojemności puli i obciążenia klastra
        now_ts = time.time()
        last_fin = _last_account_finish_time[account_idx]
        elapsed = (now_ts - last_fin) if last_fin > 0 else 9999.0
        
        # Oblicz ile slotow realnie dziala i nie jest wyciszonych
        num_active = 0
        pool = getattr(self, 'ap', None) or globals().get('ap')
        if pool is not None:
            num_active = sum(1 for i in range(MAX_ACCOUNTS) if pool.is_valid(i))
        else:
            num_active = 1

        # Ochrona per-konto: niezaleznie od liczby kont w puli, to samo konto NIE MOZE
        # dostac zapytania szybciej niz 28-35s od zakonczenia poprzedniego (tarcza anty-ban DeepSeek)!
        base_pacing = 28.0 + random.uniform(2.0, 7.0)  # 30.0 - 35.0s
        pacing_label = f"TARCZA ANTY-BAN SLOTU {account_idx} (30-35s)"

        cong_mult, cong_desc = _get_cluster_congestion_factor()
        min_pacing = base_pacing * cong_mult
        pacing_reason = f"{pacing_label} [mnożnik {cong_mult:.2f}x: {cong_desc}]"

        if _retry == 0 and elapsed < min_pacing:
            sleep_needed = min_pacing - elapsed
            print(f"[PACING] Pacing {sleep_needed:.2f}s na slocie {account_idx} ({pacing_reason}, od zakończenia poprzedniego zadania minęło {elapsed:.1f}s)...", flush=True)
            time.sleep(sleep_needed)
        proxy_kwargs = cloud_shield.get_proxy_kwargs(account_idx)
        for attempt in range(max_retries + 1):
            try:
                s = self._ses(account_idx)
                if is_continue:
                    req_url = "https://chat.deepseek.com/api/v0/chat/continue"
                    req_headers = self._headers(account_idx)
                    req_json = {
                        "chat_session_id": chat_session_id,
                        "message_id": parent_message_id,
                        "fallback_to_resume": True,
                    }
                else:
                    pow_resp = self._get_pow(account_idx)
                    req_url = "https://chat.deepseek.com/api/v0/chat/completion"
                    req_headers = self._headers(account_idx, pow_resp)
                    req_json = {
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
                    }

                t_post_start = time.time()
                r = requests.post(
                    req_url,
                    headers=req_headers,
                    json=req_json,
                    cookies=s.cookies,
                    impersonate="chrome120",
                    stream=True,
                    timeout=(15, 120),
                    **proxy_kwargs,
                )
                break
            except CurlError as e:
                err_str = str(e).lower()
                if proxy_kwargs and ("proxy" in err_str or "connect" in err_str or "resolve" in err_str):
                    cloud_shield.mark_proxy_unhealthy(str(e))
                    proxy_kwargs = {}
                    print(f"[CLOUD PROXY FALLBACK] Blad proxy ({e}). Plynne przelaczenie na bezposrednie polaczenie...", flush=True)
                    continue
                if attempt < max_retries:
                    print(f"[RETRY] curl error (attempt {attempt+1}/{max_retries}): {e}", flush=True)
                    time.sleep(5)
                    continue
                raise

        if r.status_code == 401:
            print(f"[HTTP 401] Slot {account_idx} wygasl. Oznaczam jako nieaktywny w puli.", flush=True)
            _auth_expired_slots.add(account_idx)
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
            try:
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
            finally:
                stop_ev.set()
                try:
                    r.close()
                except Exception:
                    pass

        # Preambuła objęta watchdogiem: zero danych przez 180s kończy czekanie zamiast
        # wisieć do 300s (LOW_SPEED_TIME curl_cffi = timeout=300) na martwym sockecie.
        watchdog_it = _iter_lines_with_watchdog(it, timeout_sec=180.0)
        resp_msg_id: str | int | None = ""
        pre_lines: list[bytes] = []
        rate_limit_detected = False
        preamble_data_count = 0
        ttft_recorded = False
        for line in watchdog_it:
            pre_lines.append(line)
            if not line:
                continue
            decoded = line.decode("utf-8", "ignore")
            if decoded.startswith("data: "):
                if not ttft_recorded:
                    ttft_recorded = True
                    ttft_val = time.time() - t_post_start
                    _record_ttft(ttft_val)
                    avg_t = sum(_recent_ttfts) / len(_recent_ttfts) if _recent_ttfts else ttft_val
                    print(f"[TTFT] Slot {account_idx}: pierwsze dane po {ttft_val:.2f}s (średnia={avg_t:.2f}s, próbki={len(_recent_ttfts)})", flush=True)
                preamble_data_count += 1
                try:
                    d = json.loads(decoded[6:])
                    if d.get("type") == "error":
                        err = d.get("content", "Unknown error")
                        fr = str(d.get("finish_reason") or "")
                        print(f"[ERROR] DeepSeek error: {err} (finish_reason={fr})", flush=True)
                        _record_cluster_busy()
                        if "length limit" in err.lower() or "start a new chat" in err.lower() or "context_length" in err.lower() or "content is too long" in err.lower() or "input_exceeds_limit" in err.lower() or "limit długości" in err.lower() or "rozpocznij nowy czat" in err.lower() or "context_length" in fr.lower():
                            raise RuntimeError(f"DeepSeek error [{fr}]: {err}" if fr else f"DeepSeek error: {err}")
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
                print(f"[POW] INVALID_POW_RESPONSE (attempt {_retry+1}) – clearing PoW cache and retrying...", flush=True)
                with self._pow_lock:
                    self._cached_pow.pop(account_idx, None)
                    self._pow_expires.pop(account_idx, 0)
                return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry, watermark_uuid=watermark_uuid, _spam_budget=_spam_budget)

        if rate_limit_detected:
            if not ENABLE_ACCOUNT_MIGRATION:
                if _retry < 3 and _spam_budget[0] > 5:
                    wait = min(60.0, _spam_budget[0])
                    _spam_budget[0] -= wait
                    print(f"[ANTYSPAM COOLDOWN] Preamble rate-limited na slocie {account_idx} ({err}). "
                          f"Pauza {wait:.0f}s (próba {_retry+1}/3, pozostały budżet {_spam_budget[0]:.0f}s)...", flush=True)
                    time.sleep(wait)
                    return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1, watermark_uuid=watermark_uuid, _spam_budget=_spam_budget)
                raise RuntimeError(
                    f"DeepSeek anty-spam: wyczerpany budżet oczekiwania ({MAX_SPAM_WAIT_S:.0f}s) — {err}")
            _rate_limited_until[account_idx] = time.time() + 120
            now_check = time.time()
            other_available = any(i != account_idx and self.ap.is_valid(i) and now_check >= _rate_limited_until[i] for i in range(MAX_ACCOUNTS))
            if _retry >= 1 or other_available:
                print(f"[RETRY] Preamble rate-limited on account={account_idx} (other_available={other_available}), giving up fast to migrate", flush=True)
                raise RuntimeError(f"DeepSeek busy after {_retry+1} retries: preamble rate-limited")
            wait = 60 + random.randint(-10, 15)
            _rate_limited_until[account_idx] = time.time() + wait + 10
            print(f"[RETRY] Preamble rate-limited (attempt {_retry+1}), waiting {wait}s...", flush=True)
            time.sleep(wait)
            return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1, watermark_uuid=watermark_uuid)
        resp_msg_id = int(resp_msg_id) if resp_msg_id else None
        if preamble_data_count == 0:
            raw_preview = b"".join(pre_lines).decode("utf-8", "ignore")[:300] if pre_lines else "empty"
            print(f"[WARN] No data lines from DeepSeek for session={chat_session_id} parent={parent_message_id} (body: {raw_preview})", flush=True)
            if "user is muted" in raw_preview.lower() or '"biz_code":5' in raw_preview or '"biz_code": 5' in raw_preview:
                mute_sec = 7200.0
                mute_until_dt = ""
                mute_until_ts = time.time() + mute_sec
                try:
                    data_obj = json.loads(raw_preview)
                    mu = data_obj.get("data", {}).get("biz_data", {}).get("mute_until")
                    if mu:
                        diff = float(mu) - time.time()
                        mute_sec = max(60.0, diff + 10.0)
                        mute_until_ts = float(mu)
                        mute_until_dt = f" (odblokowanie: {datetime.fromtimestamp(float(mu)).strftime('%H:%M:%S')})"
                except Exception:
                    pass
                print(f"[MUTED] Slot {account_idx} zablokowany przez DeepSeek (user is muted na {mute_sec/60:.1f} min{mute_until_dt}).", flush=True)
                _muted_slots_until[account_idx] = mute_until_ts
                _save_muted_slots()
                _rate_limited_until[account_idx] = mute_until_ts
                raise RuntimeError(f"DeepSeek account {account_idx} is muted na {mute_sec/60:.1f} min{mute_until_dt}: {raw_preview}")
            elif "message still wip" in raw_preview.lower() or '"biz_code":11' in raw_preview or '"biz_code": 11' in raw_preview:
                print(f"[WIP] Previous message still generating on DeepSeek. Requesting stop and waiting...", flush=True)
                self.stop_completion(account_idx, chat_session_id)
                time.sleep(3.5)
                if _retry < 4:
                    return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1, watermark_uuid=watermark_uuid)
            elif _retry < 2:
                print(f"[RETRY] 0 data lines received, retrying (attempt {_retry+1})...", flush=True)
                time.sleep(3)
                return self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1, watermark_uuid=watermark_uuid)
            raise RuntimeError(f"DeepSeek empty stream (0 data lines) on account={account_idx}")
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
            reasoning_yielded_len = 0
            prev_yielded = 0
            raw_count = 0
            finished_normally = False
            loop_aborted = False
            stream_aborted = False  # DeepSeek przerwał generację w połowie (generation_err po starcie)
            # Czy to tura NAJWYŻSZEGO poziomu (żądanie użytkownika), czy wywołanie zagnieżdżone
            # przez wewnętrzne ponowienie? Zagnieżdżone też logowały "[TURN] FINAL", przez co
            # w logu wyglądało to tak, jakby tura zakończyła się sukcesem, gdy naprawdę
            # zakończyło się tylko wewnętrzne ponowienie, a tura zewnętrzna była urwana.
            # Zapamiętujemy to RAZ, na wejściu — budżet jest później zmniejszany przez drabinkę.
            _is_top_level_turn = _auto_continue_budget > 0

            def _route_token(text):
                """Kieruje token treści do właściwego bufora na podstawie fazy.
                Yields chunki tekstu do wyemitowania (ReasoningChunk dla fazy THINK, str dla RESPONSE).
                BUG-031: Jeśli w trakcie fazy THINK model zacznie generować znaczniki narzędzi
                (<tool_calls>, <invoke> itp.) lub </think>, następuje natychmiastowe dynamiczne
                przełączenie fazy z THINK na RESPONSE."""
                nonlocal content_buffer, thinking_buffer, response_started, thinking_active, prev_yielded, reasoning_yielded_len
                if not text:
                    return
                if not response_started and not thinking_active:
                    # Brak deklaracji fazy = tryb bez myślenia (lub starszy format):
                    # bare tokeny to RESPONSE. Myślenie jest tłumione TYLKO gdy
                    # DeepSeek jawnie zadeklarował fragment THINK przed tokenami.
                    response_started = True
                if response_started:
                    content_buffer += text
                    if watermark_uuid:
                        monitor.token(watermark_uuid)
                    inc = content_buffer[prev_yielded:]
                    if inc:
                        prev_yielded = len(content_buffer)
                        yield inc
                    return
                # Faza THINK — reasoning streamujemy do Trae jako reasoning_content (BUG-004)
                thinking_buffer += text
                if watermark_uuid:
                    monitor.thinking_token(watermark_uuid, count=max(1, len(text.split())))

                # Ścisła izolacja CoT: W trakcie fazy THINK narzędzia NIGDY nie są parsowane
                # ani wyciągane z myśli. Jedynym legalnym przejściem w RESPONSE ze strumienia myślenia
                # jest jawny znacznik końca myślenia </think> (lub </thought>).
                _think_end = re.search(r'</\s*(?:think|thought)\s*>', thinking_buffer, re.IGNORECASE)
                if _think_end:
                    split_pos = _think_end.start()
                    # Wyemituj zaległe myślenie sprzed znacznika </think>
                    if split_pos > reasoning_yielded_len:
                        rem_reasoning = thinking_buffer[reasoning_yielded_len:split_pos]
                        reasoning_yielded_len = split_pos
                        if rem_reasoning:
                            yield _ReasoningChunk(rem_reasoning)

                    tool_content = thinking_buffer[_think_end.end():]
                    thinking_buffer = thinking_buffer[:split_pos]
                    thinking_active = False
                    response_started = True
                    content_buffer = tool_content
                    prev_yielded = len(content_buffer)
                    if tool_content:
                        yield tool_content
                    return

                # Jeśli nie ma narzędzia, powstrzymaj emisję prefiksu tagu (np. '<', '<tool'),
                # aby w razie rozpoczęcia wywołania narzędzia w kolejnym tokenie nie wyciekło ono do reasoning.
                pref_m = _TAG_PREFIX_PAT.search(thinking_buffer)
                safe_end = pref_m.start() if pref_m else len(thinking_buffer)
                if safe_end > reasoning_yielded_len:
                    to_yield = thinking_buffer[reasoning_yielded_len:safe_end]
                    reasoning_yielded_len = safe_end
                    if to_yield:
                        yield _ReasoningChunk(to_yield)

            def _begin_phase(ftype, fcontent):
                """Obsługuje deklarację fragmentu THINK/RESPONSE: ustawia fazę i emituje
                początkowy fragment treści. Yields chunki do emisji."""
                nonlocal response_started, thinking_active, content_buffer, thinking_buffer, prev_yielded, reasoning_yielded_len
                if ftype == "THINK":
                    thinking_active = True
                    response_started = False
                    if watermark_uuid:
                        monitor.thinking_token(watermark_uuid, count=len(fcontent.split()) if fcontent else 1)
                    if fcontent:
                        yield from _route_token(fcontent)
                    return
                if ftype == "RESPONSE":
                    thinking_active = False
                    response_started = True
                    # Spłucz wszelkie pozostałe reasoning_content z bufora myślenia
                    if thinking_buffer and len(thinking_buffer) > reasoning_yielded_len:
                        rem = thinking_buffer[reasoning_yielded_len:]
                        # Sprawdz czy na koncu myslenia nie zostal urwany znacznik poczatku taga narzedzia (np. "<" lub "<||DS")
                        pref_m = _TAG_PREFIX_PAT.search(rem) or re.search(r'<\s*[|｜\uff5c\u2502\s]*/?\s*(?:DSML|DS|tool|invoke)[^>]*$', rem, re.IGNORECASE)
                        if pref_m:
                            cut_idx = pref_m.start()
                            tag_prefix = rem[cut_idx:]
                            rem = rem[:cut_idx]
                            content_buffer = tag_prefix + content_buffer
                        reasoning_yielded_len = len(thinking_buffer)
                        if rem:
                            yield _ReasoningChunk(rem)
                    if watermark_uuid:
                        monitor.token(watermark_uuid)
                    if fcontent:
                        content_buffer += fcontent
                        inc = content_buffer[prev_yielded:]
                        if inc:
                            prev_yielded = len(content_buffer)
                            yield inc
                    return
            # Diagnostyka: świeży plik z SUROWYM strumieniem DeepSeek (pełne linie JSON,
            # bez obcinania do 200 znaków). Nadpisywany przy każdym strumieniu, więc po
            # następnej reprodukcji błędu zobaczymy dokładny format thinking/response/tools.
            _raw_capture = os.path.join(DATA_DIR, "raw_stream_capture.jsonl")
            try:
                open(_raw_capture, "w", encoding="utf-8").close()
            except Exception:
                _raw_capture = None
            for line in chain(pre_lines, remaining_it):
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
                    fr_raw = str(data.get("finish_reason") or "")
                    err_lower = err_msg.lower()
                    # DeepSeek potrafi PRZERWAĆ generację już po jej starcie: model zdążył
                    # wygenerować wyłącznie reasoning (np. "Let me read the task file first."),
                    # po czym przychodzi quasi_status=INCOMPLETE + generation_err. To NIE jest
                    # limit konta — mamy już węzeł odpowiedzi i częściowy strumień. Wychodzimy
                    # z pętli (zamiast rzucać wyjątek), żeby zadziałało auto-continue, które
                    # dokończy turę w TEJ SAMEJ sesji. Wcześniej klasyfikowaliśmy to jako
                    # rate-limit: proxy migrowało konto, gubiło sesję i kończyło komunikatem
                    # "wyślij kontynuuj" — dokładnie to, co blokowało pracę.
                    if (("generation_err" in fr_raw.lower() or "niedostępny" in err_lower
                         or "niedostepny" in err_lower or "unavailable" in err_lower)
                            and (thinking_buffer.strip() or content_buffer.strip())):
                        print(f"[GEN-ABORT] DeepSeek przerwał generację po częściowym strumieniu "
                              f"(reason={fr_raw}, resp={resp_msg_id}, thinking={len(thinking_buffer)}, "
                              f"content={len(content_buffer)}) — oddaję do auto-continue w tej samej sesji", flush=True)
                        stream_aborted = True
                        break
                    print(f"[ERROR] DeepSeek error: {err_msg}", flush=True)
                    if ("too frequent" in err_lower or "server is busy" in err_lower or "serwer jest zajęty" in err_lower
                        or "zajęty" in err_lower or "zajety" in err_lower or "zbyt" in err_lower
                        or "niedostępny" in err_lower or "niedostepny" in err_lower or "unavailable" in err_lower
                        or "message is being generated" in err_lower or "parallel_chat_limit" in fr_raw or "busy" in fr_raw.lower()
                        or "generation_err" in fr_raw.lower() or "rate_limit" in fr_raw.lower()):
                        if not ENABLE_ACCOUNT_MIGRATION:
                            # Brak rotacji kont: ponawiamy na tym samym koncie po odpowiedniej pauzie
                            is_spam = ("zbyt" in err_lower or "too frequent" in err_lower or "rate_limit" in fr_raw.lower())
                            max_retries = 3
                            if _retry < max_retries and (not is_spam or _spam_budget[0] > 5):
                                # "Serwer jest tymczasowo niedostępny" przy dużym promptcie to NIE zajętość
                                # konta, tylko odrzucenie zbyt długiej wiadomości. Ponawianie identycznego
                                # promptu gwarantuje ten sam błąd, więc od 2. próby twardo obcinamy prompt.
                                retry_prompt = prompt
                                if _retry >= 1 and not is_spam and len(prompt) > _PROMPT_HARD_LIMIT:
                                    # Cięcie na granicy linii, żeby nie rozerwać bloku kodu w połowie.
                                    _cut = prompt.rfind("\n", 0, _PROMPT_HARD_LIMIT)
                                    if _cut < _PROMPT_HARD_LIMIT // 2:
                                        _cut = _PROMPT_HARD_LIMIT
                                    retry_prompt = prompt[:_cut] + "\n\n[...treść obcięta — zbyt długi prompt...]"
                                    print(f"[SHRINK] Prompt {len(prompt)} -> {len(retry_prompt)} chars przed ponowieniem", flush=True)
                                if is_spam:
                                    wait = 60
                                elif "busy" in err_lower or "zajęty" in err_lower or "zajety" in err_lower or "busy" in fr_raw.lower():
                                    wait = 8 + (_retry * 4) + random.uniform(1.0, 3.0)  # Przeciążenie klastra: pauza 9-15s na rozładowanie kolejki
                                else:
                                    wait = 2 + (_retry * 2)
                                if is_spam:
                                    # Pauza pobierana ze WSPÓLNEGO budżetu — kolejne poziomy rekurencji
                                    # nie mogą już doliczyć własnych 3 × 60 s (to dawało 600 s zawieszenia).
                                    wait = min(float(wait), _spam_budget[0])
                                    _spam_budget[0] -= wait
                                    print(f"[ANTYSPAM COOLDOWN] DeepSeek zwrócił 'za szybko' na koncie {account_idx}. "
                                          f"Pauza {wait:.0f}s (próba {_retry+1}/{max_retries}, pozostały budżet {_spam_budget[0]:.0f}s)...", flush=True)
                                else:
                                    print(f"[RETRY] Chwilowy błąd DeepSeek ({err_msg}), ponawiam na slocie {account_idx} za {wait}s (próba {_retry+1}/{max_retries})...", flush=True)
                                time.sleep(wait)
                                retry_result = self.stream_completion(account_idx, chat_session_id, retry_prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1, watermark_uuid=watermark_uuid, _spam_budget=_spam_budget)
                                if retry_result is not None:
                                    new_gen, retry_meta = retry_result
                                    if retry_meta.get("resp_msg_id") is not None:
                                        resp_msg_id = retry_meta["resp_msg_id"]
                                    result_meta["resp_msg_id"] = resp_msg_id
                                    result_meta["finished_normally"] = retry_meta.get("finished_normally", False)
                                    yield from new_gen
                                    return
                            raise RuntimeError(f"DeepSeek error po {max_retries} próbach: {err_msg}")
                        _rate_limited_until[account_idx] = time.time() + 120
                        now_check = time.time()
                        other_available = any(i != account_idx and self.ap.is_valid(i) and now_check >= _rate_limited_until[i] for i in range(MAX_ACCOUNTS))
                        if _retry >= 1 or other_available:
                            print(f"[RETRY] Giving up fast on account={account_idx} (other_available={other_available}) to trigger migration", flush=True)
                            raise RuntimeError(f"DeepSeek busy after {_retry+1} retries: {err_msg}")
                        wait = 60 + random.randint(-10, 15)
                        _rate_limited_until[account_idx] = time.time() + wait + 10
                        print(f"[RETRY] Rate-limited (attempt {_retry+1}, reason={fr_raw}), waiting {wait}s...", flush=True)
                        time.sleep(wait)
                        retry_result = self.stream_completion(account_idx, chat_session_id, prompt, parent_message_id, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, _retry=_retry+1, watermark_uuid=watermark_uuid)
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
                    raise RuntimeError(f"DeepSeek error [{fr_raw}]: {err_msg}" if fr_raw else f"DeepSeek error: {err_msg}")
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
                                    for _tok in _begin_phase(_frag.get("type"), _frag.get("content") or ""):
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
                    for _tok in _route_token(val):
                        if _tok:
                            yield _tok
                    if _detect_loop(content_buffer):
                        loop_aborted = True
                        break
                    continue
                if not path and isinstance(val, str) and val:
                    for _tok in _route_token(val):
                        if _tok:
                            yield _tok
                    # Anti-loop guard: przetnij petle tokenow (loop_aborted=True)
                    if _detect_loop(content_buffer):
                        loop_aborted = True
                        break
                    continue
                if path == "response/fragments" and isinstance(val, list):
                    for fragment in val:
                        if isinstance(fragment, dict):
                            for _tok in _begin_phase(fragment.get("type"), fragment.get("content") or ""):
                                if _tok:
                                    yield _tok
                    # Anti-loop guard: przetnij petle tokenow (loop_aborted=True)
                    if _detect_loop(content_buffer):
                        loop_aborted = True
                        break
                    continue
            if thinking_active and thinking_buffer and len(thinking_buffer) > reasoning_yielded_len:
                rem = thinking_buffer[reasoning_yielded_len:]
                reasoning_yielded_len = len(thinking_buffer)
                if rem:
                    yield _ReasoningChunk(rem)

            if not response_started or not content_buffer.strip():
                # Ścisła izolacja CoT: Sprawdź czy w thinking_buffer nie został znacznik </think>.
                # Tylko tekst po </think> ma prawo stać się treścią czatu.
                # NIGDY nie wyciągamy narzędzi ze środka myślenia przed </think>!
                _think_end = re.search(r'</\s*(?:think|thought)\s*>', thinking_buffer, re.IGNORECASE)
                if _think_end:
                    extracted_content = thinking_buffer[_think_end.end():]
                    thinking_buffer = thinking_buffer[:_think_end.start()]
                    if extracted_content.strip():
                        thinking_active = False
                        response_started = True
                        content_buffer += extracted_content
                        inc = content_buffer[prev_yielded:]
                        if inc:
                            prev_yielded = len(content_buffer)
                            yield inc
                        print(f"[THINK RECOVERY] Safely extracted {len(extracted_content)} chars post-</think> into content.", flush=True)
                elif thinking_buffer:
                    print(f"[THINK] captured {len(thinking_buffer)} chars of reasoning (clean CoT, zero tool leakage)", flush=True)

            # ── Moduł 2: Kontrakt ukończenia tury ──
            # UWAGA: NIE ma tu już żadnego TWIERDZĄCEGO ustawiania `finished_normally`
            # ("jest treść albo narzędzie => sukces"). To był dokładnie ten mechanizm, przez
            # który każdy nieprzewidziany scenariusz wychodził jako "sukces" z pustą odpowiedzią.
            # Teraz o dostarczeniu tury decyduje WYŁĄCZNIE totalny klasyfikator `_classify_turn()`
            # plus drabinka `TURN_LADDER` (patrz niżej) — sukces trzeba UDOWODNIĆ.
            def _declared_action_only() -> bool:
                """Model zapowiedział akcję samym tekstem ("Let me read the file...", "Sprawdzam
                stan...") i NIE wyemitował wywołania narzędzia. Tura wygląda wtedy na zakończoną,
                Trae czeka w miejscu, a użytkownik musi ręcznie pisać "kontynuuj"."""
                if not tools_available or _parse_tool_calls(content_buffer):
                    return False
                txt = _STRIP_TAGS.sub("", _clean_dsml_wait(content_buffer)).strip()
                if not txt or "```" in txt or len(txt) > 2000:
                    return False
                # Pytanie do użytkownika to NIE jest pusta obietnica — model czeka na odpowiedź
                if txt.endswith("?") or "?" in txt[-80:]:
                    return False
                # Krótka wypowiedź (<=250 znaków) z bezpośrednią zapowiedzią akcji
                if len(txt) <= 250:
                    return bool(_ACTION_PROMISE_RE.search(txt) or _ACTION_FUTURE_RE.search(txt))
                # Dłuższa wypowiedź merytoryczna — tylko jeśli kończy się urwanym dwukropkiem/myślnikiem po zapowiedzi
                tail = txt[-100:].strip()
                if tail.endswith(":") or tail.endswith("...") or tail.endswith("—") or tail.endswith("-"):
                    return bool(_ACTION_PROMISE_RE.search(tail) or _ACTION_FUTURE_RE.search(tail))
                return False

            def _classify_turn() -> str:
                """TOTALNY klasyfikator tury — decyduje, czy tura jest dostarczona."""
                if loop_aborted:
                    return TURN_ABORTED
                _calls = _parse_tool_calls(content_buffer)
                # Jeśli wyemitowano poprawne, kompletne narzędzia — tura jest ZAWSZE ukończona sukcesem
                if _calls:
                    return TURN_COMPLETE
                _tail = content_buffer
                if _has_unclosed_tool_call(_tail):
                    return TURN_UNCLOSED_TOOL
                if not content_buffer.strip():
                    return TURN_ONLY_THINKING if thinking_buffer.strip() else TURN_EMPTY
                if _declared_action_only():
                    return TURN_PROMISE
                if stream_aborted:
                    return TURN_PARTIAL
                return TURN_COMPLETE

            # ── PĘTLA ODZYSKIWANIA STEROWANA KLASYFIKATOREM ──
            # Jedna pętla, jedna tabela bodźców (TURN_STIMULUS), jedna drabinka eskalacji
            # (TURN_LADDER). Wcześniej było tu sześć niezależnych warunków i łańcuch
            # if/elif — każde nowe urwanie strumienia wymagało dopisania kolejnej gałęzi.
            turn_outcome = _classify_turn()
            ladder_step = 0
            auto_continue_count = 0
            while turn_outcome != TURN_COMPLETE:
                ladder = TURN_LADDER.get(turn_outcome)
                if ladder is None:
                    print(f"[TURN] outcome={turn_outcome} — brak dalszej eskalacji dla tej klasy (nie ponawiam)", flush=True)
                    break
                if ladder_step >= len(ladder) or _auto_continue_budget <= 0 or resp_msg_id is None:
                    print(f"[TURN] outcome={turn_outcome} — koniec drabinki ({ladder_step}/{len(ladder)}), budżet={_auto_continue_budget}", flush=True)
                    break
                thinking_override, cooldown = ladder[ladder_step]
                ladder_step += 1
                _auto_continue_budget -= 1
                auto_continue_count += 1
                cont_prompt = TURN_STIMULUS.get(turn_outcome, "kontynuuj")
                print(f"[TURN-RETRY {ladder_step}/{len(ladder)}] outcome={turn_outcome} parent={resp_msg_id} "
                      f"(content={len(content_buffer)} chars, thinking={len(thinking_buffer)} chars) "
                      f"-> thinking={thinking_override}, cooldown={cooldown}s", flush=True)
                # Sesja właśnie zakończyła (przerwaną) generację — DeepSeek potrzebuje chwili,
                # zanim przyjmie kolejną wiadomość w tym samym czacie. Bez tego od razu leci
                # "Zbyt częste wiadomości" (rate_limit_reached) i odzyskiwanie pada, a użytkownik
                # dostaje "pusty strumień". Cooldown rośnie z każdym szczeblem drabinki.
                time.sleep(cooldown)
                # Ponawiamy CAŁĄ kontynuację razem z iteracją generatora — błąd potrafi wylecieć
                # dopiero przy czytaniu tokenów, nie przy samym wywołaniu stream_completion.
                # Ponawiamy wyłącznie wtedy, gdy nic jeszcze nie wysłaliśmy (inaczej duplikaty).
                cont_yielded = False
                cont_ok = False

                # Próba 1 dla urwanego strumienia (TURN_PARTIAL / stream_aborted): natywne /continue
                if (turn_outcome == TURN_PARTIAL or stream_aborted) and resp_msg_id is not None:
                    print(f"[AUTO-CONTINUE] Próba natywnego continue (POST api/v0/chat/continue) dla session={chat_session_id[:12]} msg={resp_msg_id}...", flush=True)
                    try:
                        cont_res = self.stream_continue(
                            account_idx, chat_session_id, resp_msg_id,
                            _auto_continue_budget=0, watermark_uuid=watermark_uuid,
                            _spam_budget=_spam_budget
                        )
                        if cont_res is not None:
                            cont_gen, cont_meta = cont_res
                            for tok in cont_gen:
                                if tok is _HEARTBEAT_SENTINEL:
                                    yield tok
                                    continue
                                if tok and isinstance(tok, str):
                                    cont_yielded = True
                                    content_buffer += tok
                                    yield tok
                            if cont_meta.get("resp_msg_id") is not None:
                                resp_msg_id = cont_meta["resp_msg_id"]
                            stream_aborted = bool(cont_meta.get("stream_aborted", False))
                            loop_aborted = bool(cont_meta.get("loop_aborted", False))
                            if cont_meta.get("finished_normally") or cont_yielded:
                                cont_ok = True
                                print(f"[AUTO-CONTINUE] Natywny continue udany (content={len(content_buffer)} chars)!", flush=True)
                    except Exception as nce:
                        print(f"[AUTO-CONTINUE] Natywny continue zgłosił błąd ({nce}), przechodzę do standardowego bodźca...", flush=True)

                if not cont_ok and not cont_yielded:
                    for _ca_try in range(3):
                        try:
                            cont_res = self.stream_completion(
                                account_idx, chat_session_id, cont_prompt, resp_msg_id,
                                max_tokens=max_tokens, temperature=temperature, top_p=top_p,
                                model_type=model_type, ref_file_ids=ref_file_ids,
                                # Myślenie sterowane drabinką: przy zablokowaniu w fazie THINK,
                                # samej zapowiedzi akcji lub pustej turze wyłączamy je, żeby model
                                # MUSIAŁ wyemitować wywołanie narzędzia albo finalną odpowiedź
                                # (potwierdzone testem na żywo); ostatni szczebel może je włączyć.
                                thinking_enabled=(thinking_enabled if thinking_override is None else thinking_override),
                                search_enabled=search_enabled,
                                _auto_continue_budget=0, watermark_uuid=watermark_uuid,
                                _spam_budget=_spam_budget)
                            if cont_res is None:
                                raise RuntimeError("session expired")
                            cont_gen, cont_meta = cont_res
                            for tok in cont_gen:
                                if tok is _HEARTBEAT_SENTINEL:
                                    yield tok
                                    continue
                                if tok and isinstance(tok, str):
                                    cont_yielded = True
                                    content_buffer += tok
                                    yield tok
                            if cont_meta.get("resp_msg_id") is not None:
                                resp_msg_id = cont_meta["resp_msg_id"]
                            # KRYTYCZNE: flagi opisują OSTATNIĄ próbę, a nie historię tury.
                            # Wcześniej `stream_aborted` ustawione przez pierwszy urwany strumień
                            # zostawało True na zawsze, więc po UDANYM dokończeniu (np. 30 000 znaków
                            # wygenerowanych poprawnie) klasyfikator dalej widział `partial` — proxy
                            # raportowało turę jako niedostarczoną i dobijało kolejne ponowienia.
                            stream_aborted = bool(cont_meta.get("stream_aborted", False))
                            loop_aborted = bool(cont_meta.get("loop_aborted", False))
                            cont_ok = True
                            break
                        except Exception as ce:
                            if cont_yielded:
                                print(f"[AUTO-CONTINUE] Continue error after partial output: {str(ce)[:140]}", flush=True)
                                break
                            wait = 5 + _ca_try * 7
                            print(f"[AUTO-CONTINUE] Continue failed ({str(ce)[:120]}) — próba {_ca_try+1}/3, czekam {wait}s", flush=True)
                            if _ca_try < 2:
                                time.sleep(wait)
                if not cont_ok and not cont_yielded:
                    print(f"[AUTO-CONTINUE] Sesja zajęta/rate-limited — odzyskiwanie nieudane", flush=True)
                    break
                # Reklasyfikacja po próbie — dopiero teraz wiemy, czy tura jest kompletna.
                # Pętla kończy się sama, gdy klasyfikator zwróci TURN_COMPLETE.
                turn_outcome = _classify_turn()
                print(f"[TURN-RETRY] po próbie {ladder_step}: outcome={turn_outcome} (yielded={cont_yielded})", flush=True)

            # Sukces WYŁĄCZNIE wtedy, gdy klasyfikator udowodnił kompletność tury.
            # To jest jedyne miejsce, w którym zapada decyzja "dostarczone / nie".
            finished_normally = (_classify_turn() == TURN_COMPLETE)
            result_meta["turn_outcome"] = turn_outcome
            if auto_continue_count and not finished_normally:
                result_meta["auto_continue_failed"] = True

            result_meta["resp_msg_id"] = resp_msg_id
            result_meta["finished_normally"] = finished_normally
            result_meta["loop_aborted"] = loop_aborted
            # Przekazywane do tury nadrzędnej, żeby jej klasyfikator widział stan OSTATNIEJ
            # próby, a nie stan z początku tury (patrz komentarz przy pętli retry).
            result_meta["stream_aborted"] = stream_aborted
            if not finished_normally:
                print(f"[STREAM] Incomplete — returning partial content ({len(content_buffer)} chars). Next RESUME will continue.", flush=True)
            # Jedna linia na zakończoną turę — samoopisujący się wynik, żeby diagnoza nie
            # wymagała już grzebania w surowym strumieniu DeepSeeka. Wywołania zagnieżdżone
            # oznaczamy inaczej, żeby nie udawały wyniku tury zewnętrznej.
            _tag = "[TURN] FINAL" if _is_top_level_turn else "[TURN-SUB] (ponowienie wewnętrzne)"
            print(f"{_tag} outcome={turn_outcome} finished={finished_normally} "
                  f"retries={auto_continue_count} content={len(content_buffer)} chars "
                  f"thinking={len(thinking_buffer)} chars resp={resp_msg_id}", flush=True)
            _last_account_finish_time[account_idx] = time.time()
            try:
                r.close()
            except Exception:
                pass

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
            self.stop_completion(account_idx, chat_session_id)
        time.sleep(1.5)
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
    """Deleguje logowanie do login.direct_login() w celu unifikacji logowania w jednym module."""
    try:
        import login
        ok = login.direct_login(slot)
        if not ok:
            raise Exception(f"Logowanie slotu {slot} nie powiodło się.")
        ap.reload_slot(slot)
        ds._cached_pow.clear()
        ds._pow_expires.clear()
        return f"Slot {slot} authenticated successfully"
    except Exception as e:
        print(f"[AUTH ERROR] Slot {slot} logowanie przerwane: {e}", flush=True)
        raise


# â”€â”€â”€ FastAPI App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

app = FastAPI(title="DeepSeek V4-Pro Proxy")

@app.get("/")
@app.get("/v1/info")
def proxy_info(request: Request):
    port = request.url.port or request.scope.get("server", [None, 4570])[1]
    is_clean = (port == 4571)
    return {
        "status": "online",
        "current_port": port,
        "mode": "CZYSTY_PASSTHROUGH (zero promptu)" if is_clean else "KODOWANIE_DEV (z promptem)",
        "guide": {
            "4570": "KODOWANIE & DEV (dla Trae / Cursor / Cortex Chat - wstrzykuje instrukcje programisty)",
            "4571": "CZYSTY PASSTHROUGH (dla Useme Core / botow / skryptow - zero wstrzykiwania, model dostaje czyste dane)"
        }
    }

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
DEBUG_DIAGNOSTICS = os.environ.get("DEEPSEEK_DIAGNOSTICS", "0") == "1"

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


MAX_PROMPT_LEN = 150000
# Awaryjny limit pojedynczej wiadomości wysyłanej do DeepSeek. Prompty powyżej
# CHUNK_THRESHOLD są dzielone na chunk-bezpieczne paczki, więc normalnie ten limit
# nigdy nie powinien zadziałać — to tylko ostatnia siatka bezpieczeństwa na wypadek,
# gdyby coś przeszło niepodzielone. Powyżej DeepSeek zwraca generation_err
# "Serwer jest tymczasowo niedostępny" (de facto odrzucenie zbyt długiej wiadomości).
_PROMPT_HARD_LIMIT = 95000
# Polityka kont: BEZ ROTACJI przy każdej przerwie.
# Rotacja konta oznacza, że sesja DeepSeek tej rozmowy NIE ISTNIEJE na nowym koncie, więc
# trzeba wysłać CAŁY kontekst od zera — a model na takim zduplikowanym, wielotysięcznym
# prompcie wpada w pętlę. Dlatego przy chwilowych błędach (rate_limit / generation_err /
# "serwer zajęty") proxy CZEKA i ponawia na TYM SAMYM koncie (gałęzie
# "if not ENABLE_ACCOUNT_MIGRATION" w stream_completion). Na inne konto przechodzi dopiero
# po wyczerpaniu timeoutu w acquire_slot — jako świadoma, logowana ostateczność.
ENABLE_ACCOUNT_MIGRATION = False

def _compress_tool_results(messages: list[dict], threshold: int = 25000) -> list[dict]:
    """Przycina zbyt wielkie wyniki narzędzi z zachowaniem numerów linii i informacji o fragmencie.
    Nie wycina wszystkiego do 3 linijek, lecz dostarcza bezpieczną porcję i precyzyjny zakres."""
    result = []
    for msg in messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) <= threshold:
            result.append(msg)
            continue
        char_count = len(content)
        lines = content.splitlines()
        total_lines = len(lines)
        
        # Read-like content z numerami linii (np. "  1→" lub "1:")
        if re.match(r'^\s*\d+[\u2192\->:]', content):
            kept = []
            curr_chars = 0
            for l in lines:
                if curr_chars + len(l) + 1 > threshold:
                    break
                kept.append(l)
                curr_chars += len(l) + 1
            kept_count = len(kept)
            omitted = max(0, total_lines - kept_count)
            
            # Wyciągnij numery linii
            line_nums = [int(m.group(1)) for m in re.finditer(r"^\s*(\d+)[\u2192\->:]", "\n".join(kept), re.MULTILINE)]
            start_l = min(line_nums) if line_nums else 1
            end_l = max(line_nums) if line_nums else kept_count
            
            banner = (
                f"[FILE METADATA: STATUS: PARTIAL SNIPPET (linie {start_l}-{end_l} z {total_lines} łącznie, ~{curr_chars} znaków)]\n"
                f"[INFO DLA AI: Plik jest duży — dostarczono linie {start_l}-{end_l}. Pozostałe {omitted} linii ({end_l+1}-{total_lines}) możesz odczytać kolejnym zapytaniem narzędziem Read z parametrem offset={end_l+1}]"
            )
            compressed = f"{banner}\n\n" + "\n".join(kept) + f"\n\n[... Pominięto {omitted} kolejnych linii ({end_l+1}-{total_lines}) — użyj Read z offset={end_l+1} aby przeczytać resztę ...]"
        else:
            # Inny wynik narzędzia (Grep, Glob, itp.)
            kept_chunk = content[:threshold]
            omitted_chars = char_count - len(kept_chunk)
            banner = f"[INFO DLA AI: Wynik przycięty do {len(kept_chunk)}/{char_count} znaków ze względu na limit długości.]"
            compressed = f"{banner}\n\n{kept_chunk}\n\n[... Pominięto {omitted_chars} kolejnych znaków wyniku ...]"
        result.append(dict(msg, content=compressed))
    return result


_last_known_env = {
    "cwd": os.path.abspath(os.getcwd()),
    "os": "windows" if os.name == "nt" else os.name
}


def _extract_environment_info(messages: list[dict]) -> tuple[str, str]:
    """Wyciąga Primary working directory oraz Operating system z tagów <system-reminder>."""
    global _last_known_env
    cwd = None
    os_name = None
    if messages:
        for m in messages:
            c = m.get("content", "")
            texts = []
            if isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        texts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        texts.append(part)
            elif isinstance(c, str):
                texts.append(c)
            full_text = "\n".join(texts)
            if not full_text:
                continue
            norm = full_text.replace('\\r\\n', '\n').replace('\\n', '\n')
            if "Primary working directory:" in norm and not cwd:
                m_cwd = re.search(r'Primary working directory:\s*([^\n\r<]+)', norm)
                if m_cwd:
                    cwd = m_cwd.group(1).strip()
            if "Operating system:" in norm and not os_name:
                m_os = re.search(r'Operating system:\s*([^\n\r<]+)', norm)
                if m_os:
                    os_name = m_os.group(1).strip()
            if cwd and os_name:
                break

    if cwd:
        _last_known_env["cwd"] = cwd
    if os_name:
        _last_known_env["os"] = os_name

    return _last_known_env["cwd"], _last_known_env["os"]


def _clean_system_reminders(text: str) -> str:
    """Usuwa zbędne boilerplate Trae/IDE, ale ZACHOWUJE wyniki narzędzi, błędy i stan odczytu."""
    if not isinstance(text, str):
        return text
    
    # 1. Usuń dyrektywy systemowe i przypomnienia IDE
    text = re.sub(r'<critical_directive>[\s\S]*?</critical_directive>', '', text)
    text = re.sub(r'<skills_instructions>[\s\S]*?</skills_instructions>', '', text)
    text = re.sub(r'<available_skills>[\s\S]*?</available_skills>', '', text)
    text = re.sub(r'</?previous_tool_call[^>]*>', '', text)
    text = re.sub(r'intent\.\s*When a skill is relevant[^\n]*', '', text, flags=re.IGNORECASE)

    # 2. Zachowaj wyniki i błędy narzędzi z tagów <system-reminder>, a resztę boilerplate usuń
    def _handle_system_reminder(m):
        inner = m.group(1).strip()
        if any(k in inner for k in ("Calling the", "Result of the calling", "Failed to", "Error", "toolcall",
                                    "limit of", "Read tool", "selected content size", "exceeds the limit",
                                    "shorter than", "does not exist", "No such file", "not found",
                                    "permission denied", "outside the", "empty file")):
            return f"\n[System Tool Notification]:\n{inner}\n"
        return ""
    text = re.sub(r'<system-reminder>([\s\S]*?)</system-reminder>', _handle_system_reminder, text, flags=re.IGNORECASE)
    text = re.sub(r'</?system-reminder[^>]*>', '', text, flags=re.IGNORECASE)

    # 3. Odpakuj właściwy <user_input> użytkownika (zabezpieczone przed pętlą nieskończoną)
    for _ in range(5):
        if "<user_input>" not in text or "</user_input>" not in text:
            break
        new_text = re.sub(r'<user_input>\s*([\s\S]*?)\s*</user_input>', r'\1', text, flags=re.IGNORECASE)
        if new_text == text:
            break
        text = new_text
    text = re.sub(r'</?user_input[^>]*>', '', text, flags=re.IGNORECASE)
    
    # 4. Sanityzuj tagi narzędzi IDE z Trae/Cline/Cortex
    text = re.sub(r'<toolcall_status>[\s\S]*?</toolcall_status>', '', text)
    text = re.sub(r'<toolcall_error_message>\s*([\s\S]*?)\s*</toolcall_error_message>', r'Error: \1', text)
    text = re.sub(r'<toolcall_result>\s*([\s\S]*?)\s*</toolcall_result>', r'\1', text)
    text = re.sub(r'</?toolcall_[^>]*>', '', text)
    
    return text.strip()



def _annotate_read_tool_result(content: str, file_path: str, offset: int | None = None, limit: int | None = None) -> str:
    """Wzbogaca wynik narzędzia Read/read_file o metadane rozmiaru, zakresu i wskazówkę akcji."""
    if not isinstance(content, str) or not content.strip() or "[FILE METADATA:" in content:
        return content
    if not file_path or not isinstance(file_path, str):
        return content

    fp = os.path.abspath(file_path)
    total_lines = None
    if os.path.isfile(fp):
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                total_lines = sum(1 for _ in f)
        except Exception:
            total_lines = None

    line_nums = [int(m.group(1)) for m in re.finditer(r"^(\d+)[\u2192:>\s]", content, re.MULTILINE)]
    if line_nums:
        start_line = min(line_nums)
        end_line = max(line_nums)
    else:
        start_line = offset if (isinstance(offset, int) and offset > 0) else 1
        cnt = len(content.splitlines())
        end_line = start_line + max(0, cnt - 1)

    fname = os.path.basename(file_path)
    if total_lines is not None and total_lines > 0:
        is_full = (start_line <= 1 and end_line >= total_lines) or (len(content.splitlines()) >= total_lines)
        if is_full:
            banner = (
                f"[FILE METADATA: {fname} | STATUS: FULL FILE (100% loaded, lines 1-{total_lines} of {total_lines})]\n"
                f"[GUIDANCE: You have the complete file content in context. Do NOT re-read this file.]"
            )
        else:
            pct = min(100.0, max(0.1, (end_line - start_line + 1) / total_lines * 100))
            banner = (
                f"[FILE METADATA: {fname} | STATUS: PARTIAL SNIPPET (lines {start_line}-{end_line} of {total_lines} total, {pct:.1f}% coverage)]\n"
                f"[ACTION GUIDANCE: To modify these lines, use SearchReplace on this specific snippet. "
                f"The Write tool is reserved for NEW files or 100% full rewrites from scratch.]"
            )
    else:
        banner = (
            f"[FILE METADATA: {fname} | STATUS: LINES DELIVERED ({start_line}-{end_line})]\n"
            f"[ACTION GUIDANCE: For editing this snippet use SearchReplace. Write is reserved for new files or full rewrites.]"
        )
    return f"{banner}\n\n{content}"


def _format_msgs(msgs: list[dict], keep_images: bool = False, strip_reminders: bool = False) -> list[str]:
    parts = []
    tool_call_map = {}
    for m in msgs:
        if m.get("role") == "assistant":
            for call in (m.get("tool_calls") or []):
                if isinstance(call, dict):
                    cid = call.get("id")
                    if cid:
                        fn = call.get("function") or {}
                        raw_args = fn.get("arguments", "{}")
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                        except Exception:
                            args = {}
                        tool_call_map[cid] = (fn.get("name", ""), args if isinstance(args, dict) else {})
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
                    txt = _clean_system_reminders(part)
                    if txt:
                        texts.append(txt)
            content = "\n\n".join(texts).strip()
        elif isinstance(content, str):
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
                tname, targs = tool_call_map.get(tid, ("", {}))
                if tname in ("Read", "read", "read_file"):
                    fp = targs.get("file_path") or targs.get("path") or targs.get("filePath")
                    if fp:
                        content = _annotate_read_tool_result(content, str(fp), offset=targs.get("offset"), limit=targs.get("limit"))
                tool_label = f"[Tool Result ({tname})]" if tname else "[Tool Result]"
                parts.append(f"{tool_label}:\n{content.strip()}")
        if tc:
            action_strs = []
            for call in tc:
                fn = call.get("function", {})
                name = fn.get("name", "tool")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}
                formatted_args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()) if isinstance(args, dict) else ""
                action_strs.append(f"[Assistant Action]: {name}({formatted_args})")
            if action_strs:
                parts.append("\n".join(action_strs))
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
    """Dla odzyskiwania sesji: przycina wyniki narzędzi z zachowaniem numerów linii i treści (do 15k znaków) zamiast 1-linijkowych śmieci."""
    return _compress_tool_results(messages, threshold=15000)


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


def _build_anti_loop_guard(messages: list[dict]) -> str:
    """Buduje notkę anty-pętlową (BUG-001/005/010/013/015): pliki już przeczytane
    i komendy już uruchomione w historii konwersacji. Wstrzykuje ją do promptu,
    żeby model nie czytał ponownie tych samych plików (doom-loop) i nie powtarzał
    tych samych komend terminala (paranoja konsoli)."""
    files_read: set[str] = set()
    commands_run: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for call in (msg.get("tool_calls") or []):
            if not isinstance(call, dict):
                continue
            fn = call.get("function") or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}
            fp = args.get("file_path") or args.get("path") or args.get("filePath") or ""
            if name in ("Read", "read", "read_file") and fp:
                files_read.add(str(fp))
            elif name in ("Glob", "glob", "Grep", "grep", "SearchCodebase") and fp:
                files_read.add(str(fp))
            elif name in ("RunCommand", "run_command", "run_command_in_terminal"):
                cmd = args.get("command")
                if isinstance(cmd, str) and cmd.strip():
                    commands_run.append(cmd.strip())

    if not files_read and not commands_run:
        return ""

    lines = ["## STATE GUARD (anti-loop)"]
    if files_read:
        lines.append("Files already read — their content is in context above, do NOT re-read:")
        for f in sorted(files_read)[:15]:
            lines.append(f"- {f}")
    if commands_run:
        deduped: list[str] = []
        for c in commands_run:
            if c not in deduped:
                deduped.append(c)
        lines.append("Shell commands already run recently — do NOT repeat them unless the result is missing:")
        for c in deduped[-8:]:
            lines.append(f"- {c}")
    return "\n\n" + "\n".join(lines)


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
        # Keep CURRENT turn intact — DO NOT compress unless individually massive (>25000 chars),
        # but deduplicate identical tool outputs (e.g. 5x read of same 70k file) to avoid 350k+ prompt explosions
        current_turn = rest[keep_from:]
        safe_current = []
        seen_current_tool_hashes = set()
        for msg in current_turn:
            c = msg.get("content", "")
            if msg.get("role") == "tool" and isinstance(c, str):
                c_hash = hash(c[:2000] + str(len(c)))
                if c_hash in seen_current_tool_hashes:
                    # Duplikat tego samego wyniku narzędzia w bieżącej turze!
                    compressed_dup = dict(msg, content=f"[Zduplikowany wynik narzędzia — treść tożsama z poprzednim wywołaniem ({len(c)} znaków)]")
                    safe_current.append(compressed_dup)
                    continue
                seen_current_tool_hashes.add(c_hash)
                # Pojedynczy odczyt powyżej 25k znaków skracamy, aby nie przebić limitu 35k
                if len(c) > 25000:
                    safe_current.append(_compress_tool_results([msg])[0])
                else:
                    safe_current.append(msg)
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
    # ── Tool Schemas & Instructions Suffix (Compact Format: ~4k vs 44k chars) ──
    tools_suffix = ""
    if tools:
        tools_suffix += "\n\n# Available Tool Schemas\n"
        for t in tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function", t)
            name = fn.get("name", "?")
            desc = fn.get("description", "").split("\n")[0][:150].strip()
            params = fn.get("parameters", {})
            param_strs = []
            if isinstance(params, dict):
                props = params.get("properties", {})
                required = set(params.get("required", [])) if isinstance(params.get("required"), list) else set()
                if isinstance(props, dict):
                    for pname, pdef in props.items():
                        if not isinstance(pdef, dict):
                            continue
                        ptype = pdef.get("type", "any")
                        req = "*" if pname in required else ""
                        enum = pdef.get("enum", [])
                        enum_str = f"[{'|'.join(str(e) for e in enum)}]" if enum else ""
                        param_strs.append(f"{pname}{req}{enum_str}: {ptype}")
            params_joined = ", ".join(param_strs)
            tools_suffix += f"\n## {name}\n- **{name}**({params_joined}): {desc}\n"
        tools_suffix += """

# CRITICAL TOOL CALLING RULES:
1. When you need to inspect files, search code, read directories, or perform any action, you MUST immediately invoke the tool call in this response.
2. DO NOT announce or say what you plan to do in text without emitting the tool call in the same turn (NEVER say "Zacznę od...", "Zaraz przeczytam...", "I will read..." without invoking the tool).
3. If a tool previously failed (e.g. file size exceeded limit), immediately invoke the tool with offset and limit parameters to inspect portions of the file.
4. When writing or editing files (Write, Edit, SearchReplace), ALWAYS put "file_path" as the VERY FIRST parameter before "content".
5. Format tool calls using standard format:
<tool_call name="ToolName">
  <parameter name="file_path">c:/path/to/file</parameter>
  <parameter name="content">file content here</parameter>
</tool_call>"""

    # Obliczamy dynamiczny budżet na wiadomości po odliczeniu schematów narzędzi
    msgs_budget = max(25000, MAX_PROMPT_LEN - len(tools_suffix))
    strip_reminders = (tools is None or _clean_mode_enabled())
    parts = _format_msgs(system + rest, keep_images=bool(images), strip_reminders=strip_reminders)
    
    # Jeśli jesteśmy w trybie wznawiania (tools is None) i mamy tylko jedną wiadomość użytkownika,
    # wysyłamy czystą treść bez zbędnych etykiet [User]:
    if tools is None and len(parts) == 1 and parts[0].startswith("[User]: "):
        prompt = parts[0][len("[User]: "):].strip()
    else:
        prompt = "\n\n".join(parts)

    # Progresywne przycinanie STAREJ historii tylko wtedy, gdy cała historia przekracza budżet
    if len(prompt) > msgs_budget and rest:
        for keep_n in (20, 10, 5, 2, 1):
            if len(prompt) <= msgs_budget:
                break
            parts = _format_msgs(system + rest[-keep_n:], keep_images=bool(images), strip_reminders=strip_reminders)
            prompt = "\n\n".join(parts)

    # ── Anti-loop guard (BUG-001/005/010/013/015) ──
    guard = _build_anti_loop_guard(messages)
    if guard:
        prompt += guard

    # Doklejenie schematów narzędzi (ZAWSZE PEŁNYCH, NIGDY NIE UCINANYCH)
    prompt += tools_suffix

    # Zwracamy pełny prompt — jeśli prompt > 50k znaków, _chunk_oversized_prompt wyśle go bezpiecznie w chunkach
    return prompt


CHUNK_THRESHOLD = 95000


def _chunk_oversized_prompt(prompt: str, max_chunk_size: int = CHUNK_THRESHOLD) -> list[str]:
    """
    Dzieli duży prompt (> 95k znaków) na listę mniejszych części (<= max_chunk_size),
    respektując granice wiadomości ([User]:, [Assistant]:, [System]:, [Tool Result]:)
    oraz akapitów (\\n\\n), aby nie uszkodzić żadnego bloku kodu ani tagu XML.
    """
    if len(prompt) <= max_chunk_size:
        return [prompt]

    # Szukamy granic wiadomości: \n\n[User]: , \n\n[Assistant]: , \n\n[System]: , \n\n[Tool Result , \n\n# Available Tools
    split_pattern = r"(?=\n\n(?:\[(?:User|Assistant|System|Tool|Tool Result|Assistant Action)[^\]]*\]:|<tool_result\b|# Available Tool))"
    raw_sections = [s for s in re.split(split_pattern, prompt) if s.strip()]
    if not raw_sections:
        raw_sections = [prompt]

    def _hard_split(text: str) -> list[str]:
        """Dzieli tekst na kawałki <= max_chunk_size: po akapitach, potem po liniach,
        a na końcu twardo po znakach — np. zminifikowany plik bez ani jednego newline.
        Lookahead/lookbehind w splitach nie zjada separatorów, więc konkatenacja
        kawałków odtwarza oryginalny tekst 1:1."""
        out: list[str] = []
        for para in re.split(r"(?<=\n\n)", text):
            if len(para) <= max_chunk_size:
                if para.strip():
                    out.append(para)
                continue
            for line in re.split(r"(?<=\n)", para):
                while len(line) > max_chunk_size:
                    out.append(line[:max_chunk_size])
                    line = line[max_chunk_size:]
                if line.strip():
                    out.append(line)
        return out

    chunks: list[str] = []
    current_chunk = ""

    for sec in raw_sections:
        is_oversized = len(sec) > max_chunk_size
        # Wcześniej liczono tu "and sub_chunk" na samym "\n\n" (truthy), a potem
        # robiono .strip() -> do listy trafiał PUSTY chunk. DeepSeek odrzucał go
        # komunikatem "missing prompt or ref file", co kończyło się 502.
        for piece in (_hard_split(sec) if is_oversized else [sec]):
            if current_chunk and len(current_chunk) + len(piece) > max_chunk_size:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            current_chunk += piece
        if is_oversized and current_chunk:
            # Duża sekcja domyka bieżący chunk, żeby nie sklejać jej z następną.
            chunks.append(current_chunk.strip())
            current_chunk = ""

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Twarda gwarancja: zero pustych chunków i zero chunków ponad limit.
    clean_chunks = [c for c in chunks if c.strip()]
    return clean_chunks if clean_chunks else [prompt[:max_chunk_size]]


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
    # Model czasem duplikuje tag parametru:
    #   <parameter name="pattern"><parameter name="pattern">**/README.md</parameter>
    # Wtedy wyłuskana wartość ZACZYNA się od zagnieżdżonego tagu (zamykający tag zostaje
    # zjedzony jako delimiter), a Trae dostawał w argumencie surowy XML zamiast wzorca.
    # Zdejmij wiodące tagi parametru (także osierocony tag zamykający na końcu).
    _param_open = r'<\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)?(?:parameter|参数|參數)\s+name=(["\']).*?\1[^>]*>'
    for _ in range(3):
        m_lead = re.match(_param_open, s, re.IGNORECASE)
        if not m_lead:
            break
        s = s[m_lead.end():].strip()
    s = _strip_close_tail(s)
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


_NUMERIC_PARAM_KEYS = {"offset", "limit", "head_limit", "max_tokens", "max_completion_tokens", "wait_ms_before_async"}


def _sanitize_tool_params(name: str, params: dict) -> dict:
    """Normalizuje parametry numeryczne (BUG-021: offset=False -> deserialize params error).

    - bool -> śmieć, kasuj (False nie jest poprawnym offsetem/limitem)
    - int >= 0 -> zostaw
    - str z cyframi (np. "60") -> konwertuj do int (NIE kasuj!)
    - wszystko inne -> kasuj
    """
    if not isinstance(params, dict):
        return params
    out = {}
    for k, v in params.items():
        if k in _NUMERIC_PARAM_KEYS:
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                if v < 0:
                    continue
                out[k] = v
                continue
            if isinstance(v, str):
                sv = v.strip()
                try:
                    out[k] = int(sv)
                except ValueError:
                    continue
                continue
        out[k] = v

    # Normalizacja aliasów dla narzędzi edycyjnych (Edit / SearchReplace)
    if (name or "").lower() in ("edit", "searchreplace"):
        if "old_str" in out and "old_string" not in out:
            out["old_string"] = out["old_str"]
        elif "old_string" in out and "old_str" not in out:
            out["old_str"] = out["old_string"]
        if "new_str" in out and "new_string" not in out:
            out["new_string"] = out["new_str"]
        elif "new_string" in out and "new_str" not in out:
            out["new_str"] = out["new_string"]

    if name in ("RunCommand", "run_command") and isinstance(out.get("command"), str):
        cmd = out["command"]
        safe_ps_kill = "Get-CimInstance Win32_Process -Filter \\\"Name = 'python.exe'\\\" | Where-Object { $_.CommandLine -notmatch 'server\\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        if re.search(r'Stop-Process\s+(?:-(?:Process)?Name\s+)?["\']?python(?:\.exe)?["\']?', cmd, re.IGNORECASE):
            out["command"] = re.sub(
                r'Stop-Process\s+(?:-(?:Process)?Name\s+)?["\']?python(?:\.exe)?["\']?(?:\s+-[A-Za-z0-9_]+(?:\s+[A-Za-z0-9_]+)?)*',
                safe_ps_kill,
                cmd,
                flags=re.IGNORECASE
            )
            print(f"[SHIELD] Sanitized suicide command in RunCommand (protected server.py)!", flush=True)
        elif re.search(r'taskkill\s+(?:/[A-Za-z0-9]+\s+)*(/IM\s+python(?:\.exe)?)', cmd, re.IGNORECASE):
            out["command"] = re.sub(
                r'taskkill\s+.*?(?:/IM\s+python(?:\.exe)?).*?(?:$|[;&|])',
                f'powershell -NoProfile -Command "{safe_ps_kill}"; ',
                cmd,
                flags=re.IGNORECASE
            )
            print(f"[SHIELD] Sanitized suicide taskkill in RunCommand (protected server.py)!", flush=True)

    return out


def _map_positional(name: str, body: str) -> dict:
    """Mapuje surową treść tagu narzędzia (bez zagnieżdżonych <parameter>) na argumenty.

    Deterministycznie rozdziela opcjonalne liczby na końcu dla narzędzi z plikiem
    (Read), aby nie wkleić "plik 1220 200" do pola file_path (błąd File does not exist).
    """
    b = (body or "").strip()
    if not b:
        return {}
    if name == "Read":
        parts = b.rsplit(None, 2)
        nums_at_end = []
        while parts and parts[-1].isdigit() and len(nums_at_end) < 2:
            nums_at_end.insert(0, parts.pop())
        file_path = " ".join(parts).strip()
        d = {"file_path": file_path} if file_path else {}
        if nums_at_end:
            d["offset"] = int(nums_at_end[0])
        if len(nums_at_end) == 2:
            d["limit"] = int(nums_at_end[1])
        return d
    if name == "Glob":
        parts = b.split(None, 1)
        if len(parts) == 2:
            p1, p2 = parts[0].strip(), parts[1].strip()
            is_path = lambda s: bool(re.search(r'^[a-zA-Z]:|^[\\/]|\.[\\/]', s)) or ('\\' in s and '*' not in s)
            if is_path(p1) and not is_path(p2):
                return {"path": p1, "pattern": p2}
            elif is_path(p2) and not is_path(p1):
                return {"path": p2, "pattern": p1}
        return {"pattern": b}
    if name == "Grep":
        parts = b.split()
        if len(parts) >= 2:
            pat = parts[0].strip()
            path = parts[1].strip()
            d = {"pattern": pat, "path": path}
            if len(parts) >= 3 and parts[2] in ("files_with_matches", "content"):
                d["output_mode"] = parts[2]
            if len(parts) >= 4 and parts[3].isdigit():
                d["head_limit"] = int(parts[3])
            return d
        return {"pattern": b}
    if name == "LS":
        return {"path": b}
    if name == "RunCommand":
        return {"command": b}
    if name == "Task":
        return {"query": b}
    return {"query": b}


def _should_bump_state(tools_yielded: int, result_meta: dict) -> bool:
    """Czy tura jest sukcesem uprawniającym do bumpowania msgs_len.

    Ucięty/zapętlony strumień (loop_aborted) NIGDY nie jest sukcesem, nawet jeśli
    w content_buffer była preambuła tekstu.
    """
    return tools_yielded > 0 or (
        bool(result_meta.get("finished_normally"))
        and not bool(result_meta.get("loop_aborted"))
    )


# --- BUG-034: wywołanie ucięte przez znacznik zamknięcia tkwiący w treści ---
# Gdy model zapisuje plik, którego TREŚĆ sama zawiera markap DSML (np. transkrypt
# rozmowy z zapisanymi wywołaniami narzędzi), znaczniki wewnątrz treści są
# nierozróżnialne od prawdziwego zamknięcia. Dotychczasowe parsowanie (body
# nie-zachłanne + pierwsze napotkane zamknięcie) ucinało wywołanie w tym miejscu:
# ginął cały parametr (Trae: "missing field content") albo jego ogon (cicha utrata
# treści). Poniżej deterministyczny odzysk oparty na tym, że wartości parametrów
# rozdzielamy KOLEJNYM OTWARCIEM parametru, a nie znacznikiem zamknięcia.
# --- BUG-034 & BUG-035: Odporny parser DSML i ochrona przed rozjeżdżaniem parametrów ---
# Obsługuje zarówno pełne domknięcia </||DSML||parameter>, </parameter>, jak i nagi </||DSML||>,
# oraz zagnieżdżony markap DSML wewnątrz treści (np. zapisy logów/transkryptów w Write/SearchReplace).
_INVOKE_OPEN_RE = re.compile(
    r'''<\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*\s*(?:tool_call|invoke|tool_capability|_call|call|tool|调用|調用|工具|函数)?|(?:tool_call|invoke|tool_capability|_call|call|tool|调用|調用|工具|函数))\s+(?:[^>]*?\s+)?name=(["'])([^"']*?)\1[^>]*>''',
    re.IGNORECASE
)
_INVOKE_CLOSE_RE = re.compile(
    r'''</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*\s*(?:ask|tool_calls?|calls?|invoke|tool_capability|_calls?|call|tool|action)|(?:ask|tool_calls?|calls?|invoke|tool_capability|_calls?|call|tool|action|调用|調用|工具|函数))\s*>''',
    re.IGNORECASE
)
_PARAM_OPEN_RE = re.compile(
    r'''<\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*\s*)?(?:parameter|参数|參數)\s+(?:[^>]*?\s+)?name=(["'])([^"']+?)\1[^>]*>''',
    re.IGNORECASE
)
_PARAM_CLOSE_RE = re.compile(
    r'''</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*\s*(?:parameter|参数|參數)?|(?:parameter|参数|參數))\s*>''',
    re.IGNORECASE
)
_ANY_CLOSE_TAIL_RE = re.compile(
    r'''(?:\s*</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*\s*)?(?:[a-zA-Z0-9_\u4e00-\u9fff\-]+)?\s*>|\s*<[|｜\uff5c\u2502\s]*tool\s+call\s+end[|｜\uff5c\u2502\s]*>|\s*</?\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*>?\s*)+(?=\s*$)''',
    re.IGNORECASE
)

# Znane parametry per narzędzie (ochrona przed połykaniem parametrów przez poprzedzające pola)
_TOOL_VALID_PARAMS = {
    "read": ["file_path", "offset", "limit"],
    "write": ["file_path", "content"],
    "edit": ["file_path", "old_str", "new_str", "old_string", "new_string", "instruction", "content"],
    "searchreplace": ["file_path", "old_str", "new_str", "old_string", "new_string"],
    "ls": ["path", "ignore"],
    "glob": ["pattern", "path"],
    "grep": ["pattern", "path", "glob", "output_mode", "-B", "-A", "-C", "-n", "-i", "type", "head_limit", "offset", "multiline"],
    "runcommand": ["cwd", "command", "target_terminal", "command_type", "blocking", "wait_ms_before_async", "requires_approval"],
    "checkcommandstatus": ["command_id", "wait_ms_before_check", "output_character_count", "skip_character_count", "output_priority", "filter"],
    "stopcommand": ["command_id"],
    "deletefile": ["file_paths"],
    "task": ["description", "query", "subagent_type", "response_language"],
    "skill": ["name"],
    "websearch": ["query", "num", "lr"],
    "webfetch": ["url"],
    "todowrite": ["todos", "merge", "summary"],
    "askuserquestion": ["questions"],
    "notifyuser": ["explanation", "file_paths"],
    "getdiagnostics": ["uri"],
    "openpreview": ["preview_url", "command_id"],
    "get_goal": [],
    "create_goal": ["objective", "token_budget"],
    "update_goal": ["status"],
    "run_mcp": ["server_name", "tool_name", "args"],
}

_REQUIRED_PARAMS = {
    "write": (("file_path",), ("content",)),
    "edit": (("file_path",), ("old_str", "old_string", "new_str", "new_string", "content", "instruction")),
    "searchreplace": (("file_path",), ("old_str", "old_string", "new_str", "new_string")),
    "read": (("file_path",),),
    "runcommand": (("command",),),
    "deletefile": (("file_paths",),),
    "grep": (("pattern",),),
    "glob": (("pattern",),),
    "ls": (("path",),),
    "task": (("query",),),
}


def _params_complete(name: str, params: dict) -> bool:
    """Czy call ma wszystkie wymagane pola? Decyduje o kompletności wywołania."""
    if not isinstance(params, dict):
        return False
    tname = (name or "").lower()
    if tname in ("get_goal", "getdiagnostics"):
        return True
    if not params:
        return False
    groups = _REQUIRED_PARAMS.get(tname)
    if not groups:
        return len(params) > 0
    for group in groups:
        if not any(k in params and params[k] is not None and str(params[k]).strip() != "" for k in group):
            return False
    return True


def _strip_close_tail(raw: str) -> str:
    """Zdejmuje z końca wartości osierocone znaczniki zamknięcia."""
    prev = None
    while prev != raw:
        prev = raw
        raw = _ANY_CLOSE_TAIL_RE.sub("", raw).rstrip()
    return raw


def _parse_invoke_body_with_meta(name: str, body: str) -> tuple[dict, bool]:
    """Odzyskuje i parsuje parametry wywołania z uwzględnieniem tagów DSML i zagnieżdżonego markapu.
    Zwraca (params, all_params_closed) gdzie all_params_closed informuje, czy każdy otwarty parametr
    został poprawnie i jawnie domknięty przez </parameter> lub </||DSML||>."""
    valid_params = _TOOL_VALID_PARAMS.get(name.lower(), [])
    valid_param_set = {p.lower() for p in valid_params} if valid_params else set()

    # Krok 1: Próba standardowego dopasowania czystych par <parameter name="...">...</parameter>
    param_pat = re.compile(
        rf'''{_PARAM_OPEN_RE.pattern}(.*?){_PARAM_CLOSE_RE.pattern}''',
        re.DOTALL | re.IGNORECASE
    )
    params = {}
    matches = list(param_pat.finditer(body))
    for m in matches:
        pname = m.group(2).strip()
        pval = _parse_param_value(m.group(3))
        params[pname] = pval

    # JSON fallback
    if not params:
        jm = re.search(r'\{.*\}', body, re.DOTALL)
        if jm:
            parsed_jm = _safe_json_loads(jm.group(0))
            if isinstance(parsed_jm, dict):
                params = parsed_jm

    # BUG-022: surowy <content>...</content> zamiast <parameter name="content">
    if name.lower() in ("write", "edit") and "content" not in params:
        raw_content = re.search(r'<\s*content\b[^>]*>([\s\S]*?)(?:</\s*content\s*>|$)', body, re.IGNORECASE)
        if raw_content:
            params["content"] = raw_content.group(1)

    open_tags = list(_PARAM_OPEN_RE.finditer(body))

    last_param_name = None
    if name.lower() in ("write", "edit"):
        last_param_name = "content"
    elif name.lower() == "searchreplace":
        last_param_name = "new_str"

    is_complete = _params_complete(name, params)
    has_unmatched_opens = len(open_tags) > len(matches)
    all_params_closed = (len(open_tags) == 0) or (len(matches) == len(open_tags))

    # Jeśli param_pat dopasował wszystkie otwarte tagi i wymagane parametry są kompletne:
    if is_complete and not has_unmatched_opens and params:
        # Sprawdzenie czy ostatni parametr (np. content w Write) nie został obcięty
        # przez zagnieżdżony znacznik (BUG-034):
        if last_param_name and last_param_name in params and matches:
            last_match = matches[-1]
            rem = body[last_match.end():]
            rem_stripped = _strip_close_tail(rem).strip()
            if rem_stripped:
                for pm in open_tags:
                    if pm.group(2).strip().lower() == last_param_name.lower():
                        full_val = _strip_close_tail(body[pm.end():])
                        params[last_param_name] = _parse_param_value(full_val)
                        break
        return params, all_params_closed

    # Krok 2: Odzysk parametrów po kolejnych tagach otwarcia
    # Gdy regex nie dopasował wszystkich parametrów (np. nagi </||DSML||>, brak domknięcia,
    # ucięcie strumienia, lub zagnieżdżone tagi).
    found = []
    seen_params = set()
    for pm in open_tags:
        pname = pm.group(2).strip()
        plower = pname.lower()
        if valid_param_set and plower not in valid_param_set:
            continue
        if plower in seen_params:
            # Pierwsze wystąpienie parametru wygrywa (kolejne to zagnieżdżony markup lub pętla tokenów)
            continue
        seen_params.add(plower)
        found.append((pname, pm.start(), pm.end()))

    if not found:
        return params, all_params_closed

    found.sort(key=lambda x: x[1])
    for idx, (pname, ostart, oend) in enumerate(found):
        if idx + 1 < len(found):
            vend = found[idx + 1][1]
            raw_val = _strip_close_tail(body[oend:vend])
        else:
            raw_val = _strip_close_tail(body[oend:])

        parsed_val = _parse_param_value(raw_val)
        if pname not in params or not params[pname] or (parsed_val and len(str(parsed_val)) > len(str(params.get(pname, "")))):
            params[pname] = parsed_val

    return params, all_params_closed


def _parse_invoke_body(name: str, body: str) -> dict:
    """Kompatybilny wrapper zwracający słownik parametrów."""
    params, _ = _parse_invoke_body_with_meta(name, body)
    return params


def _parse_tool_calls(text: str, known_tools: set | list | None = None, allow_unclosed: bool = False) -> list[tuple[int, int, str, str]]:
    """Parse all tool call formats. Returns [(start, end, name, args_json), ...]"""
    results = []
    if known_tools is None:
        known_tools = {"Read", "Write", "Edit", "SearchReplace", "Grep", "Glob", "LS", "RunCommand", "Task", "CheckCommandStatus", "DeleteFile", "TodoWrite", "Skill", "AskUserQuestion", "NotifyUser", "WebSearch", "WebFetch", "GetDiagnostics", "OpenPreview", "run_mcp"}
    else:
        known_tools = set(known_tools)

    # 1. Depth-tracked invoke calls (odporne na zagnieżdżone markapy wewnątrz Write/SearchReplace)
    tags = []
    for m in _INVOKE_OPEN_RE.finditer(text):
        tags.append((m.start(), m.end(), 'open', m.group(2)))
    for m in _INVOKE_CLOSE_RE.finditer(text):
        tags.append((m.start(), m.end(), 'close', None))

    tags.sort(key=lambda x: x[0])

    depth = 0
    top_invokes = []
    cur_start = None
    cur_body_start = None
    cur_name = None
    all_invoke_spans = []

    for pos_start, pos_end, ttype, iname in tags:
        if ttype == 'open':
            if depth == 0:
                cur_start = pos_start
                cur_body_start = pos_end
                cur_name = iname
            depth += 1
        elif ttype == 'close':
            if depth > 0:
                depth -= 1
                if depth == 0:
                    top_invokes.append((cur_start, pos_end, cur_name, text[cur_body_start:pos_start], True))
                    all_invoke_spans.append((cur_start, pos_end))

    # Odzysk uciętego/niedomkniętego wywołania na końcu bufora (np. urwany strumień SSE)
    # Dopuszczalny WYŁĄCZNIE gdy allow_unclosed=True (koniec strumienia).
    # all_invoke_spans rejestrujemy ZAWSZE, aby bloki 1b/1c nie traktowały parametrów otwartego invoke jako osieroconych!
    if depth > 0 and cur_start is not None:
        all_invoke_spans.append((cur_start, len(text)))
        if allow_unclosed:
            top_invokes.append((cur_start, len(text), cur_name, text[cur_body_start:], False))

    for s, e, tname, body, is_closed in top_invokes:
        params, all_params_closed = _parse_invoke_body_with_meta(tname, body)
        params = _sanitize_tool_params(tname, params)
        tname, params = _repair_tool_call(tname, params)
        if is_closed:
            # Zamknięty invoke przez model — akceptujemy
            results.append((s, e, tname, json.dumps(params) if params else "{}"))
        elif allow_unclosed:
            # Niedomknięty invoke (brak </invoke>) — akceptujemy TYLKO jeśli:
            # 1. allow_unclosed=True (koniec strumienia)
            # 2. Wszystkie parametry w treści były jawnie domknięte (nie ucięte w połowie tokenu)
            # 3. Wszystkie wymagane pola narzędzia są obecne i niepuste
            if all_params_closed and _params_complete(tname, params):
                results.append((s, e, tname, json.dumps(params)))

    # 1b. Orphaned / unwrapped parameter blocks: <parameter name="...">... or <参数 name="...">...
    param_block_pat = re.compile(
        r'''(?:<\s*(?:parameter|参数|參數)\s*name=(["'])([^"']+?)\1[^>]*>([\s\S]*?)</\s*(?:parameter|参数|參數)>\s*)+''',
        re.IGNORECASE
    )
    for m in param_block_pat.finditer(text):
        span_start, span_end = m.start(), m.end()
        # Jeśli blok parametrów znajduje się wewnątrz tagu <invoke>, nie traktuj go jako osieroconego!
        if any(inv_s <= span_start and inv_e >= span_end for inv_s, inv_e in all_invoke_spans):
            continue
        block = m.group(0)
        params = {}
        for pm in re.finditer(r'''<\s*(?:parameter|参数|參數)\s*name=(["'])([^"']+?)\1[^>]*>([\s\S]*?)</\s*(?:parameter|参数|參數)>''', block, re.IGNORECASE):
            params[pm.group(2)] = _parse_param_value(pm.group(3))
        if params:
            inferred_tool = "Task" if ("query" in params or "subagent_type" in params or "description" in params) else None
            if not inferred_tool and "file_path" in params:
                inferred_tool = "Write" if "content" in params else "Read"
            if not inferred_tool and "command" in params:
                inferred_tool = "RunCommand"
            if inferred_tool:
                if not any(r[0] <= span_start and r[1] >= span_end for r in results):
                    results.append((span_start, span_end, inferred_tool, json.dumps(params)))

    # 1c. Orphaned direct parameter tags: e.g. <pattern>...</pattern><path>...</path>
    known_param_names = {'pattern', 'path', 'file_path', 'content', 'command', 'query', 'description', 'subagent_type', 'offset', 'limit', 'output_mode', 'glob'}
    param_pat_str = '|'.join(known_param_names)
    matches_1c = list(re.finditer(rf'<\s*({param_pat_str})\b[^>]*>([\s\S]*?)</\s*\1>', text, re.IGNORECASE))
    if matches_1c:
        def _infer_orphaned_tool(pdict):
            if 'pattern' in pdict:
                return 'Grep'
            elif 'file_path' in pdict:
                return 'Write' if 'content' in pdict else 'Read'
            elif 'command' in pdict:
                return 'RunCommand'
            elif 'query' in pdict or 'description' in pdict:
                return 'Task'
            elif 'path' in pdict and 'glob' in pdict:
                return 'Glob'
            return None

        cur_params = {}
        cur_start = None
        cur_end = None
        for m_1c in matches_1c:
            if any(inv_s <= m_1c.start() and inv_e >= m_1c.end() for inv_s, inv_e in all_invoke_spans):
                continue
            k = m_1c.group(1).lower()
            v = _parse_param_value(m_1c.group(2).strip())
            if k in cur_params:
                tname = _infer_orphaned_tool(cur_params)
                if tname and not any(r[0] <= cur_start and r[1] >= cur_end for r in results):
                    results.append((cur_start, cur_end, tname, json.dumps(cur_params)))
                cur_params = {}
                cur_start = None
            if cur_start is None:
                cur_start = m_1c.start()
            cur_end = m_1c.end()
            cur_params[k] = v
        if cur_params:
            tname = _infer_orphaned_tool(cur_params)
            if tname and not any(r[0] <= cur_start and r[1] >= cur_end for r in results):
                results.append((cur_start, cur_end, tname, json.dumps(cur_params)))


    # 1d. Corrupted tag DSML parameters: <user_input>val</ | | DSML | | parameter> ... </ | | DSML | | invoke>
    invoke_block_pat = re.compile(
        r'''((?:<\s*user_input\s*>\s*)+[\s\S]*?</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?invoke\s*>?)''',
        re.IGNORECASE
    )
    dsml_param_pat = re.compile(
        r'(?:<\s*(?:\w+)?\s*>)*\s*([\s\S]*?)</\s*(?:[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*)?(?:parameter|参数|參數)>',
        re.IGNORECASE
    )
    for bm in invoke_block_pat.finditer(text):
        block = bm.group(1)
        matches = list(dsml_param_pat.finditer(block))
        vals = []
        for m in matches:
            v = m.group(1).strip()
            v = re.sub(r'<\s*user_input\s*>', '', v, flags=re.IGNORECASE).strip()
            v = re.sub(r'<\s*\w+\s*>', '', v).strip()
            vals.append(v)
            
        inferred = None
        args = {}
        if len(vals) == 1:
            if vals[0].startswith('python ') or vals[0].startswith('npm ') or vals[0].startswith('pytest ') or vals[0].startswith('git ') or vals[0].startswith('pip '):
                inferred = "RunCommand"
                args = {"command": vals[0]}
            elif re.search(r'\.[a-zA-Z0-9_-]+$', vals[0]) or ':/' in vals[0] or ':\\' in vals[0]:
                inferred = "Read"
                args = {"file_path": vals[0]}
        elif len(vals) >= 2:
            first, second = vals[0], vals[1]
            if first.startswith('python ') or first.startswith('npm ') or first.startswith('pytest ') or first.startswith('git ') or first.startswith('pip ') or (' ' in first and not first.startswith('#') and not re.search(r'^[a-zA-Z]:[\\/]', first)):
                inferred = "RunCommand"
                args = {"command": first, "cwd": second}
            elif (re.search(r'\.[a-zA-Z0-9_-]+$', first) or ':/' in first or ':\\' in first) and ('\n' in second or '# coding' in second or 'import ' in second or len(second) > 50):
                inferred = "Write"
                args = {"file_path": first, "content": second}
            elif '**' in first or '*' in first or (not ('/' in first or '\\' in first) and ('/' in second or '\\' in second)):
                inferred = "Glob"
                args = {"pattern": first, "path": second}
            elif ':/' in second or ':\\' in second:
                inferred = "Grep" if len(first) > 0 else "Glob"
                args = {"pattern": first, "path": second}
                
        if inferred:
            span_start, span_end = bm.start(), bm.end()
            if not any(r[0] <= span_start and r[1] >= span_end for r in results):
                results.append((span_start, span_end, inferred, json.dumps(args)))

    # 2. DSML variant: < | | DSML | | name="ToolName"> ... </ | | DSML | | > or <DSML name="...">
    for m in re.finditer(r'''<(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?DSML(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?\s*name=(["'])([^"']*?)\1>(.*?)</(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?DSML(?:\s*[|\uff5c\u2502]\s*[|\uff5c\u2502]\s*)?>''', text, re.DOTALL | re.IGNORECASE):
        name = m.group(2)
        body = m.group(3).strip()
        params = {}
        for pm in re.finditer(r'''<(?:parameter|参数|參數)\s*name=(["'])([^"']+?)\1[^>]*>(.*?)</(?:parameter|参数|參數)>''', body, re.DOTALL | re.IGNORECASE):
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
        for pm in re.finditer(r'''<(?:parameter|参数|參數)\s*name=(["'])([^"']+?)\1[^>]*>(.*?)</(?:parameter|参数|參數)>''', body, re.DOTALL | re.IGNORECASE):
            params[pm.group(2)] = _parse_param_value(pm.group(3))
        if not params:
            pm2 = re.search(r'''name=(["'])([^"']+?)\1\s*>\s*(.*?)(?:</(?:parameter|参数|參數)>|/(?:parameter|参数|參數)>|$)''', body, re.DOTALL | re.IGNORECASE)
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
    #     Akceptuje małe/wielkie litery i pozycyjny content bez zagnieżdżonych tagów innych narzędzi.
    tool_names_pattern = "|".join(re.escape(kt) for kt in known_tools) if known_tools else ""
    for m in re.finditer(r"<([A-Za-z][a-zA-Z0-9_]+)>(.*?)</\1>", text, re.DOTALL):
        raw_name = m.group(1)
        canon = next((kt for kt in known_tools if kt.lower() == raw_name.lower()), None)
        if not canon:
            continue
        inner = m.group(2)
        if tool_names_pattern and re.search(rf"<(?:\/?(?:{tool_names_pattern}))\b", inner, re.IGNORECASE):
            continue
        params = {}
        for pm in re.finditer(r"<([a-zA-Z_]\w*)>(.*?)</\1>", inner, re.DOTALL):
            params[pm.group(1)] = _parse_param_value(pm.group(2))
        if not params:
            params = _map_positional(canon, inner)
        if params:
            results.append((m.start(), m.end(), canon, json.dumps(params)))

    # 6b. Shorthand consecutive tool tags (unclosed or stacked): <tool> body <next_tool>
    #     e.g. <glob> * c:/path <glob> **/*.md c:/path <grep> query c:/path <read> c:/path/f.py
    if known_tools:
        tool_names_pattern = "|".join(re.escape(kt) for kt in known_tools)
        for m in re.finditer(rf"<({tool_names_pattern})>([\s\S]*?)(?=<(?:\/?(?:{tool_names_pattern}))[^>]*>|\Z)", text, re.IGNORECASE):
            tname = m.group(1)
            raw_body = m.group(2).strip()
            clean_body = re.sub(rf"</?(?:{tool_names_pattern})[^>]*>", "", raw_body, flags=re.IGNORECASE).strip()
            if not clean_body:
                continue
            canon = next((kt for kt in known_tools if kt.lower() == tname.lower()), None)
            if not canon:
                continue
            params = {}
            for pm in re.finditer(r"<([a-zA-Z_]\w*)>(.*?)</\1>", clean_body, re.DOTALL):
                params[pm.group(1)] = _parse_param_value(pm.group(2))
            if not params:
                params = _map_positional(canon, clean_body)
            if params:
                span_start, span_end = m.start(), m.end()
                if not any(r[0] <= span_start and r[1] >= span_end for r in results):
                    results.append((span_start, span_end, canon, json.dumps(params)))

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
            fixed_params = _sanitize_tool_params(fixed_name, fixed_params)
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

def _clean_dsml_wait(text: str) -> str:
    """BUG-033: Usuwa wewnętrzne znaczniki bezczynności DeepSeek:
    <｜｜DSML｜｜_wait>—brak</｜｜DSML｜｜_wait>
    oraz wszelkie ich warianty (np. <|DSML|_wait>...</|DSML|_wait>, <DSML_wait/> itp.).
    Zapobiega paraliżowi bufora streamingowego i nie dopuszcza do fałszywych alarmów pętli.
    """
    if not text or "wait" not in text.lower():
        return text
    # 1. Pełny blok wraz z zawartością (np. —brak, —无, puste linie):
    pat_block = re.compile(
        r'<\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\b[^>]*>[\s\S]*?</\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\s*>',
        re.IGNORECASE
    )
    text = pat_block.sub("", text)
    # 2. Samodzielny, samozamykający lub urwany tag _wait:
    pat_single = re.compile(
        r'</?\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\b[^>]*>',
        re.IGNORECASE
    )
    text = pat_single.sub("", text)
    # 3. Format nawiasów kwadratowych: [/｜｜DSML｜｜_wait] itp.
    pat_sq = re.compile(
        r'\[/?\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\b[^\]]*\]',
        re.IGNORECASE
    )
    return pat_sq.sub("", text)

_STRIP_TAGS = re.compile(
    r"<\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\b[^>]*>[\s\S]*?</\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\s*>|"  # BUG-033: bloki _wait z zawartością (np. —brak)
    r"</?\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\b[^>]*>|"                                                            # BUG-033: pojedyncze tagi _wait
    r"\[/?\s*[|｜\uff5c\u2502\s]*DSML[|｜\uff5c\u2502\s]*_wait\b[^\]]*\]|"                                                          # BUG-033: kwadratowe tagi _wait
    r"</?system-reminder[^>]*>|</?-reminder[^>]*>|"
    r"-reminder>[^\n]*|"
    r"<critical_directive>[\s\S]*?</critical_directive>|"
    r"</?previous_(?:tool_)?calls?[^>]*>|"
    r"</?user_input[^>]*>|"
    r"</?(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*|tool_calls?|tool_capability|invoke|_calls?|[|\uff5c\u2502\s]*cl_calls?|call|tools?|center|调用|調用|工具|函数|结果|思考|glob|grep|read|ls|write|deletefile|searchreplace|task|skill|runcommand|checkcommandstatus|stopcommand|askuserquestion|notifyuser|websearch|webfetch|getdiagnostics|todowrite|openpreview|run_mcp)[^>]*>|"
    r"</?\s*(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*)(?:invoke|parameter|call|tool)?(?:\s*>|\b|\Z)|"
    r"<tool_result[^>]*>.*?</tool_result>|</?tool_result[^>]*>|"
    r"<result[^>]*>|</result>|<status[^>]*>.*?</status>|"
    r"</?thinking[^>]*>|<tool_use_json[^>]*>.*?</tool_use_json>|"
    r"</?(?:parameter|参数|參數|pattern|path|file_path|content|command|query|description|subagent_type|output_mode)[^>]*>|"
    r"<[|\uff5c\u2502\s]*tool\s*call\s*begin[|\uff5c\u2502\s]*>.*?<[|\uff5c\u2502\s]*tool\s*call\s*end[|\uff5c\u2502\s]*>|"
    r"</?[|\uff5c\u2502\s]*tool[_\s]*calls?\s*(?:begin|end)?[|\uff5c\u2502\s]*>|"
    r"<tool_call[^>]*>.*?</tool_calls?>|"
    rf"\[{_CALL_MARKER}\s*\w+\]|"
    r"\[/?[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*[a-z0-9_]*\]|"   # [｜｜DSML｜｜], [｜｜DSMLparam], [/｜｜DSMLparam] - kwadratowe znaczniki DSML
    r"\[/[|\uff5c\u2502\s]*[a-z_][a-z0-9_]*\]|"                     # [/parameter], [/｜｜parameter] - zamykajacy tag kontrolny w [ ]
    r"(?:</[a-zA-Z0-9_-]+>\s*){2,}",                                # kaskadowe zamykające tagi </glob></glob></grep> itp.
    re.DOTALL | re.IGNORECASE
)


_LEAK_DETECTOR = re.compile(
    r"</?(?:[|\uff5c\u2502\s]*DSML[|\uff5c\u2502\s]*|tool_call|invoke|_call|user_input|parameter|参数|參數|pattern|path|file_path|tool_capability|previous_(?:tool_)?calls?)[^>]*>|"
    r"\[(?:call:|Task:|Read:|Write:|Grep:|Glob:|RunCommand:)|"
    r"<[|\uff5c\u2502\s]*tool\s*call|"
    r"\{\s*\"(?:file_path|command|pattern|subagent_type)\"\s*:",
    re.IGNORECASE
)


def _log_leak_if_any(content: str, full_buffer: str = "", conv_key: str = ""):
    if not content:
        return
    matches = _LEAK_DETECTOR.findall(content)
    if matches:
        timestamp = datetime.now().isoformat()
        sig_list = list(set(matches))
        entry_text = f"[{timestamp}] [LEAK DETECTED] signatures={sig_list} | conv={conv_key[:24]} | content={repr(content[:300])}\n"
        try:
            LEAKS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LEAKS_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry_text)
            with open(WORKSPACE_LEAKS_LOG, "a", encoding="utf-8") as f:
                f.write(entry_text)
        except Exception as e:
            print(f"[LEAK WATCHDOG] Failed to write leak log: {e}", flush=True)
        print(f"[LEAK WATCHDOG] 🚨 RECORDED LEAK TO leaks.log: {sig_list} in {repr(content[:60])}", flush=True)


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


_image_upload_cache: dict[tuple[int, str], str] = {}
_image_cache_lock = threading.Lock()


def _upload_images_to_deepseek(ds, account_idx: int, images: list[dict]) -> list[str]:
    """Upload images to DeepSeek for account_idx and return list of file_ids.
    Features:
    - Base64 and URL support
    - SSRF protection for URLs
    - Safe compression/downscaling if image exceeds DeepSeek upload limit (10MB)
    - Thread-safe deduplication cache by (account_idx, sha256)
    """
    if not images:
        return []

    ref_file_ids: list[str] = []
    print(f"[VISION] Uploading {len(images)} image(s) for account {account_idx}...", flush=True)

    for idx, img in enumerate(images):
        try:
            file_data: bytes | None = None
            mime: str = "image/png"

            if img.get("base64"):
                b64_raw = img["base64"]
                file_data = base64.b64decode(b64_raw)
                mime = img.get("mime_type") or "image/png"
            elif img.get("url"):
                import urllib.parse
                import ipaddress
                import requests as req_lib
                _u = urllib.parse.urlparse(img["url"])
                _host = _u.hostname or ""
                if _u.scheme not in ("http", "https"):
                    raise ValueError(f"Nieobsługiwany protokół obrazu: {_u.scheme}")
                try:
                    _ip = ipaddress.ip_address(_host)
                    is_ip = True
                except ValueError:
                    is_ip = False

                if is_ip:
                    if _ip.is_private or _ip.is_loopback or _ip.is_link_local or _ip.is_reserved or _ip.is_multicast:
                        raise ValueError("Niedozwolony adres obrazu (sieć prywatna)")
                else:
                    if _host.lower() in ("localhost",) or _host.endswith(".local") or _host.endswith(".internal"):
                        raise ValueError("Niedozwolony adres obrazu (host lokalny)")
                resp = req_lib.get(img["url"], timeout=30)
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code} during image fetch from URL")
                file_data = resp.content
                mime = resp.headers.get("content-type") or "image/png"

            if not file_data:
                continue

            # Jeśli obraz jest bardzo duży (> 7MB), kompresujemy go bezpiecznie za pomocą PIL
            if len(file_data) > 7 * 1024 * 1024:
                try:
                    from PIL import Image
                    from io import BytesIO
                    buf = BytesIO(file_data)
                    pil_img = Image.open(buf)
                    if pil_img.mode in ("RGBA", "P"):
                        pil_img = pil_img.convert("RGBA")
                        bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                        bg.paste(pil_img, mask=pil_img.split()[3] if pil_img.mode == "RGBA" else None)
                        pil_img = bg
                    elif pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    w, h = pil_img.size
                    max_dim = 2048
                    if max(w, h) > max_dim:
                        ratio = max_dim / max(w, h)
                        pil_img = pil_img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                    out = BytesIO()
                    pil_img.save(out, format="JPEG", quality=85)
                    file_data = out.getvalue()
                    mime = "image/jpeg"
                    print(f"[VISION] Compressed oversized image {idx+1} down to {len(file_data)} bytes", flush=True)
                except Exception as comp_err:
                    print(f"[VISION] Warning: compression fallback failed: {comp_err}", flush=True)

            # Deduplikacja / cache po sha256
            h = hashlib.sha256(file_data).hexdigest()
            cache_key = (account_idx, h)
            with _image_cache_lock:
                cached_id = _image_upload_cache.get(cache_key)
            if cached_id:
                ref_file_ids.append(cached_id)
                print(f"[VISION] Image {idx+1} hit upload cache: {cached_id} (sha256={h[:8]})", flush=True)
                continue

            ext = mime.split("/")[-1] if "/" in mime else "png"
            if ext in ("jpeg", "jpg"):
                ext = "jpg"
            elif ext not in ("png", "webp", "gif"):
                ext = "png"

            file_id = ds.upload_file(account_idx, file_data, f"image_{idx+1}_{h[:6]}.{ext}", mime)
            if file_id:
                ref_file_ids.append(file_id)
                with _image_cache_lock:
                    if len(_image_upload_cache) > 300:
                        _image_upload_cache.clear()
                    _image_upload_cache[cache_key] = file_id
                print(f"[VISION] Uploaded image {idx+1} ({len(file_data)} bytes): {file_id}", flush=True)
        except Exception as e:
            print(f"[VISION] Failed to upload image {idx+1}: {e}", flush=True)

    return ref_file_ids


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



# ── Bramka limitu równoległości (#2): ile żądań może jednocześnie przechodzić
# przez fazę budowy promptu + wywołania DeepSeek (blokujący requests.post + preambuła).
# Streaming po przejściu bramki działa równolegle — bramka ogranicza burst upstream.
_MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_STREAMS", "8"))
_parallel_gate = threading.BoundedSemaphore(_MAX_PARALLEL)


def _ensure_slot(slot: int, clean: bool = False):
    global _slot_in_progress
    print(f"[DEBUG] _ensure_slot(slot={slot}) called, current in_progress={_slot_in_progress[slot]}", flush=True)
    with _slot_locks[slot]:
        valid = ap.is_valid(slot)
        print(f"[DEBUG] ap.is_valid({slot}) = {valid}", flush=True)
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


@app.get("/models")
@app.get("/v1/models")
def list_models():
    now_ts = int(time.time())
    model_ids = [
        # Standardowe modele DeepSeek / OpenAI (nowy standard zunifikowanego silnika)
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-coder",
        "deepseek-v3",
        "deepseek-r1",
        "deepseek-vision",
        # Warianty funkcyjne
        "deepseek-chat-search",
        "deepseek-chat-nothink",
        # Aliasty kompatybilności wstecznej (dla istniejących konfiguracji Trae / Cortex / Cursor)
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-v4-flash-search",
        "deepseek-v4-flash-nothink",
        "deepseek-fast",
        "deepseek-fast-search",
        "deepseek-fast-nothink",
        "deepseek-expert",
    ]
    return {
        "object": "list",
        "data": [{
            "id": mid,
            "object": "model",
            "created": now_ts,
            "owned_by": "deepseek",
        } for mid in model_ids]
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
        # OPTIMIZATION: Do not persist full tool schemas and truncate huge user prompts in disk state
        clean_state = {}
        for k, v in _conv_state.items():
            if isinstance(v, dict):
                item = dict(v)
                item.pop("tools", None)
                if "first_user_prompt" in item and isinstance(item["first_user_prompt"], str):
                    if len(item["first_user_prompt"]) > 256:
                        item["first_user_prompt"] = item["first_user_prompt"][:256]
                clean_state[k] = item
            else:
                clean_state[k] = v

        tmp = CONV_STATE_FILE.with_suffix(".tmp")
        # Explicit UTF-8 open to avoid Windows cp1250 encoding bug with -> (U+2192)
        with open(str(tmp), "w", encoding="utf-8") as f:
            json.dump(clean_state, f, indent=2, ensure_ascii=False)
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

_tools_cache_mem: dict | None = None
_tools_cache_lock = threading.Lock()

def _load_tools(sys_hash: str) -> list[dict] | None:
    global _tools_cache_mem
    with _tools_cache_lock:
        if _tools_cache_mem is None:
            _tools_cache_mem = {}
            try:
                if os.path.exists(_TOOLS_CACHE):
                    with open(_TOOLS_CACHE, "r", encoding="utf-8") as f:
                        _tools_cache_mem = json.load(f)
            except Exception as e:
                print(f"[TOOLS CACHE READ ERROR] {e}", flush=True)
        return _tools_cache_mem.get(sys_hash)

def _save_tools(sys_hash: str, tools: list[dict]):
    global _tools_cache_mem
    with _tools_cache_lock:
        if _tools_cache_mem is None:
            _tools_cache_mem = {}
            try:
                if os.path.exists(_TOOLS_CACHE):
                    with open(_TOOLS_CACHE, "r", encoding="utf-8") as f:
                        _tools_cache_mem = json.load(f)
            except Exception:
                pass
        if _tools_cache_mem.get(sys_hash) == tools:
            return
        _tools_cache_mem[sys_hash] = tools
        try:
            with open(_TOOLS_CACHE, "w", encoding="utf-8") as f:
                json.dump(_tools_cache_mem, f, ensure_ascii=False)
        except Exception as e:
            print(f"[TOOLS CACHE WRITE ERROR] {e}", flush=True)

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
    """True gdy request pochodzi od oddelegowanego subagenta (nie głównego czatu Trae)."""
    if not messages:
        return False
    sys_content = messages[0].get("content", "") if messages else ""
    if isinstance(sys_content, list):
        sys_content = " ".join(p.get("text", "") for p in sys_content if isinstance(p, dict) and p.get("type") == "text")
    # Główny agent Trae zawiera specyficzne znaczniki w system prompt:
    if "You are an interactive agent in TraeCode" in sys_content or "# Doing tasks" in sys_content or "TraeCode" in sys_content:
        return False
    # Subagenty jednokrokowe mają 2 wiadomości:
    if len(messages) == 2:
        return True
    # Subagenty wielokrokowe również nie mają głównego system promptu TraeCode:
    if sys_content and not any(k in sys_content for k in ("TraeCode", "# Doing tasks", "interactive agent")):
        return True
    return False


# â”€â”€â”€ Sonda diagnostyczna (zbiera WSZYSTKIE headery + ACL) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _dump_request_diagnostics(raw_request: Request, acl_payload: dict | None, body_str: str):
    """Log all headers, ACL fields, and body fields for correlation analysis."""
    if not DEBUG_DIAGNOSTICS:
        return
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
    """Find the FIRST user message with actual user content in the history and return its plain text content."""
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
                    text = m_tag.group(1).strip()
                cleaned = _clean_system_reminders(text)
                if cleaned:
                    return cleaned
    return ""


def _get_user_fp(messages: list[dict]) -> str:
    """Odcisk KONKRETNEGO czatu — liczony z pierwszej faktycznej wiadomości użytkownika.

    KRYTYCZNE dla ROZDZIELENIA CZATÓW. Bez tego wszystkie okna Trae dzieliły jeden wpis
    stanu (`jwt_leg_<user>`), więc dwa czaty/subagenty nadpisywały sobie nawzajem sesję
    DeepSeek. Skutki były dokładnie tym, co widział użytkownik: "zatrute stany",
    ponowne wysyłanie ~150 000 znaków historii i pętle LOOP GUARD.

    Hash liczymy z tekstu OCZYSZCZONEGO z dynamicznego szumu: bloki <system-reminder>,
    dowolne znaczniki XML oraz powtórzone białe znaki. Dzięki temu Trae może doklejać
    kolejne przypomnienia w trakcie rozmowy, a odcisk pozostaje ten sam — czyli klucz jest
    stabilny w obrębie czatu, ale RÓŻNY dla dwóch różnych czatów."""
    first_text = _get_first_user_prompt_text(messages)
    if not first_text:
        return ""
    t = re.sub(r"<system-reminder>.*?</system-reminder>", " ", first_text, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<[^>]{1,120}>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 12:
        return ""
    return hashlib.md5(t[:4000].encode("utf-8")).hexdigest()[:8]

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
        new_session_id, account_idx = ds_client.create_session_with_fallback(account_idx)
        print(f"[ROTATION] New DS session: {new_session_id} (account={account_idx})", flush=True)
        state["ds_session"] = new_session_id
        state["account"] = account_idx
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
    Unikalny klucz KONKRETNEGO czatu.

    Priorytet:
      1. Watermark w odpowiedzi asystenta (najodporniejszy na trimowanie historii)
      2. chat_id od Trae (gdyby kiedyś zaczęli wysyłać)
      3. JWT identity + ODCISK CZATU (z oczyszczonego pierwszego promptu)

    KRYTYCZNE: klucz MUSI być różny dla różnych czatów. Wcześniej główny agent dostawał
    goły `jwt_leg_<user>`, czyli WSZYSTKIE okna Trae, taski i czaty dzieliły jeden wpis
    stanu i nadpisywały sobie sesję DeepSeek. To była przyczyna "zatrutych stanów",
    ponownego wysyłania ~150 000 znaków historii i pętli LOOP GUARD.

    Odcisk liczymy z pierwszej wiadomości użytkownika OCZYSZCZONEJ z dynamicznego szumu
    (<system-reminder>, znaczniki XML, białe znaki) — patrz `_get_user_fp`. Dzięki temu
    doklejanie przypomnień przez Trae nie zmienia klucza w trakcie rozmowy, ale dwa różne
    czaty mają różne klucze.
    """
    # ── PRIORYTET 1: Watermark (najstabilniejszy) ──
    wm_id = _extract_watermark(messages)
    if wm_id:
        print(f"[CONV_KEY] watermark found: {wm_id[:12]}...", flush=True)
        return f"wm_{wm_id}"

    # ── PRIORYTET 2: chat_id z Trae ──
    if chat_id:
        return f"trae_{chat_id}"

    # Odcisk czatu liczymy ZAWSZE — to on rozdziela czaty.
    user_fp = _get_user_fp(messages)

    # ── PRIORYTET 3: JWT + (opcjonalnie) fingerprint ──
    if acl_payload:
        # Sprawdź legid jako potencjalny klucz zakładki
        legid = acl_payload.get("legid")
        if isinstance(legid, dict):
            stable_id = legid.get("user") or legid.get("sub") or ""
        elif legid:
            stable_id = str(legid)
        else:
            stable_id = ""
        if stable_id:
            if user_fp:
                return f"jwt_leg_{stable_id}_{user_fp}"
            return f"jwt_leg_{stable_id}"
        jwt_id = acl_payload.get("sub") or acl_payload.get("session") or ""
        if jwt_id:
            jwt_hash = hashlib.md5(jwt_id.encode()).hexdigest()[:8]
            if user_fp:
                return f"jwt_{jwt_hash}_{user_fp}"
            return f"jwt_{jwt_hash}"

    # ── PRIORYTET 4: Sys hash + odcisk czatu ──
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
    tool_call_map = {}
    for m in req.messages:
        if m.get("role") == "assistant":
            for call in (m.get("tool_calls") or []):
                if isinstance(call, dict):
                    cid = call.get("id")
                    if cid:
                        fn = call.get("function") or {}
                        raw_args = fn.get("arguments", "{}")
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                        except Exception:
                            args = {}
                        tool_call_map[cid] = (fn.get("name", ""), args if isinstance(args, dict) else {})

    api_messages = []
    for m in req.messages:
        role = m.get("role")
        content = m.get("content", "")
        
        if role == "tool":
            tid = m.get("tool_call_id", "")
            tname, targs = tool_call_map.get(tid, ("", {}))
            if tname in ("Read", "read", "read_file"):
                fp = targs.get("file_path") or targs.get("path") or targs.get("filePath")
                if fp and isinstance(content, str):
                    content = _annotate_read_tool_result(content, str(fp), offset=targs.get("offset"), limit=targs.get("limit"))
            # Compress large tool results
            if isinstance(content, str) and len(content) > 500000:
                content = f"[Tool result: {len(content)} chars — compressed for context limits]"
            api_messages.append({"role": "tool", "content": content,
                                "tool_call_id": tid})
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
                    "Be thorough. Synthesize findings into concise facts. Quote at most 2-3 key "
                    "code lines. NEVER copy raw tool dumps with line-number prefixes like '120→'. "
                    "Invoke tools individually with proper XML tags. NEVER concatenate unclosed tags like <glob>...<grep>. "
                    "Do not chat — just do the task."
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


@app.post("/chat/completions")
@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest, raw_request: Request):
    """Bramka limitu równoległości (#2): max _MAX_PARALLEL żądań w fazie
    budowy promptu + blokującego wywołania DeepSeek naraz."""
    _parallel_gate.acquire()
    try:
        return _chat_completions_impl(req, raw_request)
    finally:
        _parallel_gate.release()


def _chat_completions_impl(req: ChatRequest, raw_request: Request):
    t0 = time.time()
    try:
        req_port = raw_request.url.port or raw_request.scope.get("server", [None, 4570])[1]
    except Exception:
        req_port = raw_request.scope.get("server", [None, 4570])[1] if hasattr(raw_request, "scope") and isinstance(raw_request.scope, dict) else 4570
    is_clean_port = (req_port == 4571) or (raw_request.headers.get("x-proxy-clean") == "true")
    # Log raw request body to see EVERYTHING Trae sends
    body_bytes = raw_request._body or b""
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
                    if DEBUG_DIAGNOSTICS:
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
    _extract_environment_info(req.messages)
    print(f"[REQUEST] roles={roles} tools={tcs} msgs={len(req.messages)}", flush=True)
    # Log all messages structure for debugging (only if DEEPSEEK_DIAGNOSTICS=1)
    if DEBUG_DIAGNOSTICS:
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
        if DEBUG_DIAGNOSTICS:
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
    image_files = _extract_images(req.messages)
    is_vision = bool(image_files) or ("vision" in req_model_lower)
    if image_files:
        print(f"[VISION] Found {len(image_files)} image(s) in request", flush=True)

    # Rozpoznanie profilu zunifikowanego modelu DeepSeek:
    # 1. Flaga thinking (Głębokie myślenie / R1 / CoT):
    if any(k in req_model_lower for k in ("nothink", "no_think", "no-think", "fast-nothink", "flash-nothink")):
        thinking_enabled = False
    elif any(k in req_model_lower for k in ("reasoner", "r1", "think", "expert", "pro")):
        thinking_enabled = True
    elif is_vision:
        thinking_enabled = VISION_THINKING or ("think" in req_model_lower)
    else:
        thinking_enabled = DEFAULT_THINKING

    # 2. Flaga search (Przeszukiwanie internetu):
    if any(k in req_model_lower for k in ("no-search", "nosearch", "no_search")):
        search_enabled = False
    elif "search" in req_model_lower:
        search_enabled = True
    else:
        search_enabled = DEFAULT_SEARCH

    # DeepSeek Web wspiera równoczesne działanie głębokiego myślenia (R1) i wyszukiwania sieciowego (Search).
    model_type = "default"

    print(f"[ROUTER] Model '{req.model}' -> model_type='{model_type}', thinking={thinking_enabled}, search={search_enabled}, vision={is_vision}", flush=True)

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

        # Invariant 1: Jeśli w requeście NIE MA żadnej wiadomości asystenta,
        # to bez względu na stan jest to NOWY CZAT.
        if not has_assistant_messages:
            print(f"[NEW CHAT] No assistant messages in request -> Forcing fresh DeepSeek session", flush=True)
            is_new_conversation = True

        # Invariant 2 (WYŁĄCZONY): drobne zmiany / prefixy w pierwszej wiadomości użytkownika
        # (dodawane dynamicznie przez IDE typu Trae/Cursor) NIE oznaczają nowego czatu,
        # dopóki są wiadomości asystenta i liczba wiadomości nie spadła.
        # Zapobiega to zbędnemu ponownemu wysyłaniu całego wielotysięcznego kontekstu.
        elif prev_first_prompt and first_user_prompt and prev_first_prompt != first_user_prompt:
            print(f"[CHAT UPDATE] First prompt changed slightly, keeping existing session (no fresh session forced)", flush=True)
            state["first_user_prompt"] = first_user_prompt

    # Sprawdzamy, czy w NOWYCH wiadomościach (od ostatniego stanu) pojawiły się nowe obrazy:
    new_incoming_messages = req.messages[state.get("msgs_len", 0):] if (state and state.get("msgs_len", 0) > 0) else req.messages
    new_images = _extract_images(new_incoming_messages)

    if is_new_conversation:
        if state:
            state["parent_id"] = None
            state["first_user_prompt"] = first_user_prompt
        resume = False
    else:
        resume = bool(state and state.get("parent_id") is not None and state.get("ds_session"))

    ref_file_ids = []

    # Pick and atomically acquire account for this conversation (Mutual Exclusion & Zero TOCTOU)
    preferred_idx = None
    forced_slot = raw_request.headers.get("x-target-slot") or raw_request.headers.get("x-slot")
    if forced_slot and forced_slot.strip().isdigit():
        preferred_idx = int(forced_slot.strip())
        print(f"[TARGET SLOT] Explicitly targeting slot {preferred_idx} via request header", flush=True)
    elif state and "account" in state:
        saved_acc = state["account"]
        now_req = time.time()
        # NOWA KONWERSACJA (nowy czat w Trae: brak wiadomości asystenta / drastyczny spadek
        # liczby wiadomości). Klucz konwersacji jest ten sam (jwt_leg_<user>), więc bez tego
        # warunku KAŻDE nowe okno dziedziczyło przypięcie do konta poprzedniej rozmowy —
        # wszystkie nowe czaty lądowały na tym samym slocie (np. 7). Nowa rozmowa nie ma
        # jeszcze sesji DeepSeek, więc nie ma czego przypinać: bierzemy najmniej obciążone.
        if is_new_conversation:
            print(f"[NEW CHAT PIN] nowa konwersacja -> nie przypinam konta {saved_acc}, wybieram najdłużej nieużywane (rotacja)", flush=True)
            preferred_idx = None
        elif ENABLE_ACCOUNT_MIGRATION and now_req < _rate_limited_until[saved_acc]:
            print(f"[RATE-LIMIT] Account {saved_acc} currently rate-limited (for {_rate_limited_until[saved_acc]-now_req:.1f}s) -> migrating conv {conv_key[:20]} to clean account", flush=True)
            preferred_idx = None
        else:
            preferred_idx = saved_acc

    # Timeout dobrany do polityki "bez rotacji": przy chwilowym rate-limicie wolelibyśmy
    # POCZEKAĆ na własne konto (sesja DeepSeek zostaje nietknięta), niż przełączyć się i stracić
    # cały kontekst. DeepSeek ustawia limit zwykle na ~120 s, więc 150 s pozwala go przeczekać.
    account_idx = ap.acquire_slot(preferred_slot=preferred_idx, timeout=150.0, is_subagent=is_subagent)
    slot_released = False
    t_slot_start = time.time()

    def _release_slot_safe(status: str = "OK"):
        nonlocal slot_released
        if not slot_released:
            slot_released = True
            dur = time.time() - t_slot_start
            ap.release_slot(account_idx, status=status, duration=dur)

    print(f"[ACCOUNT] conv_key={conv_key[:24]}... acquired account_idx={account_idx} (preferred={preferred_idx})", flush=True)

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
    if is_clean_port:
        tools = req.tools
    else:
        if not tools and state:
            tools = state.get("tools")
        if not tools and not state:
            tools = _load_tools(sys_hash)

    # Wstrzyknięcie narzędzi WebSearch i WebFetch dla subagentów, jeśli Trae ich nie przekazał:
    if not is_clean_port and is_subagent and tools and not _clean_mode_enabled():
        has_websearch = any(
            (t.get("function", {}).get("name") if isinstance(t, dict) else "") == "WebSearch"
            for t in tools
        )
        if not has_websearch:
            cached_tools = _load_tools(sys_hash) or []
            web_tools = [
                t for t in cached_tools
                if isinstance(t, dict) and t.get("function", {}).get("name") in ("WebSearch", "WebFetch")
            ]
            if web_tools:
                tools = list(tools) + web_tools
                print(f"[SUBAGENT] Injected {len(web_tools)} cached web search tools into subagent toolset!", flush=True)
            else:
                tools = list(tools) + [
                    {
                        "type": "function",
                        "function": {
                            "name": "WebSearch",
                            "description": "Search the web for real-time information, websites, forums, and articles.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "The search query"}
                                },
                                "required": ["query"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "WebFetch",
                            "description": "Fetch content from a URL via HTTP request.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "url": {"type": "string", "description": "The URL to fetch"}
                                },
                                "required": ["url"]
                            }
                        }
                    }
                ]
                print(f"[SUBAGENT] Injected default WebSearch & WebFetch tools into subagent!", flush=True)

    # DeepSeek zunifikowany: wyszukiwanie natywne (search_enabled) działa równolegle z narzędziami i myśleniem
    print(f"[ROUTER] Final config: search_enabled={search_enabled}, thinking_enabled={thinking_enabled}, tools={len(tools) if tools else 0}", flush=True)

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
        _release_slot_safe()
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
    # UWAGA: `stream_aborted` i `incomplete_count` NIE są tu już traktowane jako "zatruty stan".
    # DeepSeek przerywa generację (finish_reason="generation_err") notorycznie, a tura kończy się
    # wtedy np. samym reasoningiem. Sesja DeepSeek jest jednak NADAL w pełni użyteczna: mamy
    # ważny węzeł odpowiedzi i cały kontekst, więc kolejna tura po prostu kontynuuje od niego
    # (RESUME, send=1 nowej wiadomości). Wcześniej KAŻDY taki przypadek wymuszał NOWĄ sesję,
    # czyli ponowne wysłanie CAŁEGO kontekstu (log: prompt=149422 chars, 2 chunki ingestii ~8s).
    # Model na takim monstrualnym, zduplikowanym kontekście wpadał w pętlę (LOOP GUARD) i urywał
    # odpowiedź w połowie słowa — dokładnie to widział użytkownik. Świeża sesja zostaje tylko
    # po REALNEJ pętli, gdzie ogon sesji (ostatni węzeł) jest bezwartościowy.
    if resume and state and state.get("loop_aborted"):
        print(f"[RESUME] Poisoned state detected (loop_aborted=True) -> forcing fresh session with schemas", flush=True)
        state["parent_id"] = None
        state["msgs_len"] = 0
        state["loop_aborted"] = False
        state["stream_aborted"] = False
        state["incomplete_count"] = 0
        resume = False
    if resume and state:
        # Jeśli liczba wiadomości spadła do <= 2, a wcześniej było więcej, to użytkownik otworzył nowy czat w Trae!
        if len(req.messages) <= 2 and state.get("msgs_len", 0) > 2:
            print(f"[NEW CHAT DETECTED] req.messages={len(req.messages)} <= 2 while state msgs_len={state.get('msgs_len')} -> starting fresh DS session", flush=True)
            resume = False
            state = None
            with _conv_lock:
                _conv_state.pop(conv_key, None)
                _save_conv_state()

    if resume:
        chat_id = state["ds_session"]
        parent_id = state["parent_id"]
        # Kontynuujemy w tej samej sesji DeepSeek.
        # Wysyłamy wyłącznie nowe wiadomości użytkownika i wyniki narzędzi (bez powtarzania asystenta i bez schematów).
        if len(req.messages) == state["msgs_len"]:
            # RETRY / kontynuacja po niepełnym strumieniu: wyślij tylko ostatnią wiadomość
            new_msgs = [m for m in req.messages[-1:] if m.get("role") in ("user", "tool")]
            if not new_msgs:
                new_msgs = [m for m in req.messages[-1:] if m.get("role") != "system"]
            print(f"[RESUME] RETRY/continue (same msgs_len={state['msgs_len']}), last msg only", flush=True)
            prompt = _build_prompt(new_msgs, tools=None, state=state)
        elif len(req.messages) > state["msgs_len"]:
            # Normalny resume: tylko nowe wiadomości użytkownika i narzędzi (bez powtarzania asystenta)
            new_msgs = [m for m in req.messages[state["msgs_len"]:] if m.get("role") in ("user", "tool")]
            if not new_msgs:
                new_msgs = [m for m in req.messages[-1:] if m.get("role") != "system"]
            existing_goal = state.get("original_task_goal", "")
            if not existing_goal:
                new_goal = extract_goals_from_messages(new_msgs)
                if new_goal:
                    state["original_task_goal"] = new_goal
                    print(f"[GOAL] RESUME: set goal from new msgs", flush=True)
            print(f"[RESUME] ds_session={chat_id} account={account_idx} parent={parent_id} skip={state['msgs_len']} send={len(new_msgs)} new msgs (no schemas, no echo)", flush=True)
            prompt = _build_prompt(new_msgs, tools=None, state=state)
        else:
            # Trae przyciął wiadomości w trakcie aktywnego wątku
            new_msgs = [m for m in req.messages[-1:] if m.get("role") in ("user", "tool")]
            if not new_msgs:
                new_msgs = [m for m in req.messages[-1:] if m.get("role") != "system"]
            print(f"[RESUME] Trae trimmed ({len(req.messages)} < {state['msgs_len']}) — continue same session, last msg only", flush=True)
            prompt = _build_prompt(new_msgs, tools=None, state=state)

        # ── Universal Meta-Awareness Nudge (Dla subagenta / Flash / pętli narzędzi) ──
        # Jeśli subagent wykonuje wiele operacji narzędziowych (>= 8) lub po zapętleniu:
        # uświadamiamy model prostym bodźcem metakognitywnym, dając mu impuls do ogarnięcia się.
        tool_turns = sum(1 for m in req.messages if m.get("role") == "tool" or "<tool_result" in str(m.get("content", "")))
        if is_subagent and (tool_turns >= 8 or (state and state.get("loop_aborted"))):
            meta_nudge = (
                "\n\n[SYSTEM]:\n"
                "Zauważyliśmy problem z przebiegiem tego zadania (możliwe zapętlenie w narzędziach, utrata głównego wątku lub błąd protokołu).\n"
                "Twoim zadaniem jest się teraz ogarnąć: wróć myślami do pierwszego zlecenia, przeanalizuj krytycznie swój dotychczasowy postęp i doprowadź zadanie do końca — "
                "albo wykonując jedno konkretne, w 100% poprawne zapytanie narzędziowe, albo przedstawiając gotowy, finalny raport w Markdownie."
            )
            prompt += meta_nudge
            print(f"[META-NUDGE] Injected universal awareness nudge for subagent (tool_turns={tool_turns}, loop_aborted={state.get('loop_aborted') if state else False})", flush=True)

        # ── Vision support in resume: upload images attached to new_msgs in this turn ──
        turn_images = _extract_images(new_msgs)
        if turn_images:
            ref_file_ids = _upload_images_to_deepseek(ds, account_idx, turn_images)
            print(f"[RESUME VISION] Uploaded {len(ref_file_ids)} image(s) for turn: {ref_file_ids}", flush=True)

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
        chat_id, account_idx = ds.create_session_with_fallback(account_idx)
        parent_id = None
        clean_msgs = []
        for m in req.messages:
            if m.get("role") == "tool":
                m2 = dict(m)
                clean_msgs.append(m2)
            elif is_vision and isinstance(m.get("content"), list):
                # Format text parts, preserve [Image] tag for prompt
                m2 = dict(m)
                text_parts = []
                for p in m["content"]:
                    if isinstance(p, dict) and p.get("type") == "text":
                        text_parts.append(p.get("text", ""))
                    elif isinstance(p, dict) and p.get("type") == "image_url":
                        text_parts.append("[Image]")
                m2["content"] = " ".join(text_parts).strip() or "[Image]"
                clean_msgs.append(m2)
            else:
                clean_msgs.append(m)
        if is_vision and image_files:
            ref_file_ids = _upload_images_to_deepseek(ds, account_idx, image_files)
        # ── Prompt engineering: ensure system prompt exists, subagents, main agent ──
        if is_clean_port:
            print(f"[PORT 4571 - CLEAN PASSTHROUGH] Pure passthrough mode. Zero prompt injection. Request passed 1:1.", flush=True)
        else:
            # Gwarancja obecności system promptu na nowym czacie:
            # Jeśli klient nie przesłał roli 'system' na początku, pobieramy zapisaną z cache lub fallback.
            if not clean_msgs or clean_msgs[0].get("role") != "system":
                cached_sys = ""
                if os.path.exists(SYS_PROMPT_LOG):
                    try:
                        with open(SYS_PROMPT_LOG, "r", encoding="utf-8") as f:
                            cached_sys = f.read().strip()
                    except Exception:
                        pass
                if not cached_sys:
                    cached_sys = "You are an expert AI software engineer and coordinator."
                clean_msgs.insert(0, {"role": "system", "content": cached_sys})
                print(f"[SYSTEM PROMPT] Injected base system prompt ({len(cached_sys)} chars) because client sent none", flush=True)

            if is_subagent:
                # SUBAGENT for coding: replace 15KB Trae prompt with minimal task-focused version
                _cwd, _os = _extract_environment_info(req.messages)
                _orig_len = len(clean_msgs[0]["content"])
                clean_msgs[0] = dict(clean_msgs[0], content=(
                    f"You are a subagent. Execute the task below using the provided tools.\n"
                    f"ENVIRONMENT:\n"
                    f"- Operating system: {_os}\n"
                    f"- Primary workspace root: {_cwd}\n"
                    f"PATH & TOOL RULES:\n"
                    f"- Read tool strictly requires an existing absolute path. NEVER guess or invent non-existent absolute paths like /Users/... or /home/...\n"
                    f"- If you are given a relative path (e.g. 'src/...'), a filename, or do not know the exact absolute path on {_os}, ALWAYS invoke 'Glob' (e.g. pattern='**/filename.tsx') or 'LS' first to locate the exact path before calling 'Read'!\n"
                    f"- If you already have the verified full path on {_os}, you can call 'Read' directly.\n"
                    f"EXECUTION RULES:\n"
                    f"- Be thorough and complete. Synthesize findings into concise facts.\n"
                    f"- Quote at most 2-3 key code lines when evidence is needed.\n"
                    f"- NEVER copy raw tool dumps with line-number prefixes like '120→'.\n"
                    f"- Do not chat, explain, repeat the prompt, echo task instructions, list file paths, or write preambles before calling tools — invoke the tools directly and immediately.\n"
                    f"- TOOL CALLS: Always invoke tools individually using standard XML tags like <invoke name=\"Tool\"><parameter name=\"param\">value</parameter></invoke> or <Tool><param>val</param></Tool>. NEVER concatenate unclosed tags like <glob>...<grep>."
                ))
                print(f"[SUBAGENT] Real subagent detected (env: {_os}, cwd={_cwd}). Prompt: {_orig_len}→{len(clean_msgs[0]['content'])} chars (saved {_orig_len - len(clean_msgs[0]['content'])})", flush=True)
            elif _clean_mode_enabled():
                _cp = _get_clean_prompt()
                if _cp:
                    clean_msgs[0] = dict(clean_msgs[0], content=_cp)
                    print(f"[CLEAN] Mode=clean — Trae prompt replaced by prompt2.txt ({len(clean_msgs[0]['content'])} chars)", flush=True)
                else:
                    print(f"[CLEAN] Clean mode active, preserved default system prompt ({len(clean_msgs[0]['content'])} chars)", flush=True)
            else:
                # MAIN AGENT for coding: different prompt depending on mode
                # MAIN AGENT for coding: coordinator prompt with full tool capabilities
                _mode = _get_mode()
                _prepend = (
                    "## ⚠️ ARCHITECTURE — COORDINATOR & SUBAGENT ROLES\n"
                    "You are the lead COORDINATOR:\n"
                    "- Talk to the user, understand requirements, plan architecture, and write clean, robust code.\n"
                    "- Launch subagents (Task tool) in PARALLEL for broad codebase exploration, directory audits, and reading multiple files across the project to keep your context window clean.\n"
                    "- You CAN and SHOULD use Read/Write/Edit/SearchReplace directly when inspecting or modifying specific target files requested by the user, or when full file content is required for synthesis or editing.\n"
                    "- DO NOT read dozens of files sequentially yourself — launch parallel subagents (Task) instead for bulk research.\n"
                    "- After subagents finish, synthesize their findings, present clear conclusions, or perform necessary file modifications.\n"
                    "- When delegating file inspection to subagents, provide full or project-relative paths (e.g. including subfolder), or instruct them to locate files with Glob.\n"
                    "WHY: Delegating broad searches keeps YOUR context window clean for high-level reasoning, while allowing you direct access to the files you actively edit.\n\n"
                )
                if _mode in ("web", "free", "biedny"):
                    _prepend += (
                        "## NOTE: You are running on FREE web chat (context window ~32K).\n"
                        "Be efficient. Avoid huge tool dumps. Keep code edits focused and precise.\n\n"
                    )
                # DYSCYPLINA WYWOŁAŃ NARZĘDZI.
                # Powód: model potrafił ZAPOWIEDZIEĆ działanie samym tekstem ("Let me read...",
                # "Sprawdzam plik...", "doczytam resztę...") i zakończyć turę bez wywołania
                # narzędzia. Trae czekało wtedy w miejscu, a użytkownik musiał pisać "kontynuuj".
                # Zamiast łapać to regexem na polskie słówka (co przegrywa, bo wariantów
                # językowych jest nieskończenie wiele), wymuszamy poprawną formę u źródła.
                _prepend += (
                    "## ⚠️ TOOL CALL DISCIPLINE (MANDATORY)\n"
                    "When you decide to use a tool, emit the tool call block ONLY.\n"
                    "Do NOT write any plan, intention, promise or explanation before or instead of it\n"
                    "(e.g. never write 'Let me check...', 'I'll read...', 'Sprawdzam...', 'doczytam...').\n"
                    "Announcing an action WITHOUT calling the tool ends your turn and blocks the user.\n"
                    "If the task is already finished, give the final answer directly — no promises.\n\n"
                )
                clean_msgs[0] = dict(clean_msgs[0], content=_prepend + clean_msgs[0]["content"])
                print(f"[MAIN] Mode={_mode} — prepended prompt (+{len(_prepend)} chars). Total: {len(clean_msgs[0]['content'])} chars", flush=True)

            # Jeśli użytkownik stworzył własny prompt3.txt dla trybów Search/Vision i plik nie jest pusty:
            if (search_enabled or is_vision) and PROMPT3_FILE.exists():
                _sv = _get_search_vision_prompt()
                if _sv.strip():
                    clean_msgs[0] = dict(clean_msgs[0], content=_sv.strip() + "\n\n" + clean_msgs[0]["content"])
                    print(f"[SEARCH/VISION] Appended custom prompt3.txt ({len(_sv)} chars) to system prompt", flush=True)

        # ── Persistent Goal Injection: wyciągnij cele ze wszystkich wiadomości użytkownika ──
        # Tryb czysty: bez wstrzykiwania <critical_directive> / ORIGINAL GOAL — czysty kontekst.
        goals = extract_goals_from_messages(req.messages) if (not _clean_mode_enabled() and not is_clean_port) else ""
        # ── Semantic summary + proactive rotation warning (web chat only) ──
        conv_summary = ""
        rotation_warning = ""
        if not is_subagent and not is_clean_port:
            # For web chat, check if we need proactive rotation warning
            if state and state.get("msgs_len", 0) >= 45:
                rotation_warning = get_rotation_warning(state["msgs_len"])
            conv_summary = build_conversation_summary(req.messages) if len(req.messages) > 10 else ""
        
        prefix_parts = []
        if goals and len(req.messages) > 2:
            prefix_parts.append(format_goals_context(goals))
            print(f"[GOALS] Extracted goals from {len(req.messages)} msgs, injecting into prompt", flush=True)
        if rotation_warning:
            prefix_parts.append(rotation_warning)
        if conv_summary:
            prefix_parts.append(conv_summary)
        
        base_prompt = _build_prompt(clean_msgs, tools=tools, images=None if is_vision else image_files)
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

    # Bezpiecznik: PUSTY prompt kończy się na DeepSeek błędem biz_code 6
    # "missing prompt or ref file" -> 0 data lines -> 3 jałowe próby -> HTTP 502.
    # Zdarza się, gdy jedyna nowa wiadomość w RESUME to wynik narzędzia, którego treść
    # w całości zniknęła przy czyszczeniu boilerplate (np. sam <system-reminder>).
    # Sesja DeepSeek MA już kontekst, więc wystarczy krótki bodziec.
    if not prompt or not prompt.strip():
        print(f"[EMPTY PROMPT GUARD] Prompt wyszedł pusty — zamiast niego wysyłam bodziec (sesja ma kontekst)", flush=True)
        prompt = "[System: Please continue the task.]"


    result = None
    migrated = False
    # ── Subagent Circuit Breaker timing ──
    subagent_timing_key = record_subagent_start() if is_subagent else None
    subagent_stream_start = time.time() if is_subagent else 0
    # ── Monitor sesji: rejestracja tego żądania ──
    monitor.start(watermark_uuid, conv_key=conv_key, is_subagent=is_subagent, account_idx=account_idx)
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
                        chat_id, account_idx = ds.create_session_with_fallback(account_idx)
                    print(f"[CHUNKED INGESTION] Prompt ({len(prompt)} chars) > {CHUNK_THRESHOLD} -> split into {len(chunks)} chunks for session {chat_id}", flush=True)
                    current_parent = parent_id
                    for c_idx, c_text in enumerate(chunks[:-1]):
                        monitor.heartbeat(watermark_uuid)
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
            monitor.heartbeat(watermark_uuid)
            result = ds.stream_completion(account_idx, chat_id, prompt, parent_id, max_tok, req.temperature, req.top_p, model_type=model_type, ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled, search_enabled=search_enabled, tools_available=bool(tools), watermark_uuid=watermark_uuid)
            break
        except Exception as e:
            err_str = str(e).lower()
            if not migrated and ("content is too long" in err_str or "input_exceeds_limit" in err_str):
                # Poziom 2: Reaktywny podział na mniejsze paczki (30k) w nowej sesji
                smaller_chunks = _chunk_oversized_prompt(prompt, 30000)
                if len(smaller_chunks) > 1:
                    print(f"[REACTIVE CHUNKING] Splitting prompt into {len(smaller_chunks)} smaller 30k chunks in fresh session...", flush=True)
                    chat_id, account_idx = ds.create_session_with_fallback(account_idx)
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
                    _release_slot_safe()
                    return _handle_official_api_chat(
                        req, conv_key, watermark_uuid, None, tools, sys_hash,
                        is_subagent, t0
                    )
                print(f"[CONTEXT-OVERFLOW] DS context exceeded, crushing tool results for web chat...", flush=True)
                # Clear old state and build a heavily compressed full-prompt for new session
                with _conv_lock:
                    _conv_state.pop(conv_key, None)
                    _save_conv_state()
                chat_id, account_idx = ds.create_session_with_fallback(account_idx)
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
                _release_slot_safe()
                print(f"[ERROR] stream_completion failed: {e}", flush=True)
                raise HTTPException(502, f"Upstream error: {e}")
            print(f"[MIGRATE] Account {account_idx} exhausted, looking for alternative...", flush=True)
            now_migrate = time.time()
            alt = [i for i in range(MAX_ACCOUNTS) if i != account_idx and ap.is_valid(i) and now_migrate >= _rate_limited_until[i]]
            if not alt:
                alt = [i for i in range(MAX_ACCOUNTS) if i != account_idx and ap.is_valid(i)]
            if not alt:
                _release_slot_safe()
                print(f"[MIGRATE] No alternative account available, giving up", flush=True)
                raise HTTPException(502, f"Upstream error: {e}")
            new_idx = ap.pick_for_conv(conv_key)
            if new_idx == account_idx:
                new_idx = alt[0]
            print(f"[MIGRATE] Moving conv {conv_key[:24]}... from account {account_idx} to {new_idx}", flush=True)
            _release_slot_safe()
            account_idx = ap.acquire_slot(preferred_slot=new_idx, timeout=30.0)
            slot_released = False
            _ensure_slot(account_idx)
            chat_id, account_idx = ds.create_session_with_fallback(account_idx)
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
                        elif isinstance(p, dict) and p.get("type") == "image_url":
                            text_parts.append("[Image]")
                    m2["content"] = " ".join(text_parts).strip() or "[Image]"
                    clean_msgs.append(m2)
                else:
                    clean_msgs.append(m)
            if is_vision and image_files:
                print(f"[VISION] Re-uploading {len(image_files)} image(s) for migration to account {account_idx}...", flush=True)
                ref_file_ids = _upload_images_to_deepseek(ds, account_idx, image_files)
            saved_goal = state.get("original_task_goal", "") if state else (goals if isinstance(goals, str) else "")
            prompt = _build_prompt(clean_msgs, tools=tools or state.get("tools") if state else None, images=image_files, state=state)
            state = {"ds_session": chat_id, "parent_id": None, "msgs_len": len(req.messages), "tools": tools or state.get("tools") if state else tools, "account": account_idx, "_ts": time.time(), "original_task_goal": saved_goal, "incomplete_count": 0, "model_type": model_type, "is_vision": is_vision}
            with _conv_lock:
                _conv_state[conv_key] = state
                _save_conv_state()
            print(f"[MIGRATE] New session on account {new_idx}: {chat_id}, retrying ({len(prompt)} chars)", flush=True)
            migrated = True
    if result is None:
        _release_slot_safe()
        ap.reset_slot(account_idx)
        raise HTTPException(401, f"Account {account_idx} session expired. Use POST /v1/login?slot={account_idx}")

    if not isinstance(result, tuple) or len(result) != 2:
        _release_slot_safe()
        print(f"[ERROR] stream_completion returned: {type(result).__name__} {repr(result)[:200]}", flush=True)
        raise HTTPException(502, "Upstream error")

    stream, result_meta = result
    resp_msg_id = result_meta.get("resp_msg_id")
    # State NOT saved yet — defer until streaming completes successfully
    # to avoid bumping msgs_len on an error that Trae will discard and retry
    print(f"[TIMING] Stream ready ({time.time()-t0:.1f}s, resp_id={resp_msg_id})", flush=True)

    if not req.stream:
        full_text = ""
        reasoning_text = ""
        try:
            for chunk in stream:
                if chunk and chunk is not _HEARTBEAT_SENTINEL:
                    if isinstance(chunk, _ReasoningChunk):
                        if chunk.text:
                            reasoning_text += chunk.text
                    elif isinstance(chunk, str):
                        full_text += chunk
        except Exception as e:
            _release_slot_safe()
            raise HTTPException(502, f"Upstream error: {str(e)}")
        finally:
            _release_slot_safe()
        tools = _parse_tool_calls(full_text)
        clean_text = full_text
        if tools:
            for ts, te, _, _ in sorted(tools, key=lambda x: -x[1]):
                clean_text = clean_text[:ts] + clean_text[te:]
            clean_text = clean_text.strip()
        clean_text = _clean_text(clean_text)
        print(f"[TIMING] Response ready ({time.time()-t0:.1f}s)", flush=True)
        msg = {"role": "assistant", "content": clean_text or None}
        if reasoning_text:
            msg["reasoning_content"] = _clean_reasoning(reasoning_text).strip()
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

    def _estimate_tokens(t: str | None) -> int:
        if not t:
            return 0
        return max(1, int(len(t) / 2.5))

    if not req.stream:
        # non-streaming logic omitted for brevity, keeping below
        pass

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    _created = int(time.time())
    _model = req.model

    _stream_usage = {"prompt_tokens": _estimate_tokens(prompt), "completion_tokens": 0, "total_tokens": _estimate_tokens(prompt)}
    _tokens_generated = 0

    def _chunk(delta: dict, fr: str | None = None) -> str:
        nonlocal _tokens_generated
        if "content" in delta and delta["content"]:
            _tokens_generated += _estimate_tokens(delta["content"])
            _log_leak_if_any(delta["content"], full_buffer=full if 'full' in locals() else "", conv_key=conv_key)
        # BUG-023: zliczaj też reasoning i tool_calls — inaczej tura Write (kod w arguments)
        # kończy się z completion_tokens=0 i Trae pokazuje 0% / zamrożony widok.
        if delta.get("reasoning_content"):
            _tokens_generated += _estimate_tokens(delta["reasoning_content"])
        _tc = delta.get("tool_calls")
        if isinstance(_tc, list):
            for _t in _tc:
                if isinstance(_t, dict):
                    _fn = _t.get("function") or {}
                    _args = _fn.get("arguments")
                    if isinstance(_args, str):
                        _tokens_generated += _estimate_tokens(_args)
        c = {"id": completion_id, "object": "chat.completion.chunk", "created": _created, "model": _model,
             "system_fingerprint": "fp_deepseek_proxy_v1",
             "choices": [{"index": 0, "delta": delta}]}
        if fr is not None:
            c["choices"][0]["finish_reason"] = fr
            _stream_usage["completion_tokens"] = _tokens_generated
            _stream_usage["total_tokens"] = _stream_usage["prompt_tokens"] + _tokens_generated
            c["usage"] = _stream_usage
        return f"data: {json.dumps(c)}\n\n"

    def generate():
        try:
            full = ""
            sent_until = 0
            tools_yielded = 0
            yielded_tool_starts = set()
            yielded_tool_signatures = set()

            try:
                yield _chunk({"role": "assistant"})
            except GeneratorExit:
                print(f"[DISCONNECT] Client disconnected before stream", flush=True)
                return
            success = False
            _restart_budget = 1

            def _stream_source():
                """Źródło chunków z auto-restartem (#3): sweeper ustawia stop
                na sesji 'slow'/'dead' → podmieniamy strumień (max 1 raz).
                Hard stop (ręczny POST /v1/monitor/stop) → natychmiastowe przerwanie."""
                nonlocal stream, result_meta, _restart_budget, full, sent_until, tools_yielded, yielded_tool_starts, yielded_tool_signatures
                while True:
                    for _ch in _heartbeat_iter(stream):
                        _ev = monitor.get_stop_event(watermark_uuid)
                        if _ev is not None and _ev.is_set():
                            if monitor.is_hard_stop(watermark_uuid):
                                print(f"[MONITOR] Hard stop {watermark_uuid[:12]}...", flush=True)
                                raise GeneratorExit
                            if _restart_budget > 0:
                                _restart_budget -= 1
                                print(f"[MONITOR] Auto-restart {watermark_uuid[:12]}... (kill->restart, budget={_restart_budget})", flush=True)
                                monitor.clear_stop(watermark_uuid)
                                try:
                                    _ns, _nm = ds.stream_completion(
                                        account_idx, chat_id, prompt, parent_id, max_tok,
                                        req.temperature, req.top_p, model_type=model_type,
                                        ref_file_ids=ref_file_ids, thinking_enabled=thinking_enabled,
                                        search_enabled=search_enabled, tools_available=bool(tools),
                                        watermark_uuid=watermark_uuid)
                                except Exception as _e:
                                    print(f"[MONITOR] Restart failed: {_e}", flush=True)
                                    raise GeneratorExit
                                if _ns is None:
                                    print(f"[MONITOR] Restart returned None (401?)", flush=True)
                                    raise GeneratorExit
                                stream = _ns
                                result_meta.update(_nm)
                                full = ""
                                sent_until = 0
                                tools_yielded = 0
                                yielded_tool_starts.clear()
                                yielded_tool_signatures.clear()
                                break
                        yield _ch
                    else:
                        return

            try:
                def _is_orphaned_block(ts, te, full_text):
                    snippet = full_text[ts:te].strip()
                    if _INVOKE_CLOSE_RE.search(snippet):
                        return False
                    if '<｜tool call end｜>' in snippet:
                        return False
                    if re.search(r'</\s*(?:glob|grep|read|write|task|skill)\s*>', snippet, re.IGNORECASE):
                        return False
                    return True

                for chunk in _stream_source():
                    if chunk is _HEARTBEAT_SENTINEL:
                        # Bug 26: podtrzymuj polaczenie SSE podczas ciszy (myslenie/CoT)
                        monitor.heartbeat(watermark_uuid)
                        yield ": keep-alive\n\n"
                        continue
                    if isinstance(chunk, _ReasoningChunk):
                        # BUG-004: streamuj myślenie na żywo jako delta.reasoning_content
                        if chunk.text:
                            clean_text = _clean_reasoning(chunk.text)
                            if clean_text:
                                yield _chunk({"reasoning_content": clean_text})
                        continue
                    if chunk:
                        monitor.token(watermark_uuid)
                        full += chunk

                        tools = _parse_tool_calls(full, allow_unclosed=False)
                        if tools:
                            cursor = sent_until
                            all_resolved = True
                            for ts, te, tname, targs in tools:
                                if ts in yielded_tool_starts or te <= cursor:
                                    continue
                                if _is_orphaned_block(ts, te, full):
                                    all_resolved = False
                                    continue
                                call_sig = (tname, targs)
                                if call_sig in yielded_tool_signatures:
                                    yielded_tool_starts.add(ts)
                                    cursor = max(cursor, te)
                                    continue
                                if ts > cursor:
                                    text = _STRIP_TAGS.sub("", full[cursor:ts])
                                    text = _clean_reasoning(text).strip()
                                    if text:
                                        print(f"[YIELD] text[{cursor}:{ts}] -> {repr(text[:100])}", flush=True)
                                        yield _chunk({"content": text})
                                print(f"[TC] {tname}({targs[:80]})  span=({ts},{te})", flush=True)
                                tc_id = f"call_{uuid.uuid4().hex[:12]}"
                                yield _chunk({"tool_calls": [{"index": tools_yielded, "id": tc_id, "type": "function", "function": {"name": tname, "arguments": targs}}]})
                                tools_yielded += 1
                                yielded_tool_starts.add(ts)
                                yielded_tool_signatures.add(call_sig)
                                try:
                                    targs_dict = json.loads(targs) if isinstance(targs, str) else targs
                                    record_tool_call(state or {}, tname, targs_dict, len(req.messages))
                                except Exception:
                                    pass
                                cursor = max(cursor, te)
                            sent_until = cursor
                            if not all_resolved:
                                continue

                        if _has_unclosed_tool_call(full):
                            continue

                        tail = full[sent_until:]
                        # BUG-033: Ignoruj wewnętrzne pseudotagi _wait przy sprawdzaniu otwartych narzędzi
                        tail_check = _clean_dsml_wait(tail)
                        # BUG-034: _REAL_TOOL_TAG zamiast gołych "tool_call"/nazw narzędzi,
                        # ktore lapaly slowa z prozy (np. "write", "task") i wstrzymywaly streaming.
                        if _REAL_TOOL_TAG.search(tail_check) or re.search(r'</?\s*(?:[|｜\uff5c\u2502\s]*DSML|user_input|parameter|参数|參數|pattern|file_path|command)\b', tail_check, re.IGNORECASE):
                            continue

                        delta = full[sent_until:]
                        # Sprawdzamy czy w delcie pojawia się rzeczywisty początek tagu narzędzia
                        m_tool = re.search(r'(?:<[|｜\uff5c\u2502\s]*(?:tool|invoke|DSML)|\[[|｜\uff5c\u2502\s]*DSML|<\s*(?:tool_call|invoke)|\{\s*"(?:file_path|command))', delta, re.IGNORECASE)
                        # Sprawdzamy czy na końcu delty nie ma urwanego prefiksu tagu (<, </, <||DS itp.)
                        m_pref = re.search(
                            r'<\s*/?[|｜\uff5c\u2502\s]*(?:[a-zA-Z0-9_]{0,25})$|'
                            r'\[\s*/?[|｜\uff5c\u2502\s]*(?:[a-zA-Z0-9_]{0,25})$|'
                            r'<[|｜\uff5c\s]*tool\s*(?:call\s*(?:begin|end)?)?$',
                            delta, re.IGNORECASE
                        )
                        m_cut = m_tool or m_pref
                        if m_cut:
                            delim_pos = m_cut.start()
                            if delim_pos > 0:
                                safe = delta[:delim_pos]
                                clean = _STRIP_TAGS.sub("", safe)
                                clean = _clean_reasoning(clean)
                                if clean:
                                    yield _chunk({"content": clean})
                                sent_until += delim_pos
                        else:
                            safe = delta
                            clean = _STRIP_TAGS.sub("", safe)
                            clean = _clean_reasoning(clean)
                            if clean:
                                yield _chunk({"content": clean})
                            sent_until += len(safe)

                # End-of-stream final check for any late resolved tool calls
                if sent_until < len(full):
                    final_tools = _parse_tool_calls(full, allow_unclosed=True)
                    if final_tools:
                        cursor = sent_until
                        for ts, te, tname, targs in final_tools:
                            if ts in yielded_tool_starts or te <= cursor:
                                continue
                            call_sig = (tname, targs)
                            if call_sig in yielded_tool_signatures:
                                yielded_tool_starts.add(ts)
                                cursor = max(cursor, te)
                                continue
                            if ts > cursor:
                                text = _STRIP_TAGS.sub("", full[cursor:ts])
                                text = _clean_reasoning(text).strip()
                                if text:
                                    yield _chunk({"content": text})
                            print(f"[TC-FINAL] {tname}({targs[:80]})  span=({ts},{te})", flush=True)
                            tc_id = f"call_{uuid.uuid4().hex[:12]}"
                            yield _chunk({"tool_calls": [{"index": tools_yielded, "id": tc_id, "type": "function", "function": {"name": tname, "arguments": targs}}]})
                            tools_yielded += 1
                            yielded_tool_starts.add(ts)
                            yielded_tool_signatures.add(call_sig)
                            cursor = max(cursor, te)
                        sent_until = cursor

                # Flush any held-back trailing text that is confirmed not to be a tool call
                if sent_until < len(full):
                    remaining = full[sent_until:]
                    rem_check = _clean_dsml_wait(remaining)
                    # BUG-034: zamiast gołego "tool_call" (lapie wzmianki w prozie) uzywamy _REAL_TOOL_TAG.
                    if not _has_unclosed_tool_call(rem_check) and not _REAL_TOOL_TAG.search(rem_check) and not re.search(r'<\s*(?:user_input|parameter|参数|參數|pattern|path)', rem_check, re.IGNORECASE):
                        clean_rem = _STRIP_TAGS.sub("", rem_check)
                        clean_rem = _clean_reasoning(clean_rem)
                        if clean_rem.strip():
                            yield _chunk({"content": clean_rem})
                    sent_until = len(full)

                # BUG-024 & BUG-033: Bezpiecznik pustych deklaracji oraz paraliżu _wait.
                # Jeśli model nie wyemitował żadnego narzędzia (tools_yielded == 0),
                # ale zakończył wypowiedź obietnicą podjęcia akcji lub wyemitował wyłącznie tagi _wait,
                # rzuć jawny komunikat o braku wywołania narzędzia zamiast cichego sukcesu / zamrożenia na 0%.
                if tools_yielded == 0:
                    clean_full = _clean_dsml_wait(full)
                    clean_full = _STRIP_TAGS.sub("", clean_full).strip()
                    if not clean_full:
                        print(f"[STREAM ZERO TOKENS] No content and no tools generated for {conv_key[:24]}", flush=True)
                        success = False
                        if "_wait" in full.lower():
                            _alert = "\n\n[BŁĄD PROXY: Model DeepSeek wyemitował wewnętrzny znacznik bezczynności (_wait) zamiast wywołania narzędzia. Ponów polecenie.]"
                        else:
                            _alert = "\n\n[BŁĄD PROXY: Serwer DeepSeek nie zwrócił żadnych tokenów (pusty strumień). Ponów zapytanie w nowym czacie.]"
                        yield _chunk({"content": _alert})
                    else:
                        success = True
                else:
                    success = True
            except GeneratorExit:
                print(f"[DISCONNECT] Client disconnected", flush=True)
                return
            except Exception as e:
                err_str = str(e)
                elapsed = time.time() - t0
                print(f"[TIMING] Stream error at {elapsed:.1f}s: {e}", flush=True)
                # Save whatever content or message node we got before the error
                resp_msg_id = result_meta.get("resp_msg_id")
                if state and resp_msg_id:
                    state["parent_id"] = resp_msg_id
                    state["msgs_len"] = len(req.messages)
                    _save_conv_state()
                    print(f"[STREAM ERROR] Saved parent_id={resp_msg_id} for {conv_key[:24]}", flush=True)
                elif full.strip() and state:
                    state["parent_id"] = state.get("parent_id")
                    state["msgs_len"] = len(req.messages)
                    _save_conv_state()
                    print(f"[STREAM ERROR] Partial content saved ({len(full)} chars) for {conv_key[:24]}", flush=True)

                if full.strip():
                    # Yield what we have so far + info message + [DONE]
                    remaining = full[sent_until:] if sent_until < len(full) else ""
                    remaining = _STRIP_TAGS.sub("", remaining)
                    remaining = re.sub(r"<[^>]*>", "", remaining).strip()
                    if remaining:
                        yield _chunk({"content": remaining})
                if any(k in err_str.lower() for k in ("length limit", "context_length", "start a new chat", "content is too long", "input_exceeds_limit", "too long", "limit długości", "rozpocznij nowy czat")):
                    # Zamiast czyścić stan, rotujemy sesję DS automatycznie
                    print(f"[CONTEXT LIMIT] Rotating DS session for {conv_key[:24]}... (prompt was {len(prompt)} chars)", flush=True)
                    if state:
                        try:
                            new_session_id, rot_account = ds.create_session_with_fallback(account_idx)
                            state["ds_session"] = new_session_id
                            state["account"] = rot_account
                            state["parent_id"] = None
                            state["msgs_len"] = len(req.messages)
                            with _conv_lock:
                                _conv_state[conv_key] = state
                                _save_conv_state()
                            print(f"[CONTEXT LIMIT] New DS session: {new_session_id} (account={rot_account})", flush=True)
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
                    if doctor.should_trigger("auto-continue failed (2 attempts)", err_str):
                        try:
                            rep = doctor.diagnose_and_repair(
                                conv_key=conv_key,
                                reason="auto-continue failed (2 attempts)",
                                error=err_str,
                                partial_content=full,
                                messages=req.messages,
                                tools=req.tools,
                                parse_tool_calls_fn=_parse_tool_calls,
                                ap=ap
                            )
                            if rep.get("repaired"):
                                if rep.get("type") == "tool_calls" and rep.get("tools"):
                                    for _, _, tname, targs in rep["tools"]:
                                        tc_id = f"call_{uuid.uuid4().hex[:12]}"
                                        yield _chunk({"tool_calls": [{"index": tools_yielded, "id": tc_id, "type": "function", "function": {"name": tname, "arguments": targs}}]})
                                        tools_yielded += 1
                                    fr = "tool_calls" if tools_yielded > 0 else "stop"
                                    yield _chunk({}, fr)
                                    yield "data: [DONE]\n\n"
                                    return
                                elif rep.get("type") == "content" and rep.get("content"):
                                    yield _chunk({"content": rep["content"]})
                                    yield _chunk({}, "stop")
                                    yield "data: [DONE]\n\n"
                                    return
                        except Exception as doc_e:
                            print(f"[DOCTOR] Auto-continue repair hook exception: {doc_e}", flush=True)

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
                            if result_meta.get("loop_aborted"):
                                state["loop_aborted"] = True
                            if result_meta.get("auto_continue_failed"):
                                state["stream_aborted"] = True
                            print(f"[INCOMPLETE] Count={state['incomplete_count']}, not bumping msgs_len ({state['msgs_len']}), next RESUME will continue from partial response", flush=True)
                        elif _should_bump_state(tools_yielded, result_meta):
                            state["msgs_len"] = len(req.messages)
                            state["incomplete_count"] = 0  # Reset na sukces
                            state["loop_aborted"] = False
                            state["stream_aborted"] = False
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
                    # BUG-034: uzywamy _REAL_TOOL_TAG (wymaga name=/id= lub jawnego zamkniecia), zeby
                    # cytowana w prozie wzmianka "<tool_call>" nie blokowala poprawnej odpowiedzi.
                    if _has_unclosed_tool_call(full) or _REAL_TOOL_TAG.search(remaining):
                        print(f"[STREAM] Suppressed unclosed tool call leakage ({len(remaining)} chars not sent to chat)", flush=True)
                        try:
                            _write_crash_dump(conv_key=conv_key, session_id=chat_id, account_idx=account_idx,
                                              messages=req.messages, state=state, partial_content=full,
                                              reason="unclosed tool call aborted before completion", error="")
                        except Exception:
                            pass

                        doctor_repaired = False
                        if doctor.should_trigger("unclosed tool call aborted before completion"):
                            try:
                                rep = doctor.diagnose_and_repair(
                                    conv_key=conv_key,
                                    reason="unclosed tool call aborted before completion",
                                    error="",
                                    partial_content=full,
                                    messages=req.messages,
                                    tools=req.tools,
                                    parse_tool_calls_fn=_parse_tool_calls,
                                    ap=ap
                                )
                                if rep.get("repaired"):
                                    if rep.get("type") == "tool_calls" and rep.get("tools"):
                                        for _, _, tname, targs in rep["tools"]:
                                            tc_id = f"call_{uuid.uuid4().hex[:12]}"
                                            yield _chunk({"tool_calls": [{"index": tools_yielded, "id": tc_id, "type": "function", "function": {"name": tname, "arguments": targs}}]})
                                            tools_yielded += 1
                                        doctor_repaired = True
                                    elif rep.get("type") == "content" and rep.get("content"):
                                        yield _chunk({"content": rep["content"]})
                                        doctor_repaired = True
                            except Exception as doc_e:
                                print(f"[DOCTOR] Repair hook exception: {doc_e}", flush=True)

                        if not doctor_repaired:
                            # BUG-007/018: jawny alert zamiast cichego połykania uciętego wywołania narzędzia,
                            # żeby model NIE twierdził, że zapis/operacja się powiodła.
                            if re.search(r'name\s*=\s*["\']?(?:Write|Edit|SearchReplace)\b', full, re.IGNORECASE):
                                _alert = "\n\n[BŁĄD PROXY: Zapis pliku został ucięty przez limit tokenów. Plik NIE został zapisany na dysku. Ponów zapis.]"
                            else:
                                _alert = "\n\n[BŁĄD PROXY: Wywołanie narzędzia zostało ucięte i NIE zostało wykonane. Ponów operację.]"
                            yield _chunk({"content": _alert})
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
            monitor.finish(watermark_uuid, ok=True)
            _release_slot_safe()

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


@app.get("/v1/slots")
@app.get("/slots")
def get_slots_status():
    """Zwraca stan obciążenia i status wszystkich kont w puli (dla monitoringu)."""
    _check_idle_reset()
    now = time.time()
    disabled = _get_disabled_slots()
    result = {}
    busy_count = 0
    total_valid = 0
    for i in range(MAX_ACCOUNTS):
        if i in disabled:
            continue
        p = Path(__file__).parent / f"session_{i}.json"
        if not p.exists():
            continue
        total_valid += 1
        st = _account_stats[i]
        is_busy = _slot_busy[i]
        if is_busy:
            busy_count += 1
        mute_until = _muted_slots_until.get(i, 0.0)
        is_muted = mute_until > now
        mute_remain = max(0.0, mute_until - now) if is_muted else 0.0
        mute_unban_str = datetime.fromtimestamp(mute_until).strftime("%Y-%m-%d %H:%M:%S") if is_muted else None
        is_rl = now < _rate_limited_until[i]
        rl_remain = max(0.0, _rate_limited_until[i] - now) if is_rl else 0.0

        if i in _auth_expired_slots:
            slot_status = "EXPIRED"
        elif is_muted:
            slot_status = "MUTED"
        elif is_rl:
            slot_status = "RATE_LIMITED"
        elif is_busy:
            slot_status = "BUSY"
        else:
            slot_status = "IDLE"

        last_fin = _last_account_finish_time[i] if i < len(_last_account_finish_time) else 0.0
        idle_s = max(0.0, now - last_fin) if last_fin > 0 else None

        result[str(i)] = {
            "slot": i,
            "status": slot_status,
            "is_busy": is_busy,
            "is_muted": is_muted,
            "mute_remaining_s": round(mute_remain, 1) if is_muted else 0.0,
            "unban_time": mute_unban_str,
            "rate_limited": is_rl,
            "rate_limit_remaining_s": round(rl_remain, 1),
            "last_role": st.get("last_role", "NONE"),
            "total_requests": st.get("total_requests", 0),
            "main_requests": st.get("main_requests", 0),
            "subagent_requests": st.get("subagent_requests", 0),
            "consecutive_rate_limits": st.get("consecutive_rate_limits", 0),
            "idle_seconds": round(idle_s, 1) if idle_s is not None else None,
        }

    active_mutes = {int(k): v for k, v in _muted_slots_until.items() if v > now}
    next_unban = None
    if active_mutes:
        nxt_s, nxt_t = min(active_mutes.items(), key=lambda x: x[1])
        nxt_diff = max(0.0, nxt_t - now)
        next_unban = {
            "slot": nxt_s,
            "time": datetime.fromtimestamp(nxt_t).strftime("%Y-%m-%d %H:%M:%S"),
            "in_seconds": round(nxt_diff, 1),
            "in_hours": round(nxt_diff / 3600.0, 2)
        }

    return {
        "active_slots_count": total_valid,
        "busy_slots_count": busy_count,
        "free_slots_count": total_valid - busy_count,
        "next_unban": next_unban,
        "summary": _format_pool_status(),
        "proxy_shield": cloud_shield.get_status(),
        "slots": result,
    }


@app.get("/proxy/status")
@app.get("/v1/proxy/status")
def get_proxy_status():
    """Zwraca aktualny status menedzera Cloud / Proxy."""
    return cloud_shield.get_status()


@app.post("/v1/pool/reset")
@app.post("/pool/reset")
def reset_pool_status():
    """Ręczny reset liczników poola."""
    with ap._pool_lock:
        for i in range(MAX_ACCOUNTS):
            st = _account_stats[i]
            st["total_requests"] = 0
            st["main_requests"] = 0
            st["subagent_requests"] = 0
            st["consecutive_rate_limits"] = 0
            st["last_role"] = "NONE"
            st["last_status"] = "IDLE"
            if _rate_limited_until[i] > 0 and time.time() >= _rate_limited_until[i]:
                _rate_limited_until[i] = 0.0
        _save_account_usage()
    return {"status": "ok", "message": "Zresetowano liczniki poola", "pool_status": _format_pool_status()}


@app.get("/v1/monitor/sessions")
def monitor_sessions():
    """Podgląd: co robią teraz główny agent i subagenci (active/slow/dead)."""
    return {"sessions": monitor.get_snapshot()}


@app.post("/v1/monitor/stop")
def monitor_stop(session_id: str):
    """Zatrzymaj żądanie o podanym session_id (np. martwe). Hard stop — bez restaru."""
    if monitor.request_stop(session_id, hard=True):
        return {"status": "ok", "session_id": session_id, "requested": "hard_stop"}
    raise HTTPException(404, f"Nie znaleziono aktywnej sesji: {session_id}")


def _sweeper_loop():
    """Auto-kill (#3): co 5s przeszukuje sesje monitora i zabija 'slow' za długo / 'dead'.
    Zabite sesje dostają max 1 auto-restart w generate() (budżet _restart_budget).
    Dodatkowo:
    - co 30s sprawdza wygasle bany (mute) i przywraca odblokowane sloty do puli.
    - co 120s podejmuje automatyczna probe odnowienia wygaslych tokenow w tle.
    """
    last_mute_check = 0.0
    last_auto_login_check = 0.0
    while True:
        now = time.time()
        try:
            killed = monitor.sweep()
            for sid in killed:
                print(f"[MONITOR] Auto-kill: {sid[:12]}... (slow/dead -> restart przydzielony)", flush=True)
        except Exception as e:
            print(f"[MONITOR] sweep error: {e}", flush=True)

        if now - last_mute_check > 30:
            last_mute_check = now
            try:
                _check_idle_reset()
            except Exception as e:
                print(f"[SWEEPER] idle reset check error: {e}", flush=True)
            try:
                unbanned = []
                for slot, until in list(_muted_slots_until.items()):
                    if now >= until:
                        unbanned.append(slot)
                        _muted_slots_until.pop(slot, None)
                if unbanned:
                    _save_muted_slots()
                    print(f"[BAN RECOVERY] Sloty {unbanned}: okres kary mute minal! Przywracam do puli roboczej.", flush=True)
                    for slot in unbanned:
                        _rate_limited_until[slot] = 0.0
                        _last_account_finish_time[slot] = time.time()
                        try:
                            # Bezpieczna weryfikacja czy token jest sprawny (GET /users/current)
                            # Jeśli token wygasł w trakcie bana, spróbuj automatycznego logowania
                            ok = ds.probe_auth(slot, allow_auto_login=True)
                            if ok:
                                ap.reload_slot(slot)
                                print(f"[BAN RECOVERY] Slot {slot}: pomyślnie zautoryzowany i gotowy do pracy!", flush=True)
                            else:
                                print(f"[BAN RECOVERY] Slot {slot}: probe_auth zwrócił brak gotowości.", flush=True)
                        except Exception as probe_err:
                            print(f"[BAN RECOVERY] Slot {slot}: błąd podczas probe_auth: {probe_err}", flush=True)
            except Exception as e:
                print(f"[SWEEPER] mute recovery check error: {e}", flush=True)

        # Wylaczono automatyczne odpalanie Chrome w tle podczas normalnej pracy proxy.
        # Odnawianie sesji powinno odbywac sie wylacznie na zadanie uzytkownika (auto_login.py),
        # aby nie zamrazac serwera i nie blokowac aktywnych zapytan.
        time.sleep(5)


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
    disabled_slots = sorted(_get_disabled_slots())
    if disabled_slots:
        print(f"[SLOTS] Ignorowane sloty (wylaczone): {disabled_slots}", flush=True)
    valid_slots = [i for i in range(MAX_ACCOUNTS) if ap.is_valid(i)]
    if valid_slots:
        # Weryfikacja tokenów PRZED podaniem się do ruchu. Bez tego proxy twierdziło "4 konta
        # gotowe", choć realnie działało jedno, a wygasłe konta zjadały żądania i wyglądały
        # jak rate-limit. To była ukryta przyczyna większości dzisiejszych awarii.
        print(f"[STARTUP] Szybka weryfikacja tokenow {len(valid_slots)} kont (GET /users/current)...", flush=True)
        for _i in list(valid_slots):
            if not ds.probe_auth(_i, allow_auto_login=False):
                _auth_expired_slots.add(_i)
                print(f"[STARTUP] Slot {_i}: token NIEAKTYWNY lub KONTO ZMUTOWANE — pomijam.", flush=True)
        valid_slots = [i for i in range(MAX_ACCOUNTS) if ap.is_valid(i)]
    if valid_slots:
        print(f"Active accounts: {len(valid_slots)} logged in (slots: {valid_slots}). Ready for requests.", flush=True)
    else:
        print("!!! UWAGA: BRAK DZIALAJACYCH KONT DEEPSEEK — kazde zadanie zakonczy sie bledem. "
              "Zaloguj konto: login_slot.bat N, potem zrestartuj proxy. !!!", flush=True)
        print(f"Brak aktywnych kont (sloty {disabled_slots} sa wylaczone). Zaloguj nowy slot: login_slot.bat 3", flush=True)
    threading.Thread(target=_sweeper_loop, daemon=True).start()
    _port = int(os.environ.get("PORT", 4570))
    if "--port" in sys.argv:
        try:
            _port = int(sys.argv[sys.argv.index("--port") + 1])
        except (ValueError, IndexError):
            pass
    _host = os.environ.get("HOST", "127.0.0.1")
    if "--host" in sys.argv:
        try:
            _host = sys.argv[sys.argv.index("--host") + 1]
        except IndexError:
            pass

    _clean_port = 4571
    print("=================================================================", flush=True)
    print("  DEEPSEEK DUAL-PORT PROXY WYSTARTOWAL POMYSLNIE:", flush=True)
    print(f"  [1] http://{_host}:{_port}  -> KODOWANIE & DEV (Trae / Cursor / Cortex Chat)", flush=True)
    print(f"  [2] http://{_host}:{_clean_port}  -> CZYSTY PASSTHROUGH (Useme Core / Boty / Raw)", flush=True)
    print("=================================================================", flush=True)

    if "--single-port" in sys.argv:
        uvicorn.run(app, host=_host, port=_port)
    else:
        import asyncio

        async def _run_dual():
            cfg_main = uvicorn.Config(app, host=_host, port=_port, log_level="warning")
            cfg_clean = uvicorn.Config(app, host=_host, port=_clean_port, log_level="warning")
            srv_main = uvicorn.Server(cfg_main)
            srv_clean = uvicorn.Server(cfg_clean)
            await asyncio.gather(srv_main.serve(), srv_clean.serve())

        try:
            asyncio.run(_run_dual())
        except (KeyboardInterrupt, SystemExit):
            pass
        except OSError as e:
            if "10048" in str(e) or "address already in use" in str(e).lower():
                print("\n" + "=" * 65, flush=True)
                print(f"[BLAD STARTU]: Port {_port} lub {_clean_port} jest juz zajety przez inny proces!", flush=True)
                print("Uruchom 'start_silent.bat' lub 'start.bat', aby automatycznie zwolnic porty.", flush=True)
                print("=" * 65 + "\n", flush=True)
                sys.exit(1)
            raise
