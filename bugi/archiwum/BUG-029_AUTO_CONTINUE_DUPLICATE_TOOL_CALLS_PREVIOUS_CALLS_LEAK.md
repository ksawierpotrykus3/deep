# BUG-029: Niepotrzebne Auto-Continue przy Poprawnych Wywołaniach Narzędzi (6-krotne Czytanie Tego Samego Pliku) oraz Wyciek Tagu `</previous_calls>` do Czatu

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (`server.py`)  
**Status:** NAPRAWIONY (ZWERIFIKOWANY DETERMINISTYCZNIE TESTAMI JEDNOSTKOWYMI)  
**Dotknięte komponenty:** `server.py` (`_STRIP_TAGS`, `_LEAK_DETECTOR`, `DeepSeek.stream_completion` pętla auto-continue)  
**Dowód wizualny:** `media_1788603786496.png` w Trae IDE:  
- Widoczny w oknie rozmowy wycieknięty tag: `</previous_calls>`  
- `Read 6 files` (6 identycznych odczytów: `Reading Kontynuuj Zadanie AI Not Responding Issue.md`)  

---

## 1. Objawy Awarii

W interfejsie agenta w Trae IDE po poprawnym uruchomieniu zapytania:
1. W treści wypowiedzi asystenta pojawił się "goły" tag techniczny:
   ```text
   </previous_calls>
   ```
2. Agent zamiast jednokrotnie odczytać plik zadania, w pojedynczej turze wygenerował sekwencję 6 identycznych wywołań narzędzia:
   ```text
   Read 6 files
     Reading Kontynuuj Zadanie AI Not Responding Issue.md
     Reading Kontynuuj Zadanie AI Not Responding Issue.md
     Reading Kontynuuj Zadanie AI Not Responding Issue.md
     Reading Kontynuuj Zadanie AI Not Responding Issue.md
     Reading Kontynuuj Zadanie AI Not Responding Issue.md
     Reading Kontynuuj Zadanie AI Not Responding Issue.md
   ```
3. W logu DeepSeek wypowiedział słowa:
   `"I'm not getting the file body in my context. Delegating the full read to a subagent."`

---

## 2. Dowody z Logów Proxy (`task-1961.log`)

W logu serwera zarejestrowano sekwencję:
```text
[TC] Read({"file_path": "...\\Kontynuuj Zadanie AI Not Responding Issue.md"}) span=(13,315)
[AUTO-CONTINUE] attempt 1, budget left=1, parent=4 (content=333 chars, thinking=961 chars)
[YIELD] text[315:346] -> '\n</previous_calls>\n'
[TC] Read({"file_path": "...\\Kontynuuj Zadanie AI Not Responding Issue.md"}) span=(346,648)
[AUTO-CONTINUE] attempt 1, budget left=0, parent=6 (content=315 chars, thinking=532 chars)
[TC] Read({"file_path": "...\\Kontynuuj Zadanie AI Not Responding Issue.md"}) span=(661,963)
[AUTO-CONTINUE] attempt 1, budget left=1, parent=8 (content=315 chars, thinking=3433 chars)
[TC] Read({"file_path": "...\\Kontynuuj Zadanie AI Not Responding Issue.md"}) span=(976,1279)
[AUTO-CONTINUE] attempt 1, budget left=0, parent=10 (content=316 chars, thinking=319 chars)
[TC] Read({"file_path": "...\\Kontynuuj Zadanie AI Not Responding Issue.md"}) span=(1292,1595)
[TC] Read({"file_path": "...\\Kontynuuj Zadanie AI Not Responding Issue.md"}) span=(1616,1911)
```
Łącznie wyemitowano aż 6 wywołań `Read` tego samego pliku w jednej odpowiedzi SSE.

---

## 3. Przyczyna Źródłowa (Root Cause Analysis)

### A. Dlaczego wyciekł tag `</previous_calls>`?
Wyrażenie regularne `_STRIP_TAGS` w `server.py` zawierało wzorzec:
```python
r"</?previous_tool_call[^>]*>|"
```
Brakowało w nim obsługi tagu `previous_calls` (bez `tool_` i w liczbie mnogiej). Gdy model po otrzymaniu promptu `"kontynuuj"` zamknął blok poprzednich wywołań znacznikiem `</previous_calls>`, filtr go nie usunął i trafił on do czatu użytkownika.

