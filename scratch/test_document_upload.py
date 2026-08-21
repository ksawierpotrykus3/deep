import urllib.request
import json
import time
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://127.0.0.1:8045/v1"

def test_code_file_upload():
    # 1. Create a sample code file to upload
    sample_file = Path("scratch/sample_algorithm.py")
    sample_file.write_text("""
def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)
""", encoding="utf-8")
    
    print("[1] Resetowanie sesji czatu...")
    urllib.request.urlopen(urllib.request.Request(f"{BASE_URL}/chat/reset", data=b"{}", headers={"Content-Type": "application/json"}))
    time.sleep(1.5)
    
    print(f"[2] Wysyłanie zapytania z plikiem źródłowym ({sample_file.resolve()})...")
    payload = {
        "model": "gemini-3.7-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Przeanalizuj dołączony plik w Pythonie. Jaka jest jego złożoność czasowa (średnia i pesymistyczna) i jak można go zoptymalizować pod kątem pamięci?"
                    },
                    {
                        "type": "file",
                        "file_path": str(sample_file.resolve())
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
                
    print("\n\n[WERYFIKACJA DOKUMENTU]:")
    print(f"Zawiera 'quick_sort' lub 'QuickSort': {'quick_sort' in full_content.lower() or 'quicksort' in full_content.lower()}")
    print(f"Zawiera 'O(n log n)': {'O(n log n)' in full_content or 'n log n' in full_content}")
    print(f"Długość odpowiedzi: {len(full_content)} znaków.")

if __name__ == "__main__":
    test_code_file_upload()
