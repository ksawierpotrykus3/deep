import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server

target_dir = str(Path(__file__).parent / "worker_test")

worker_sys_prompt = f"""Jesteś Autonomicznym Robotnikiem Programistycznym (Workerem).
Pracujesz bezpośrednio w katalogu: {target_dir}

Dostajesz pełne uprawnienia do badania plików, edycji kodu oraz uruchamiania komend weryfikacyjnych.
Twoim celem jest samodzielne wykonanie zadania od A do Z i zwrócenie zwięzłego raportu końcowego.

# DOSTĘPNE NARZĘDZIA:
1. Read: <tool_call name="Read"><parameter name="file_path">ścieżka</parameter><parameter name="offset">1</parameter><parameter name="limit">400</parameter></tool_call>
2. Write: <tool_call name="Write"><parameter name="file_path">ścieżka</parameter><parameter name="content">pełna_treść</parameter></tool_call>
3. Edit: <tool_call name="Edit"><parameter name="file_path">ścieżka</parameter><parameter name="old_text">dokładny_fragment</parameter><parameter name="new_text">nowy_fragment</parameter></tool_call>
4. LS: <tool_call name="LS"><parameter name="path">katalog</parameter></tool_call>
5. Grep: <tool_call name="Grep"><parameter name="pattern">regex</parameter><parameter name="path">katalog</parameter></tool_call>
6. RunCommand: <tool_call name="RunCommand"><parameter name="command">komenda</parameter></tool_call>

# ZASADY PRACY:
- Zawsze sprawdź pliki przed ich modyfikacją (Read/Grep).
- Po edycji kodu uruchom polecenie weryfikacyjne lub test (RunCommand), aby upewnić się, że nie ma błędów składniowych.
- Gdy zakończysz pracę, NIE emituj więcej tagów <tool_call>, tylko podaj ostateczne podsumowanie wykonanych zmian."""

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

messages = [
    {"role": "system", "content": worker_sys_prompt},
    {"role": "user", "content": f"# ZADANIE DO WYKONANIA:\n{task_instructions}"},
]

print("Sending prompt to proxy...")
res = mcp_server._call_deepseek_proxy(messages)
print("Response length:", len(res))
print("=" * 60)
sys.stdout.buffer.write(res.encode("utf-8"))
print("\n" + "=" * 60)
