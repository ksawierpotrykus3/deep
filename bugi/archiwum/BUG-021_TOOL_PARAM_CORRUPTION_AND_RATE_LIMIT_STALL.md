# BUG-021: Kaskada Błędów Narzędzi (`deserialize params error`), Samowolny Auto-Continue, Blokada Rate-Limit DeepSeek Web i Przerwanie Czatu na 32%

**Data rejestracji:** 2026-09-02 18:01  
**Komponenty:** `server.py` (`_parse_param_value:L1676`, `[AUTO-CONTINUE]:L881`, `_stream_source`), DeepSeek Web API (429 Rate Limit), Trae UI Stream Consumer  
**Wpływ na działanie:** KRYTYCZNY (Proxy przekazało do Trae zły typ parametru `offset: False` zamiast integera; Trae odrzuciło narzędzie błędem deserializacji; model próbował samonaprawy; proxy wpadło w pętlę `[AUTO-CONTINUE]` wysyłając „kontynuuj”; DeepSeek Web zablokował konto kodem `rate_limit_reached` i `Serwer jest zajęty`; proxy zwróciło pusty strumień 0 tokenów i Trae zamknęło dymek na 32%).

---

## 1. DOWODY EMPIRYCZNE (Zrzut ekranu, surowy strumień myślenia i logi proxy)

### Incydent 1: Przedwczesne urwanie generowania na 32%
* **Widok w Trae (ze zrzutu ekranu):**
  * Tura generowania tabeli w projekcie OLX została ucięta.
  * Wskaźnik postępu zatrzymał się na sztywno na **`32%`**.
  * Pojawił się pasek `1 files to review` z przyciskami `Keep All` / `Undo All`, a pole tekstowe powróciło do stanu gotowości z zieloną strzałką.

### Incydent 2: Twardy dowód ze strumienia myślenia modelu (wyciągnięty z `data/raw_stream_capture.jsonl`)
Model dosłownie zarejestrował swoją bezradność w logu myślenia:
> *„Wygląda na to, że mam problemy z wywołaniami narzędzi — parametry są zniekształcane (np. offset i limit przekazywane jako string false zamiast liczby). To dziwne. Spróbuję ponownie z poprawną składnią.”*

### Incydent 3: Twarde dowody z logu proxy (`proxy_output.log`)
1. **Seryjne błędy deserializacji parametrów w Trae:**
   ```text
   [tool] content: <toolcall_error_message>invalid params: deserialize params error: missing field / invalid type: boolean, expected integer</toolcall_error_message>
   ```
   (Kilkanaście odrzuconych wywołań narzędzi Read i Grep w ułamku sekundy).
2. **Pętla modułu Auto-Continue w proxy:**
   ```text
   [AUTO-CONTINUE] attempt 1, budget left=1, parent=248 (content=3342 chars, thinking=1096 chars)
   [AUTO-CONTINUE] Continue stream error: DeepSeek error: Zbyt częste wiadomości. Spróbuj ponownie później.
   ```
3. **Uderzenie w ścianę limitów anty-spamowych DeepSeek Web:**
   ```json
   [RAW] {"type":"error","content":"Zbyt częste wiadomości. Spróbuj ponownie później.","clear_response":true,"finish_reason":"rate_limit_reached"}
   [RAW] {"type":"error","content":"Serwer jest zajęty. Spróbuj ponownie później lub użyj trybu szybkiego.","clear_response":true,"finish_reason":"expert_busy_use_default"}
   ```
4. **Pusty zwrot z proxy:**
   Sesja `e51adb40` w monitorze zwróciła **0 tokenów** (`tokens: 0, thinking: 0`) i zamknęła strumień znacznikiem `[DONE]`.

---

## 2. SEKCJA ZWŁOK I PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Błąd w `server.py:L1676` (`_parse_param_value`)
W tagach XML generowanych przez DeepSeek Web tagi parametrów opcjonalnych przyjmowały postać:
`<parameter name="offset" string="true">false</parameter>`
Funkcja `_parse_param_value` wykonuje:
```python
parsed = _safe_json_loads(s)
if parsed is not None:
    return parsed
```
Dla napisu `"false"`, `json.loads("false")` zwraca wartość logiczną `False` (typ `bool`).
W schemacie narzędzia `Read` parametr `offset` ma typ `integer`. Gdy Trae otrzymało w parametrach JSON:
`{"file_path": "...", "offset": false}`
klient Trae rzucił natychmiast błędem: `deserialize params error`.

### B. Przegrzanie slotu przez pętlę Auto-Continue
Gdy model natrafił na błąd narzędzia, proxy zamiast zapytać o dalsze instrukcje, odpaliło wewnętrzny mechanizm `[AUTO-CONTINUE]` wysyłając `"kontynuuj"` do tego samego czatu webowego. Seria zapytań w ciągu milisekund wywołała blokadę `rate_limit_reached`.

### C. Fałszywy sukces `[DONE]` z 0 tokenami
Gdy konto zostało zablokowane kodem błędu zajętości, proxy nie podjęło próby auto-rotacji na inne dostępne konto (np. konto 2, 3 lub 4), lecz odesłało do Trae czysty znacznik zakończenia `[DONE]`. Trae zamknęło dymek w stanie uciętym na 32%.

---

## 3. DETERMINISTYCZNY PLAN NAPRAWY

1. **Poprawka w `_parse_param_value` oraz sanityzator parametrów numerycznych:**
   * Dla znanych parametrów numerycznych (`offset`, `limit`, `head_limit`):
     Jeśli wartość sparsowana nie jest dodatnią liczbą całkowitą (np. jest `False`, `True`, `""` lub ujemna), parametr musi zostać **całkowicie usunięty ze słownika parametrów**, zamiast trafiać jako `false` do Trae.
2. **Wyłączenie `[AUTO-CONTINUE]` w przypadku błędów narzędzi:**
   * Auto-continue ma prawo działać wyłącznie przy obcięciu długich tekstów Markdown, a nigdy przy błędach wykonania narzędzi (`deserialize params error`).
3. **Automatyczna rotacja konta przy `rate_limit_reached`:**
   * W razie napotkania komunikatu *„Zbyt częste wiadomości”* lub *„Serwer jest zajęty”*, proxy natychmiast rotuje slot na następne wolne konto (`account_idx = (account_idx + 1) % MAX_ACCOUNTS`).
