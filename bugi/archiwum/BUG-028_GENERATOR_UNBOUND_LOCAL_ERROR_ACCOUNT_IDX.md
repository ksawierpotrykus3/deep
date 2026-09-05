# BUG-028: Błąd Zasięgu Zmiennej w Generatorze Strumienia (`UnboundLocalError: cannot access local variable 'account_idx'`) Powodujący Natychmiastową Awarię Żądań SSE

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (`server.py`)  
**Status:** Rozwiązany / Zweryfikowany testami jednostkowymi (`tests/test_bug027.py::test_generate_stream_does_not_raise_unbound_local_error` PASS)  
**Dotknięte komponenty:** `server.py` (`_chat_completions_impl.generate`)  
**Dowód wizualny:** `media_1788603471428.png` w Trae IDE: model zamrożony na `2%`, brak odpowiedzi  

---

## 1. Objawy Awarii

Po wdrożeniu poprawki BUG-027 pierwsze żądanie wysłane przez użytkownika w Trae IDE zablokowało się natychmiast na wskaźniku postępu **`2%`**. Serwer w tle zakończył działanie z kodem błędu 1.

---

## 2. Dowody z Logów Proxy

W logu ASGI / Uvicorn zarejestrowano wyjątek:
```text
  File "server.py", line 4003, in generate
    _slot_busy[account_idx] = True
UnboundLocalError: cannot access local variable 'account_idx' where it is not associated with a value
```

---

## 3. Przyczyna Źródłowa (Root Cause Analysis)

W języku Python, jeśli zmienna jest gdziekolwiek w ciele funkcji celem przypisania (`var = ...`), kompilator oznacza tę zmienną jako **lokalną dla całego zasięgu tej funkcji**.

W funkcji `generate()` (zagnieżdżonej wewnątrz `_chat_completions_impl`) w bloku obsługi wyczerpania kontekstu dodano wywołanie:
```python
new_session_id, account_idx = ds.create_session_with_fallback(account_idx)
```
Instrukcja ta sprawiła, że zmienna `account_idx` przestała być traktowana jako zmienna domknięcia (z funkcji nadrzędnej `_chat_completions_impl`), lecz jako zmienna lokalna funkcji `generate()`.

W rezultacie, na samym początku generatora przy próbie oznaczenia slotu jako zajętego:
```python
_slot_busy[account_idx] = True
```
Python zgłosił błąd `UnboundLocalError`, ponieważ lokalna zmienna `account_idx` nie miała jeszcze przypisanej wartości w tym punkcie wykonania.

Testy jednostkowe nie wykryły tego błędu wcześniej, ponieważ żądania z parametrem `stream=False` omijają generator `generate()` i zwracają natychmiastowy słownik JSON, podczas gdy Trae IDE zawsze wysyła żądania ze `stream=True`.

---

## 4. Wprowadzona Poprawka

1. W `server.py` wewnątrz `generate()` zmienna w bloku rotacji została przemianowana na `rot_account`:
   ```python
   new_session_id, rot_account = ds.create_session_with_fallback(account_idx)
   state["ds_session"] = new_session_id
   state["account"] = rot_account
   ```
2. Do pliku `tests/test_bug027.py` dodano asynchroniczny test jednostkowy `test_generate_stream_does_not_raise_unbound_local_error`, który bezpośrednio weryfikuje pobieranie pierwszego chunku z generatora bez rzucenia błędu zakresu zmiennych.
3. Zweryfikowano działanie na żywo żądaniem HTTP z `stream=True`, które odebrało 59 pakietów danych i zakończyło się statusem 200 OK.