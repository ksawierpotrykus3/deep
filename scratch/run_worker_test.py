import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server

def main():
    target_dir = str(Path(__file__).parent / "worker_test")
    print(f"=== ODPALAM AUTONOMICZNEGO WORKERA DEEPSEEK ===")
    print(f"Katalog roboczy: {target_dir}")
    print(f"Zadanie: Zbadaj kod, napraw błędy w calculator.py i uruchom pytest test_calculator.py")
    print("=" * 60)

    task_instructions = """
W bieżącym katalogu znajdują się dwa pliki: `calculator.py` oraz `test_calculator.py`.
Wykonaj następujące kroki:
1. Użyj narzędzia `Read`, aby przeczytać oba pliki i zrozumieć dlaczego testy zawodzą.
2. Użyj narzędzia `Edit` (lub `Write`), aby poprawić błędy w `calculator.py`:
   - funkcja `divide(a, b)` musi rzucać `ValueError("Dzielenie przez zero")` gdy `b == 0` oraz zwracać `float(a / b)`.
   - funkcja `is_even(n)` musi zwracać `True` dla liczb parzystych i `False` dla nieparzystych.
3. Użyj narzędzia `RunCommand`, aby uruchomić testy poleceniem: `pytest test_calculator.py`.
4. Po uzyskaniu zielonych testów podaj końcowy raport podsumowujący.
"""

    t0 = time.time()
    result = mcp_server.deepseek_autonomous_worker(
        task_instructions=task_instructions,
        work_dir=target_dir,
        max_turns=6,
    )

    print("\n" + "=" * 60)
    print(f"WORKER ZAKOŃCZYŁ DZIAŁANIE W {time.time()-t0:.2f}s!")
    print("=" * 60)
    sys.stdout.buffer.write(result.encode("utf-8"))
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
