# DeepSeek Proxy — Server Fixes Design

**Date:** 2026-06-28
**Status:** approved
**Scope:** 9 poprawek w pojedynczym pliku `deepseek-proxy/server.py`

## Overview

Na podstawie audytu kodu zidentyfikowano 9 nieprawidłowości. Ten dokument opisuje każdą z nich wraz z implementacją.

Wszystkie zmiany w jednym pliku `server.py`. Bez nowych plików, bez nowych zależności. Każda zmiana niezależna.

---

## Fix 1: `_get_conv_key()` — użycie JWT z acl-token

**Problem:** Funkcja używa pierwszej wiadomości user jako fingerprintu konwersacji. Jeśli wiele czatów zaczyna się tą samą wiadomością (np. "Cześć"), dostają ten sam `conv_key` i serwer próbuje kontynuować starą sesję DeepSeek.

**Rozwiązanie:** Funkcja `_get_conv_key()` przyjmie dodatkowy parametr `acl_payload` (dict zdekodowany z JWT). Jeśli zawiera `sub`, `session`, `conv`, `chat` lub `sid` — użyje go jako klucza. Fallback: ostatnia wiadomość user (iteracja od końca, nie `break` po pierwszej).

**Plik:** `server.py`, linie 747-763
**Sygnatura:** `_get_conv_key(messages: list[dict], acl_payload: dict | None = None) -> str`

---

## Fix 2: Thread-safety dla `_conv_state`

**Problem:** Brak synchronizacji dla globalnego słownika `_conv_state`. Concurrent requesty mogą nadpisać stan, prowadząc do utraty `parent_id` lub duplikacji sesji.

**Rozwiązanie:** Dodać `_conv_lock = threading.Lock()`. Wszystkie operacje na `_conv_state` (odczyt, zapis, pop, save) opakować w `with _conv_lock:`.

**Plik:** `server.py`, linia 634 (obok `_auth_lock`)
**Miejsca do opakowania:** ~8 lokalizacji w handlerze `/v1/chat/completions` i funkcjach pomocniczych

---

## Fix 3: Obsługa `tool_choice`

**Problem:** Pole `tool_choice` zdefiniowane w `ChatRequest` ale nigdy nie odczytywane.

**Rozwiązanie:** Logika w handlerze:
- `"none"` → `tools = None`, pomiń sekcję `# Available Tool Schemas` w prompcie
- `"required"` → dodaj `\n\nYou MUST call at least one tool in your response.` do prompta
- `"auto"` lub brak → bez zmian (domyślne zachowanie)
- `{"type": "function", "function": {"name": "X"}}` → filtruj `tools` tylko do wskazanego narzędzia

**Plik:** `server.py`, po linii ~847 (po `_get_conv_key`)

---

## Fix 4: Warunek resume `>=` zamiast `>`

**Problem:** `len(req.messages) > state.get("msgs_len", 0)` — przy retry Trae z tą samą liczbą wiadomości, warunek nie jest spełniony i tworzona jest nowa sesja z pełną historią (duplikacja kontekstu).

**Rozwiązanie:** Zmienić `>` na `>=`. Dodać logikę: jeśli `len == msgs_len`, wysłać tylko ostatnią wiadomość (retry detection).

**Plik:** `server.py`, linia 844

---

## Fix 5: Race condition w `_ensure_auth()`

**Problem:** Sprawdzenie `is_valid()` i `validate_remote()` przed blokadą `_auth_lock` — dwa wątki mogą jednocześnie przejść walidację i oba otworzyć przeglądarkę.

**Rozwiązanie:** Przenieść sprawdzenia POD `with _auth_lock:`, zachowując wczesne wyjście dla już zalogowanej sesji sprzed locka (fast path).

**Plik:** `server.py`, linie 636-657

---

## Fix 6: Tools w ścieżce resume

**Problem:** `_build_prompt(new_msgs, tools=tools)` — jeśli `req.tools` jest puste (co jest typowe przy kontynuacji konwersacji), tools z cache/stanu nie są przekazywane.

**Rozwiązanie:** `tools=tools or state.get("tools")`

**Plik:** `server.py`, linia 858

---

## Fix 7: Przekazywanie `max_tokens`, `temperature`, `top_p` do DeepSeek

**Problem:** Parametry zdefiniowane w `ChatRequest` ale nie wysyłane w body do DeepSeek API.

**Rozwiązanie:** Dodać do JSON body w `stream_completion()`:
```python
"max_tokens": max_tokens,
"temperature": temperature,
"top_p": top_p,
```
Metoda `stream_completion()` otrzyma dodatkowe parametry.

**Plik:** `server.py`, linie 152-162 oraz wywołanie w handlerze

---

## Fix 8: `usage` — estymacja tokenów

**Problem:** `usage` zawsze zwraca `{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}`.

**Rozwiązanie:** DeepSeek nie zwraca token counts w API. Dla non-stream: estymować `len(full_text) // 4`. Dla stream: estymować `len(full) // 4`.

**Plik:** `server.py`, linie 947 i 1056

---

## Fix 9: `system_fingerprint`

**Problem:** Brak pola `system_fingerprint` w odpowiedzi.

**Rozwiązanie:** Dodać `"system_fingerprint": "fp_deepseek_proxy_v1"` do:
- Non-stream response (linia ~943)
- Każdego chunka SSE w funkcji `_chunk()` (linia ~954)

**Plik:** `server.py`