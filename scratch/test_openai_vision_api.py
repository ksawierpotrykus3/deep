import urllib.request
import json
import base64
import time
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://127.0.0.1:8045/v1/chat/completions"

def test_vision_completion():
    image_path = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787146308302.png")
    assert image_path.exists(), f"Image not found at {image_path}"
    
    b64_image = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    data_url = f"data:image/png;base64,{b64_image}"
    
    print("================================================================================")
    print("[*] TEST ENDPOINTA OPENAI VISION / MULTIMODAL Z PLIKIEM I OBRAZEM (BASE64)")
    print("================================================================================")
    
    payload = {
        "model": "gemini-3.7-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Przeanalizuj dołączony zrzut ekranu i odpowiedz w punktach: jakie dwa modele są porównywane, jakie zadania otrzymały i jakie były ich czasy odpowiedzi?"
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
        BASE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    
    print("[STREAM] Odbieranie strumienia tokenów z analizy wizualnej Gemini 3.7 Flash:")
    start_time = time.time()
    res = urllib.request.urlopen(req, timeout=120)
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
    print(f"\n\n[INFO] Zakończono odbiór w {duration:.2f}s | Długość tekstu: {len(full_content)} znaków.")
    assert len(full_content) > 50, "Brak lub za krótka odpowiedź!"
    print("\n[SUKCES] Test endpointa OpenAI Vision z plikiem zakończony w 100% pomyślnie!")

if __name__ == "__main__":
    test_vision_completion()
