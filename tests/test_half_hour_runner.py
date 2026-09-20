import time
import random
import json
import urllib.request
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "half_hour_proof_log.jsonl"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

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
    "Napisz w Pythonie funkcję spłaszczającą zagnieżdżoną listę dowolnej głębokości (flat list)."
]

PROXY_URL = "http://127.0.0.1:4570/v1/chat/completions"

def run_test(duration_minutes=30):
    start_time = time.time()
    end_time = start_time + (duration_minutes * 60)
    
    print("=" * 70, flush=True)
    print(f"ROZPOCZYNAM 30-MINUTOWY TEST STABILNOSCI I BRAKU BANOW (Pancerna Tarcza 2.0)", flush=True)
    print(f"Cel: Generowanie zapytań przez {duration_minutes} minut bez banów, mute ani błędów 429", flush=True)
    print(f"Logi testu: {LOG_FILE}", flush=True)
    print("=" * 70, flush=True)
    
    req_idx = 0
    success_count = 0
    error_count = 0
    ban_detected = False
    
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
        leaks_found = 0
        
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
                            if r:
                                if first_token_time is None:
                                    first_token_time = time.time() - t0
                                reasoning_acc += r
                        except Exception:
                            pass
                            
            gen_duration = time.time() - t0
            ttft_str = f"{first_token_time:.2f}s" if first_token_time else "brak"
            print(f"[WYNIK #{req_idx:02d}] Status 200 OK | TTFT: {ttft_str} | Generowanie: {gen_duration:4.1f}s | Reasoning: {len(reasoning_acc)} zn | Treść: {len(content_acc)} zn", flush=True)
            success_count += 1
            
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

        # Zapisz log próby
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "req_index": req_idx,
            "status_code": status_code,
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
            print("[STOP] Test przerwany z powodu wykrycia bana!", flush=True)
            break

        # Bezpieczny pacing: losowa przerwa 18-26 sekund
        cooldown = random.uniform(18.0, 26.0)
        time_left = end_time - time.time()
        if time_left <= 0:
            break
        cooldown = min(cooldown, time_left)
        print(f"[COOLDOWN] Bezpieczna pauza {cooldown:4.1f}s przed kolejnym zapytaniem...", flush=True)
        time.sleep(cooldown)

    actual_elapsed = time.time() - start_time
    print("\n" + "=" * 70, flush=True)
    print(f"PODSUMOWANIE 30-MINUTOWEGO TESTU", flush=True)
    print("=" * 70, flush=True)
    print(f"Łączny czas testu: {actual_elapsed/60:4.1f} minut ({actual_elapsed:.0f} sekund)", flush=True)
    print(f"Liczba wykonanych zapytań: {req_idx}", flush=True)
    print(f"Sukcesy: {success_count} / {req_idx}", flush=True)
    print(f"Błędy: {error_count}", flush=True)
    print(f"Bany / Mute: {'TAK (WYKRYTO BAN!)' if ban_detected else 'BRAK (0 BANÓW - TEST ZDANY!)'}", flush=True)
    print("=" * 70, flush=True)

if __name__ == "__main__":
    run_test()
