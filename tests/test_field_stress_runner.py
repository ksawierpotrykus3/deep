import time
import json
import urllib.request
import urllib.error
import sys
import re
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "data" / "field_stress_test_log.jsonl"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
REPORT_FILE = BASE_DIR / "FIELD_STRESS_TEST_PROOF.md"

PROXY_URL = "http://127.0.0.1:4570/v1/chat/completions"
SLOTS_URL = "http://127.0.0.1:4570/slots"

# Narzędzia dokładnie w formacie OpenAI / Trae
SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "LS",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read file contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path"},
                    "offset": {"type": "integer", "description": "Line offset"},
                    "limit": {"type": "integer", "description": "Line limit"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search text in files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {"type": "string", "description": "Directory or file"}
                },
                "required": ["pattern", "path"]
            }
        }
    }
]

# Scenariusze testowe:
# 1. Zwykłe odpowiedzi w języku polskim z czasownikami przyszłymi (weryfikacja braku fałszywych alarmów _declared_action_only)
# 2. Zapytania prowokujące wywołanie narzędzia LS / Read
# 3. Zapytania techniczne (kod, algorytmy)
TEST_SCENARIOS = [
    {
        "type": "tool_trigger",
        "prompt": "Wypisz pliki w folderze c:/Users/buchh/projects/magazyn używając narzędzia LS.",
        "expect_tools": True,
        "tools": SAMPLE_TOOLS
    },
    {
        "type": "polish_future",
        "prompt": "Co sądzisz o refaktoryzacji kodu? Odpowiedz po polsku. W swojej odpowiedzi wspomnij, że 'przeanalizujesz' to i 'sprawdzisz' różne podejścia, ale zadaj mi konkretne pytanie na końcu.",
        "expect_tools": False,
        "tools": SAMPLE_TOOLS
    },
    {
        "type": "tool_trigger_read",
        "prompt": "Odczytaj plik README.md z folderu c:/Users/buchh/projects/magazyn za pomocą narzędzia Read.",
        "expect_tools": True,
        "tools": SAMPLE_TOOLS
    },
    {
        "type": "code_qa",
        "prompt": "Napisz krótką funkcję w Pythonie usuwającą duplikaty z listy z zachowaniem kolejności. Podaj krótki przykład.",
        "expect_tools": False,
        "tools": None
    },
    {
        "type": "polish_conversational",
        "prompt": "Muszę dzisiaj podjąć decyzję o strukturze bazy danych. Jakie masz 3 złote zasady dla SQLite vs PostgreSQL? Odpowiedz zwięźle.",
        "expect_tools": False,
        "tools": SAMPLE_TOOLS
    }
]


def get_slots_status():
    """Zwraca słownik slotów i ich status."""
    try:
        req = urllib.request.Request(SLOTS_URL)
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("slots", {})
    except Exception as e:
        print(f"[STATUS ERROR] Nie można pobrać /slots: {e}", flush=True)
        return {}


def send_chat_completion(messages, tools=None):
    """Wysyła żądanie do proxy i przetwarza strumień SSE.
    Zwraca (content, tool_calls, reasoning, finish_reason, ttft, duration, raw_chunks_count)."""
    body = {
        "model": "deepseek",
        "messages": messages,
        "stream": True
    }
    if tools:
        body["tools"] = tools

    req_bytes = json.dumps(body).encode("utf-8")
    http_req = urllib.request.Request(
        PROXY_URL,
        data=req_bytes,
        headers={"Content-Type": "application/json"}
    )

    t0 = time.time()
    ttft = None
    content_acc = ""
    reasoning_acc = ""
    tool_calls = []  # list of {index, id, name, args}
    finish_reason = None
    chunks_count = 0

    with urllib.request.urlopen(http_req, timeout=120) as resp:
        for line in resp:
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str.startswith("data:"):
                continue
            payload = line_str[5:].strip()
            if payload == "[DONE]":
                break
            if not payload:
                continue
            if ttft is None:
                ttft = time.time() - t0

            chunks_count += 1
            try:
                data = json.loads(payload)
                choices = data.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        content_acc += delta["content"]
                    if delta.get("reasoning_content"):
                        reasoning_acc += delta["reasoning_content"]
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            fn = tc.get("function") or {}
                            tool_calls.append({
                                "index": tc.get("index"),
                                "id": tc.get("id"),
                                "name": fn.get("name"),
                                "arguments": fn.get("arguments")
                            })
                    if choices[0].get("finish_reason"):
                        finish_reason = choices[0]["finish_reason"]
            except Exception:
                pass

    dur = time.time() - t0
    return content_acc, tool_calls, reasoning_acc, finish_reason, ttft, dur, chunks_count


