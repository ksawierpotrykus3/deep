import urllib.request
import json
import base64
import time
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://127.0.0.1:8045/v1"

def test_clean_vision():
    # 1. Reset conversation to ensure fresh context
    print("[1] Resetowanie sesji czatu...")
    urllib.request.urlopen(urllib.request.Request(f"{BASE_URL}/chat/reset", data=b"{}", headers={"Content-Type": "application/json"}))
    time.sleep(1.5)
    
    # 2. Prepare image
    image_path = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787146308302.png")
    b64_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    data_url = f"data:image/png;base64,{b64_image}"
    
    print("[2] Wysyłanie zapytania OpenAI Vision z obrazem...")
    payload = {
        "model": "gemini-3.7-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Odczytaj dokładnie cały tekst ze zrzutu ekranu i podaj punkt 1 oraz punkt 2."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url
                        }
                    }
                ]
            }
        ],
        "stream": True,
    }
    
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    
    res = urllib.request.urlopen(req, timeout=120)
    full_content = ""
    print("[3] Odbieranie tokenów:")
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
                
    print("\n\n[WERYFIKACJA TREŚCI]:")
    print(f"Zawiera 'Gemini 3.1 Pro': {'Gemini 3.1 Pro' in full_content or '3.1 Pro' in full_content}")
    print(f"Zawiera 'Gemini 3.7 Flash': {'Gemini 3.7 Flash' in full_content or '3.7 Flash' in full_content}")
    print(f"Zawiera 'Gra w 24': {'Gra w 24' in full_content or '24' in full_content}")

if __name__ == "__main__":
    test_clean_vision()
