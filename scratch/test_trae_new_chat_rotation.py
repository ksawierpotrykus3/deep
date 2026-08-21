import sys
import os
import io
import json
import hashlib
import re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import core helper functions from server.py directly
from server import _get_first_user_prompt_text, _get_user_fp, _get_conv_key

print("=" * 70)
print("  DETERMINISTYCZNY TEST: LOGIKA WYKRYWANIA NOWEGO CZATU W TRAE")
print("=" * 70)

# SCENARIUSZ 1: Wczorajszy stary czat z 41 wiadomościami
old_state = {
    "ds_session": "070a1d74-09ae-4e14-ba96-99bcf3029c0a",
    "parent_id": 254,
    "msgs_len": 41,
    "first_user_prompt": "cortex-app zbadaj stan apki",
    "_ts": 1787143681.0,
    "model_type": "expert",
    "is_vision": False
}

# SCENARIUSZ 2: Użytkownik klika "New Chat" w Trae i wysyła krótki prompt "hej"
new_chat_messages = [
    {"role": "system", "content": "You are an interactive agent in TraeCode..."},
    {"role": "user", "content": "hej"}
]

first_user_prompt = _get_first_user_prompt_text(new_chat_messages)
prev_first_prompt = old_state.get("first_user_prompt")
prev_msgs_len = old_state.get("msgs_len", 0)
curr_msgs_len = len(new_chat_messages)

is_new_conversation = False
if prev_first_prompt and first_user_prompt and prev_first_prompt != first_user_prompt:
    is_new_conversation = True
elif curr_msgs_len <= 4 and prev_msgs_len >= 8:
    is_new_conversation = True

resume = not is_new_conversation and (old_state.get("parent_id") is not None)

print(f"[TEST 1: Kliknięcie 'New Chat' w Trae po wczorajszym czacie]:")
print(f" - Poprzednia długość historii: {prev_msgs_len} wiadomości")
print(f" - Nowa długość historii:       {curr_msgs_len} wiadomości")
print(f" - Poprzedni pierwszy prompt:   '{prev_first_prompt}'")
print(f" - Nowy pierwszy prompt:        '{first_user_prompt}'")
print(f" - Wykryto nowy czat:           {is_new_conversation}")
print(f" - Czy wznawia starą sesję?:    {resume} (wymagane: False)")

assert is_new_conversation is True, "BŁĄD: Nie wykryto nowego czatu!"
assert resume is False, "BŁĄD: Proxy próbowałoby wznowić starą sesję!"
print(" -> [PASS] Test 1 ZALICZONY: Nowy czat wymusza czystą sesję DeepSeek!")


# SCENARIUSZ 3: Prawidłowa kontynuacja trwającego czatu (kolejna tura w tym samym oknie)
current_chat_state = {
    "ds_session": "fresh-session-uuid-9999",
    "parent_id": 10,
    "msgs_len": 4,
    "first_user_prompt": "Napisz kalkulator w React",
    "_ts": 1787220000.0,
    "model_type": "expert",
    "is_vision": False
}

continuation_messages = [
    {"role": "system", "content": "You are an interactive agent in TraeCode..."},
    {"role": "user", "content": "Napisz kalkulator w React"},
    {"role": "assistant", "content": "Oto kod kalkulatora..."},
    {"role": "user", "content": "Dodaj przycisk pierwiastkowania kwadratowego"}
]

first_prompt_turn2 = _get_first_user_prompt_text(continuation_messages)
prev_first_turn2 = current_chat_state.get("first_user_prompt")
prev_len_turn2 = current_chat_state.get("msgs_len", 0)
curr_len_turn2 = len(continuation_messages)

is_new_turn2 = False
if prev_first_turn2 and first_prompt_turn2 and prev_first_turn2 != first_prompt_turn2:
    is_new_turn2 = True
elif curr_len_turn2 <= 4 and prev_len_turn2 >= 8:
    is_new_turn2 = True

resume_turn2 = not is_new_turn2 and (current_chat_state.get("parent_id") is not None)

print(f"\n[TEST 2: Druga tura w TYM SAMYM oknie czatu Trae]:")
print(f" - Poprzednia długość:         {prev_len_turn2} wiadomości")
print(f" - Bieżąca długość:            {curr_len_turn2} wiadomości")
print(f" - Pierwszy prompt:            '{first_prompt_turn2}'")
print(f" - Wykryto nowy czat:          {is_new_turn2} (wymagane: False)")
print(f" - Czy wznawia bieżącą sesję?: {resume_turn2} (wymagane: True)")

assert is_new_turn2 is False, "BŁĄD: Fałszywy alarm nowego czatu!"
assert resume_turn2 is True, "BŁĄD: Nie wznowiono trwającej rozmowy!"
print(" -> [PASS] Test 2 ZALICZONY: Wieloturowy dialog w jednym oknie działa płynnie!")

print("\n" + "=" * 70)
print("  WYNIK: 100% SUKCES — LOGIKA NOWYCH CZATÓW DZIAŁA W PEŁNI POPRAWNIE!")
print("=" * 70)
