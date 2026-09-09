# BUG-034: Przepełnienie kontekstu DeepSeek Web przez nadmiarowość schematów narzędzi (44k schema bloat) i fałszywy komunikat 'Stream przerwany'

## 1. Objawy i opis incydentu
W nowym, czystym czacie Trae użytkownik wysłał krótkie polecenie z odnośnikiem do pliku:
`Oceń mechanikę wyceniania ofert.md#L1315-1320`

W odpowiedzi asystent natychmiast wygenerował błąd:
`*Stream został przerwany przez DeepSeek. Wyślij 'kontynuuj' aby dokończyć — kontekst został zachowany.*`
Kliknięcie „kontynuuj” zapętlało błąd bez żadnego wygenerowanego słowa treści.

W logu serwera (`proxy_output.log`) dla sesji `966d2e50-5546-4edc-b9a3-28e52e0f439a`:
```json
[RAW] {"request_message_id":1,"response_message_id":2,"model_type":"expert"}
[RAW] {"type":"error","content":"Osiągnięto limit długości. Rozpocznij nowy czat.","clear_response":true,"finish_reason":"context_length_exceeded"}
[ERROR] DeepSeek error: Osiągnięto limit długości. Rozpocznij nowy czat.
```

---

## 2. Diagnoza przyczyn źródłowych

### Przyczyna A: Gigantyczny rozmiar schematów narzędzi (44 023 znaki)
- W starych konwersacjach Trae uruchamiało w tle **subagenta** (`You are a sub-agent...`, 3k promptu systemowego, 20 narzędzi), co dawało łącznie ok. 41 842 znaki i mieściło się „na styk” w limicie DeepSeek Web (~45-50k).
- W nowym czacie Trae wywołało **głównego agenta** (`You are an interactive agent in TraeCode...` — 15 384 znaki) i załadowało 24 narzędzia (`Task`, `AskUserQuestion`, `NotifyUser`, `run_mcp`).
- Funkcja `_build_prompt` wklejała pełną dokumentację i zagnieżdżone opisy Trae (samo `RunCommand` miało 10 171 znaków opisu).
- Łącznie: 15.4k (system) + 44k (narzędzia) + 1k (koordynator) = **59 407 znaków** przed wpisaniem czegokolwiek przez użytkownika.
- Wraz z zapytaniem prompt osiągnął **60 545 znaków**, co przekroczyło limit DeepSeek Web na turn 1.

### Przyczyna B: Utrata `finish_reason` i brak obsługi języka polskiego
- W `server.py` linia 924 rzucała błąd `raise RuntimeError(f"DeepSeek error: {err_msg}")`, ucinając pole `finish_reason: context_length_exceeded`.
- W linii 4450 kod sprawdzał wyłącznie angielskie frazy (`"length limit"`, `"context_length"`, `"start a new chat"`).
- Polski komunikat `"Osiągnięto limit długości. Rozpocznij nowy czat."` nie został dopasowany do limitu kontekstu.
- Kod spadł do linii 4480, wypisując mylące: `Stream został przerwany przez DeepSeek. Wyślij 'kontynuuj'`.

---

## 3. Weryfikacja empiryczna na żywo (Live A/B Testing)
Przeprowadzono testy porównawcze na żywym modelu DeepSeek Web (`test_tool_calling_compare.py` oraz `test_tool_calling_compare_grep.py`):

1. **Test `Read`:**
   - Schematy pełne: 43 210 znaków -> wyemitowano `<tool_call name="Read">`
   - Schematy kompaktowe: 4 354 znaki (spadek o 89.9%) -> wyemitowano w 100% identyczny `<tool_call name="Read">`
2. **Test `Grep` (4 parametry: pattern, path, output_mode, -n):**
   - Schematy pełne: 43 242 znaki -> wyemitowano `<tool_call name="Grep">`
   - Schematy kompaktowe: 4 386 znaków (spadek o 89.9%) -> wyemitowano w 100% identyczny `<tool_call name="Grep">` z wszystkimi 4 parametrami!

---

## 4. Wprowadzone zmiany w kodzie
1. **Kompaktowe formatowanie w `_build_prompt` (`server.py`):**
   - Zastąpiono wielostronicowe eseje Trae jednolinijkowymi sygnaturami parametrów i krótkim opisem.
   - Zachowano nagłówki `## {name}` i formatowanie Markdown.
   - Oszczędność: z 44k do 4.3k znaków (~90% redukcji).
2. **Obsługa błędów i `finish_reason`:**
   - W liniach 712 i 925 zachowano `finish_reason` w `RuntimeError`: `DeepSeek error [{fr}]: {err}`.
   - W liniach 712 i 4434 dodano polskie frazy: `"limit długości"`, `"rozpocznij nowy czat"`.
3. **Zestaw testów regresyjnych:**
   - `tests/test_bug034.py`: 3 testy weryfikujące rozmiar schematów, obecność sygnatur i detekcję polskich komunikatów.
