"""Monitor sesji — widoczność i rozróżnienie timeout vs martwy.

Śledzi każde aktywne żądanie (główny agent i subagenci) po session_id.
Zapisuje snapshot do data/sessions_monitor.json co MONITOR_INTERVAL sekund.

Stany:
  active  — serce bije (ostatnia aktywność < DEAD_AFTER)
  slow    — serce bije, ale bez nowych tokenów > SLOW_AFTER (timeout: żyje, wolno)
  dead    — serce stanęło > DEAD_AFTER (martwy: wymaga resetu)

Rozróżnienie timeout vs martwy jest kluczowe:
  - slow = żyje, tylko wolno → czekamy / auto-continue
  - dead = przestał pracować → trzeba zabić i odpalić ponownie
"""
import json
import os
import threading
import time

MONITOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SNAPSHOT_FILE = os.path.join(MONITOR_DIR, "sessions_monitor.json")

MONITOR_INTERVAL = 5.0   # jak często zapisujemy snapshot [s]
SLOW_AFTER = 30.0        # bez tokenu > tyle = slow (timeout)
DEAD_AFTER = 45.0        # bez serca > tyle = dead (martwy)

_lock = threading.Lock()
_sessions: dict[str, dict] = {}
_stop_events: dict[str, threading.Event] = {}
_writer_started = False


def _ensure_dir():
    try:
        os.makedirs(MONITOR_DIR, exist_ok=True)
    except Exception:
        pass


def start(session_id: str, conv_key: str = "", is_subagent: bool = False,
          account_idx: int = -1) -> None:
    """Zarejestruj nowe żądanie."""
    now = time.time()
    with _lock:
        _sessions[session_id] = {
            "session_id": session_id,
            "conv_key": (conv_key or "")[:24],
            "is_subagent": bool(is_subagent),
            "account": int(account_idx),
            "state": "active",
            "started_at": now,
            "last_heartbeat": now,
            "last_token": now,
            "tokens": 0,
            "finished": False,
            "ok": None,
        }
        _stop_events[session_id] = threading.Event()
        _ensure_writer()


def heartbeat(session_id: str) -> None:
    """Serce bije — żądanie żyje."""
    with _lock:
        s = _sessions.get(session_id)
        if s and not s["finished"]:
            s["last_heartbeat"] = time.time()


def token(session_id: str) -> None:
    """Nowy token odpowiedzi — serce bije i postęp jest."""
    now = time.time()
    with _lock:
        s = _sessions.get(session_id)
        if s and not s["finished"]:
            s["last_heartbeat"] = now
            s["last_token"] = now
            s["tokens"] += 1


def finish(session_id: str, ok: bool) -> None:
    """Zamknij żądanie."""
    with _lock:
        s = _sessions.get(session_id)
        if s:
            s["finished"] = True
            s["ok"] = bool(ok)
            s["state"] = "done"
        ev = _stop_events.pop(session_id, None)


def get_stop_event(session_id: str) -> threading.Event | None:
    with _lock:
        return _stop_events.get(session_id)


def request_stop(session_id: str) -> bool:
    """Poproś żądanie, żeby się zatrzymało. Zwraca True, jeśli istniało."""
    with _lock:
        ev = _stop_events.get(session_id)
        if ev is not None:
            ev.set()
            return True
        return False


def _derive_state(s: dict) -> str:
    if s.get("finished"):
        return "done"
    now = time.time()
    # last_heartbeat >0: serce bije stale (heartbeat_tick), last_token to postęp
    if s.get("last_heartbeat") and (now - s["last_heartbeat"]) > DEAD_AFTER:
        return "dead"
    if s.get("last_token") and (now - s["last_token"]) > SLOW_AFTER:
        return "slow"
    return "active"


def get_snapshot() -> list[dict]:
    """Zwróć aktualny stan wszystkich żądań."""
    with _lock:
        out = []
        for sid, s in _sessions.items():
            c = dict(s)
            c["state"] = _derive_state(s)
            c["age"] = round(time.time() - s["started_at"], 1)
            out.append(c)
        # porządek: aktywne najpierw, potem wg wieku
        out.sort(key=lambda x: (x["state"] != "active", -x["started_at"]))
        return out


def _save_snapshot() -> None:
    try:
        _ensure_dir()
        data = {
            "updated_at": time.time(),
            "sessions": get_snapshot(),
        }
        tmp = SNAPSHOT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SNAPSHOT_FILE)
    except Exception:
        pass


def _writer_loop() -> None:
    while True:
        time.sleep(MONITOR_INTERVAL)
        _save_snapshot()


def _ensure_writer() -> None:
    global _writer_started
    if _writer_started:
        return
    _writer_started = True
    t = threading.Thread(target=_writer_loop, daemon=True)
    t.start()


def reset_all() -> None:
    """Wyczyść stan (głównie do testów)."""
    with _lock:
        _sessions.clear()
        _stop_events.clear()