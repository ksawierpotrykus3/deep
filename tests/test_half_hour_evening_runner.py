import time
import random
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
LOG_FILE = BASE_DIR / "data" / "half_hour_proof_log_evening.jsonl"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

LEAK_REGEX = re.compile(r'[|｜\uff5c\u2502\s]*DSML', re.IGNORECASE)

PROMPTS = [
    "Wyjaśnij krótko różnicę między async/await a wątkami (threading) w Pythonie. Podaj 1 mały przykład.",
    "Napisz funkcję w Pythonie sprawdzającą czy podany string jest poprawnym adresem IPv4 bez użycia modułu ipaddress.",
    "Wyjaśnij czym różni się indeks B-tree od indeksu Hash w PostgreSQL i kiedy którego użyć.",
    "Zaimplementuj algorytm wyszukiwania binarnego w Pythonie z obsługą przypadków brzegowych.",
    "Jak działa mechanizm Garbage Collectora w Pythonie (liczniki referencji + generacje)? Podaj zwięzłe podsumowanie.",
    "Napisz krótki kod dekoratora w Pythonie mierzącego czas wykonania funkcji z obsługą argumentów *args i **kwargs.",
    "Czym jest zasada idempotencji w REST API? Podaj przykłady metod HTTP, które są i nie są idempotentne.",
    "Wyjaśnij czym różni się proces od wątku w systemach operacyjnych z perspektywy pamięci wirtualnej.",
    "Napisz w Pythonie funkcję do odwracania kolejności słów w zdaniu bez odwracania samych liter w słowach.",
    "Jak działa mechanizm Copy-on-Write (CoW) przy forkowaniu procesów w Linuksie?",
    "Opisz różnicę między optimistic a pessimistic locking w bazach danych.",
    "Napisz funkcję w Pythonie usuwającą duplikaty z listy z zachowaniem oryginalnej kolejności elementów.",
    "Co to jest Connection Pool i dlaczego nie powinno się otwierać nowego połączenia do bazy przy każdym żądaniu HTTP?",
    "Napisz prosty generator w Pythonie implementujący ciąg Fibonacciego do zadanego N.",
    "Jakie są główne różnice między protokołem TCP a UDP i kiedy warto wybrać UDP zamiast TCP?",
    "Wyjaśnij czym jest problem C10k i jak architektury asynchroniczne (np. epoll/kqueue) go rozwiązały.",
    "Napisz funkcję walidującą czy nawiasy '()', '{}', '[]' w zadanym stringu są poprawnie domknięte (stos).",
    "Co to jest ACID w relacyjnych bazach danych? Krótko opisz każdą z czterech liter.",
    "Jak działa mechanizm WAL (Write-Ahead Logging) w PostgreSQL?",
    "Napisz w Pythonie funkcję spłaszczającą zagnieżdżoną listę dowolnej głębokości (flat list).",
    "Wyjaśnij zasadę działania algorytmu Raft Consensus w systemach rozproszonych.",
    "Jakie są różnice między gRPC a REST w komunikacji mikroserwisów?",
    "Jak działa mechanizm Zero-Copy w systemach Linux (np. funkcja sendfile)?",
    "Czym jest Bloom Filter i w jakich zastosowaniach przewyższa tradycyjne struktury set/hashmap?",
    "Napisz implementację kolejki FIFO opartej o dwa stosy w Pythonie."
]

PROXY_URL = "http://127.0.0.1:4570/v1/chat/completions"
SLOTS_URL = "http://127.0.0.1:4570/slots"


