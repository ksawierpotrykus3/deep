# BUG-008: Emisja Pustego Dymka Asystenta (0 Tokenów / Ghost Bubble), Desynchronizacja `parent_id` i Zduplikowane Obietnice Narzędzi bez Egzekucji

**Data rejestracji:** 2026-08-31 20:14  
**Komponenty:** `server.py` (`generate()`, `_stream_source`, `_chunk({"role": "assistant"})`, `parent_id` State Tracker), DeepSeek Web Backend  
**Wpływ na działanie:** KRYTYCZNY (Wygenerowanie w Trae pustego dymka odpowiedzi z 0 tokenami i statusem 0%, rozbicie drzewa rozmowy w DeepSeek Web, pozorne deklaracje odczytów i zapisów bez fizycznego wywołania narzędzi).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu i monitora sesji)

### Incydent 1: Podwójna obietnica w górnym dymku bez wywołania `Write`
* **Treść wygenerowana u góry (ze zrzutu ekranu):**
  > `Mam pełny obraz obu projektów. Zaczynam naprawy modułu supervisor. Najpierw types.ts.`  
  > `Czytam pełny SupervisorView.tsx, żeby móc go edytować.`  
  > `Nie mam narzędzia Edit — użyję Write do nadpisania pliku. Zaczynam od types.ts.`
* **Wynik:** Model aż trzykrotnie zadeklarował chęć modyfikacji kodu, ale ani razu nie wyemitował skutecznego `tool_call` do Trae (tagi zostały urwane/połknięte zgodnie z BUG-007).

### Incydent 2: Całkowicie pusty dymek asystenta na dole (Ghost Bubble)
* **Objaw w Trae:** Po wysłaniu `kontynuuj` pojawił się pusty dymek `Agent` o zerowej wysokości, z paskiem narzędzi (Kopiuj/Retry) i statusem postępu **`0%`**.
* **Twardy dowód z monitora sesji (`data/sessions_monitor.json`):**
  ```json
  [0] session_id: 02933554 acc: 3 state: done tokens: 0 thinking: 0 age: 45.8s finished: True ok: True
  [1] session_id: 45fd152a acc: 3 state: done tokens: 0 thinking: 0 age: 53.0s finished: True ok: True
  ```
  Aż **dwie kolejne sesje z rzędu** zakończyły się wygenerowaniem dokładnie **0 TOKENÓW** i statusem `ok: True`.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Przedwczesna emisja chunka otwierającego rolę (`server.py:L3711`)
```python
try:
    yield _chunk({"role": "assistant"})
except GeneratorExit:
    return
```
Proxy wysyła do Trae chunk inicjujący dymek asystenta **zanim w ogóle odbierze choćby jeden bajt danych z DeepSeeka**. 
Jeśli backend DeepSeek natychmiast zamknie strumień bez wygenerowania żadnego słowa, Trae ma już otwarty pusty dymek w interfejsie użytkownika.

### B. Bezkrytyczne traktowanie pustego strumienia jako sukcesu (`tokens: 0 -> finished: True`)
Gdy iterator `stream` nie zwróci ani jednego tokena (pusta odpowiedź SSE z web chatu):
1. Pętla `for _ch in stream` natychmiast się kończy.
2. Proxy nie sprawdza, czy `content_buffer` zawiera jakąkolwiek treść.
3. Proxy wysyła:
   ```python
   yield _chunk({}, "stop")
   yield "data: [DONE]\n\n"
   ```
4. Trae uznaje, że asystent „celowo milczy” i kończy turę statusem sukcesu (`0%`).

### C. Desynchronizacja `parent_id` w sesji DeepSeek Web
W wyniku wcześniejszych uciętych odpowiedzi (BUG-006 i BUG-007), identyfikator wiadomości rodzica (`parent_message_id`) w stanie rozmowy stał się niespójny z bazą danych czatu DeepSeeka. Backend webowy otrzymał żądanie kontynuacji z nieistniejącym lub zablokowanym `parent_id`, co spowodowało natychmiastowe zakończenie odpowiedzi z pustym ciałem.

---

## 3. DETERMINISTYCZNA ARCHITEKTURA NAPRAWCZA

```mermaid
flowchart TD
    A[Odebranie żądania z Trae] --> B[Nawiąż połączenie z DeepSeek Web]
    
    B --> C{Czy odebrano pierwszy token treści lub myślenia?}
    
    C -->|Tak| D[Dopiero teraz wyemituj role: assistant i rozpocznij strumień do Trae]
    
    C -->|Nie, strumień pusty 0 tokenów| E{Liczba prób auto-retry < 2?}
    
    E -->|Tak| F[Zresetuj parent_id do ostatniej stabilnej wiadomości i ponów]
    E -->|Nie| G[ZWRÓĆ BŁĄD HTTP 502: Nie emituj pustego dymka [DONE]!]
```

### Zasady deterministycznej ochrony:
1. **Leniwa inicjalizacja roli (*Lazy Assistant Chunk*):**
   * Usunięcie sztywnego `yield _chunk({"role": "assistant"})` na starcie generatora. Chunk z rolą asystenta jest emitowany **wyłącznie wtedy, gdy proxy fizycznie odbierze pierwszy rzeczywisty token** z DeepSeeka.
2. **Zero-Token Guard (Zakaz pustych sukcesów):**
   * Jeśli generator DeepSeeka zakończy się z 0 wygenerowanymi tokenami: proxy bezwzględnie traktuje to jako błąd transportu (Transport Failure), a nie sukces.
3. **Automatyczna resynchronizacja `parent_id`:**
   * W przypadku pustego strumienia proxy czyści wadliwy `parent_id` z `_conv_state` i ponawia zapytanie z pełnym kontekstem historii w nowej sesji.
