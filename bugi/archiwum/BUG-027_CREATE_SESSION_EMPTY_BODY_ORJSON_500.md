# BUG-027: Błąd Tworzenia Sesji DeepSeek (`orjson.JSONDecodeError: Input is a zero-length, empty document`) Powodujący HTTP 500 w Proxy i Błąd `5400001` w Trae IDE

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (`server.py`)  
**Status:** Rozwiązany / Zweryfikowany testami jednostkowymi (`tests/test_bug027.py` PASS, 76 testów przeszło)  
**Dotknięte komponenty:** `server.py` (`DeepSeek.create_session`, `DeepSeek.create_session_with_fallback`, `start_silent.bat`)  
**Dowód wizualny:** `media_1788602035216.png` w Trae IDE: `Model Request failed, please try again later. (5400001) | Abnormally stopped | 0%`  

---

## 1. Objawy Awarii (Objawy Widoczne w GUI Trae)

Po restarcie proxy i wznowieniu pracy agenta w Trae IDE natychmiast po uruchomieniu pojawił się błąd:
> `Model Request failed, please try again later. (5400001)`  
> `Abnormally stopped | 0%`

Przed zatrzymaniem Trae wielokrotnie odczytał gigantyczny plik zadania (`Kontynuuj Zadanie AI Not Responding Issue.md`), a następnie 3-krotnie uruchomił procedurę `History Chats Compacted` (kompresję historii czatu).

---

## 2. Dowody z Logów Proxy (`data/server_errors.log`)

W pliku `data/server_errors.log`:
```text
  File "C:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\deepseek-proxy-clean\server.py", line 2815, in chat_completions
    return _chat_completions_impl(req, raw_request)
  File "C:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\deepseek-proxy-clean\server.py", line 3206, in _chat_completions_impl
    chat_id = ds.create_session(account_idx)
  File "C:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\deepseek-proxy-clean\server.py", line 521, in create_session
    resp_json = r.json()
  File "C:\Users\Ksawier\AppData\Local\Programs\Python\Python313\Lib\site-packages\curl_cffi\requests\models.py", line 253, in json
    return loads(self.content, **kw)
orjson.JSONDecodeError: Input is a zero-length, empty document: line 1 column 1 (char 0)
```

---

## 3. Przyczyna Źródłowa (Root Cause Analysis)

1. **Chwilowa utrata pakietu / pusty dokument od serwera DeepSeek**:
   Endpoint `https://chat.deepseek.com/api/v0/chat_session/create` pod obciążeniem może zwrócić status z pustym body (`0 bajtów`).
   Biblioteka `curl_cffi` nie traktuje 0 bajtów jako wyjątku sieciowego (`CurlConnectionError`), lecz zwraca pusty obiekt `Response`.
   Wywołanie `r.json()` natychmiast rzucało `orjson.JSONDecodeError`.
2. **Brak retry i brak failoveru na inne konta w puli**:
   Dotychczasowa metoda `create_session(account_idx)` nie ponawiała próby po odebraniu pustego dokumentu i nie pozwalała na rotację konta, co bąbelkowało do FastAPI jako nieobsłużony błąd i zwracało Trae HTTP 500. Kod błędu `(5400001)` w Trae IDE oznacza kod HTTP 500 z customowego API.
3. **Konflikt portów `start_silent.bat` vs Trae**:
   Skrypt `start_silent.bat` uruchamiał proxy na porcie `8790` bez ubicia starego procesu, podczas gdy Trae wysyłał żądania na port `4570` (gdzie w tle wisiał proces z 11:52 ze starym kodem).

---

## 4. Wprowadzone Poprawki

1. **Wzmocnienie `create_session` o weryfikację zawartości i retry**:
   - Sprawdzenie `r.status_code == 200` oraz czy `r.content` nie jest puste.
   - Pętla ponawiania (do 3 prób z odstępami 1s i 2s) w przypadku przejściowego pustego body.
2. **Dodanie mechanizmu `create_session_with_fallback(preferred_idx)`**:
   - W przypadku niepowodzenia konta preferowanego, proxy automatycznie iteruje po wszystkich pozostałych aktywnych kontach w puli.
   - Po znalezieniu działającego konta aktualizuje `account_idx` w sesji oraz w `conv_state`, nie przerywając żądania użytkownika.
3. **Zastąpienie bezpośrednich wywołań w `server.py`**:
   - Wszystkie 7 miejsc tworzenia sesji (inicjalizacja rozmowy, chunked ingestion, reactive chunking, session rotation, stream generator) korzystają teraz z `create_session_with_fallback`.
4. **Naprawa `start_silent.bat`**:
   - Wyrównano port do domyślnego `4570`, dodano czyszczenie procesów nasłuchujących na 4570 oraz czyszczenie pamięci podręcznej `__pycache__`.

---

## 5. Weryfikacja Deterministyczna

- Utworzono test jednostkowy `tests/test_bug027.py` testujący:
  1. Retry na pustym dokumencie (`test_create_session_retries_on_empty_response` -> PASS)
  2. Rzucanie błędu po wyczerpaniu ponowień (`test_create_session_raises_on_persistent_empty_body` -> PASS)
  3. Automatyczny failover na drugie konto (`test_create_session_with_fallback_switches_account` -> PASS)
  4. Obsługę sytuacji wyczerpania wszystkich kont (`test_create_session_with_fallback_all_fail` -> PASS)
  5. Asynchroniczne uruchomienie streamingu SSE bez błędu zakresu zmiennych (`test_generate_stream_does_not_raise_unbound_local_error` -> PASS)
- Pełny zestaw testów: `pytest -q` -> **77 passed**.

---

## 6. Addendum: Poprawka Zakresu Zmiennych w `generate()` (`UnboundLocalError`)

Podczas pierwszego żądania strumieniowego z Trae IDE wystąpił błąd:
```text
UnboundLocalError: cannot access local variable 'account_idx' where it is not associated with a value
  at line 4003: _slot_busy[account_idx] = True
```
Przyczyna: Wewnątrz funkcji zagnieżdżonej `generate()` w bloku rotacji sesji przypisano wartość do `account_idx` (`new_session_id, account_idx = ...`), co w Pythonie powoduje uznanie zmiennej za lokalną w całym ciele funkcji. Zmienna została przemianowana na `rot_account`, a test asynchroniczny `test_generate_stream_does_not_raise_unbound_local_error` deterministycznie potwierdził brak błędu.
Odpowiedź strumieniowa na żywo została zweryfikowana testem z 59 pakietami chunków SSE.