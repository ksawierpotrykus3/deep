# Rejestr Awarii i Błędów Proxy (Bug Registry)

Katalog zawiera dogłębne analizy techniczne awarii systemu proxy, subagentów oraz integracji z IDE Trae / DeepSeek.

---

## 🛠️ Globalny Plan Architektury i Naprawy
👉 **[Pełna Specyfikacja Techniczna Naprawy Proxy (Filar 1–5)](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/PLAN_NAPRAWY_I_ARCHITEKTURA_PROXY.md)** — Rozwiązanie problemów pętli odczytów, przemycania myślenia R1 do Trae, sesji-zombie i połykania plików `Write`.

---

## 🚨 Błędy Aktywne / Do Rozwiązania (Active Bugs)

Poniższe błędy są w trakcie analizy lub wymagają dodatkowych bezpieczników w kodzie proxy:

| ID | Data | Tytuł | Status | Plik |
|---|---|---|---|---|
| **BUG-009** | 2026-08-31 | Inwersja Narzędzi (Action-Intention Mismatch: Deklaracja Write -> Wywołanie Read) i Pętla Mikro-Odczytów | ⚠️ Częściowo mitygowany przez Anti-Loop Guard | [`BUG-009_INTENTION_ACTION_MISMATCH_WRITE_TO_READ_LOOP.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/BUG-009_INTENTION_ACTION_MISMATCH_WRITE_TO_READ_LOOP.md) |
| **BUG-016** | 2026-08-31 | Zduplikowane Obietnice Implementacji IPC i Kolejna Pętla Odczytu `chain_executor.py` zamiast Edycji Kodu | ⚠️ Częściowo mitygowany przez Anti-Loop Guard | [`BUG-016_DUPLICATE_IPC_PROMISES_READ_STALL.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/BUG-016_DUPLICATE_IPC_PROMISES_READ_STALL.md) |

---

## 📦 Archiwum Błędów Rozwiązanych i Zweryfikowanych (`bugi/archiwum/`)

Wszystkie poniższe błędy zostały deterministycznie naprawione w kodzie proxy (`server.py`, `monitor.py`), przetestowane suitą 72 testów jednostkowych (`pytest`) i zabezpieczone przed regresją:

