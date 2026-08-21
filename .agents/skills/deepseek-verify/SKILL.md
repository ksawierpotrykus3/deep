---
name: deepseek-verify
description: "Zarządza autonomicznym Workerem DeepSeek (modyfikacja plików, testy na dysku) oraz wyrocznią wnioskowania i audytu (MCP Oracle)."
---

# DeepSeek Reasoning, Verification & Autonomous Worker

Masz do dyspozycji potężny zestaw narzędzi oparty na lokalnym klastrze DeepSeek (z pełnym Thinking / Chain of Thought):

## 1. `deepseek_autonomous_worker` (Gdy zlecasz całą pracę wykonawczą)
**KIEDY UŻYWAĆ:**
- Gdy zadanie wymaga zbadania i modyfikacji wielu plików w projekcie.
- Gdy trzeba napisać kod, zmienić konfigurację i odpalić testy (`pytest`, `npm test`, `python`).
- Zamiast czytać 20 plików i zatykać własny kontekst — oddeleguj to zadanie do Workera.

**JAK SFORMUŁOWAĆ POLECENIE DLA WORKERA (`task_instructions`):**
Podaj mu konkretny, jasny brief inżynierski:
1. **Cel:** Co dokładnie ma osiągnąć (np. *"Zaimplementuj walidację tokenów JWT w module auth"*).
2. **Pliki:** Wskaż kluczowe pliki lub katalogi do sprawdzenia.
3. **Kryteria sukcesu:** Jakie testy lub komendy ma odpalić na końcu (np. *"Uruchom `pytest tests/test_auth.py` i upewnij się że kod przechodzi"*).

---

## 2. `deepseek_critical_verify` (Gdy potrzebujesz bezkompromisowego audytu)
**KIEDY UŻYWAĆ:**
- Przed zatwierdzeniem kluczowego planu architektonicznego, refaktoru lub diffa kodu.
- Gdy chcesz znaleźć subtelne luki logiczne, stany wyścigu (race conditions) lub przeoczone przypadki brzegowe.

---

## 3. `deepseek_deep_reasoning` (Gdy potrzebujesz głębokiej dedukcji matematycznej/algorytmicznej)
**KIEDY UŻYWAĆ:**
- Do optymalizacji złożoności asymptotycznej ($O(N)$), wyprowadzeń formuł matematycznych i trudnych problemów kombinatorycznych.
