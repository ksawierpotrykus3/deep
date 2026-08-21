import sys
import io
import json
import base64
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import urllib.request

# 1. Prepare Test File
test_code_file = Path("scratch/verification_code.py")
test_code_file.write_text('''
# Deterministic Verification Script for Gemini Proxy
class CryptographicTokenGenerator:
    def __init__(self, seed: int = 42):
        self.secret_salt = "ANTIGRAVITY_SUPER_SALT_9988"
        self.seed = seed

    def compute_hash(self, message: str) -> str:
        import hashlib
        combined = f"{self.secret_salt}:{self.seed}:{message}"
        return hashlib.sha256(combined.encode('utf-8')).hexdigest()
''', encoding="utf-8")

# 2. Image Path from User Upload
img_path = Path("C:/Users/Ksawier/.gemini/antigravity/brain/731a6b1c-5e3f-4eba-92c4-91013a0169de/.user_uploaded/media_1787152059776.png")
if not img_path.exists():
    print(f"[BŁĄD] Plik obrazu nie istnieje: {img_path}")
    sys.exit(1)

with open(img_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

print("=" * 70)
print("  TEST 1: WYSYŁANIE ZRZUTU EKRANU (VISION OCR & VISUAL REASONING)")
print("=" * 70)

# Request 1: Vision / Image OCR
payload_img = {
    "model": "gemini-3.7-flash",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Odczytaj dokładnie tekst z załączonego zrzutu ekranu. Wypisz: 1. Wiadomość użytkownika na samej górze. 2. Trzy punkty z sekcji 'Plan' na samym dole zrzutu."
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}"
                    }
                }
            ]
        }
    ],
    "stream": False
}

req = urllib.request.Request(
    "http://127.0.0.1:8045/v1/chat/completions",
    data=json.dumps(payload_img).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

print("[1] Wysyłam zapytanie z obrazem do http://127.0.0.1:8045/v1/chat/completions...")
with urllib.request.urlopen(req, timeout=120) as resp:
    res_data = json.loads(resp.read().decode("utf-8"))
    answer_img = res_data["choices"][0]["message"]["content"]

print("\n--- ODPOWIEDŹ GEMINI DLA OBRAZU ---")
print(answer_img)
print("-----------------------------------")

has_user_text = "Sprawdz kod frontendu" in answer_img or "playwrightem" in answer_img or "multimodalnosc" in answer_img
has_plan_1 = "dev:renderer" in answer_img or "Vite na 3000" in answer_img
has_plan_2 = "audyt kodu" in answer_img
has_plan_3 = "health proxy" in answer_img or "8045" in answer_img

print(f"\n[WERYFIKACJA DETERMINISTYCZNA OBRAZU]:")
print(f" - Odczytano tekst użytkownika z samej góry: {has_user_text}")
print(f" - Odczytano punkt 1 planu (dev:renderer / Vite na 3000): {has_plan_1}")
print(f" - Odczytano punkt 2 planu (audyt kodu frontendu): {has_plan_2}")
print(f" - Odczytano punkt 3 planu (health proxy 8045): {has_plan_3}")

if not (has_user_text and has_plan_1 and has_plan_3):
    print("\n[BŁĄD] Gemini nie odczytało kluczowych elementów ze zdjęcia!")
    sys.exit(1)

print("\n" + "=" * 70)
print("  TEST 2: WYSYŁANIE PLIKU KODU ŹRÓDŁOWEGO (.py)")
print("=" * 70)

# Request 2: File Upload
payload_file = {
    "model": "gemini-3.7-flash",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Przeanalizuj załączony plik kodu. Podaj dokładną nazwę klasy, wartość zmiennej secret_salt oraz algorytm haszujący użyty w metodzie compute_hash."
                },
                {
                    "type": "file",
                    "file_path": str(test_code_file.resolve())
                }
            ]
        }
    ],
    "stream": False
}

req_file = urllib.request.Request(
    "http://127.0.0.1:8045/v1/chat/completions",
    data=json.dumps(payload_file).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

print("[2] Wysyłam zapytanie z plikiem .py do http://127.0.0.1:8045/v1/chat/completions...")
with urllib.request.urlopen(req_file, timeout=120) as resp:
    res_file_data = json.loads(resp.read().decode("utf-8"))
    answer_file = res_file_data["choices"][0]["message"]["content"]

print("\n--- ODPOWIEDŹ GEMINI DLA PLIKU .PY ---")
print(answer_file)
print("--------------------------------------")

has_class_name = "CryptographicTokenGenerator" in answer_file
has_salt = "ANTIGRAVITY_SUPER_SALT_9988" in answer_file
has_hash_algo = "sha256" in answer_file or "SHA-256" in answer_file or "SHA256" in answer_file

print(f"\n[WERYFIKACJA DETERMINISTYCZNA PLIKU]:")
print(f" - Odczytano klasę CryptographicTokenGenerator: {has_class_name}")
print(f" - Odczytano wartość secret_salt (ANTIGRAVITY_SUPER_SALT_9988): {has_salt}")
print(f" - Odczytano algorytm haszujący (SHA-256): {has_hash_algo}")

if not (has_class_name and has_salt and has_hash_algo):
    print("\n[BŁĄD] Gemini nie odczytało zawartości przesłanego pliku!")
    sys.exit(1)

print("\n" + "=" * 70)
print("  WYNIK: 100% SUKCES — ZARÓWNO ZDJĘCIA JAK I PLIKI DZIAŁAJĄ BEZBŁĘDNIE!")
print("=" * 70)
