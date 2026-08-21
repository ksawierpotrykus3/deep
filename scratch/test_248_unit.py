"""Testy jednostkowe dla #2 (bramka równoległości), #3 (auto-kill sweepera), #8 (strip cl_calls)."""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import monitor
import server

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"[PASS] {name} {detail}")
    else:
        print(f"[FAIL] {name} {detail}")
        failures.append(name)


# ───────────────────────── #8: cl_calls w _STRIP_TAGS ─────────────────────────
def test_strip_cl_calls():
    samples = [
        "<cl_calls>",
        "</cl_calls>",
        "<|cl_calls|>",
        "</|cl_calls|>",
        "<CL_CALLS>",
        "text<cl_calls>x</cl_calls>after",
    ]
    for s in samples:
        cleaned = server._STRIP_TAGS.sub("", s)
        check(f"#8 strip {s!r}", "cl_calls" not in cleaned.lower(), f"-> {cleaned!r}")
    t = "hello world"
    check("#8 zwykly tekst nietknietny", server._STRIP_TAGS.sub("", t) == t, f"-> {server._STRIP_TAGS.sub('', t)!r}")


# ───────────────────────── #2: bramka równoległości ─────────────────────────
def test_gate():
    old_gate = server._parallel_gate
    old_impl = server._chat_completions_impl
    server._parallel_gate = threading.BoundedSemaphore(2)
    inside = []
    lock = threading.Lock()
    release_ev = threading.Event()

    def fake_impl(req, raw):
        with lock:
            inside.append(threading.get_ident())
        release_ev.wait(timeout=5)
        with lock:
            inside.remove(threading.get_ident())
        return "ok"

    server._chat_completions_impl = fake_impl

    class FakeReq:
        model = "x"

    class FakeRaw:
        pass

    results = []

    def run():
        results.append(server.chat_completions(FakeReq(), FakeRaw()))

    t1 = threading.Thread(target=run)
    t2 = threading.Thread(target=run)
    t1.start()
    t2.start()
    # czekaj aż oba wejdą do impl
    for _ in range(100):
        if len(inside) == 2:
            break
        time.sleep(0.02)
    check("#2 limit: max 2 w srodku", len(inside) == 2, f"(w srodku {len(inside)})")

    t3 = threading.Thread(target=run)
    t3.start()
    time.sleep(0.3)
    check("#2 trzeci czeka na bramce", len(inside) == 2, f"(w srodku {len(inside)})")

    release_ev.set()  # zwolnij t1/t2 -> t3 wchodzi
    t1.join(timeout=5)
    t2.join(timeout=5)
    t3.join(timeout=5)
    check("#2 po zwolnieniu wpuszcza", len(inside) == 0, f"(w srodku {len(inside)})")
    check("#2 zwraca wynik impl", results == ["ok", "ok", "ok"], str(results))
    server._parallel_gate = old_gate
    server._chat_completions_impl = old_impl


# ───────────────────────── #3: sweep / hard stop / clear ─────────────────────────
def test_sweep():
    monitor.reset_all()

    # slow za długo: serce żyje, token stary
    monitor.start("s1")
    monitor.token("s1")
    with monitor._lock:
        monitor._sessions["s1"]["last_token"] = time.time() - 100
        monitor._sessions["s1"]["last_heartbeat"] = time.time() - 5
    killed = monitor.sweep()
    check("#3 slow->kill", "s1" in killed, f"(killed={killed})")
    check("#3 stop event ustawiony", monitor.get_stop_event("s1").is_set())
    check("#3 to NIE hard stop", not monitor.is_hard_stop("s1"))
    check("#3 idempotentny", monitor.sweep() == [], "(drugi sweep nic nie zabija)")

    # dead: serce stanęło
    monitor.start("s2")
    with monitor._lock:
        monitor._sessions["s2"]["last_heartbeat"] = time.time() - 100
        monitor._sessions["s2"]["last_token"] = time.time() - 100
    killed2 = monitor.sweep()
    check("#3 dead->kill", "s2" in killed2, f"(killed={killed2})")

    # świeża sesja NIE zabijana
    monitor.start("s3")
    check("#3 aktywna nie zabijana", "s3" not in monitor.sweep(), f"(killed={monitor.sweep()})")

    # zakończona nie zabijana
    monitor.finish("s1", ok=True)
    with monitor._lock:
        monitor._sessions["s1"]["last_heartbeat"] = time.time() - 100
    check("#3 finished nie zabijana", "s1" not in monitor.sweep())

    # clear_stop resetuje event i hard
    monitor.request_stop("s3", hard=True)
    check("#3 hard stop flag", monitor.is_hard_stop("s3"))
    monitor.clear_stop("s3")
    check("#3 clear_stop resetuje event", not monitor.get_stop_event("s3").is_set())
    check("#3 clear_stop resetuje hard", not monitor.is_hard_stop("s3"))

    monitor.reset_all()


test_strip_cl_calls()
test_gate()
test_sweep()

print("=" * 60)
if failures:
    print(f"WYNIK: {len(failures)} BLEDOW -> {failures}")
    raise SystemExit(1)
print("WYNIK: WSZYSTKIE ASERCJE #2/#3/#8 PRZESZLY")
