# BUG-004: Pętla Zagłady Auto-Continue ("kontynuuj"), Zatrucie Fazy Myślenia (Thinking Poisoning), 35k+ Przepalonych Tokenów i Blokada UI Trae

**Data rejestracji:** 2026-08-31  
**Komponenty:** `server.py` (`stream_completion`, `_stream`, `_auto_continue_budget`), `monitor.py`, DeepSeek Web API  
**Wpływ na działanie:** KRYTYCZNY (Zablokowanie edytora Trae na >10 minut, przepalenie ponad 35 600 tokenów w jednej turze, halucynacja modelu rozważającego intencje użytkownika, brak reakcji na UI).

---

## 1. DOWODY EMPIRYCZNE (Objawy z sesji na żywo, monitora i surowego strumienia)

### Incydent 1: Zwis interfejsu Trae na akcji odczytu pliku
* **Objaw:** Trae utknęło w stanie `Reading files...` / `Reading PLAN_NADZORCY.md` z kręcącym się spinnerem. Brak jakiejkolwiek aktualizacji tekstu na ekranie przez ponad 10 minut.
* **Stan w terminalu Proxy:** Niekończący się ciąg wywołań w pętli:
  ```text
  [AUTO-CONTINUE] attempt 1, budget left=1, parent=106 (content=244 chars, thinking=442 chars)
  [AUTO-CONTINUE] attempt 1, budget left=0, parent=108 (content=185 chars, thinking=532 chars)
  [AUTO-CONTINUE] attempt 1, budget left=1, parent=110 (content=176 chars, thinking=1944 chars)
  [AUTO-CONTINUE] attempt 1, budget left=0, parent=112 ...
  ```

### Incydent 2: Wskaźniki z monitora sesji (`data/sessions_monitor.json`)
* **Parametry aktywnej sesji `20c4a11ee98440969abb8320b681058e`:**
  * `age`: **626.4 s (10.5 minuty)**
  * `tokens`: **35 642 tokeny**
  * `thinking_tokens`: **12 500+ tokenów**
  * `state`: `active` / `thinking`, `finished`: `false`

### Incydent 3: Twardy dowód ze zrzutu surowego strumienia (`data/raw_stream_capture.jsonl`)
Przechwycony fragment tokenów generowanych w czasie rzeczywistym przez DeepSeek:
```json
{"p":"response/fragments/-1/content","o":"APPEND","v":" user"}
{"v":" keeps"}
{"v":" saying"}
{"v":" \""}
{"v":"kont"}
{"v":"yn"}
{"v":"u"}
{"v":"uj"}
{"v":"\""}
{"v":" ("}
{"v":"continue"}
{"v":")."}
{"v":" I"}
{"v":"'ve"}
{"v":" been"}
{"v":" trying"}
{"v":" to"}
{"v":" read"}
{"v":" the"}
{"v":" file"}
{"v":" but"}
{"v":" the"}
{"v":" tool"}
{"v":" calls"}
{"v":" seem"}
{"v":" to"}
{"v":" not"}
{"v":" be"}
{"v":" executing"}
{"v":" properly"}
{"v":"."}
```
**Dosłowny tekst z myśli modelu:**
> *"The user keeps saying 'kontynuuj' (continue). I've been trying to read the file but the tool calls seem to not be executing properly. Let me actually..."*

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Wstrzykiwanie słowa kluczowego `"kontynuuj"` do wątku konwersacji
W pliku [`server.py`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/server.py#L887):
```python
cont_res = self.stream_completion(
    account_idx, chat_session_id, "kontynuuj", resp_msg_id, ...
)
```
Gdy backend webowy DeepSeek ucina odpowiedź (np. limit długości fragmentu lub status `WIP`), proxy automatycznie wysyła prompt o treści `"kontynuuj"`. Webowy silnik DeepSeek rejestruje ten prompt jako **prawdziwą wiadomość użytkownika w czacie**.

### B. Rozszczepienie protokołu i konfuzja agenta
Model wyemitował początek wywołania narzędzia (`<invoke>...`), po czym otrzymał od proxy wiadomość `"kontynuuj"`. Model zinterpretował to jako ignorowanie narzędzia przez człowieka i zaczął filozofować w fazie `THINK`, dlaczego użytkownik nie wykonuje narzędzia, tylko pisze „kontynuuj”. 

### C. Niekontrolowana eskalacja budżetu Auto-Continue
Funkcja `stream_completion` wywołuje samą siebie w pętli z przekazywaniem `_auto_continue_budget`. Dopóki model generuje choćby 1 token w statusie `WIP`, proxy uznaje, że strumień żyje i wysyła kolejne żądanie `"kontynuuj"`. W ten sposób sesja wygenerowała kilkadziesiąt zapytań PoW i ponad 35k tokenów.

### D. Ślepota detektora pętli (`_detect_loop`) na bufor `thinking_buffer`
Mechanizm anty-loop w proxy analizował wyłącznie `content_buffer` (który był krótki, bo zawierał tylko ucięte tagi). Cała pętla 12 500 tokenów toczyła się w `thinking_buffer`, który nie był objęty żadną analizą zapętlenia.

---

## 3. DETERMINISTYCZNA ARCHITEKTURA NAPRAWCZA I BEZPIECZNIKI

```mermaid
flowchart TD
    A[Wykryto ucięty strumień lub WIP w DeepSeek Web] --> B{Jaki jest stan bufora?}
    
    B -->|Niedomknięty tool call| C{Czy auto_continue_count >= 2?}
    C -->|Tak (Osiągnięto limit 2 prób)| D[TWARDY ABORT: Domknij sztucznie tag narzędzia i wyślij do Trae]
    C -->|Nie| E[Wyślij auto-continue z precyzyjną instrukcją techniczną]
    
    B -->|Faza Thinking > 3000 tokenów| F[THINKING CIRCUIT BREAKER: Przerwij sesję, wymuś start RESPONSE]
    
    E --> G{Czy w myśleniu modelu wykryto pętlę fraz 'keeps saying' / 'kontynuuj'?}
    G -->|Tak| H[LOOP DETECTED: Natychmiastowy stop sesji finish_reason='stop']
    G -->|Nie| I[Kontynuuj odbiór strumienia]
```

### Zasady deterministycznej ochrony:
1. **Twardy limit prób Auto-Continue (Max 2 iteracje):**
   * Zmniejszenie maksymalnego budżetu `_auto_continue_budget` z wartości nieskończonej/płynnej do **sztywnego limitu 2 powtórzeń**. Jeśli model po 2 próbach nie zamknie odpowiedzi – tura zostaje natychmiast przerwana.
2. **Thinking Budget Cap (Limit myślenia per tura):**
   * Jeśli faza `thinking_tokens` przekroczy próg **3 000 tokenów** bez wygenerowania ani jednego tokena odpowiedzi (`RESPONSE`) – proxy automatycznie przerywa generowanie.
3. **Thinking Loop Guard (Analiza n-gramów w myśleniu):**
   * Objęcie bufora `thinking_buffer` detektorem powtórzeń i fraz o zatruciu sesji (np. `user keeps saying`, `stuck in loop`).
4. **Syntaktyczny Auto-Close dla Tool Calli:**
   * Jeśli model urwie strumień wewnątrz `<invoke ...>`, proxy zamiast wysyłać `"kontynuuj"`, samodzielnie dokleja brakujący tag zamykający `</invoke>` i oddaje sterowanie do Trae.
