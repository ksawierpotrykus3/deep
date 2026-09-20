import time
import random
import json
import urllib.request
import urllib.error
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "data" / "clean_benchmark_slot13_log.jsonl"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 25 czystych pytań w języku naturalnym (styl Useme / Magazyn / Developer)
# ZERO znaczników XML, ZERO DSML, ZERO opakowań JSON
PROMPTS = [
    "Przeanalizuj to zlecenie: Potrzebuję skryptu w Pythonie do pobierania kursów walut z NBP i zapisywania do bazy SQLite. Jakie tabele i biblioteki proponujesz?",
    "Wyjaśnij zwięźle czym różni się indeks B-tree od indeksu Hash w PostgreSQL i kiedy którego użyć w systemie magazynowym.",
    "Napisz prostą funkcję w Pythonie, która grupuje listę produktów magazynowych po kategorii i sumuje ich stany.",
    "Jak zaprojektować prosty system powiadomień o nowych zleceniach z Useme, aby nie obciążać zbytnio serwera (polling vs webhook)?",
    "Wyjaśnij różnicę między autoryzacją Bearer tokenem a sesją opartą o ciasteczka HTTP-only. Co lepiej sprawdza się w małym API?",
    "Napisz kod w Pythonie do walidacji numeru NIP z obliczeniem sumy kontrolnej.",
    "Jak działa mechanizm Copy-on-Write (CoW) przy forkowaniu procesów w systemach operacyjnych?",
    "Opisz jak działa algorytm Exponential Backoff i dlaczego jest kluczowy przy ponawianiu zapytań do zewnętrznych serwisów.",
    "Napisz w Pythonie funkcję do bezpiecznego parsowania kwot pieniężnych ze stringów (np. '1 250,50 zł' -> float 1250.50).",
    "Co to jest ACID w relacyjnych bazach danych? Krótko opisz każdą z czterech liter na przykładzie transakcji sprzedaży.",
    "Jak zaimplementować prosty cache w pamięci RAM (TTL cache) w Pythonie za pomocą słownika i modułu time?",
    "Wyjaśnij czym różni się gRPC od tradycyjnego REST API w kontekście komunikacji między mikroserwisami.",
    "Napisz funkcję w Pythonie usuwającą duplikaty słowników z listy na podstawie wybranego klucza (np. id produktu).",
    "Jakie są najlepsze praktyki przechowywania haseł użytkowników (bcrypt/argon2 vs sha256)?",
    "Napisz krótki generator w Pythonie implementujący paginację danych (stronicowanie po N elementów).",
    "Jak działa mechanizm Garbage Collectora w Pythonie (liczniki referencji + generacje)?",
    "Wyjaśnij pojęcie idempotencji w REST API na przykładzie metod PUT i POST w module faktur.",
    "Napisz funkcję w Pythonie sprawdzającą czy podany string jest poprawnym adresem IPv4 bez użycia modułu ipaddress.",
    "Czym jest Connection Pool w SQLAlchemy i dlaczego nie powinno się tworzyć nowego engine przy każdym zapytaniu?",
    "Napisz prosty dekorator w Pythonie logujący czas wykonania funkcji oraz ewentualne wyjątki."
]

PROXY_URL = "http://127.0.0.1:4571/v1/chat/completions"
SLOTS_URL = "http://127.0.0.1:4570/slots"
TARGET_SLOT = 13


def check_target_slot():
    try:
        req = urllib.request.Request(SLOTS_URL)
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            s = data["slots"].get(str(TARGET_SLOT), {})
            return not s.get("is_muted", False), s.get("mute_remaining_s", 0.0), s.get("total_requests", 0)
    except Exception as e:
        return False, 0.0, 0


