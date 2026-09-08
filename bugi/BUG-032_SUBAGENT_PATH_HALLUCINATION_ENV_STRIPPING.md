# BUG-032: Subagent Path Hallucination caused by Stripping Environment Context

**Data**: 2026-09-08
**Status**: Naprawiony (Deterministic Fix + 4 Testy Jednostkowe)
**Komponent**: `server.py` (`_extract_environment_info`, `_clean_system_reminders`, Subagent Prompt Injection)

---

## 1. Objawy i Zgłoszenie Użytkownika

* **Zrzut ekranu / Widok w Trae IDE**:
  * Tytuł: `Search Agent Outputting...` (Subagent w Trae IDE)
  * Sekcja `Thought >`: 7 czerwonych błędów:
    * `Failed to read KosmosView.tsx (!)`
    * `Failed to read KosmosView.test.tsx (!)`
    * `Failed to read StorageEngine.ts (!)`
    * `Failed to read ElectronIpcBridge.ts (!)`
    * `Failed to read KosmosScanner.ts (!)`
    * `Failed to read preload.ts (!)`
    * `Failed to read index.ts (!)`
  * Pod spodem: `Read 29 files, Searched files 7 times`.
* **Pytanie użytkownika**: *"czm fail"* (Dlaczego to padło na czerwono?).

---

## 2. Przyczyna Źródłowa (Root Cause Analysis)

1. **Wymóg narzędzia Read w Trae**:
   Definicja narzędzia `Read` (`data/tools_cache.json`) zawiera kategoryczną instrukcję:
   `"The file_path parameter must be an absolute path, not a relative path"`.
2. **Ucięcie środowiska przez Proxy**:
   * Trae przekazuje informacje o systemie operacyjnym i katalogu roboczym wewnątrz tagu `<system-reminder>`:
     `Primary working directory: c:\Users\Ksawier\Pictures\Screenshots`
     `Operating system: windows`
   * Funkcja `_clean_system_reminders` w `server.py` bezwarunkowo usuwała wszystkie tagi `<system-reminder>`, aby chronić okno kontekstowe (oszczędność 5-10k znaków).
   * Prompt subagenta był podmieniany na 659-znakową generyczną instrukcję, która **nie zawierała ani ścieżki roboczej, ani nazwy systemu operacyjnego**.
3. **Ślepa halucynacja modelu**:
   * Główny agent zlecił subagentowi: *„Przeczytaj pełną zawartość: src/components/KosmosView.tsx...”* (ścieżka względna).
   * Model DeepSeek został postawiony pod ścianą: Trae zakazało ścieżek względnych, a proxy wycięło ścieżkę absolutną.
   * Model zmyślił ścieżkę z macOS z danych treningowych:
     `Read({"file_path": "/Users/kamil/Projekty/electron-kosmos/src/components/KosmosView.tsx"})` (dla 7 plików).
     *(W innej sesji zmyślił ścieżkę linuksową `/home/user/src/...`)*.
4. **Odrzucenie przez Trae i Self-Healing**:
   * Trae na Windowsie zwróciło: `<toolcall_error_message>File does not exist: /Users/kamil/...`.
   * Subagent po 7 błędach samorzutnie odratował sytuację wywołując `Glob({"pattern": "**/KosmosView.tsx"})` (7 razy), znalazł prawdziwe pliki w `Projekty_autorskie\cortex-app`, przeczytał 29 plików i ukończył zadanie.
   * Niemniej jednak wywołało to opóźnienia, zmarnowane zapytania i czerwone alerty w UI.

---

## 3. Zastosowane Rozwiązanie Deterministyczne

1. **`_extract_environment_info(messages)` w `server.py`**:
   * Bez naruszania oszczędności kontekstu, funkcja precyzyjnie parsuje `Primary working directory` oraz `Operating system` z przychodzącego `<system-reminder>`.
   * Zachowuje stan w `_last_known_env` z automatycznym fallbackiem do środowiska lokalnego, jeśli w danej klatce zabraknie tagu.
2. **Precyzyjne Wstrzyknięcie Środowiska do Promptu Subagenta**:
   * Prompt subagenta otrzymuje jawny blok:
     ```text
     ENVIRONMENT:
     - Operating system: {os}
     - Primary workspace root: {cwd}
     PATH & TOOL RULES:
     - Read tool strictly requires an existing absolute path. NEVER guess or invent non-existent absolute paths like /Users/... or /home/...
     - If you are given a relative path (e.g. 'src/...'), a filename, or do not know the exact absolute path on {os}, ALWAYS invoke 'Glob' (e.g. pattern='**/filename.tsx') or 'LS' first to locate the exact path before calling 'Read'!
     - If you already have the verified full path on {os}, you can call 'Read' directly.
     ```
3. **Instrukcja Koordynatora dla Głównego Agenta**:
   * Dodano wskazówkę, by przy delegowaniu zadań do subagentów podawać pełniejsze ścieżki projektu (uwzględniając podfoldery) lub nakazywać lokalizację przez `Glob`.

---

## 4. Weryfikacja Deterministyczna

* Utworzono zestaw testów `tests/test_bug032.py`:
  1. `test_extract_environment_info_standard`: Ekstrakcja CWD i OS z przypomnienia.
  2. `test_extract_environment_info_escaped_newlines`: Obsługa znaków nowej linii w JSON.
  3. `test_extract_environment_info_fallback`: Prawidłowe działanie fallbacku.
  4. `test_subagent_prompt_injection`: Poprawne wstrzyknięcie reguł do promptu subagenta.
* Cała suita testowa: **91 passed, 0 failed**.
