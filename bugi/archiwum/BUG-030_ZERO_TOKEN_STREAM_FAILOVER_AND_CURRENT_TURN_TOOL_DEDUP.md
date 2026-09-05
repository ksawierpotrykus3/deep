# BUG-030: Zacięcie na 0% (Pusty Strumień z Serwera DeepSeek / Zero Tokenów) oraz Brak Deduplikacji Wielokrotnych Wyników Narzędzi w Bieżącej Turze

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (server.py)  
**Status:** W trakcie naprawy  
**Komponenty:** server.py (stream_completion, generate, _build_prompt)  
**Dowód wizualny:** media_1788604632942.png oraz media_1788604649466.png w Trae IDE:  
- Model wywołał 12 narzędzi naprzemiennie w jednej turze (Read Kontynuuj... oraz Read AI Not Responding...).
- Narzędzie Read AI Not Responding Issue.md zakończyło się błędem File does not exist (czerwony wykrzyknik), ponieważ plik nie istnieje na dysku.
- Narzędzie Read Kontynuuj Zadanie AI Not Responding Issue.md powtórzyło się 5 razy (plik 70 KB wklejony 5 razy = 350 KB).
- W kolejnym zapytaniu po zebraniu wyników edytor stanął na wskaźniku 0%.

---

## 1. Objawy Awarii

1. W oknie rozmowy asystent wywołał serię narzędzi naprzemiennie:
   - Reading Kontynuuj Zadanie AI Not Responding Issue.md
   - Reading AI Not Responding Issue.md (błąd: File does not exist)
   - Listing Projekty_autorskie
2. Po wykonaniu narzędzi przez Trae, edytor wysłał zebrane wyniki do proxy (msgs=18).
3. Zapytanie w Trae zakończyło się natychmiastowym zatrzymaniem na wskaźniku 0% bez żadnej odpowiedzi tekstowej asystenta.

---

## 2. Przyczyny Źródłowe (Root Cause Analysis)

### A. Przeładowanie pamięci DeepSeek przez brak deduplikacji w bieżącej turze (current_turn)
W server.py kompresja narzędzi kompresowała wyłącznie starą historię, pozostawiając całą bieżącą turę (current_turn) bez ograniczeń.
Gdy model w jednej turze wywołał 5 odczytów tego samego 70-kilobajtowego pliku, do promptu trafiło 5 pełnych kopii (~350 KB tekstu). W połączeniu z listingiem katalogu prompt przekroczył możliwości webowego czatu DeepSeek.

### B. Ciche połykanie pustego strumienia (preamble_data_count == 0 / 0 tokenów)
Gdy serwer DeepSeek odebrał przeładowane zapytanie, zamknął połączenie socketu natychmiast (HTTP 200, ale 0 linii danych SSE).
Proxy wypisało tylko ostrzeżenie i przeszło do generatora _stream(). Generator nie wyemitował ani jednego tokena.
Gdy generator zakończył się bez wyjątku z 0 tokenami:
- Ustawiono success = True.
- Wysłano do Trae pakiet finish_reason: stop i [DONE] z pustą treścią.
- Trae odebrał pusty komunikat asystenta i zablokował interfejs na wskaźniku 0%.

---

## 3. Plan Naprawy

1. Obsługa preamble_data_count == 0 w stream_completion:
   Jeśli odpowiedź nie zawiera żadnych linii danych, proxy natychmiast ponawia próbę lub rzuca RuntimeError('DeepSeek empty stream (0 data lines)'), co uruchamia failover na inne konto.
2. Bezpiecznik Zero-Token w generate():
   Jeśli tools_yielded == 0 i not full.strip(), proxy oznacza success = False i emituje jawny komunikat o pustym strumieniu zamiast cichego pustego [DONE].
3. Deduplikacja wyników narzędzi w current_turn:
   Jeśli ten sam plik lub tożsamy wynik narzędzia został powtórzony w bieżącej turze, pełna treść wklejana jest tylko raz. Wszystkie kolejne duplikaty są skracane do 1-liniowej notatki informacyjnej.

---

## 4. Deterministyczna Weryfikacja (Testy Jednostkowe)

Utworzono zestaw testów w 	ests/test_bug030.py:
1. 	est_stream_completion_retries_and_raises_on_0_data_lines:
   - Sprawdza, że gdy DeepSeek zwraca pusty strumień bez danych SSE, proxy nie połyka go po cichu, lecz natychmiast rzuca RuntimeError('DeepSeek empty stream'), co uruchamia procedurę migracji/failover.
2. 	est_tool_deduplication_in_current_turn:
   - Weryfikuje, że wklejenie wielu powtórzonych odczytów tego samego pliku w jednej turze zostaje zdeduplikowane: pierwszy odczyt pozostaje pełny, a kolejne zostają zastąpione zwięzłą notatką informacyjną, chroniąc przed przepełnieniem pamięci DeepSeeka.

Wynik testów:
`	ext
tests/test_bug030.py .. [100%]
2 passed in 0.02s
`
Pełny zestaw regresyjny: 83 passed, 0 failed.