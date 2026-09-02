# BUG-020: Zacięcie Strumienia Edycji `NotesCanvas.tsx` z Powodu Kolizji z Tłem (0 Tokenów na Zablokowanym `acc: 3`) i Nienaprawiony Błąd Typów

**Data rejestracji:** 2026-09-01 16:00  
**Komponenty:** `server.py` (Slot Deadlock, Zero-Token Leak), DeepSeek Web Account Rotation, Trae Execution  
**Wpływ na działanie:** KRYTYCZNY (Agent zaktualizował `useLiveTracking.ts`, 4 razy odczytał `NotesCanvas.tsx`, po czym kolejne zapytanie zderzyło się z wiszącą sesją 14k tokenów na koncie 3 i zwróciło 0 tokenów; błąd kompilacji TypeScript w `NotesCanvas.tsx` pozostał nienaprawiony).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu i monitora sesji)

### Incydent 1: Nagłe urwanie po 4 odczytach `NotesCanvas.tsx`
* **Sekwencja w Trae (ze zrzutu ekranu):**
  * `Read NotesCanvas.tsx` x4
  * `Created 1 file` $\rightarrow$ `useLiveTracking.ts` (+21, -23)
  * Brak jakiejkolwiek odpowiedzi tekstowej, powrót do pola edycji i status zakończenia.
* **Stan kompilacji (`npx tsc --noEmit`):**
  ```text
  src/components/NotesCanvas.tsx(2190,30): error TS2304: Cannot find name 'liveTrackingEnabled'.
  src/components/NotesCanvas.tsx(2191,33): error TS2304: Cannot find name 'setLiveTrackingEnabled'.
  ```
  Agent nie zdążył wstawić poprawki do `NotesCanvas.tsx`.

### Incydent 2: Twardy dowód kolizji w monitorze sesji (`data/sessions_monitor.json`)
W momencie tego żądania na koncie `acc: 3` wisiała nieukończona sesja generująca gigantyczny strumień:
```json
[0] session_id: e3a28b0a... acc: 3 | state: active | tokens: 14 480 | thinking: 7 627 | age: 278.6s (prawie 5 minut!)
[1] session_id: d1eee880... acc: 3 | state: done   | tokens: 0      | thinking: 0     | age: 6.6s  | ok: True
[2] session_id: 5c5b3f84... acc: 3 | state: done   | tokens: 0      | thinking: 0     | age: 35.4s | ok: True
```
Gdy Trae wysłało zapytanie o dokończenie edycji, zapytanie uderzyło w zajęty slot konta 3, DeepSeek zwrócił **0 tokenów**, a proxy odesłało `[DONE]`.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Brak ochrony przed nakładaniem się sesji (*Slot Deadlock*)
W pliku `server.py` konto 3 było bez przerwy okupowane przez sesję `e3a28b0a`. Zamiast odrzucić nowe żądanie kodem 429 lub zrotować do innego wolnego konta (np. konto 1, 2, 4), proxy wysłało nowe zapytanie do tego samego konta 3, które natychmiast zwróciło pusty strumień.

### B. Interwencja naprawcza
Wszystkie wiszące sesje zombie w proxy zostały zatrzymane przez wysłanie sygnałów stopu.

---

## 3. DETERMINISTYCZNA NAPRAWA

Naprawa w Trae:
Otwórz nowy czat lub wklej bezpośrednie polecenie naprawy:
> *„Dodaj na samej górze `src/components/NotesCanvas.tsx`: `import { useLiveTracking } from './canvas/useLiveTracking';` oraz wewnątrz komponentu: `const { liveTrackingEnabled, setLiveTrackingEnabled } = useLiveTracking({ activeProjectIdRef: activeProjectRef, offsetRef: panRef, scaleRef: useRef(scale), selectedIdsRef: useRef(selectedIds) });`. Zapisz plik natychmiast narzędziem Write.”*
