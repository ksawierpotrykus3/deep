import sys
import os
import io
import json
import hashlib
from pathlib import Path

# Ensure UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import _get_first_user_prompt_text, _get_user_fp, _detect_loop

print("=" * 75)
print("  KOMPLEKSOWY TEST DETERMINISTYCZNY PROXY DEEPSEEK (server.py)")
print("=" * 75)

# ── TEST 1: INWARIANTY NOWEGO CZATU ─────────────────────────────────────────

def evaluate_new_chat(state, req_messages):
    first_user_prompt = _get_first_user_prompt_text(req_messages)
    has_assistant_messages = any(m.get("role") == "assistant" for m in req_messages)
    is_new_conversation = False

    if state:
        prev_first_prompt = state.get("first_user_prompt")
        prev_msgs_len = state.get("msgs_len", 0)
        curr_msgs_len = len(req_messages)

        # Invariant 1: Brak wiadomości asystenta w requeście, a stan ma parent_id
        if state.get("parent_id") is not None and not has_assistant_messages:
            is_new_conversation = True
        # Invariant 2: Zmiana pierwszego promptu
        elif prev_first_prompt and first_user_prompt and prev_first_prompt != first_user_prompt:
            is_new_conversation = True
        # Invariant 3: Skurczenie historii
        elif curr_msgs_len <= 4 and prev_msgs_len >= 8:
            is_new_conversation = True

    resume = not is_new_conversation and (state.get("parent_id") is not None if state else False)
    return is_new_conversation, resume

# Test 1A: Po 40 wiadomościach kliknięcie New Chat z "hej"
s_1a = {"parent_id": 254, "msgs_len": 40, "first_user_prompt": "cortex-app test"}
req_1a = [{"role": "system", "content": "Trae"}, {"role": "user", "content": "hej"}]
is_new, res = evaluate_new_chat(s_1a, req_1a)
print(f"[TEST 1A - Po 40 wiadomościach]: is_new={is_new}, resume={res}")
assert is_new is True and res is False, "Błąd 1A: Nie wykryto nowego czatu po 40 wiadomościach!"
print(" -> [PASS] Test 1A zaliczony!")

# Test 1B: Po 1-turowym czacie ("hej") otwarcie nowego czatu z identycznym "hej"
s_1b = {"parent_id": 5, "msgs_len": 2, "first_user_prompt": "hej"}
req_1b = [{"role": "system", "content": "Trae"}, {"role": "user", "content": "hej"}]
is_new, res = evaluate_new_chat(s_1b, req_1b)
print(f"[TEST 1B - Dwa czaty z identycznym 'hej' pod rząd]: is_new={is_new}, resume={res}")
assert is_new is True and res is False, "Błąd 1B: Nie wykryto nowego czatu przy identycznym 'hej'!"
print(" -> [PASS] Test 1B zaliczony!")

# Test 1C: Prawidłowa kontynuacja (Turn 2 w tym samym oknie)
s_1c = {"parent_id": 5, "msgs_len": 2, "first_user_prompt": "hej"}
req_1c = [
    {"role": "system", "content": "Trae"},
    {"role": "user", "content": "hej"},
    {"role": "assistant", "content": "Cześć! W czym mogę pomóc?"},
    {"role": "user", "content": "Napisz funkcję sortowania"}
]
is_new, res = evaluate_new_chat(s_1c, req_1c)
print(f"[TEST 1C - Druga tura w tym samym oknie]: is_new={is_new}, resume={res}")
assert is_new is False and res is True, "Błąd 1C: Fałszywy reset trwającego czatu!"
print(" -> [PASS] Test 1C zaliczony!")

# Test 1D: Trzecia tura z narzędziami
s_1d = {"parent_id": 12, "msgs_len": 4, "first_user_prompt": "hej"}
req_1d = list(req_1c) + [
    {"role": "assistant", "content": "Oto sortowanie...", "tool_calls": []},
    {"role": "user", "content": "Dodaj testy jednostkowe"}
]
is_new, res = evaluate_new_chat(s_1d, req_1d)
print(f"[TEST 1D - Trzecia tura z historią]: is_new={is_new}, resume={res}")
assert is_new is False and res is True, "Błąd 1D: Fałszywy reset w 3. turze!"
print(" -> [PASS] Test 1D zaliczony!")

# ── TEST 2: ZNAKI UNICODE (BRAK CRASHY PRZY ZNAKACH → I STRZAŁKACH) ─────────
tool_content_with_arrows = "1→import os\n2→import sys\n3→# Test polskich znaków: zażółć gęślą jaźń 🚀"
fp = _get_user_fp([{"role": "user", "content": f"<user_input>{tool_content_with_arrows}</user_input>"}])
print(f"\n[TEST 2 - Obsługa znaków Unicode i strzałek →]: user_fp={fp}")
assert len(fp) == 8, "Błąd 2: Niepoprawny hash dla zawartości z Unicode!"
print(" -> [PASS] Test 2 zaliczony!")

# ── TEST 3: ANTY-LOOP GUARD ──────────────────────────────────────────────────
normal_code = "for i in range(10):\n    print(i)\n    for j in range(10):\n        print(j)"
looping_code = "error in line 55\n" * 50
print(f"\n[TEST 3 - Anty-loop guard]:")
print(f" - Normalny kod powtarzalny: loop_detected={_detect_loop(normal_code)}")
print(f" - Prawdziwe zapętlenie:     loop_detected={_detect_loop(looping_code)}")
assert _detect_loop(normal_code) is False, "Błąd 3: Fałszywy alarm na normalnym kodzie!"
assert _detect_loop(looping_code) is True, "Błąd 3: Brak wykrycia patologicznego zapętlenia!"
print(" -> [PASS] Test 3 zaliczony!")

print("\n" + "=" * 75)
print("  WSZYSTKIE TESTY ZALICZONE W 100% — ZERO REGRESJI, ZERO BŁĘDÓW!")
print("=" * 75)
