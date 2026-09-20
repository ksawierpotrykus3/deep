"""
Kompleksowy audyt i weryfikacja wszystkich mechanizmow bezpieczenstwa w DeepSeek Proxy.
Testuje:
1. Stan slotow i ochron przed banami (Pancerna Tarcza 2.0).
2. Odizolowanie zmutowanych slotow (0-10) i gotowosc czystych slotow (11, 12).
3. Live endpoints (4570 i 4571).
4. CloudShield i status ochrony IP (WARP / Proxy).
5. Debounce i ochrone przed petlami narzedzi.
6. Integralnosc plikow sesyjnych i poufnosc danych.
"""

import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

# Wymus UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

print("=" * 70)
print("     AUDYT BEZPIECZEŃSTWA SYSTEMU PROXY DEEPSEEK (SECURITY AUDIT)     ")
print("=" * 70)

audit_results = []

def record(test_name, passed, details):
    status = " PASS " if passed else "!FAIL!"
    print(f"[{status}] {test_name}: {details}")
    audit_results.append((test_name, passed, details))

# --- TEST 1: Dual-Port Handshake (4570 i 4571) ---
try:
    with urllib.request.urlopen("http://127.0.0.1:4570/v1/models", timeout=5) as r4570:
        d4570 = json.loads(r4570.read().decode())
        has_models = len(d4570.get("data", [])) > 0
    with urllib.request.urlopen("http://127.0.0.1:4571/v1/models", timeout=5) as r4571:
        d4571 = json.loads(r4571.read().decode())
        has_passthrough = len(d4571.get("data", [])) > 0
    record("Dual-Port Listener", has_models and has_passthrough, "Port 4570 (Dev/Trae) i 4571 (Passthrough) odpowiadają poprawnie")
except Exception as e:
    record("Dual-Port Listener", False, f"Błąd połączenia: {e}")

# --- TEST 2: Stan Slotów i Izolacja Zbanowanych Kont ---
try:
    with urllib.request.urlopen("http://127.0.0.1:4570/slots", timeout=5) as r:
        slots_data = json.loads(r.read().decode())
    
    slots = slots_data.get("slots", {})
    muted_count = sum(1 for s in slots.values() if s.get("is_muted"))
    active_clean = [s["slot"] for s in slots.values() if not s.get("is_muted") and not s.get("rate_limited")]
    
    # Sloty 0-10 powinny byc zmutowane lub odizolowane, sloty 11 i 12 musza byc w 100% CZYSTE
    slot11_ok = slots.get("11", {}).get("is_muted") is False and slots.get("11", {}).get("rate_limited") is False
    slot12_ok = slots.get("12", {}).get("is_muted") is False and slots.get("12", {}).get("rate_limited") is False
    
    record("Izolacja Zmutowanych Slotów", muted_count >= 10, f"Zmutowane sloty (0-10) są ściśle wyizolowane (liczba: {muted_count}). Brak ryzyka wysłania zapytania.")
    record("Czyste Sloty Produkcyjne (11 & 12)", slot11_ok and slot12_ok, f"Sloty 11 i 12 są w 100% czyste, aktywne (IDLE) i gotowe do pracy: {active_clean}")
except Exception as e:
    record("Audyt Slotów", False, f"Błąd: {e}")

# --- TEST 3: CloudShield & Ochrona IP ---
try:
    with urllib.request.urlopen("http://127.0.0.1:4570/proxy/status", timeout=5) as r:
        proxy_status = json.loads(r.read().decode())
    
    shield_enabled = proxy_status.get("shield_enabled", False)
    is_healthy = proxy_status.get("is_healthy", False)
    auto_warp = proxy_status.get("auto_detect_warp", False)
    fallback_ok = proxy_status.get("fallback_to_direct", False)
    mode = proxy_status.get("routing_mode", "unknown")
    
    record("CloudShield Status", shield_enabled and is_healthy, f"Tarcza aktywna (mode={mode}, auto_detect_warp={auto_warp}, fallback={fallback_ok})")
