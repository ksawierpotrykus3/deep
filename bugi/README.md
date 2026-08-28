# Rejestr Awarii i Błędów Proxy (Bug Registry)

Katalog zawiera dogłębne analizy techniczne awarii systemu proxy, subagentów oraz integracji z IDE Trae / DeepSeek.

---

## Indeks Raportów

| ID | Data | Tytuł | Status | Plik |
|---|---|---|---|---|
| **BUG-001** | 2026-08-26 | Pętla Zagłady (Doom Loop), 4x Redundant Read (`macro_engine.py`), 17x Puste Wyszukiwania i Wyłączony Debounce | Zdiagnozowany / Gotowy plan naprawy | [`BUG-001_DOOM_LOOP_REDUNDANT_READS_I_STALL.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/BUG-001_DOOM_LOOP_REDUNDANT_READS_I_STALL.md) |
| **BUG-002** | 2026-08-28 | Zatrucie Sesji Web (Poisoned Session), Halucynacja Tagów XML (`<invoke>`, `</previous_calls>`), Pętla 10x `git status` i Cicha Rotacja do Nowego Czatu | Zdiagnozowany / Gotowy plan naprawy | [`BUG-002_POISONED_SESSION_ROTATION_I_TOOL_BURST.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/bugi/BUG-002_POISONED_SESSION_ROTATION_I_TOOL_BURST.md) |

---

## Zasada Wprowadzania Poprawek (Determinizm & Pesymizm)
Każda naprawa musi:
1. Posiadać **niepodważalny dowód empiryczny** wystąpienia (zrzut ekranu, log SSE, surowy dump konwersacji).
2. Posiadać **deterministyczny warunek zatrzymania / sanityzacji** (np. normalizator tagów, dedup komend powłoki, filtr promptu).
3. Posiadać dedykowany test automatyczny (`pytest`), który weryfikuje odporność na daną awarię.