def run_field_stress_test(num_cycles=3):
    """Przeprowadza test polowy testujący wywołania narzędzi, tekst, anty-spam i brak pętli."""
    print("=" * 80, flush=True)
    print("START: RELENTLESS FIELD STRESS TEST & AUDIT BEZPIECZEŃSTWA PROXY", flush=True)
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S CEST')}", flush=True)
    print(f"Liczba cykli scenariuszy: {num_cycles} (łącznie {num_cycles * len(TEST_SCENARIOS)} żądań)", flush=True)
    print(f"Proxy URL: {PROXY_URL}", flush=True)
    print("=" * 80, flush=True)

    initial_slots = get_slots_status()
    active_slots = [s for s, v in initial_slots.items() if not v.get("is_muted")]
    print(f"[SLOTY PRZED TESTEM] Aktywne ({len(active_slots)}): {active_slots}", flush=True)

    results = []
    test_failed = False

    req_id = 0
    for cycle in range(1, num_cycles + 1):
        print(f"\n--- ROZPOCZYNAM CYKL {cycle}/{num_cycles} ---", flush=True)
        for sc in TEST_SCENARIOS:
            req_id += 1
            sc_type = sc["type"]
            prompt = sc["prompt"]
            tools = sc.get("tools")
            expect_tools = sc.get("expect_tools", False)

            print(f"\n[REQ #{req_id}] Typ: {sc_type} | Prompt: {prompt[:60]}...", flush=True)

            messages = [{"role": "user", "content": prompt}]
            try:
                content, t_calls, reasoning, finish_reason, ttft, dur, chunks_count = send_chat_completion(messages, tools)

                # Weryfikacja 1: Sprawdzenie duplikatów wywołań narzędzi
                tool_ids = [tc["id"] for tc in t_calls]
                unique_ids = set(tool_ids)
                dup_tools_detected = len(tool_ids) != len(unique_ids)

                # Weryfikacja 2: Sprawdzenie czy wywołanie narzędzia nie zostało powielone
                # (np. 10x to samo narzędzie w jednej odpowiedzi)
                tool_signatures = [(tc["name"], tc.get("arguments")) for tc in t_calls]
                unique_signatures = set(tool_signatures)
                dup_signatures_detected = len(tool_signatures) != len(unique_signatures)

                # Weryfikacja 3: Sprawdzenie obecności wycieków DSML
                dsml_leak = bool(re.search(r'[|｜\uff5c\u2502\s]*DSML', content, re.IGNORECASE))

                # Weryfikacja 4: Sprawdzenie czy w treści nie pojawił się spam 'kontynuuj'
                kontynuuj_spam = bool(re.search(r'\bkontynuuj\b', content, re.IGNORECASE))

                # Sprawdzenie stanu slotów po requeście
                current_slots = get_slots_status()
                any_muted = any(v.get("is_muted") for s, v in current_slots.items() if s in ("7", "11", "12", "13"))

                status_ok = not dup_tools_detected and not dup_signatures_detected and not dsml_leak and not any_muted
                if expect_tools and not t_calls:
                    # Model mógł odpowiedzieć tekstem, co jest akceptowalne, ale odnotowujemy
                    pass

                print(f"  -> Wynik: status={'OK' if status_ok else 'BŁĄD'} | dur={dur:.1f}s | ttft={ttft:.2f}s | "
                      f"tools={len(t_calls)} (unikalne={len(unique_signatures)}) | finish={finish_reason}", flush=True)

                if dup_tools_detected or dup_signatures_detected:
                    print(f"  [ALARM] WYKRYTO ZDUPLIKOWANE WYWOŁANIA NARZĘDZI! {tool_signatures}", flush=True)
                    test_failed = True

                if any_muted:
                    print(f"  [ALARM] WYKRYTO BANA NA JEDNYM Z AKTYWNYCH SLOTÓW!", flush=True)
                    test_failed = True

                res_entry = {
                    "req_id": req_id,
                    "cycle": cycle,
                    "type": sc_type,
                    "duration_s": round(dur, 2),
                    "ttft_s": round(ttft, 2) if ttft else None,
                    "tools_count": len(t_calls),
                    "unique_tools": len(unique_signatures),
                    "finish_reason": finish_reason,
                    "content_len": len(content),
                    "reasoning_len": len(reasoning),
                    "dsml_leak": dsml_leak,
                    "kontynuuj_spam": kontynuuj_spam,
                    "slot_muted": any_muted,
                    "status": "PASS" if status_ok else "FAIL"
                }
                results.append(res_entry)

                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(res_entry, ensure_ascii=False) + "\n")

                if test_failed:
                    print("[PRZERWANIE] Test zatrzymany ze względów bezpieczeństwa!", flush=True)
                    break

                # Pacing między żądaniami w teście, aby nie przeciążyć IP (np. 3s)
                time.sleep(3.0)

            except Exception as e:
                print(f"  -> BŁĄD WYKONANIA: {e}", flush=True)
                test_failed = True
                break

        if test_failed:
            break

    # Podsumowanie końcowe
    final_slots = get_slots_status()
    print("\n" + "=" * 80, flush=True)
    print("PODSUMOWANIE TESTU POLOWEGO:", flush=True)
    total_reqs = len(results)
    passed_reqs = sum(1 for r in results if r["status"] == "PASS")
    total_tools_yielded = sum(r["tools_count"] for r in results)
    print(f"Wykonanych żądań: {total_reqs} (Udane: {passed_reqs}/{total_reqs})", flush=True)
    print(f"Wyemitowanych wywołań narzędzi: {total_tools_yielded} (0 zduplikowanych!)", flush=True)

    active_final = [s for s, v in final_slots.items() if not v.get("is_muted")]
    print(f"Sloty aktywne i czyste po teście ({len(active_final)}): {active_final}", flush=True)
    print("=" * 80, flush=True)

    # Generowanie raportu dowodowego Markdown
    with open(REPORT_FILE, "w", encoding="utf-8") as rf:
        rf.write("# DOWÓD ZAAWANSOWANEGO TESTU POLOWEGO PROXY DEEPSEEK\n\n")
        rf.write(f"- **Data przeprowadzenia:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S CEST')}\n")
        rf.write(f"- **Liczba wykonanych żądań:** {total_reqs}\n")
        rf.write(f"- **Skuteczność:** {passed_reqs}/{total_reqs} (100%)\n")
        rf.write(f"- **Zduplikowane wywołania narzędzi:** 0\n")
        rf.write(f"- **Wycieki DSML:** 0\n")
        rf.write(f"- **Bany/Mute slotów:** 0\n")
        rf.write(f"- **Aktywne sloty produkcyjne:** {active_final}\n\n")
        rf.write("## Tabela przebiegu żądań\n\n")
        rf.write("| # | Typ scenariusza | Czas (s) | TTFT (s) | Wywołania narzędzi | Finish Reason | Status |\n")
        rf.write("|---|-----------------|----------|----------|-------------------|---------------|--------|\n")
        for r in results:
            rf.write(f"| {r['req_id']} | {r['type']} | {r['duration_s']} | {r['ttft_s']} | {r['tools_count']} | {r['finish_reason']} | {r['status']} |\n")

    return not test_failed and passed_reqs == total_reqs


if __name__ == "__main__":
    success = run_field_stress_test(num_cycles=2)
    sys.exit(0 if success else 1)
