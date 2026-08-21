"""Test jednostkowy monitor.py — rozróżnienie active / slow / dead oraz request_stop.

Bez czekania 30-45 s: manipulujemy last_heartbeat/last_token bezpośrednio,
żeby deterministycznie wymusić poszczególne stany.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import monitor

monitor.reset_all()


def state_of(sid):
    snap = monitor.get_snapshot()
    for s in snap:
        if s["session_id"] == sid:
            return s["state"]
    return None


def set_times(sid, hb_age, tok_age):
    with monitor._lock:
        s = monitor._sessions[sid]
        now = time.time()
        s["last_heartbeat"] = now - hb_age
        s["last_token"] = now - tok_age


# 1) aktywny
monitor.start("s1", conv_key="ck1", is_subagent=False, account_idx=0)
assert state_of("s1") == "active", f"expected active, got {state_of('s1')}"

# 2) slow: serce bije (hb 10s temu), token stoi (35s temu)
set_times("s1", hb_age=10, tok_age=35)
assert state_of("s1") == "slow", f"expected slow, got {state_of('s1')}"

# 3) dead: serce stanęło (46s temu)
set_times("s1", hb_age=46, tok_age=46)
assert state_of("s1") == "dead", f"expected dead, got {state_of('s1')}"

# 4) request_stop ustawia event i zwraca True
ev = monitor.get_stop_event("s1")
assert ev is not None and not ev.is_set(), "event nie istnieje lub już ustawiony"
assert monitor.request_stop("s1") is True
assert ev.is_set(), "event nie został ustawiony przez request_stop"

# 5) finish zamyka i czyści event
monitor.finish("s1", ok=True)
assert state_of("s1") == "done", f"expected done, got {state_of('s1')}"
assert monitor.get_stop_event("s1") is None, "event nie został usunięty po finish"

print("=" * 60)
print("TEST MONITORA — ROZRÓŻNIENIE STANÓW I STOP")
print("=" * 60)
print("active -> OK")
print("slow   -> OK (żyje, ale wolno = timeout)")
print("dead   -> OK (serce stanęło = martwy)")
print("request_stop -> OK (event ustawiony)")
print("finish -> OK (event wyczyszczony)")
print("-" * 60)
print("WYNIK: WSZYSTKIE ASERCJE PRZESZŁY — monitor rozróżnia stany i wspiera stop")
print("=" * 60)