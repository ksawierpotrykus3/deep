# BUG-031: Połknięcie Wywołań Narzędzi w Buforze Myślenia (Swallowed Tool Calls in Thinking Buffer) i Fałszywy Alarm Zero Tokenów

**Data zgłoszenia:** 2026-09-06  
**Środowisko:** Trae IDE + DeepSeek Proxy (server.py)  
**Status:** Rozwiązany (Fixed & Verified)  
**Komponenty:** `server.py` (`_stream`, `_route_token`, `_begin_phase`, `generate`), `tests/test_bug031.py`  
**Dowód wizualny:** Zrzut ekranu `media_1788687193940.png` w Trae IDE:  
- Polecenie użytkownika: `okej odpal subagentow 2 i daj im rozne prompty zobacz jaki da lepszy wynik`.
- Trae wykonał `Listed mcps`, `Command executed Get-Location`, a następnie zatrzymał się z komunikatem:
  `[BŁĄD PROXY: Serwer DeepSeek nie zwrócił żadnych tokenów (pusty strumień). Ponów zapytanie w nowym czacie.]`
- Wskaźnik zatrzymał się na 1%.

---

## 1. Objawy Awarii

1. Użytkownik zlecił uruchomienie dwóch subagentów z różnymi promptami do porównania wyników.
2. Trae wykonał wstępne komendy, a asystent po fazie myślenia nie wykonał żadnego subagenta (`Task`).
3. Zamiast wywołania narzędzi na czacie pojawił się czerwony komunikat błędu proxy:
   `[BŁĄD PROXY: Serwer DeepSeek nie zwrócił żadnych tokenów (pusty strumień). Ponów zapytanie w nowym czacie.]`
4. W pliku `data/sessions_monitor.json` dla sesji `7189a497b6c14f26ae5c3fbe90037cce`:
   `tok: 0`, `think: 878`, `state: done`, `finished: True`.
   Model wygenerował 878 tokenów myślenia, ale 0 tokenów treści!

---

## 2. Analiza Przyczyny Źródłowej (First-Principles Root Cause Analysis)

1. **Brak fragmentu `type: "RESPONSE"` przy wywołaniach narzędzi w DeepSeek Web:**
   - DeepSeek Web w początkowym pakiecie deklaruje fragment fazy myślenia:
     `{"v": {"response": {"fragments": [{"type": "THINK", "content": "..."}]}}}`.
   - W `server.py` funkcja `_begin_phase("THINK", ...)` ustawia `thinking_active = True` oraz `response_started = False`.
   - Gdy DeepSeek Web generuje zwykłą odpowiedź tekstową, po zakończeniu myślenia wysyła kolejny fragment `{"type": "RESPONSE"}`.
   - Jednak gdy model decyduje się na wywołanie narzędzi (np. format `<tool_calls><invoke name="Task">...`), silnik DeepSeek Web **NIE tworzy nowego fragmentu `RESPONSE`**! Kontynuuje strumieniowanie tokenów narzędzi w ramach otwartego fragmentu `THINK`.

2. **Połknięcie wywołań narzędzi do bufora myślenia (`thinking_buffer`):**
   - Ponieważ `thinking_active` pozostało `True`, funkcja `_route_token`:
     ```python
     thinking_buffer += text
     return _ReasoningChunk(text)
     ```
   - Każdy token wywołania narzędzia (`"<"`, `"tool"`, `"_c"`, `"alls"`, `">\n"`, `"<invoke name="Task">"`, parametry subagenta) trafiał do `thinking_buffer` i był yieldowany jako `_ReasoningChunk` (tłumaczony na `delta.reasoning_content` dla Trae).
   - Bufor odpowiedzi użytkownika (`content_buffer`) pozostał zupełnie pusty (`len == 0`)!