def run_clean_test(total_requests=20, min_cooldown=32.0, max_cooldown=38.0):
    print("=" * 75, flush=True)
    print(f"ROZPOCZYNAM CZYSTY TEST WERYFIKACYJNY HIPOTEZY (OPCJA B)", flush=True)
    print(f"Konto docelowe: Slot {TARGET_SLOT} (pawel.kowal.kp@gmail.com)", flush=True)
    print(f"Port docelowy: 4571 (CZYSTY PASSTHROUGH - Zero XML, Zero DSML, Zero Injection)", flush=True)
    print(f"Planowana liczba zapytań: {total_requests} zapytań", flush=True)
    print(f"Pacing między zapytaniami: {min_cooldown:.0f}s - {max_cooldown:.0f}s (bezpieczny interwał ludzki)", flush=True)
    print(f"Plik logów: {LOG_FILE}", flush=True)
    print("=" * 75, flush=True)

    alive, mute_s, prev_reqs = check_target_slot()
    if not alive:
        print(f"[BLAD] Slot {TARGET_SLOT} jest aktualnie zmutowany! Pozostało: {mute_s}s", flush=True)
        return

    print(f"[START] Slot {TARGET_SLOT} jest ZDROWY (is_muted=False). Dotychczasowe reqs: {prev_reqs}\n", flush=True)

    start_time = time.time()
    success_count = 0
    error_count = 0
    ban_detected = False

    for idx in range(1, total_requests + 1):
        prompt = PROMPTS[(idx - 1) % len(PROMPTS)]
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] Zapytanie #{idx:02d}/{total_requests:02d} -> Slot {TARGET_SLOT}", flush=True)
        print(f"  Treść: {prompt[:70]}...", flush=True)

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "temperature": 0.3
        }

        req = urllib.request.Request(
            PROXY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-target-slot": str(TARGET_SLOT)
            },
            method="POST"
        )

        t0 = time.time()
        status_code = None
        error_msg = None
        content_len = 0
        thinking_len = 0

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status_code = resp.status
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0].get("message", {})
                content = choice.get("content", "")
                reasoning = choice.get("reasoning_content", "")
                content_len = len(content)
                thinking_len = len(reasoning)

            dur = time.time() - t0
            print(f"  [SUKCES] HTTP 200 OK | Czas: {dur:4.1f}s | Odpowiedź: {content_len} zn | Reasoning: {thinking_len} zn", flush=True)
            success_count += 1

        except urllib.error.HTTPError as he:
            dur = time.time() - t0
            status_code = he.code
            err_body = he.read().decode("utf-8", errors="replace")
            error_msg = f"HTTP {he.code}: {err_body[:120]}"
            print(f"  [BLAD] {error_msg}", flush=True)
            error_count += 1
            if he.code in (401, 403, 429) and any(b in err_body.lower() for b in ("muted", "ban", "rate limit")):
                ban_detected = True
                print("  [ALERT] WYKRYTO MUTE / RATE-LIMIT!", flush=True)

        except Exception as e:
            dur = time.time() - t0
            error_msg = str(e)
            print(f"  [WYJATEK] {error_msg}", flush=True)
            error_count += 1

        # Zapisz do pliku jsonl
        entry = {
            "timestamp": datetime.now().isoformat(),
            "slot": TARGET_SLOT,
            "req_index": idx,
            "status_code": status_code,
            "duration_s": round(dur, 2),
            "content_len": content_len,
            "thinking_len": thinking_len,
            "error": error_msg,
            "ban_detected": ban_detected
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        if ban_detected:
            print("\n[STOP] Przerywam test, wykryto ograniczenie na koncie!", flush=True)
            break

        if idx < total_requests:
            pause = random.uniform(min_cooldown, max_cooldown)
            print(f"  [PAUZA] Odstęp {pause:4.1f}s przed kolejnym zapytaniem...", flush=True)
            time.sleep(pause)

    total_elapsed = time.time() - start_time
    print("\n" + "=" * 75, flush=True)
    print(f"PODSUMOWANIE TESTU CZYSTEGO FORMATU NA SLOCIE {TARGET_SLOT}", flush=True)
    print("=" * 75, flush=True)
    print(f"Łączny czas testu: {total_elapsed/60:4.1f} minut ({total_elapsed:.0f} sekund)", flush=True)
    print(f"Zapytania udane: {success_count} / {total_requests}", flush=True)
    print(f"Błędy: {error_count}", flush=True)

    # Sprawdź stan slotu po teście
    alive_post, mute_s_post, total_reqs_post = check_target_slot()
    print(f"Stan Slotu {TARGET_SLOT} po teście: {'AKTYWNY (BRAK BANA!)' if alive_post else f'ZMUTOWANY (pozostało {mute_s_post}s)'}", flush=True)
    print(f"Łącznie obsłużonych zapytań na tym koncie: {total_reqs_post}", flush=True)
    print("=" * 75, flush=True)


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    run_clean_test(total_requests=count)
