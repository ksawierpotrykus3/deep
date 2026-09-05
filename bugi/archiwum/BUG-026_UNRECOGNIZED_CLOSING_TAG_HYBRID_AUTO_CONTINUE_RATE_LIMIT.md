# BUG-026: Odrzucenie Hybrydowego Tagu Zamykającego `</｜｜DSML｜｜ask>`, Niepotrzebne Auto-Continue i Zablokowanie Konta przez Rate-Limit (`Zbyt częste wiadomości`)

**Data zgłoszenia:** 2026-09-05  
**Środowisko:** Trae IDE + DeepSeek Proxy (`server.py`)  
**Status:** Rozwiązany / Zweryfikowany testami jednostkowymi (`tests/test_bug025_026.py` PASS)  
**Dotknięte komponenty:** `server.py` (`close_tag_pat`, `_has_unclosed_tool_call`, obsługa rate-limit na kontach)  
**Plik zrzutu awaryjnego:** [`data/crashed_chats/crash_20260905_112000_jwt_leg_caoy_39538b94.md`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/data/crashed_chats/crash_20260905_112000_jwt_leg_caoy_39538b94.md)  
**Dowód wizualny:** [`media_1788600042312.png`](file:///C:/Users/Ksawier/.gemini/antigravity/brain/87701fc8-c77e-455c-831f-ebcd5eee55d0/.user_uploaded/media_1788600042312.png) (dolny dymek)  

---

## 1. Objawy Awarii (Objawy Widoczne w GUI Trae)

Po wystąpieniu BUG-025 użytkownik wysłał do agenta polecenie `kontynuuj`.  
Agent rozpoczął pracę i wygenerował wstęp:
> *"Mam pełny obraz warstwy. Migruję wyłącznie sesje czatu (dane), zostawiając stan UI (live tracking, szerokość panelu, config kontekstu) w localStorage — mniejszy, bezpieczniejszy zakres."*

Po 2 minutach i 40 sekundach pojawił się kolejny błąd:
> `[BŁĄD PROXY: Wywołanie narzędzia zostało ucięte i NIE zostało wykonane. Ponów operację.]`

Status w Trae zatrzymał się na **`6%`**, a lista zadań nie została zaktualizowana.

---

## 2. Dowody z Logów Proxy i Pliku Crash Dump

W pliku zrzutu pamięci `crash_20260905_112000_jwt_leg_caoy_39538b94.md`:
```xml
Mam pełny obraz warstwy. Migruję wyłącznie sesje czatu (dane), zostawiając stan UI (live tracking, szerokość panelu, config kontekstu) w localStorage — mniejszy, bezpieczniejszy zakres.

<tool_call name="TodoWrite">
  <parameter name="merge" string="false">false</parameter>
  <parameter name="todos" string="false">[{"content": "Utworzyć współdzielone typy czatu (shared/types/chat.ts)", "status": "in_progress", "id": "1", "priority": "high"}, {"content": "Dodać metody czatu do StorageEngine", "status": "pending", "id": "2", "priority": "high"}, {"content": "Dodać IPC handlery czatu w ElectronIpcBridge", "status": "pending", "id": "3", "priority": "high"}, {"content": "Rozszerzyć cortexBridge + preload", "status": "pending", "id": "4", "priority": "high"}, {"content": "Zastąpić localStorage sesji w AiChatSidebar", "status": "pending", "id": "5", "priority": "high"}, {"content": "Typecheck (tsc)", "status": "pending", "id": "6", "priority": "medium"}]</parameter>
</｜｜DSML｜｜ask>
```

W logu [`proxy_output.log`](file:///c:/Users/Ksawier/Pictures/Screenshots/Projekty_autorskie/deepseek-proxy-clean/proxy_output.log):
```text
[YIELD] safe lines: 'Mam pełny obraz warstwy. Migruję wyłącznie sesje czatu (dane), zostawiając stan UI (live tracking, s'
[AUTO-CONTINUE] attempt 1, budget left=1, parent=6 (content=989 chars, thinking=1429 chars)
[RAW] {"type":"error","content":"Zbyt częste wiadomości. Spróbuj ponownie później.","clear_response":true,"finish_reason":"rate_limit_reached"}
[ERROR] DeepSeek error: Zbyt częste wiadomości. Spróbuj ponownie później.
[RETRY] Rate-limited (attempt 1, reason=rate_limit_reached), waiting 73s...
[MONITOR] Auto-kill: 0ba06d887138... (slow/dead -> restart przydzielony)
...
[AUTO-CONTINUE] Continue stream error: DeepSeek busy after 3 retries: Zbyt częste wiadomości. Spróbuj ponownie później.
[STREAM] Suppressed unclosed tool call leakage (0 chars not sent to chat)
[CRASH DUMP] Saved: data\crashed_chats\crash_20260905_112000_jwt_leg_caoy_39538b94.md
[TIMING] Stream done (88.3s, 0 tools, wm=0ba06d887138...)
```

---

## 3. Przyczyna Źródłowa (Root Cause Analysis)

### A. Błędna klasyfikacja domkniętego narzędzia jako uciętego:
Model wygenerował kompletną listę zadań `TodoWrite` w poprawnym formacie JSON. Jednak zamiast standardowego `</tool_call>` użył wewnętrznego tagu kończącego DeepSeeka:
`</｜｜DSML｜｜ask>`

Parser proxy oraz funkcja `_has_unclosed_tool_call` nie rozpoznały słowa `ask` jako dopuszczalnego tagu zamykającego narzędzia. W efekcie proxy uznało, że wywołanie jest w trakcie pisania i zostało przerwane w połowie.

### B. Uruchomienie `auto-continue` i uderzenie w Rate Limit:
Wierząc, że narzędzie jest ucięte, proxy podjęło próbę ratunkową (`[AUTO-CONTINUE]`), wysyłając w tle zapytanie dokańczające do DeepSeeka.  
Ponieważ na koncie `account: 5` wykonano w krótkim czasie wiele zapytań, DeepSeek Web odrzucił połączenie błędem `rate_limit_reached` (*"Zbyt częste wiadomości. Spróbuj ponownie później."*).

### C. Brak natychmiastowej rotacji na wolne konto:
Gdy konto 5 dostało blokadę na 73 sekundy, funkcja `_auto_continue` próbowała ponawiać zapytanie na tym samym, zablokowanym koncie, zamiast natychmiast przepiąć sesję na jeden z pozostałych 5 dostępnych slotów (0, 1, 2, 3, 4). Po wyczerpaniu budżetu prób proxy zakończyło strumień błędem uciętego narzędzia.

---

## 4. Wdrożona Poprawka w Kodzie

1. **Uelastycznienie tagów w `_parse_tool_calls` oraz `_has_unclosed_tool_call`:**
   - `close_tag_pat` w `_parse_tool_calls` dopuszcza teraz warianty `</｜｜DSML｜｜ask>`, `</｜｜DSML｜｜tool_call>`, `</｜｜DSML｜｜invoke>` oraz tagi pojedyncze `</ask>`, `</action>`.
   - `_has_unclosed_tool_call` uwzględnia zarówno asymetryczne otwarcia (`<｜｜DSML｜｜ name="...">`), jak i hybrydowe domknięcia (`</｜｜DSML｜｜ask>`), bez fałszywego zliczania tagów parametrów (`</parameter>`).
2. **Natychmiastowa rotacja konta przy `rate_limit_reached`:**
   - W `stream_completion` (preambuła oraz strumień), jeśli wykryto błąd `rate_limit_reached`, slot jest natychmiast oznaczany w `_rate_limited_until[account_idx] = time.time() + 120`. Jeśli w puli są dostępne inne konta, proxy NIE czeka bezczynnie 73s, lecz natychmiast wywołuje wyjątek uruchamiający migrację.
   - W punkcie wejścia `_chat_completions_impl`, jeśli przypisany slot rozmowy jest aktualnie zablokowany rate-limitem (`now < _rate_limited_until[account_idx]`), sesja zostaje płynnie przepięta na czyste konto przed rozpoczęciem zapytania.

---

## 5. Weryfikacja Deterministyczna

Napisano testy w `tests/test_bug025_026.py`:
- `test_bug026_parse_tool_calls_hybrid_closing_tag`: potwierdza, że wywołanie `TodoWrite` zakończone `</｜｜DSML｜｜ask>` zostaje w 100% poprawnie sparsowane do formatu OpenAI.
- `test_bug026_unclosed_tool_call_hybrid_closing_tag`: potwierdza, że `_has_unclosed_tool_call` zwraca `False` dla kompletnego wywołania i `True` dla uciętego.
- `test_bug026_rate_limited_account_migration_detection`: potwierdza deterministyczną rotację sesji na czysty slot po zablokowaniu konta przez rate-limit.
Wynik: **PASS** (100%).
