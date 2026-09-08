# BUG-033: Paraliż tagiem <｜｜DSML｜｜_wait> i zamrożenie Trae na 0% (Thought-only Bubble)

**Data**: 2026-09-08  
**Status**: Naprawiony (Deterministic Fix + 8 Testów Jednostkowych w `tests/test_bug033.py`)  
**Komponent**: `server.py` (`_clean_dsml_wait`, `_STRIP_TAGS`, `_stream`, Coordinator Prompt)

---

## 1. Objawy i Zgłoszenie Użytkownika

* **Zrzut ekranu / Widok w Trae IDE**:
  * Agent zatrzymuje się na poziomie `0%` (zielony dymek `Thought ˅` z rozwiniętym procesem myślowym).
  * Poza blokiem myślenia treść odpowiedzi jest całkowicie pusta (pusty biały dymek bez tekstu i bez wywołań narzędzi).
  * W sekcji myślenia model toczy wewnętrzny spór:
    > *„Muszę najpierw przeczytać pełne pliki 00, 01, 02... Powinienem przeczytać pliki sam? Instrukcje mówią: nie czytaj sam, deleguj do subagentów. Ale do napisania poprawionego pliku 00 potrzebuję pełnej treści... Tak, przeczytam trzy pliki równolegle przez Read.”*
    Mimo to żadne wywołanie `Read` nie pojawia się w interfejsie.
  * W kolejnej turze użytkownik pisze: *„kontynuuj. read nie dziala cos nie wiem dlaczego. zobacz czy napewno dobrze piszesz”*.
  * Model zaczyna przepraszać: *„Przepraszam — wcześniej emitowałem puste znaczniki zamiast prawdziwego wywołania...”* i ponownie zamarza.

---

## 2. Przyczyna Źródłowa (Root Cause Analysis)

Analiza surowego strumienia (`data/raw_stream_capture.jsonl`) oraz logów proxy ujawniła trzystopniową awarię:

1. **Konflikt logiczny w prompcie koordynatora (Problem poznawczy modelu)**:
   Wstrzykiwany prompt koordynatora zawierał bezwzględny zakaz:
   ```text
   DO NOT use Read/Glob/Grep/SearchCodebase yourself if a subagent can do it.
   DO NOT read files one-by-one — launch parallel subagents instead.
   ```
   Gdy użytkownik poprosił koordynatora o przygotowanie poprawionego pliku `00`, model znalazł się w sprzeczności: potrzebował dokładnej zawartości pliku do edycji, ale prompt kategorycznie zakazywał mu wywołania `Read`.
2. **Emisja wewnętrznego pseudotagu DeepSeeka (`_wait`)**:
   DeepSeek Web w stanie wahania/decyzji o niewykonywaniu akcji narzędziowej emituje wewnętrzny znacznik DSML:
   ```xml
   <｜｜DSML｜｜_wait>—brak</｜｜DSML｜｜_wait>
   ```
   W turze 12 model wyemitował go 4-krotnie pod rząd zaraz po sekcji myślenia.
3. **Potrójna blokada w silniku proxy (`server.py`)**:
   * **Blokada bufora (`tail`)**: Regex `</?\s*(?:[|｜｜│\s]*DSML...` uznał ciąg `DSML` za rozpoczęcie wywołania narzędzia i wstrzymał wysyłanie tekstu do klienta (`continue`).
   * **Odmowa zrzutu (`remaining`)**: Na końcu strumienia parser nie dopasował `_wait` do żadnego prawdziwego narzędzia, ale końcowy filtr w linii 4348 odmówił wypchnięcia tekstu, bo wciąż widział w nim wzorzec `DSML`.
   * **Obejście Empty Promise Guard**: Ponieważ `full` zawierał znaki tagu `_wait`, warunek `if not full.strip():` ocenił się jako `False`. Proxy uznało, że „coś zostało wygenerowane”, i zamknęło strumień sukcesem z 0 tokenami treści. Trae otrzymało pustą odpowiedź i zamarzło na `0%`.
   * **Fałszywy alarm pętli (`_detect_loop`)**: W turze 14 powtórzenie 38-znakowego fragmentu `<｜｜DSML｜｜_wait>—brak</｜｜DSML｜｜_wait>` 3 razy aktywowało bezpiecznik zapętlenia, który przedwcześnie uciął połączenie i stłumił tekst przeprosin.

---

## 3. Zastosowane Rozwiązanie Deterministyczne

1. **Funkcja `_clean_dsml_wait(text: str) -> str` w `server.py`**:
   * Czyści w 100% bloki `<[|｜｜│\s]*DSML[|｜｜│\s]*_wait[^>]*>[\s\S]*?</[|｜｜│\s]*DSML[|｜｜│\s]*_wait\s*>` wraz z ich zawartością (`—brak`, `—无` itp.).
   * Usuwa pojedyncze i kwadratowe warianty tagu `_wait`.
2. **Włączenie do `_STRIP_TAGS`**:
   * Dodano regułę usuwania bloków `_wait` na samym początku `_STRIP_TAGS`, zapobiegając wyciekowi tekstu `—brak`.
3. **Udrożnienie pętli streamingowej**:
   * Badanie bufora `tail` oraz końcówki `remaining` odbywa się po uprzednim oczyszczeniu z `_wait`. Żaden normalny tekst nie jest blokowany.
4. **Wzmocniony Bezpiecznik Pustego Strumienia**:
   * Jeśli po wyczyszczeniu `_clean_dsml_wait` bufor jest pusty i `tools_yielded == 0`, proxy natychmiast wysyła jawny komunikat błędu:
     `[BŁĄD PROXY: Model DeepSeek wyemitował wewnętrzny znacznik bezczynności (_wait) zamiast wywołania narzędzia. Ponów polecenie.]`
5. **Korekta promptu koordynatora**:
   * Usunięto dogmatyczny zakaz `DO NOT use Read...`.
   * Wprowadzono precyzyjny podział ról: szerokie przeszukiwanie bazy kodu i czytanie dziesiątek plików zleca się subagentom, natomiast koordynator ma jawne zezwolenie na bezpośrednie używanie `Read/Write/Edit/SearchReplace` dla plików docelowych, o które prosi użytkownik.

---

## 4. Dowód Weryfikacji (Testy Automatyczne)

Wszystkie 8 nowych testów w `tests/test_bug033.py` oraz pełny zestaw 99 testów regresyjnych przechodzą bezbłędnie:
```bash
tests/test_bug033.py ........                                            [100%]
====================== 99 passed, 4 deselected in 0.52s =======================
```
