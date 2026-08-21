import sys
import io
import json
import base64
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import urllib.request

img_path = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787152059776.png")
with open(img_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

prompts = [
    ("TEST 1 (Vision OCR)", "Wypisz dosłownie 3 punkty z sekcji 'Plan' na dole zrzutu ekranu."),
    ("TEST 2 (Vision Critique)", "Oceń krótko w 3-4 zdaniach czytelność interfejsu widocznego na zrzucie ekranu."),
    ("TEST 3 (Code Verification)", "Wyjaśnij co robi funkcja compute_hash w Pythonie.")
]

print("=" * 70)
print("  STRESS TEST: 3 KOLEJNE ZAPYTANIA BEZ RESTARTU PROXY")
print("=" * 70)

for idx, (label, text_prompt) in enumerate(prompts, 1):
    print(f"\n--- {label} ---")
    
    content = [{"type": "text", "text": text_prompt}]
    if "Vision" in label:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
        })
        
    payload = {
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": content}],
        "stream": False
    }
    
    req = urllib.request.Request(
        "http://127.0.0.1:8045/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ans = data["choices"][0]["message"]["content"]
            
        print(f"Długość odpowiedzi: {len(ans)} znaków")
        print(f"Podgląd: {ans[:180]}...")
        
        is_refusal = "Nie mogę w tym pomóc" in ans or "jestem modelem językowym" in ans
        is_too_short = len(ans) < 30
        
        if is_refusal:
            print(f"[FAIL] Wykryto odmowę modelu!")
            sys.exit(1)
        elif is_too_short:
            print(f"[FAIL] Odpowiedź zbyt krótka/ucięta!")
            sys.exit(1)
        else:
            print(f"[PASS] Zapytanie {idx} zaliczone!")
            
    except Exception as e:
        print(f"[FAIL] Błąd HTTP: {e}")
        sys.exit(1)

print("\n" + "=" * 70)
print("  WYNIK: 100% STABILNOŚĆ — WSZYSTKIE TESTY ZALICZONE BEZ UCIĘĆ I ODMÓW!")
print("=" * 70)
