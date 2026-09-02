# BUG-016: Zduplikowane Obietnice Implementacji IPC i Kolejna Pętla Odczytu `chain_executor.py` zamiast Edycji Kodu

**Data rejestracji:** 2026-08-31 22:31  
**Komponenty:** Model Planning, Action-Intention Gap, `server.py`  
**Wpływ na działanie:** WYSOKI (Model dwukrotnie zadeklarował wdrożenie całego łańcucha IPC i przycisku, ale dwukrotnie z rzędu wywołał `Read chain_executor.py`, po czym zamarł na 0%).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu)

### Incydent: Podwójna obietnica wdrożenia i ucieczka w odczyt
* **Tekst asystenta w dymku (ze zrzutu ekranu):**
  1. *„Mam pełny obraz. Teraz dodaję cały łańcuch: backend (child_process w main), typy IPC, preload i przycisk w headerze. Zacznę od nowego modułu backendu i edycji mostka.”* $\rightarrow$ **`Read 1 file >`**
  2. *„Mam pełny obraz. Dodaję end-to-end: backend child_process, typy, preload i przycisk. Zaczynam od dostosowania `__main__` w executorze, żeby przyjmował pipeline id z argv.”* $\rightarrow$ **`Read chain_executor.py`**
  3. *„Sprawdzę skąd brać dane zlecenia w `__main__`.”* $\rightarrow$ **Zwis i 0%**.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Nawrót Inwersji Narzędzi (BUG-009 / BUG-015)
Model poprawnie planuje zadanie (*dodać child_process, preload i przycisk*), ale zamiast użyć narzędzia `Write`/`Edit`, za każdym razem ucieka w asekuracyjny odczyt `chain_executor.py`. 

### B. Przebodźcowanie wielowarstwowym zadaniem
Zadanie wymaga edycji 4 plików w 2 różnych językach (Python + TypeScript/React). Model przy tak złożonym zadaniu ulega paraliżowi decyzyjnemu i zapętla się w odczytach.

---

## 3. DETERMINISTYCZNA NAPRAWA

Podziel zadanie na **jednoatomowe kroki**:
1. **Krok 1 (Tylko Python):**
   > *„W `useme_core/chain_executor.py` dodaj obsługę argumentu CLI `--pipeline-id <ID>`, aby uruchamiać konkretny potok. Zapisz plik narzędziem Write od razu.”*
2. **Krok 2 (Tylko TypeScript/UI):**
   > *„W `cortex-app/src/supervisor/SupervisorView.tsx` dodaj przycisk uruchamiania.”*
