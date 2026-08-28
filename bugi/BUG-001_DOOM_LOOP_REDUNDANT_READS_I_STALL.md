# BUG-001: Pętla Zagłady Agenta (Doom Loop), 4x Redundant Read, Puste Wyszukiwania i Wyłączony Debounce

**Data rejestracji:** 2026-08-26 / 2026-08-28  
**Komponenty:** `debounce.py`, `server.py`, `monitor.py`, `subagent_isolation.py`  
**Wpływ na działanie:** KRYTYCZNY (zawieszenie interfejsu Trae, spalanie limitu tokenów, nieskończone pętle odczytów, brak reakcji na błędy).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutów ekranu)

### Incydent 1: Pętla bezowocnych wyszukiwań regex w jednym pliku
* **Objaw:** Agent rzucał serię zapytań regex do pliku `captured_requests.json` (`checkout`, `api/v2/purchases`, `https://www.vinted.pl/api`, `og:title`).
* **Wynik:** Wszystkie zapytania zwracały `No results found`.
* **Zachowanie agenta:** Zamiast zmienić strategię, agent powtarzał schemat 4-5 razy, wczytując plik w kółko na nowo.

### Incydent 2: Niekontrolowana eksplozja subagenta
* **Objaw:** Subagent badawczy w Trae osiągnął stan: `Read 20 files, Browsed 1 folder, Searched files 17 times`.
* **Wynik:** Brak syntezy danych, zablokowanie głównego agenta, czas odpowiedzi liczony w minutach.

### Incydent 3: Pętla wielokrotnego odczytu tego samego pliku (Redundant Read)
* **Objaw:** Agent przeczytał 15 różnych plików (`event_log.py`, `ocr.py`, `macro_engine.py`, itd.), po czym na samym dole sesji wykonał **4 razy z rzędu `Read macro_engine.py`**:
  ```text
  Read __init__.py
  Read macro_engine.py
  Read macro_engine.py
  Read macro_engine.py
  Read macro_engine.py
  Planning the next step (ZWIS)
  ```
* **Wynik:** Kompletne zapchanie okna kontekstowego (Context Degradation) i permanentne zablokowanie na fazie planowania.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Dlaczego to się stało?)

### A. Debounce był całkowicie WYŁĄCZONY w kodzie produkcyjnym
W pliku [`server.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L2748) oraz L1467:
```python
# DISABLED: debounce dedup has a bug — blocks ALL read-like results, not just duplicates
# api_messages = deduplicate_tool_results_in_prompt(api_messages, state or {})
```
Mechanizm debounce został wyłączony, ponieważ pierwotna implementacja blokowała każdy kolejny odczyt pliku (nawet jeśli to były różne pliki). W efekcie proxy nie posiadało **żadnej** aktywnej ochrony przed duplikatami.

### B. Wadliwe hashowanie parametrów (`debounce.py`)
Stary mechanizm debounce hashował pełen ciąg `tool_name + arguments`. 
W przypadku zapytań regex zmiana chociażby jednego znaku we wzorcu generowała unikalny hash MD5. Proxy traktowało każde z 17 bezowocnych zapytań jako „nowe i unikalne”, omijając filtr powtórzeń.

### C. Ślepota `monitor.py` na pętle logiczne
`monitor.py` sprawdzał jedynie czas od ostatniego tokenu (`last_heartbeat`, `last_progress`). 
W trakcie pętli mielenia model generował tokeny `reasoning` co 3-5 sekund. Monitor uznawał sesję za w 100% zdrową i aktywną (`active`), nie wykrywając braku postępu merytorycznego.

### D. Brak twardego warunku stopu po stronie Proxy
Proxy nie przerywało tury modelem `finish_reason: "stop"`. Pozwalało modelowi i Trae na wymianę nieskończonej liczby pustych tool-calli, aż do fizycznego wyczerpania limitów API.

---

## 3. DETERMINISTYCZNA ARCHITEKTURA NAPRAWCZA

Aby deterministycznie wyeliminować ten problem, proxy musi posiadać 4 twarde bezpieczniki (Circuit Breakers):

```mermaid
flowchart TD
    A[Odebranie Tool Call z Trae / Modelu] --> B{Jaki rodzaj akcji?}
    
    B -->|Odczyt pliku: Read| C{Czy ten sam plik czytany >= 2x bez edycji?}
    C -->|Tak (2. raz)| D[Zwróć błąd BLOCKED: Zakaz ponownego czytania]
    C -->|Tak (>= 3. raz)| E[TWARDY ABORT: finish_reason='stop' + Komunikat w Trae]
    C -->|Nie| F[Wykonaj Read & zapisz w Same-File Tracker]
    
    B -->|Wyszukiwanie: Grep/Glob/Search| G{Czy >= 10 pustych wyników pod rząd?}
    G -->|Tak| H[TWARDY ABORT: finish_reason='stop' + Komunikat o braku zasobu]
    G -->|Nie| I[Wykonaj wyszukiwanie & zaktualizuj licznik empty]
    
    B -->|Inne / Generowanie| J{Brak jakiegokolwiek tokenu > 60s?}
    J -->|Tak| K[TWARDY TIMEOUT: Zerwanie połączenia 504 Gateway Timeout]
    J -->|Nie| L[Kontynuuj strumieniowanie]
```

### Szczegóły bezpieczników:

1. **Same-File Lock (Licznik per ścieżka pliku):**
   * Śledzi znormalizowaną ścieżkę pliku (`file_path`).
   * Jeśli ten sam plik jest czytany 2. raz pod rząd bez modyfikacji kodu (`Write`/`Edit`): zwraca fałszywy wynik narzędzia z ostrzeżeniem.
   * Jeśli agent próbuje czytać go 3. raz: twarde odcięcie tury z komunikatem:
     `⚠️ [PROXY ABORT]: Przerwano pętlę agenta. Wielokrotny odczyt tego samego pliku ({path}) bez postępu prac.`

2. **Search Exhaustion Breaker (Próg `>= 10`):**
   * Globalny licznik `consecutive_empty_searches`.
   * Po 10 pustych odpowiedziach z rzędu: natychmiastowe zakończenie generowania i informacja w Trae, że szukane dane nie istnieją.

3. **Stall Watchdog 60s (Ochrona przed zwisem sieci):**
   * Watchdog mierzący czas od ostatniego tokenu (`reasoning` LUB `content`).
   * Po 60s ciszy: natychmiastowy reset połączenia (504), zmuszający Trae do odblokowania UI i pokazania przycisku "Retry".

4. **Prompt Pruning (Odchudzanie kontekstu):**
   * Treści odczytów plików starsze niż 2 tury wstecz są skracane w historii do postaci:
     `[Odczytano plik X: treść zarchiwizowana dla oszczędności kontekstu]`.

---

## 4. PLAN WERYFIKACJI DETERMINISTYCZNEJ (Testy)

Przed uznaniem błędu za naprawiony należy wykonać testy w `tests/`:
1. `test_debounce_same_file_abort`: wstrzyknięcie 3 identycznych wywołań `Read("macro_engine.py")` i weryfikacja, że 3. wywołanie kończy się `finish_reason: "stop"`.
2. `test_search_exhaustion_breaker`: wstrzyknięcie 10 pustych wyników wyszukiwania i weryfikacja natychmiastowego ucięcia pętli.
3. `test_stall_watchdog_timeout`: symulacja braku tokenów przez 60.1s i weryfikacja zgłoszenia błędu 504.