3. **Fałszywy alarm bezpiecznika Zero-Token (BUG-030):**
   - Na końcu strumienia `generate()` sprawdziło:
     `if tools_yielded == 0 and not full.strip():`
   - Ponieważ `full` zawierało tylko tokeny z `content_buffer` (który był pusty), proxy uznało, że serwer DeepSeek zwrócił pusty strumień i wyemitowało komunikat błędu.
   - Faktycznie model wygenerował 2 pełne wywołania subagenta `Task` (co udowodnił zrzut `data/raw_stream_capture.jsonl`), ale zostały one uwięzione w buforze myślenia.

---

## 3. Zastosowane Rozwiązanie (Dwuwarstwowa Obrona Deterministyczna)

### Warstwa 1: Dynamiczne Przełączanie Fazy w Locie (Real-time Stream Phase Shift)
W funkcji `_route_token` w trakcie trwania fazy `THINK` wprowadzono ciągłe monitorowanie napływających tokenów:
1. Regex `_TOOL_START_PATTERNS` natychmiast wykrywa początek wywołania narzędzia (`<tool_calls>`, `<invoke>`, `<tool_call>`, `<parameter>`, `<Task>`, `<Read>` itp.) lub jawny tag `</think>` / `</thought>`.
2. Regex `_TAG_PREFIX_PAT` buforuje urwany początek znacznika (np. `<`, `<tool`), zapobiegając wyciekowi pojedynczych znaków `<`, `<t` do `reasoning_content`.
3. W momencie dopasowania znacznika narzędzia:
   - Zaległe myślenie przed znacznikiem jest natychmiast wysyłane jako ostatni `_ReasoningChunk`.
   - Faza zostaje przełączona: `thinking_active = False`, `response_started = True`.
   - Treść wywołania narzędzia trafia natychmiast do `content_buffer` i jest yieldowana do `generate()`.
   - Wszystkie kolejne tokeny strumienia są traktowane jako treść odpowiedzi (`RESPONSE`).

### Warstwa 2: Deterministyczny Bezpiecznik Końcowy (Post-Stream Safety Net)
Jeśli z jakiegokolwiek powodu warstwa w locie nie wyemitowałaby treści i strumień zakończyłby się z pustym `content_buffer`:
1. Proxy skanuje `thinking_buffer` za pomocą `_parse_tool_calls` oraz `_has_unclosed_tool_call`.
2. Jeśli w buforze myślenia znajdują się kompletne lub urwane wywołania narzędzi, są one deterministycznie odzyskiwane:
   - Narzędzia są wycinane z `thinking_buffer` i przenoszone do `content_buffer`.
   - Strumień otrzymuje status `response_started = True` oraz `finished_normally = True`.
   - Narzędzia są natychmiast emitowane do generatora `generate()`.
3. Dzięki temu wywołanie narzędzi NIGDY nie może zostać połknięte, a fałszywy alarm Zero-Token jest fizycznie niemożliwy.

---

## 4. Deterministyczna Weryfikacja i Dowody

1. **Nowe testy jednostkowe w `tests/test_bug031.py`:**
   - `test_bug031_realtime_transition_swallowed_tool_calls`: weryfikuje dynamiczne przejście ze strumienia tokenów myślenia do wywołań subagenta `Task`. Potwierdza, że 0 tokenów narzędzi wycieka do myślenia, `content_buffer` zawiera pełne wywołania, a parser wykrywa 2 narzędzia `Task`.
   - `test_bug031_post_stream_safety_net_recovery`: weryfikuje awaryjne odzyskanie wywołania narzędzia uwięzionego w `thinking_buffer`.
   - `test_bug031_explicit_think_tag_transition`: weryfikuje przejście na jawny znacznik `</think>`.
   - `test_bug031_generate_loop_zero_tokens_prevention`: weryfikuje brak fałszywego alarmu w pętli `generate()`.
2. **Wynik testów:**
   - 87/87 testów jednostkowych przechodzi pomyślnie (`87 passed, 4 deselected in 0.54s`).
