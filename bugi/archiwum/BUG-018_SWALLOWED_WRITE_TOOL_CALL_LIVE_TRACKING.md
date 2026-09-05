# BUG-018: Połknięcie Niedomkniętego Tool-Calla (`Write` dla `liveTracking.ts`), Zrzut Awaryjny i Pozorny Sukces Tekstowy (Ghost Finish)

**Data rejestracji:** 2026-09-01 15:48  
**Komponenty:** `server.py` (`_stream`, `_has_unclosed_tool_call`, Crash Dump Logger), DeepSeek Web SSE Parser  
**Wpływ na działanie:** KRYTYCZNY (Model deklaruje utworzenie modułu `liveTracking.ts`, rozpoczyna generowanie kodu w narzędziu `Write`, po czym po urwaniu strumienia proxy bezpowrotnie wycina narzędzie z odpowiedzi; Trae uznaje turę za zakończoną na 1%, a plik fizycznie nie powstaje).

---

## 1. DOWODY EMPIRYCZNE (Objawy ze zrzutu ekranu i zrzutu awarii)

### Incydent: Zakończenie wypowiedzi ze statusem 1% i brak pliku na dysku
* **Objaw w Trae:**
  * Model napisał: *„Teraz wprowadzam zmiany. Zaczynam od nowego pliku typów i mechanizmu snapshotu.”*
  * Status: kółko postępu z **`1%`**, brak wywołania narzędzia, powrót do pola edycji tekstu.
* **Weryfikacja na dysku:**
  ```python
  os.path.exists("c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/cortex-app/src/shared/liveTracking.ts")
  # Wynik: False
  ```

### Twardy dowód ze zrzutu awaryjnego (`data/crashed_chats/crash_20260901_154728_jwt_leg_caoy_36c02ea3.md`)
```markdown
# Crash dump 20260901_154728
- conv_key: jwt_leg_caoyunxiang_7e69f2c0
- session_id: 36c02ea3-4e56-4973-b83e-0bf5f36060ed
- account_idx: 3
- reason: unclosed tool call aborted before completion

## Partial content:
Teraz wprowadzam zmiany. Zaczynam od nowego pliku typów i mechanizmu snapshotu.

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="Write">
<｜｜DSML｜｜parameter name="file_path" string="true">C:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\cortex-app\src\shared\liveTracking.ts</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="content" string="true">// ============================================================================
// Live Tracking — Snapshot widoku (funkcja eksperymentalna, domyślnie WYŁĄCZONA)
//
// Minimalna, samowystarczalna wersja "live tracking 1:1" tego, co użytkownik
// widzi na kanwie Cortex. Snapshot zapisujemy wyłącznie do localStorage
// renderera (klucz `cortex_live_snapshot`). Brak IPC, brak zapisu na dysk,
// brak wysyłki do AI — to dopiero fundament pod przyszły boczny chat.
// =========================================================================
```

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Ucięcie strumienia podczas generowania kodu TypeScript
Model rozpoczął prawidłowe wywołanie `Write` dla ścieżki `src/shared/liveTracking.ts`. W trakcie generowania kodu wewnątrz tagu `<parameter name="content">`, połączenie SSE ze strony DeepSeek Web zostało przerwane.

### B. Połknięcie narzędzia przez filtr proxy
Z powodu braku domknięcia tagów `</parameter></invoke></tool_calls>`, proxy:
1. Uznało narzędzie za uszkodzone (`unclosed tool call aborted`),
2. Zapisało zrzut do `data/crashed_chats/`,
3. **Usunęło cały blok kodu z odpowiedzi do Trae**,
4. Wysłało do Trae tylko wstęp tekstowy i znacznik `[DONE]`.

---

## 3. DETERMINISTYCZNA NAPRAWA

W Trae wystarczy wymusić ponowne zapisanie pliku bez czytania całego projektu:
> *„Utwórz plik `cortex-app/src/shared/liveTracking.ts` zawierający typy i mechanizm snapshotu do localStorage (klucz `cortex_live_snapshot`). Użyj narzędzia Write od razu.”*