### B. Dlaczego proxy 6 razy przeczytało ten sam plik?
1. Model poprawnie wygenerował całe narzędzie `<tool_call name="Read">...</tool_call>` i zakończył generowanie.
2. Webowy serwer DeepSeek zamknął połączenie HTTP po wyemitowaniu tokenów, nie wysyłając jednak pakietu JSON z jawnym statusem `"status": "FINISHED"`.
3. Zmienna `finished_normally` w proxy pozostała ustawiona na `False`.
4. Warunek auto-continue w `server.py`:
   ```python
   while ((not finished_normally or _has_unclosed_tool_call(content_buffer)) and ...)
   ```
   zauważył `not finished_normally == True` i uznał, że odpowiedź została przedwcześnie ucięta.
5. Proxy wysłało do sesji DeepSeeka polecenie `"kontynuuj"`.
6. DeepSeek Web odebrał `"kontynuuj"`, ale nie miał treści pliku (bo Trae jeszcze jej nie dostarczył, gdyż tura nie została zakończona). Model uznał więc, że plik nadal nie został wczytany i ponownie wygenerował wywołanie `Read(...)`.
7. Cały cykl powtórzył się w pętli auto-continue aż do wyczerpania budżetów, generując 6 wywołań narzędzia w jednej odpowiedzi do Trae.

---

## 4. Plan Naprawy

1. **Uodpornienie `_STRIP_TAGS` i `_LEAK_DETECTOR`**:
   Rozszerzenie wzorca na:
   ```python
   r"</?previous_(?:tool_)?calls?[^>]*>|"
   ```
2. **Blokada Auto-Continue przy kompletnych wywołaniach narzędzi**:
   Jeśli w buforze znajduje się co najmniej jedno kompletne wywołanie narzędzia (`has_complete_tools = bool(_parse_tool_calls(content_buffer))`) oraz brak jest niedomkniętych tagów (`not _has_unclosed_tool_call(content_buffer)`):
   - Ustawić `finished_normally = True`.
   - Zablokować wysyłanie `"kontynuuj"`. Tura modelu jest zakończona, sterowanie natychmiast przekazywane jest do Trae.
3. **Prawidłowe wykrywanie naturalnego końca strumienia (EOF)**:
   Jeśli strumień SSE z DeepSeek zakończył się bez błędu i bez timeoutu watchdog, a w treści nie ma urwanych znaczników (`not _has_unclosed_tool_call(content_buffer)`), traktować to jako `finished_normally = True`.
4. **Ograniczenie budżetu rekurencyjnego auto-continue**:
   Przy wywołaniu kontynuacji przekazywać `_auto_continue_budget = 0`, aby zapobiec kaskadowemu pętleniu się zapytań.

---

## 5. Deterministyczna Weryfikacja (Testy Jednostkowe)

Utworzono zestaw testów w `tests/test_bug029.py`:
1. `test_strip_tags_removes_previous_calls_tag`:
   - Weryfikuje, że `</previous_calls>`, `<previous_calls>`, `</previous_call>`, `<previous_tool_calls>` są deterministycznie usuwane z tekstu wyjściowego.
2. `test_auto_continue_does_not_fire_on_complete_tool_call`:
   - Mockuje odpowiedź DeepSeeka zawierającą kompletne wywołanie narzędzia `<tool_call name="Read">...</tool_call>`.
   - Sprawdza, że `stream_completion` wywoływane jest dokładnie 1 raz (`len(calls) == 1`), `finished_normally == True` i ani razu nie jest wysyłane `"kontynuuj"`.
3. `test_auto_continue_fires_on_unclosed_tool_call_and_stops`:
   - Weryfikuje, że w przypadku faktycznie urwanego tagu narzędzia (np. brak zamykającego `</tool_call>`), proxy wysyła `"kontynuuj"` dokładnie raz z budżetem `_auto_continue_budget=0` i po domknięciu tagu kończy turę.
4. `test_leak_detector_catches_previous_calls`:
   - Weryfikuje, że filtr `_LEAK_DETECTOR` natychmiast wyłapuje wszelkie odmiany tagów `previous_calls`.

Wynik testów (`pytest tests/test_bug029.py`):
```text
tests\test_bug029.py .... [100%]
4 passed in 0.04s
```
Wynik pełnego regresyjnego zestawu testów (`pytest -q -m "not live"`):
```text
81 passed, 4 deselected in 0.53s
```