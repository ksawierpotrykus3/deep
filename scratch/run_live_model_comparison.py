import urllib.request
import json
import time
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://127.0.0.1:8045/v1/chat/completions"

def run_query(model_name: str, prompt: str, stream: bool = False):
    print(f"\n================================================================================")
    print(f"[*] URUCHAMIANIE TESTU DLA MODELU: {model_name} (stream={stream})")
    print(f"[*] PROMPT: {prompt[:80]}...")
    print(f"================================================================================")
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": stream,
    }
    
    start_time = time.time()
    req = urllib.request.Request(
        BASE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    
    if stream:
        print("[STREAM] Odbieranie tokenów w czasie rzeczywistym:")
        res = urllib.request.urlopen(req, timeout=180)
        full_content = ""
        for line in res:
            line_str = line.decode("utf-8").strip()
            if line_str.startswith("data: ") and line_str != "data: [DONE]":
                try:
                    chunk = json.loads(line_str[6:])
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        sys.stdout.write(delta)
                        sys.stdout.flush()
                        full_content += delta
                except Exception:
                    pass
        duration = time.time() - start_time
        print(f"\n\n[INFO] Zakończono stream w {duration:.2f}s | Długość tekstu: {len(full_content)} znaków.")
        return full_content, duration
    else:
        res = urllib.request.urlopen(req, timeout=180)
        data = json.loads(res.read().decode("utf-8"))
        duration = time.time() - start_time
        content = data["choices"][0]["message"]["content"]
        print(f"[INFO] Otrzymano odpowiedź w {duration:.2f}s:")
        print(content)
        return content, duration


def main():
    print(">>> ROZPOCZYNAM TEST PORÓWNAWCZY DLA GEMINI 3.1 PRO ORAZ GEMINI 3.7 FLASH (MYŚLENIE ROZSZERZONE) <<<")

    # Test 1: Gemini 3.1 Pro (Rozszerzone myślenie)
    prompt_31 = (
        "Rozwiąż zagadkę gry w 24 dla zestawu liczb: 3, 3, 8, 8. "
        "Możesz używać dodawania, odejmowania, mnożenia, dzielenia i nawiasów. "
        "Wyjaśnij szczegółowo krok po kroku drogę myślową (ułamki) i podaj końcowe równanie."
    )
    out_31, time_31 = run_query("gemini-3.1-pro", prompt_31, stream=True)

    # Reset chat for clean context
    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8045/v1/chat/reset", data=b"{}", headers={"Content-Type": "application/json"}))
    time.sleep(2.0)

    # Test 2: Gemini 3.7 Flash (Rozszerzone myślenie)
    prompt_37 = (
        "Napisz kompletną, produkcyjną klasę w Pythonie realizującą strukturę Trie (drzewo prefiksowe) "
        "z funkcją autouzupełniania słów i rankingiem według częstości występowania. "
        "Dołącz typowanie (type hints), docstringi oraz 3 testy jednostkowe z asercjami."
    )
    out_37, time_37 = run_query("gemini-3.7-flash", prompt_37, stream=True)

    # Save to disk
    with open("scratch/gemini_3_1_pro_output.txt", "w", encoding="utf-8") as f:
        f.write(f"=== GEMINI 3.1 PRO (Czas: {time_31:.2f}s) ===\n\nPrompt:\n{prompt_31}\n\nOdpowiedź:\n{out_31}\n")

    with open("scratch/gemini_3_7_flash_output.txt", "w", encoding="utf-8") as f:
        f.write(f"=== GEMINI 3.7 FLASH (Czas: {time_37:.2f}s) ===\n\nPrompt:\n{prompt_37}\n\nOdpowiedź:\n{out_37}\n")

    print("\n\n>>> WSZYSTKIE TESTY ZAKOŃCZONE POMYŚLNIE I ZAPISANE NA DYSKU! <<<")

if __name__ == "__main__":
    main()
