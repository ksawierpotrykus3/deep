# BUG-023: Zjadanie Treści Wiadomości Asystenta przez Trae UI (Pusty Dymek / 0%) z Powodu Sztywnego `completion_tokens: 0` w Obiekcie Usage

**Data rejestracji:** 2026-09-02 18:41  
**Komponenty:** `server.py` (`_chunk:L3689-3700`, `_stream_usage`), Trae UI Markdown Stream Consumer  
**Wpływ na działanie:** KRYTYCZNY (Model w pełni wygenerował odpowiedź tekstową dla użytkownika, ale proxy w kończącym chunku SSE odesłało sztywne `usage: {"completion_tokens": 0}`; klient Trae uznał odpowiedź za pustą, nie wyrenderował tekstu podsumowania w interfejsie graficznym, ustawił wskaźnik na `0%` i zamknął turę, tworząc złudzenie zerwania połączenia).

---

## 1. DOWODY EMPIRYCZNE (Zrzut ekranu, logi SSE i logi proxy)

### Incydent: Pusty dymek asystenta ze statusem 0%
* **Widok w Trae (ze zrzutów ekranu `media_1788366289191.png` i `media_1788367088598.png`):**
  * Użytkownik wysłał instrukcję: *„no kontynuuj to jebane OLX bo musze odpisac gosciowi wiec zacznij wreszczie testowac”*.
  * W oknie czatu pojawił się dymek `Agent`, a pod nim pasek narzędzi (Copy, Branch, Retry) i **status `0%`**.
  * Wewnątrz dymka **nie ma ani jednego znaku tekstu** (całkowita pustka).
  * Na dole widnieje belka `8 files to review` z przyciskami `Undo All` / `Keep All`.
  * Pole tekstowe powróciło do stanu gotowości (zielona strzałka).

### Twardy dowód z logu proxy (`proxy_output.log`):
Proxy faktycznie odebrało z DeepSeeka i zyieldowało 16 fragmentów tekstu (`safe lines`):
```text
[YIELD] safe lines: 'Gotowe. Mam komplet twardych dowodów — możesz odpisać gościowi z konkretami.

'
[YIELD] safe lines: '## Co ustaliłem testami (wszystko udowodnione, nie zgadywanie)

'
[YIELD] safe lines: '**1. Autobuy OLX jest wykonalny — to pewne.**

'
[YIELD] safe lines: 'Nasz detektor widzi oferty **9–14 min przed wyszukiwarką**...'
[YIELD] safe lines: '**2. Znalazłem mechanizm „przytrzymania okazji" w API.**...'
[YIELD] safe lines: '**3. Płatność BLIK potwierdzona (27 razy w HTML)...**'
[TIMING] DS stream done, resp_id=434 finished=True
[TIMING] Stream done (12.7s, 0 tools, wm=58cac878235b...)
```
Mimo że tekst został zyieldowany w pętli proxy, w interfejsie Trae nie pojawiła się ani jedna litera!

---

## 2. SEKCJA ZWŁOK I PRZYCZYNA ŹRÓDŁOWA (Root Cause Analysis)

### Błąd w `server.py:L3689-3700`:
```python
_stream_usage = {"prompt_tokens": len(prompt) // 4, "completion_tokens": 0, "total_tokens": len(prompt) // 4}

def _chunk(delta: dict, fr: str | None = None) -> str:
    ...
    if fr is not None:
        c["choices"][0]["finish_reason"] = fr
        c["usage"] = _stream_usage
    return f"data: {json.dumps(c)}\n\n"
```
1. Obiekt `_stream_usage` jest inicjalizowany na początku strumienia z parametrem `"completion_tokens": 0`.
2. Podczas całego strumienia generator zlicza tokeny w `monitor.token()`, ale **nigdy nie aktualizuje `_stream_usage["completion_tokens"]`**!
3. W ostatnim pakiecie z `finish_reason: "stop"` proxy wysyła:
   `{"choices": [{"finish_reason": "stop"}], "usage": {"completion_tokens": 0, "total_tokens": ...}}`.
4. Klient Trae, parsując obiekt `usage` na koniec strumienia, widzi `completion_tokens: 0`. Uznaje, że odpowiedź była pusta / anulowana:
   * Usuwa bufor tekstowy asystenta z widoku DOM,
   * Ustawia wskaźnik kołowy na twarde **`0%`**,
   * Pozostawia pustą belkę akcji i pasek recenzji plików.

---

## 3. DETERMINISTYCZNY PLAN NAPRAWY

1. **Dynamiczne zliczanie `completion_tokens` w `server.py`:**
   * Za każdym razem, gdy `_chunk` wysyła pole `"content"`, zwiększamy licznik wygenerowanych tokenów:
     `_tokens_generated += max(1, len(delta["content"]) // 4)`
   * Przy wysyłaniu pakietu końcowego (`fr is not None`):
     ```python
     _stream_usage["completion_tokens"] = _tokens_generated
     _stream_usage["total_tokens"] = _stream_usage["prompt_tokens"] + _tokens_generated
     c["usage"] = _stream_usage
     ```
2. **Gwarancja 100% w Trae:**
   * Gdy Trae otrzyma poprawną, niezerową liczbę tokenów w obiekcie `usage`, wskaźnik ukończenia ustawi się na 100%, a tekst podsumowania nie zostanie skasowany z widoku DOM.