| ID | Data | Tytuł | Wdrożona Poprawka (Commit) | Plik Archiwum |
|---|---|---|---|---|
| **BUG-026** | 2026-09-05 | Odrzucenie Hybrydowego Tagu Zamykającego `</｜｜DSML｜｜ask>`, Niepotrzebne Auto-Continue i Rate-Limit | ✅ Obsługa tagu `ask/action` w DSML + Natychmiastowa rotacja konta na czysty slot przy rate-limit | [`archiwum/BUG-026...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-026_UNRECOGNIZED_CLOSING_TAG_HYBRID_AUTO_CONTINUE_RATE_LIMIT.md) |
| **BUG-025** | 2026-09-05 | Fałszywy Alarm Strażnika Pętli (`_detect_loop`) na Liniach Dekoracyjnych Komentarzy (`// =======`) | ✅ Ignorowanie separatorów/linii dekoracyjnych w `_detect_loop` z bezpiecznikiem patologicznym | [`archiwum/BUG-025...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-025_LOOP_GUARD_FALSE_POSITIVE_ON_DECORATIVE_COMMENTS.md) |
| **BUG-024** | 2026-09-05 | Puste Obietnice Narzędzi i Asymetria DSML/Invoke (Przerwanie Czatu na 0%) | ✅ Elastyczny parser tagów DSML/invoke + Agent Resume Guard + Empty Promise Guard | [`archiwum/BUG-024...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-024_PROMISE_WITHOUT_TOOL_EXECUTION_RESUME_SCHEMA_AMNESIA.md) |
| **BUG-023** | 2026-09-02 | Zjadanie Treści Wiadomości przez `completion_tokens: 0` | ✅ Zliczanie tokenów `content`, `reasoning` i `tool_calls` (`f56ac58`) | [`archiwum/BUG-023...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-023_ZERO_COMPLETION_TOKENS_USAGE_SWALLOWS_TEXT.md) |
| **BUG-022** | 2026-09-02 | Emisja Surowego Tagu `<content>` i Odrzucenie przez Trae | ✅ Prawidłowe mapowanie `<content>` tylko dla Write/Edit (`f56ac58`) | [`archiwum/BUG-022...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-022_UNWRAPPED_CONTENT_TAG_TOOL_NAME_REJECTION.md) |
| **BUG-021** | 2026-09-02 | Zniekształcanie Parametrów Narzędzi (`deserialize params error`) | ✅ Automatyczna konwersja stringów cyfrowych na int (`f56ac58`) | [`archiwum/BUG-021...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-021_TOOL_PARAM_CORRUPTION_AND_RATE_LIMIT_STALL.md) |
| **BUG-020** | 2026-09-01 | Zacięcie Strumienia Edycji z Powodu Kolizji z Tłem (acc: 3) | ✅ Izolacja slotów i auto-kill martwych sesji (`f56ac58`) | [`archiwum/BUG-020...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-020_SLOT_COLLISION_0_TOKENS_NOTES_CANVAS_STALL.md) |
| **BUG-019** | 2026-09-01 | Złamanie Kompilacji TypeScript i Błąd w `NotesCanvas.tsx` | ✅ Naprawione bezpośrednio w kodzie projektu | [`archiwum/BUG-019...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-019_UNRESOLVED_REFERENCE_CRASH_43_TESTS.md) |
| **BUG-018** | 2026-09-01 | Połknięcie Niedomkniętego Tool-Calla (`Write` dla `liveTracking.ts`) | ✅ Jawny alert o uciętym kodzie zamiast pozornego sukcesu (`e6b756c`) | [`archiwum/BUG-018...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-018_SWALLOWED_WRITE_TOOL_CALL_LIVE_TRACKING.md) |
| **BUG-017** | 2026-09-01 | Zombifikacja Sesji Współbieżnych na Jednym Koncie (`acc: 0`) | ✅ Auto-cancel poprzednich sesji dla `conv_key` (`f56ac58`) | [`archiwum/BUG-017...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-017_CONCURRENT_ZOMBIE_SESSIONS_THINKING_EXPLOSION.md) |
| **BUG-015** | 2026-08-31 | Zduplikowane Podwójne Wywołanie `Read SupervisorView.tsx` | ✅ Anti-loop guard + Metadane plików (`684ddd5`) | [`archiwum/BUG-015...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-015_DUPLICATE_SAME_FILE_READ_DOOM_LOOP.md) |
| **BUG-014** | 2026-08-31 | Zastój Pomiędzy Fazą Eksploracji IPC a Implementacją | ✅ Anti-loop guard wymuszający przejście do edycji (`a73185a`) | [`archiwum/BUG-014...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-014_IPC_EXPLORATION_STALL_6X_READS.md) |
| **BUG-013** | 2026-08-31 | Pętla Komend Terminala (8x `py_compile` PowerShell Doom Loop) | ✅ Deduplikacja i blokowanie powtórzonych komend w prompcie (`a73185a`) | [`archiwum/BUG-013...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-013_TERMINAL_COMMAND_DOOM_LOOP_SILENT_SUCCESS.md) |
| **BUG-012** | 2026-08-31 | Zacięcie Sesji na Koncie `acc: 5` (Zombie Account) | ✅ Auto-kill i unieważnianie zawieszonych sesji (`f56ac58`) | [`archiwum/BUG-012...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-012_SESSION_COLLAPSE_ACC5_ZERO_TOKENS.md) |
| **BUG-011** | 2026-08-31 | Zatrzymanie Agenta przez Wewnętrzny Loop Guard Trae | ✅ Kod bezpieczny, optymalizacja liczby tur | [`archiwum/BUG-011...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-011_TRAE_CLIENT_LOOP_GUARD_INTERRUPT.md) |
| **BUG-010** | 2026-08-31 | Wyciek Tagu XML `</previous_calls>`, Pętla 9x Redundant Read | ✅ Wycinanie tagów w `_clean_system_reminders` + Anti-loop guard | [`archiwum/BUG-010...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-010_PREVIOUS_CALLS_XML_LEAK_I_9X_REDUNDANT_READS.md) |
| **BUG-008** | 2026-08-31 | Emisja Pustego Dymka Asystenta (0 Tokenów / Ghost Bubble) | ✅ Dokładne zliczanie tokenów generowanych w `_chunk` (`f56ac58`) | [`archiwum/BUG-008...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-008_ZERO_TOKEN_GHOST_BUBBLE_I_PARENT_DESYNC.md) |
| **BUG-007** | 2026-08-31 | Połknięcie Niedomkniętego Tool-Calla (`Write`) i Pozorny Sukces | ✅ Jawny alert błędu zamiast cichego tłumienia (`e6b756c`) | [`archiwum/BUG-007...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-007_SWALLOWED_UNCLOSED_TOOL_CALL_GHOST_FINISH.md) |
| **BUG-006** | 2026-08-31 | Podwójne Kaskadowe Zerwanie Strumienia (Cascade Stream Abort) | ✅ Bezpieczna obsługa uciętych odpowiedzi bez zatruwania kontekstu | [`archiwum/BUG-006...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-006_CASCADE_STREAM_ABORT_I_INJECTED_ERROR_POISONING.md) |
| **BUG-005** | 2026-08-31 | Pętla Zagłady 10x Redundant Read (`klient_rozmowa_umowa.md`) | ✅ Anti-loop guard dedup plików w `_build_anti_loop_guard` (`a73185a`) | [`archiwum/BUG-005...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-005_10X_REDUNDANT_READS_EMPTY_SEARCH_DOOM_LOOP.md) |
| **BUG-004** | 2026-08-31 | Pętla Zagłady Auto-Continue, Przepalanie Tokenów i Brak Myślenia R1 | ✅ Streaming `_ReasoningChunk` na żywo do Trae (`f56ac58`) | [`archiwum/BUG-004...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-004_AUTO_CONTINUE_DOOM_LOOP_I_THINKING_POISONING.md) |
| **BUG-003** | 2026-08-31 | Wyciek Surowego JSON Narzędzia (Tool Leak), Duplikacja Bloków | ✅ Filtry i parsery wycieków JSON w proxy | [`archiwum/BUG-003...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-003_RAW_TOOL_LEAK_DUPLICATE_JSON_I_SELF_ANSWERING.md) |
| **BUG-002** | 2026-08-28 | Zatrucie Sesji Web, Halucynacja Tagów XML (`<invoke>`, `</previous_calls>`) | ✅ Sanityzacja reminderów i naprawa tagów w proxy | [`archiwum/BUG-002...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-002_POISONED_SESSION_ROTATION_I_TOOL_BURST.md) |
| **BUG-001** | 2026-08-26 | Pętla Zagłady (Doom Loop), 4x Redundant Read, 17x Puste Wyszukiwania | ✅ Anti-loop guard w prompcie (`a73185a`) + Metadane plików (`684ddd5`) | [`archiwum/BUG-001...md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/archiwum/BUG-001_DOOM_LOOP_REDUNDANT_READS_I_STALL.md) |

---

## Zasada Wprowadzania Poprawek (Determinizm & Pesymizm)
Każda naprawa musi:
1. Posiadać **niepodważalny dowód empiryczny** wystąpienia (zrzut ekranu, log SSE, surowy dump konwersacji).
2. Posiadać **deterministyczny warunek zatrzymania / sanityzacji** (np. normalizator tagów, dedup komend powłoki, filtr promptu).
3. Posiadać dedykowany test automatyczny (`pytest`), który weryfikuje odporność na daną awarię.