def check_slots_health():
    """Pobiera stan slotów 11 i 12 z proxy i upewnia się, że nie ma bana (is_muted: False)."""
    try:
        with urllib.request.urlopen(SLOTS_URL, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            s11 = data["slots"].get("11", {})
            s12 = data["slots"].get("12", {})
            s11_muted = s11.get("is_muted", False)
            s12_muted = s12.get("is_muted", False)
            return True, s11_muted, s12_muted
    except Exception as e:
        return False, False, False


def run_test(duration_minutes=30):
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)

    print("=" * 75, flush=True)
    print(f"ROZPOCZYNAM WIECZORNY 30-MINUTOWY STRESS TEST (Pancerna Tarcza 2.0)", flush=True)
    print(f"Data startu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S CEST')}", flush=True)
    print(f"Czas trwania: Dokładnie {duration_minutes} minut ({duration_minutes * 60}s)", flush=True)
    print(f"Aktywne sloty produkcyjne: Slot 11 & Slot 12 (rotacja anty-ban)", flush=True)
    print(f"Log wyjściowy: {LOG_FILE}", flush=True)
    print("=" * 75, flush=True)

    with open(LOG_FILE, "w", encoding="utf-8") as lf:
        lf.write(json.dumps({
            "event": "TEST_START",
            "start_time": datetime.now().isoformat(),
            "target_duration_s": duration_minutes * 60,
            "slots": [11, 12],
            "mode": "evening_stress_test"
        }) + "\n")

    req_idx = 0
    success_count = 0
    error_count = 0
    total_leaks = 0
    ban_detected = False
    all_ttfts = []
    all_gen_durations = []

    while time.time() < end_time and not ban_detected:
        req_idx += 1
        current_time_str = datetime.now().strftime("%H:%M:%S")
        prompt = PROMPTS[(req_idx - 1) % len(PROMPTS)]

        elapsed_total = time.time() - start_time
        rem_total = max(0, end_time - time.time())
        print(f"\n[{current_time_str}] Zapytanie #{req_idx:02d} | Czas: {elapsed_total/60:4.1f}m / {duration_minutes}m (pozostało {rem_total/60:4.1f}m)", flush=True)
        print(f"Prompt: {prompt[:80]}...", flush=True)

        payload = {
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": True,
            "temperature": 0.2
        }

        req = urllib.request.Request(
            PROXY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        t0 = time.time()
        first_token_time = None
        content_acc = ""
        reasoning_acc = ""
        status_code = None
        error_msg = None
        leaks_found = []

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                status_code = resp.status
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            c = delta.get("content", "")
                            r = delta.get("reasoning_content", "")
                            if c:
                                if first_token_time is None:
                                    first_token_time = time.time() - t0
                                content_acc += c
                                if LEAK_REGEX.search(c):
                                    leaks_found.append(c)
                            if r:
                                if first_token_time is None:
                                    first_token_time = time.time() - t0
                                reasoning_acc += r
                        except Exception:
                            pass

            gen_duration = time.time() - t0
            ttft_val = first_token_time if first_token_time else 0.0
            all_ttfts.append(ttft_val)
            all_gen_durations.append(gen_duration)

            ttft_str = f"{first_token_time:.2f}s" if first_token_time else "brak"
            leak_str = f" | LEAKS: {len(leaks_found)}" if leaks_found else ""
            print(f"[WYNIK #{req_idx:02d}] Status 200 OK | TTFT: {ttft_str} | Generowanie: {gen_duration:4.1f}s | Reasoning: {len(reasoning_acc)} zn | Treść: {len(content_acc)} zn{leak_str}", flush=True)
            success_count += 1
            total_leaks += len(leaks_found)

        except urllib.error.HTTPError as he:
            gen_duration = time.time() - t0
            status_code = he.code
            err_body = he.read().decode("utf-8", errors="replace")
            error_msg = f"HTTP {he.code}: {err_body[:150]}"
            print(f"[BLAD #{req_idx:02d}] {error_msg}", flush=True)
            error_count += 1
            if he.code in (429, 403, 503) and any(b in err_body.lower() for b in ("muted", "ban", "rate limit", "cooldown")):
                ban_detected = True

        except Exception as e:
            gen_duration = time.time() - t0
            error_msg = f"Exception: {type(e).__name__}: {str(e)}"
            print(f"[BLAD #{req_idx:02d}] {error_msg}", flush=True)
            error_count += 1
            if any(b in str(e).lower() for b in ("muted", "ban")):
                ban_detected = True

        # Weryfikacja stanu slotów w proxy po każdym zapytaniu
        ok, s11_m, s12_m = check_slots_health()
        if ok and (s11_m or s12_m):
            print(f"[ALARM] Wykryto wyciszenie (mute) slotu! S11_muted={s11_m}, S12_muted={s12_m}", flush=True)
            ban_detected = True

        # Zapisz log próby
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "req_index": req_idx,
            "status_code": status_code,
            "ttft_s": round(first_token_time, 2) if first_token_time else None,
            "duration_s": round(gen_duration, 2),
            "reasoning_len": len(reasoning_acc),
            "content_len": len(content_acc),
            "leaks": leaks_found,
            "error": error_msg,
            "ban_detected": ban_detected
        }
        with open(LOG_FILE, "a", encoding="utf-8") as lf:
            lf.write(json.dumps(log_entry) + "\n")

        if ban_detected:
            print("[STOP] Test przerwany z powodu wykrycia ograniczenia lub bana!", flush=True)
            break

        # Adaptacyjny bezpieczny cooldown:
        # Bazowo 20-28s. Jeśli TTFT > 7.0s (obciążenie klastra), dodaj +10s
        base_cooldown = random.uniform(20.0, 28.0)
        if first_token_time and first_token_time > 7.0:
            base_cooldown += 10.0
            print(f"[ADAPTIVE PACER] TTFT ({first_token_time:.2f}s) > 7s -> wydłużam pauzę o +10s", flush=True)

        time_left = end_time - time.time()
        if time_left <= 0:
            break
        cooldown = min(base_cooldown, time_left)
        print(f"[COOLDOWN] Bezpieczna pauza {cooldown:4.1f}s przed kolejnym zapytaniem...", flush=True)
        time.sleep(cooldown)

    actual_elapsed = time.time() - start_time
    avg_ttft = sum(all_ttfts) / len(all_ttfts) if all_ttfts else 0.0
    avg_gen = sum(all_gen_durations) / len(all_gen_durations) if all_gen_durations else 0.0

    print("\n" + "=" * 75, flush=True)
    print(f"PODSUMOWANIE 30-MINUTOWEGO WIECZORNEGO TESTU STABILNOSCI", flush=True)
    print("=" * 75, flush=True)
    print(f"Łączny czas testu: {actual_elapsed/60:4.1f} minut ({actual_elapsed:.0f} sekund)", flush=True)
    print(f"Liczba wykonanych zapytań: {req_idx}", flush=True)
    print(f"Sukcesy: {success_count} / {req_idx} ({(success_count/req_idx*100):.1f}%)" if req_idx else "Sukcesy: 0", flush=True)
    print(f"Błędy HTTP / Timeouty: {error_count}", flush=True)
    print(f"Wycieki DSML w strumieniu: {total_leaks}", flush=True)
    print(f"Średni TTFT: {avg_ttft:.2f}s", flush=True)
    print(f"Średni czas generowania: {avg_gen:.2f}s", flush=True)
    print(f"Bany / Mute: {'TAK (WYKRYTO BAN!)' if ban_detected else 'BRAK (0 BANÓW - TEST ZDANY W 100%!)'}", flush=True)
    print("=" * 75, flush=True)


if __name__ == "__main__":
    run_test(30)