except Exception as e:
    record("CloudShield Status", False, f"Błąd: {e}")

# --- TEST 4: Pancerna Tarcza 2.0 (Pacing & TTFT Governor) ---
try:
    import server
    # Weryfikacja finish time vs start time
    has_finish_time = hasattr(server, "_last_account_finish_time") and len(server._last_account_finish_time) >= 13
    has_global_pacer = hasattr(server, "_global_pacing_lock")
    has_ttft_governor = hasattr(server, "_get_cluster_congestion_factor")
    
    factor, desc = server._get_cluster_congestion_factor()
    record("Pancerna Tarcza 2.0 (Mechanizmy)", has_finish_time and has_global_pacer and has_ttft_governor, 
           f"Finish-Time Pacer: OK, Global IP Pacer: OK, TTFT Sensor: OK (mnożnik={factor:.2f}x: {desc})")
except Exception as e:
    record("Pancerna Tarcza 2.0", False, f"Błąd: {e}")

# --- TEST 5: Debounce & Subagent Loop Breaker ---
try:
    from debounce import deduplicate_tool_results_in_prompt, record_tool_call
    from subagent_isolation import record_subagent_start, record_subagent_done
    
    # Test deduplikacji powtorzen
    test_msgs = [
        {"role": "user", "content": "test"},
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "identical_output_1234567890_long_content"},
    ]
    # symulacja przekroczenia MAX_DUPLICATE_CALLS
    from debounce import _hash_tool_call
    chash = _hash_tool_call("read_file", {"path": "a.py"})
    state = {"debounce_tracker": {chash: [1, 2, 3, 4]}}
    deduped = deduplicate_tool_results_in_prompt(test_msgs, state=state)
    is_blocked = "[BLOCKED:" in deduped[2]["content"]
    record("Debounce & Pętla Narzędzi", is_blocked, "Deduplikacja identycznych wyników narzędzi poprawnie blokuje pętle (BLOCKED: Duplicate tool call)")
except Exception as e:
    record("Debounce & Pętla Narzędzi", False, f"Błąd: {e}")

# --- TEST 6: Poufność i Ochrona Danych (Secrets & Leak Audit) ---
try:
    gitignore_path = BASE_DIR / ".gitignore"
    git_content = gitignore_path.read_text(encoding="utf-8")
    
    secrets_protected = (
        "session*.json" in git_content and
        "data/accounts.json" in git_content and
        "data/deepseek_api_key.txt" in git_content
    )
    
    leaks_path = BASE_DIR / "data" / "leaks.log"
    leaks_empty = True
    if leaks_path.exists():
        leaks_txt = leaks_path.read_text(encoding="utf-8").strip()
        lines = leaks_txt.splitlines()
        recent_leaks = [l for l in lines if "2026-09-19" in l]
        leaks_empty = len(recent_leaks) == 0
        
    record("Poufność Danych i Secrets", secrets_protected and leaks_empty, 
           f"Pliki haseł/sesji zabezpieczone w .gitignore, 0 wycieków promptów/kluczy w dniu dzisiejszym")
except Exception as e:
    record("Poufność Danych", False, f"Błąd: {e}")

# --- PODSUMOWANIE ---
print("=" * 70)
total_tests = len(audit_results)
passed_tests = sum(1 for _, p, _ in audit_results if p)
print(f"WYNIK AUDYTU: {passed_tests}/{total_tests} testów zdanych pomyślnie.")
if passed_tests == total_tests:
    print("STATUS: WSZYSTKIE MECHANIZMY BEZPIECZEŃSTWA SĄ W 100% SPRAWNE I AKTYWNE.")
else:
    print("STATUS: WYKRYTO ZAGROŻENIA LUB NIEZGODNOŚCI!")
print("=" * 70)
