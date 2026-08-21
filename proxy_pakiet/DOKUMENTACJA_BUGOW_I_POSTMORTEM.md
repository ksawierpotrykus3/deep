# Encyklopedia Błędów, Architektury i Inżynierii Wstecznej: DeepSeek Proxy Clean

> **Kompleksowe kompendium techniczne (Post-Mortem, Reverse Engineering & Protocol Reference)**
> **Projekt:** `deepseek-proxy-clean` / Integracja z Trae IDE (Protokół OpenAI API `/v1/chat/completions`)
> **Data aktualizacji:** 2026-08-15
> **Środowisko:** Windows 10/11 x64, Python 3.13, Trae IDE (1 Koordynator + do 5 równoległych Subagentów), Pula 6 kont Web DeepSeek (`session_0.json` – `session_5.json`).

---

## Spis Treści
1. [Architektura Systemu i Topologia Sieci](#1-architektura-systemu-i-topologia-sieci)
2. [Inżynieria Wsteczna Protokołu DeepSeek Web API](#2-inżynieria-wsteczna-protokołu-deepseek-web-api)
   - 2.1. Cykl życia sesji i mechanizm Proof-of-Work (PoW)
   - 2.2. Format strumienia SSE (Server-Sent Events) i kody delta
   - 2.3. Pakiety statusowe (`p`, `v`, `o`) i obsługa `FINISHED` / `WIP`
3. [Katalog Wszystkich Zidentyfikowanych Błędów (15 Szczegółowych Studiów Przypadków)](#3-katalog-wszystkich-zidentyfikowanych-błędów)
   - [BUG 01: Pętla Powtórzeń `<previous_tool_call>` (Repetition Trap)](#bug-01-pętla-powtórzeń-previous_tool_call-repetition-trap)
   - [BUG 02: Wycieki Skróconych Tagów Narzędzi (`<_call>`, `<call>`, `<tool>`)](#bug-02-wycieki-skróconych-tagów-narzędzi-_call-call-tool)
   - [BUG 03: Ignorowanie Bloków Narzędzi Markdown JSON i Awaria Ścieżek Windows (`\Users`)](#bug-03-ignorowanie-bloków-narzędzi-markdown-json-i-awaria-ścieżek-windows-users)
   - [BUG 04: 300-Sekundowe Zawieszenie w Preambule na Martwych Socketach (`CloseWait`)](#bug-04-300-sekundowe-zawieszenie-w-preambule-na-martwych-socketach-closewait)
   - [BUG 05: Blokada Subagentów przez Brak Wewnętrznego Auto-Continue](#bug-05-blokada-subagentów-przez-brak-wewnętrznego-auto-continue)
   - [BUG 06: Awaria Chunked Ingestion Poza Pętlą Migracji / Retry (BUG C)](#bug-06-awaria-chunked-ingestion-poza-pętlą-migracji--retry-bug-c)
   - [BUG 07: Błąd `NameError: raw_args` w Parserze Formatów CLI (BUG D)](#bug-07-błąd-nameerror-raw_args-w-parserze-formatów-cli-bug-d)
   - [BUG 08: Martwy Kod w Detektorze Pętli Anti-Loop Guard (BUG E)](#bug-08-martwy-kod-w-detektorze-pętli-anti-loop-guard-bug-e)
   - [BUG 09: Blokowanie Puli Równoległej Trae (Head-of-Line Blocking)](#bug-09-blokowanie-puli-równoległej-trae-head-of-line-blocking)
   - [BUG 10: Fałszywa Diagnoza Zacięcia (Mylenie Wykonywania Narzędzi Klienta z Zamrożeniem LLM)](#bug-10-fałszywa-diagnoza-zacięcia-mylenie-wykonywania-narzędzi-klienta-z-zamrożeniem-llm)
   - [BUG 11: Zjawisko Połykania Tekstu (Tag Swallowing) przy Polskich Znakach i Operatorach `<`](#bug-11-zjawisko-połykania-tekstu-tag-swallowing-przy-polskich-znakach-i-operatorach-)
   - [BUG 12: Nieważność Tokenów PoW (INVALID_POW_RESPONSE & AWS WAF TTL)](#bug-12-nieważność-tokenów-pow-invalid_pow_response--aws-waf-ttl)
   - [BUG 13: Konflikty Identyfikatorów Sesji (`conv_key`) w Zapytaniach z Tokenami ACL Trae](#bug-13-konflikty-identyfikatorów-sesji-conv_key-w-zapytaniach-z-tokenami-acl-trae)
   - [BUG 14: Przepełnienie Kontekstu (Multi-Tier Context Ingestion Strategy)](#bug-14-przepełnienie-kontekstu-multi-tier-context-ingestion-strategy)
   - [BUG 15: Kodowanie Znaków i Mojibake w Konsoli Windows (`CP1250` vs `UTF-8`)](#bug-15-kodowanie-znaków-i-mojibake-w-konsoli-windows-cp1250-vs-utf-8)
   - [BUG 16: Fałszywe Wywołania Narzędzi w Fazie Myślenia (Thinking / CoT Isolation)](#bug-16-fałszywe-wywołania-narzędzi-w-fazie-myślenia-thinking--cot-isolation)
   - [BUG 17: Protokół Uploadu Obrazów Vision i Rejestracja `ref_file_ids`](#bug-17-protokół-uploadu-obrazów-vision-i-rejestracja-ref_file_ids)
   - [BUG 18: Kolizje Wstrzykiwanych Przypomnień Systemowych Trae (`<system-reminder>`)](#bug-18-kolizje-wstrzykiwanych-przypomnień-systemowych-trae-system-reminder)
   - [BUG 19: Migracja Sesji Między Kontami przy Błędach 429 i Server Busy (Cross-Account Migration)](#bug-19-migracja-sesji-między-kontami-przy-błędach-429-i-server-busy-cross-account-migration)
   - [BUG 20: Wyścigi Zapisów Stanu Rozmów i Atomowy `conv_state.json` (Thread-Safety)](#bug-20-wyścigi-zapisów-stanu-rozmów-i-atomowy-conv_statejson-thread-safety)
   - [BUG 21: Inteligentny Model Router i Mapowanie Aliasów Modeli Trae](#bug-21-inteligentny-model-router-i-mapowanie-aliasów-modeli-trae)
   - [BUG 22: Przepełnienie Kontekstu przez Gigantyczne Logi Terminala i Auto-Crush](#bug-22-przepełnienie-kontekstu-przez-gigantyczne-logi-terminala-i-auto-crush)
   - [BUG 23: Zgubienie Pierwotnego Celu w Długich Konwersacjach (Goal Drift & Goal Preservation Engine)](#bug-23-zgubienie-pierwotnego-celu-w-długich-konwersacjach-goal-drift--goal-preservation-engine)
   - [BUG 24: Wyciek Znaczników Wodnych Sesji (`<!-- PROXY_SID:... -->`) do Interfejsu Klienta](#bug-24-wyciek-znaczników-wodnych-sesji---proxy_sid---do-interfejsu-klienta)
   - [BUG 25: Utrata Tekstu Preambuły Wygenerowanego Przed Pakietem `response_message_id` (Pre-Response Fallback)](#bug-25-utrata-tekstu-preambuły-wygenerowanego-przed-pakietem-response_message_id-pre-response-fallback)
   - [BUG 26: Zrywanie Połączeń SSE przez Pośrednie Warstwy Sieciowe z Powodu Braku SSE Keep-Alive Heartbeat](#bug-26-zrywanie-połączeń-sse-przez-pośrednie-warstwy-sieciowe-z-powodu-braku-sse-keep-alive-heartbeat)
   - [BUG 27: Niespójność Typów Parametrów w Tagach XML (`true`/`false`/`123` jako Stringi zamiast Typów Natywnych)](#bug-27-niespójność-typów-parametrów-w-tagach-xml-truefalse123-jako-stringi-zamiast-typów-natywnych)
   - [BUG 28: Zapętlenia Przełącznika Trybów Hybrydowych (`free_first` vs `official_fallback`)](#bug-28-zapętlenia-przełącznika-trybów-hybrydowych-free_first-vs-official_fallback)
   - [BUG 29: Niedopasowanie Identyfikatorów `tool_call_id` i Kolejności Ról Wiadomości w Protokole Trae](#bug-29-niedopasowanie-identyfikatorów-tool_call_id-i-kolejności-ról-wiadomości-w-protokole-trae)
   - [BUG 30: Crash Logera Konsoli Windows przez Znaki Unicode (`\u2192` / UnicodeEncodeError w stdout)](#bug-30-crash-logera-konsoli-windows-przez-znaki-unicode-u2192--unicodeencodeerror-w-stdout)
   - [BUG 31: Blokada Wątków i Wyścigi Pamięci Podręcznej PoW (Concurrent PoW Contention)](#bug-31-blokada-wątków-i-wyścigi-pamięci-podręcznej-pow-concurrent-pow-contention)
   - [BUG 32: Deserializacja Zagnieżdżonych Argumentów Narzędzi (Recursive JSON Serialization)](#bug-32-deserializacja-zagnieżdżonych-argumentów-narzędzi-recursive-json-serialization)
4. [Tabela 9 Formatów Wywołań Narzędzi w DeepSeek](#4-tabela-9-formatów-wywołań-narzędzi-w-deepseek)
5. [Przewodnik Diagnostyczny i Debugowanie Krok po Kroku](#5-przewodnik-diagnostyczny-i-debugowanie-krok-po-kroku)
6. [Nienaruszalne Zasady Architektoniczne dla Kolejnych Agentów](#6-nienaruszalne-zasady-architektoniczne-dla-kolejnych-agentów)

---

## 1. Architektura Systemu i Topologia Sieci

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                TRAE IDE                                 │
│  ┌───────────────────────┐   ┌────────────────────────────────────────┐ │
│  │   Main Coordinator    │   │  Parallel Subagents (1, 2, 3, 4, 5)    │ │
│  └──────────┬────────────┘   └───────────────────┬────────────────────┘ │
└─────────────┼────────────────────────────────────┼──────────────────────┘
              │ HTTP POST /v1/chat/completions     │
              ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     DEEPSEEK PROXY CLEAN (Port 4570)                    │
│  - Session Router & Sticky Account Allocator                            │
│  - PoW Solver & Ingestion Engine (Chunking > 50k chars)                 │
│  - Global Inactivity Watchdog (60s Preamble + Stream)                   │
│  - Multi-Format Tool Parser (9 Formats + Safe Windows Path Decoder)     │
│  - Transparent Auto-Continue & Crash Dump Engine                        │
│  - Vision 3-Step Upload Pipeline & CoT / Thought Isolator               │
│  - Thread-Safe Atomic State Manager (_conv_lock)                        │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │ HTTPS (curl_cffi Chrome Impersonation)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        DEEPSEEK WEB CLOUD POOL                          │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌──────────────┐ │
│  │ Slot 0 (Main) │ │ Slot 1 (Sub1) │ │ Slot 2 (Sub2) │ │ Slot 3..5    │ │
│  └───────────────┘ └───────────────┘ └───────────────┘ └──────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Inżynieria Wsteczna Protokołu DeepSeek Web API

### 2.1. Cykl życia sesji i Proof-of-Work (PoW)
1. **Wyzwanie PoW (`/api/v0/chat/create_pow`):** Serwer zwraca `algorithm`, `challenge`, `salt` i `difficulty` (zazwyczaj 144 000). Proxy w ułamku sekundy oblicza hash SHA-256 z dopasowaną liczbą zer wiodących.
2. **Tworzenie sesji (`/api/v0/chat/create_session`):** Zwraca unikalne `chat_session_id`.
3. **Strumień generowania (`/api/v0/chat/completion`):** Wymaga nagłówków:
   - `authorization: Bearer <auth_token>`
   - `x-ds-pow-response: <base64_pow>`
   - `cookie: ds_session_id=...; aws-waf-token=...`

### 2.2. Format strumienia SSE
Strumień SSE przesyła pakiety w formacie `data: {...}`:
- **Preamble:** Pierwszy pakiet zawiera `{"response_message_id": 12345, "model_type": "expert"}`.
- **Delta Tekstu:** Pakiety `{"p": "response/fragments", "v": [{"type": "RESPONSE", "content": "..."}]}` lub zwięzłe delty `{"v": "..."}`.
- **Myśli (CoT):** Fragmenty z `type: "THOUGHT"`.

### 2.3. Pakiety statusowe i zakończenie
- `{"p": "response/status", "o": "SET", "v": "FINISHED"}` — model zakończył generowanie pomyślnie.
- `{"p": "quasi_status", "v": "FINISHED"}` — zakończenie partii BATCH.
- `{"status": "WIP"}` — generowanie w toku (jeśli strumień zgaśnie w tym stanie, odpowiedź jest **ucięta / niekompletna**).

---

## 3. Katalog Wszystkich Zidentyfikowanych Błędów

---

### BUG 01: Pętla Powtórzeń `<previous_tool_call>` (Repetition Trap)
* **Objawy:** DeepSeek Web wpada w pętlę atencji, powtarzając setki razy tokeny `<previous_tool_call>` aż do limitu tokenów pojedynczej wiadomości, co powodowało zamrożenie odpowiedzi.
* **Przyczyna:** Prompt wysyłany z Trae zawierał markery agentowe, które stymulowały mechanizm atencji LLM do replikowania schematu XML.
* **Rozwiązanie:**
  1. W funkcji `_clean_system_reminders` dodano usuwanie tagów `</?previous_tool_call[^>]*>`.
  2. W buforze strumienia wprowadzono `Anti-Loop Guard`, który natychmiast ucina generowanie po wykryciu 4 powtórzeń sekwencji 15–50 znaków.

---

### BUG 02: Wycieki Skróconych Tagów Narzędzi (`<_call>`, `<call>`, `<tool>`)
* **Objawy:** W oknie czatu Trae pojawiały się surowe napisy `<_call name="Glob">` lub `<call name="LS">` zamiast wywołania funkcji.
* **Przyczyna:** DeepSeek Web losowo stosuje skrócone tagi XML. Stary regex dopasowywał wyłącznie `tool_call|invoke`.
* **Rozwiązanie:**
  1. Zunifikowano wyrażenie regularne `tool_pat` w `_parse_tool_calls` na: `(?:tool_call|invoke|tool_capability|_call|call|tool)`.
  2. W generatorze SSE wstrzymano przekazywanie fragmentów zaczynających się od otwartego tagu narzędzia do momentu jego pełnego sparsowania.

---

### BUG 03: Ignorowanie Bloków Narzędzi Markdown JSON i Awaria Ścieżek Windows (`\Users`)
* **Objawy:** Model generował narzędzia w bloku Markdown:
  ```json
  ```json
  {
    "tool": "LS",
    "args": {
      "path": "c:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie"
    }
  }
  ```
  Trae wyświetlało ramkę JSON jako zwykły tekst, a kliknięcie „kontynuuj” zapętlało problem.
* **Przyczyna:**
  1. Brak obsługi formatu 9 (bloki JSON) w parserze narzędzi.
  2. Ścieżki Windows `c:\Users\...` zawierają niefortunną sekwencję `\U`, którą domyślny dekoder `json.loads` traktuje jako nieprawidłowy znak Unicode, rzucając wyjątek `JSONDecodeError`.
  3. Naiwne regexy `\{[\s\S]*?\}` ucinały się na pierwszym wewnętrznym nawiasie `}` przy zagnieżdżeniach.
* **Rozwiązanie:**
  1. Dodano parser oparty o algorytm zliczania głębokości nawiasów klamrowych `{}` (`depth == 0`).
  2. Napisano funkcję `_safe_json_loads`, która automatycznie podwaja niepoprawne ukośniki (`\Users` -> `\\Users`).

---

### BUG 04: 300-Sekundowe Zawieszenie w Preambule na Martwych Socketach (`CloseWait`)
* **Objawy:** Kółko ładowania w Trae kręciło się bez przerwy przez 5–10 minut, a w logach panowała całkowita cisza.
* **Przyczyna:**
  1. Przy dużych zapytaniach (>100k znaków) serwer DeepSeek Web po 60–90 sekundach zamykał połączenie HTTP (`CloseWait`).
  2. Pętla preambuły (`for line in it` w linii 481 `server.py` oczekująca na `response_message_id`) działała na surowym generatorze `curl_cffi` z domyślnym `timeout=300` i nie była monitorowana przez Watchdoga.
* **Rozwiązanie:**
  1. Wprowadzono **Globalny Inactivity Watchdog (60s)**, który monitoruje odczyt od 1. milisekundy. Po 60s bezczynności strumień jest przerywany i natychmiast przechodzi do procedury Auto-Continue.

---

### BUG 05: Blokada Subagentów przez Brak Wewnętrznego Auto-Continue
* **Objawy:** W oknie subagenta pojawiał się komunikat:
  > *„Stream został przerwany przez DeepSeek. Wyślij 'kontynuuj' aby dokończyć — kontekst został zachowany.”*
  Subagent zatrzymywał się, a koordynator w Trae po chwili restartował zadanie od zera w nieskończonej pętli.
* **Przyczyna:** Subagenty w Trae są autonomicznymi procesami bez interfejsu czatu dla człowieka. Proxy zwracało statyczny tekst błędu zamiast wysłać prompt `"KONTYNUUJ"` bezpośrednio do DeepSeeka.
* **Rozwiązanie:**
  1. Wprowadzono **Wewnętrzne Auto-Continue** (do 2 prób).
  2. Proxy trzyma otwarte połączenie HTTP do Trae, wysyła w tej samej sesji `"KONTYNUUJ"` z `parent_message_id=last_resp_msg_id`, dokleja nowe tokeny do otwartego strumienia i zamyka odpowiedź sukcesem.
  3. Wdrożono awaryjny **Crash Dump** – jeśli dwukrotne wznowienie zawiedzie, proxy zapisuje cały kontekst rozmowy z `req.messages` i `conv_state` do pliku w folderze `data/crashed_chats/` dla celów diagnostycznych.

---

### BUG 06: Awaria Chunked Ingestion Poza Pętlą Migracji / Retry (BUG C)
* **Objawy:** Przy wysyłaniu promptów >50k znaków proxy rzucało `RuntimeError: Server is busy` -> błąd 500/502, niszcząc cały request.
* **Przyczyna:** Logika `_chunk_oversized_prompt` i wywołania `ingest_chunk_fast` znajdowały się **przed** pętlą retry/migracji (linie 2879–2904).
* **Rozwiązanie:**
  1. Objęto procedurę `chunked ingestion` pełną obsługą migracji na alternatywne konto z puli (`account_idx -> new_idx`).

---

### BUG 07: Błąd `NameError: raw_args` w Parserze Formatów CLI (BUG D)
* **Objawy:** Fałszywe komunikaty *„Stream został przerwany przez DeepSeek”* przy generowaniu przez model linii typu `Read path: foo.py`.
* **Przyczyna:** W linii 1494 `server.py` zmienna `raw_args` była używana w `re.findall` bez uprzedniego przypisania `raw_args = m.group(2)`.
* **Rozwiązanie:**
  1. Dodano przypisanie `raw_args = m.group(2)` przed wywołaniem `re.findall`.

---

### BUG 08: Martwy Kod w Detektorze Pętli Anti-Loop Guard (BUG E)
* **Objawy:** Detektor pętli tokenów nie działał podczas przetwarzania fragmentów odpowiedzi.
* **Przyczyna:** W linii 656 `server.py` znajdowało się `continue`, a blok Anti-Loop Guard (linie 657–670) był wcięty po `continue`.
* **Rozwiązanie:**
  1. Przesunięto blok weryfikacji powtórzeń przed instrukcję `continue`.

---

### BUG 09: Blokowanie Puli Równoległej Trae (Head-of-Line Blocking)
* **Objawy:** Nawet jeśli 3 subagenty zakończyły pracę i utworzyły pliki, całe zadanie w Trae wisiało z obracającym się spinnerem.
* **Przyczyna:** Trae oczekuje na zakończenie wszystkich równoległych subagentów. Jeśli choć jeden subagent napotkał urwany strumień lub brak znacznika `data: [DONE]\n\n`, cała pula pozostawała zablokowana.
* **Rozwiązanie:**
  1. Wymuszenie natychmiastowego opróżnienia bufora (flush) i odesłania `data: [DONE]\n\n` we wszystkich ścieżkach zakończenia strumienia.
  2. Wdrożenie awaryjnego **Crash Dumpa** do `data/crashed_chats/` w przypadku trwałego błędu po 2 próbach Auto-Continue.

---

### BUG 10: Fałszywa Diagnoza Zacięcia (Mylenie Wykonywania Narzędzi Klienta z Zamrożeniem LLM)
* **Objawy:** Podejrzenie zawieszenia proxy z powodu kilkudziesięciu sekund ciszy w logach, podczas gdy subagent działał prawidłowo.
* **Przyczyna:** Po zakończeniu tury i odesłaniu narzędzi (`Read`), połączenie do DeepSeeka jest czysto zamykane (`CloseWait`), a klient (Trae) lokalnie na dysku czyta pliki i buduje kolejny request.
* **Rozwiązanie:**
  1. Wprowadzono jawne rozróżnianie stanów w monitoringu:
     - `STATE: GENERATING` — DeepSeek generuje tokeny (mierzony czas od ostatniego bajtu, limit 60s).
     - `STATE: CLIENT_TOOL_EXECUTION` — Trae wykonuje narzędzia na dysku (oczekiwanie na kolejny POST).
     - `STATE: COMPLETED` — Subagent zakończył zadanie.

---

### BUG 11: Zjawisko Połykania Tekstu (Tag Swallowing) przy Polskich Znakach i Operatorach `<`
* **Objawy:** Normalny tekst zawierający operatory porównania lub fragmenty w nawiasach ostrych (np. `moduły <A-D>`, `skrót <wycena>`, `x < 10`) był wstrzymywany w buforze i nie trafiał do Trae na bieżąco.
* **Przyczyna:** Streamer SSE po napotkaniu znaku `<` czekał na znak `>`, zakładając, że może to być początek tagu narzędziowego. Jeśli `>` nie nadszedł od razu, tekst był wstrzymywany.
* **Rozwiązanie:**
  1. Zaimplementowano weryfikację prefiksów tagów: jeśli po znaku `<` nie następuje nazwa znanego narzędzia lub tagu systemowego (`tool_call`, `_call`, `Read`, `Write` itp.), znak `<` jest natychmiast zwalniany do klienta jako zwykły tekst.

---

### BUG 12: Nieważność Tokenów PoW (INVALID_POW_RESPONSE & AWS WAF TTL)
* **Objawy:** Po kilku minutach bezczynności pierwsze zapytanie kończyło się błędem `INVALID_POW_RESPONSE`.
* **Przyczyna:** Wyliczony hash PoW oraz tokeny AWS WAF posiadają ograniczony czas życia (TTL ~300s). Po wygaśnięciu serwer DeepSeek odrzucał zapytanie.
* **Rozwiązanie:**
  1. Wprowadzono automatyczne czyszczenie pamięci podręcznej PoW (`self._cached_pow.pop(account_idx, None)`) i natychmiastowe, jednorazowe ponowienie zapytania (`_retry + 1`).

---

### BUG 13: Konflikty Identyfikatorów Sesji (`conv_key`) w Zapytaniach z Tokenami ACL Trae
* **Objawy:** Nowe zapytania subagenta były błędnie łączone ze starym czatem innego projektu lub tworzyły niepotrzebne nowe sesje.
* **Przyczyna:** Trae wysyła w nagłówkach tokeny JWT z polem `legid` zawierającym losowe timestampy wygaśnięcia (`expireTime: 1786885852`), co powodowało generowanie różnych `conv_key` dla tego samego logicznego wątku czatu.
* **Rozwiązanie:**
  1. Normalizacja `conv_key` na bazie stałych pól tożsamości klienta i zawartości pierwszego komunikatu użytkownika z pominięciem zmiennych timestampów nagłówka JWT.

---

### BUG 14: Przepełnienie Kontekstu (Multi-Tier Context Ingestion Strategy)
* **Objawy:** Błędy `content is too long` lub `input_exceeds_limit` przy wczytywaniu dziesiątek plików.
* **Przyczyna:** DeepSeek Web posiada twardy limit 64k/128k tokenów na całą sesję czatu.
* **Rozwiązanie:**
  1. **Poziom 1 (Prewencyjny):** Dzielenie promptów >50k znaków na chunki (`_chunk_oversized_prompt`).
  2. **Poziom 2 (Reaktywny):** Reaktywny podział na mniejsze paczki (30k) w nowej sesji, gdy serwer zwróci błąd limitu.
  3. **Poziom 3 (Auto-Crush):** Automatyczna kompresja i streszczanie wcześniejszych wyników narzędzi (`_crush_tool_results`).

---

### BUG 15: Kodowanie Znaków i Mojibake w Konsoli Windows (`CP1250` vs `UTF-8`)
* **Objawy:** W konsoli PowerShell i plikach logów polskie znaki wyświetlały się jako krzaki (`skrƈt` zamiast `skrót`, `owca` zamiast `łowca`).
* **Przyczyna:** Domyślna strona kodowa konsoli Windows to Windows-1250 (`CP1250`), podczas gdy Python i DeepSeek operują w standardzie `UTF-8`.
* **Rozwiązanie:**
  1. Dodano automatyczne wymuszenie strony kodowej `chcp 65001 >nul` oraz `PYTHONIOENCODING=utf-8` we wszystkich skryptach uruchomieniowych (`.bat`, `.ps1`).

---

### BUG 16: Fałszywe Wywołania Narzędzi w Fazie Myślenia (Thinking / CoT Isolation)
* **Objawy:** W trybie myślenia (`deepseek-reasoner` / `THOUGHT`) model w swoich rozważaniach napisał hipotetyczny kod narzędzia (np. *„Myślę, że powinienem uruchomić `<Read><file_path>main.py</file_path></Read>`”*), a parser natychmiast wysłał to wywołanie do Trae jako prawdziwą akcję.
* **Przyczyna:** Brak separacji bufora myśli (`type: "THOUGHT"`) od bufora odpowiedzi (`type: "RESPONSE"`).
* **Rozwiązanie:**
  1. Wszystkie tokeny `THOUGHT` są kierowane wyłącznie do bloku myśli (lub wycinane), a parser `_parse_tool_calls` przetwarza wyłącznie bufor `RESPONSE`.

---

### BUG 17: Protokół Uploadu Obrazów Vision i Rejestracja `ref_file_ids`
* **Objawy:** Załączenie zrzutu ekranu w Trae rzucało błąd `invalid_file_ref` lub model pisał, że nie widzi obrazu.
* **Przyczyna:** DeepSeek Web nie przyjmuje danych Base64 bezpośrednio w prompcie. Wymaga przejścia 3-etapowego uploadu:
  1. `POST /api/v0/file/create` z metadanymi i rozmiarem.
  2. `PUT /api/v0/file/upload` z binarną zawartością.
  3. Odpytania `/api/v0/file/poll` o gotowość i przekazania `ref_file_ids` w żądaniu czatu.
* **Rozwiązanie:**
  1. Zaimplementowano dedykowany moduł `upload_image_file()` realizujący pełny pipeline z obsługą tokenów PoW.

---

### BUG 18: Kolizje Wstrzykiwanych Przypomnień Systemowych Trae (`<system-reminder>`)
* **Objawy:** Model w losowych momentach generował odpowiedzi analizujące wewnętrzne instrukcje agenta zamiast kodu użytkownika.
* **Przyczyna:** Trae wstrzykuje do historii wiadomości ukryte bloki `<system-reminder>` (przypominające o stylu, formatach, regułach projektu), które mieszały się z historią czatu DeepSeeka.
* **Rozwiązanie:**
  1. Wprowadzono funkcje `_clean_user_content` oraz `_clean_system_reminders`, które wycinają zbędne metadane systemowe przed wysłaniem żądania do DeepSeeka.

---

### BUG 19: Migracja Sesji Między Kontami przy Błędach 429 i Server Busy (Cross-Account Migration)
* **Objawy:** Po wyczerpaniu limitu na jednym koncie subagent tracił całą dotychczasową wiedzę i zaczynał od zera.
* **Przyczyna:** `chat_session_id` jest przypisany do konkretnego konta i nie istnieje na innym koncie. Zwykła zmiana `account_idx` bez odtworzenia kontekstu powodowała błąd `session_not_found`.
* **Rozwiązanie:**
  1. Zaimplementowano procedurę `[MIGRATE]`, która na nowym koncie automatycznie tworzy świeżą sesję i wstrzykuje skompresowaną historię (`crushed_msgs`) oraz bieżący prompt w jednym kroku.

---

### BUG 20: Wyścigi Zapisów Stanu Rozmów i Atomowy `conv_state.json` (Thread-Safety)
* **Objawy:** Przy 5 równoległych subagentach plik `data/conv_state.json` ulegał uszkodzeniu (0 bajtów lub ucięty JSON), co powodowało błąd parsowania przy restarcie.
* **Przyczyna:** Równoległe wątki FastAPI zapisywały stan do tego samego pliku bez blokady i bez zapisu atomowego.
* **Rozwiązanie:**
  1. Dodano blokadę wątkową `_conv_lock = threading.Lock()`.
  2. Zastosowano zapis atomowy: najpierw zapis do `conv_state.json.tmp`, a następnie atomowa podmiana `os.replace`.

---

### BUG 21: Inteligentny Model Router i Mapowanie Aliasów Modeli Trae
* **Objawy:** Wybór w Trae modelu `- deepseek-v4-pro -` lub `deepseek-reasoner` powodował błędy 400 z powodu braku takiego identyfikatora w API.
* **Przyczyna:** Trae stosuje niestandardowe nazwy modeli i aliasy.
* **Rozwiązanie:**
  1. Wprowadzono router `_route_model()`, który automatycznie tłumaczy dowolną nazwę z Trae na odpowiednią konfigurację:
     - `deepseek-reasoner` / `v4-pro` -> `model_type='expert'`, `thinking=True`.
     - `deepseek-chat` / `v3` -> `model_type='expert'`, `thinking=False`.
     - `vision` / `image` -> `model_type='vision'`.

---

### BUG 22: Przepełnienie Kontekstu przez Gigantyczne Logi Terminala i Auto-Crush
* **Objawy:** Wynik polecenia terminala (np. zrzut drzewa plików lub logi testów o rozmiarze 500 KB) natychmiast zapychał okno kontekstu i powodował awarię DeepSeeka.
* **Przyczyna:** Narzędzie `RunCommand` w Trae zwróciło olbrzymią liczbę linii, którą naiwny proxy przesłał w całości w kolejnej turze.
* **Rozwiązanie:**
  1. Wprowadzono mechanizm `_crush_tool_results()`, który automatycznie wykrywa i kompresuje wielkie wyniki narzędzi, zachowując nagłówek i ostatnie kilkadziesiąt linii, co zapobiega crashom i oszczędza kontekst.

### BUG 23: Zgubienie Pierwotnego Celu w Długich Konwersacjach (Goal Drift & Goal Preservation Engine)
* **Objawy:** Po 20–30 turach subagenta (np. wielokrotne czytanie plików) model zapominał, po co w ogóle czyta pliki i zaczynał generować luźne komentarze zamiast zrealizować zadanie (np. stworzyć plik `.md`).
* **Przyczyna:** Przy rotacji sesji lub kompresji historii (`_crush_tool_results`) pierwotna instrukcja użytkownika z wiadomości nr 1 ulegała rozmyciu w potoku setek tysięcy znaków.
* **Rozwiązanie:**
  1. Zaimplementowano silnik `_extract_goals()` oraz `format_goals_context()`, który stale ekstrahuje pierwotny cel zadania (`original_task_goal`) i wstrzykuje go jako priorytetowy nagłówek `[CURRENT TASK GOAL]` do każdego promptu odbudowywanej sesji.

---

### BUG 24: Wyciek Znaczników Wodnych Sesji (`<!-- PROXY_SID:... -->`) do Interfejsu Klienta
* **Objawy:** W oknach czatu użytkownika pojawiały się techniczne komentarze HTML: `<!-- PROXY_SID:55ba0517-c81b-4f7b-a25e-38f36214ef5e -->`.
* **Przyczyna:** Proxy dodawało znacznik wodny na końcu strumienia, aby w kolejnych turach powiązać odpowiedź z właściwym `conv_key`. Jednak przy niektórych formatach Trae nie ukrywało komentarzy HTML.
* **Rozwiązanie:**
  1. Wprowadzono filtr `_strip_leak()` w warstwie wyjściowej oraz ograniczenie wstrzykiwania znaczników wyłącznie do odpowiedzi z narzędziami.

---

### BUG 25: Utrata Tekstu Preambuły Wygenerowanego Przed Pakietem `response_message_id` (Pre-Response Fallback)
* **Objawy:** Brakujące początkowe zdania odpowiedzi w rzadkich przypadkach, gdy DeepSeek rozpoczął strumieniowanie tekstu przed wysłaniem nagłówka z ID wiadomości.
* **Przyczyna:** Pętla preambuły zbierała linie w buforze `pre_lines`. Jeśli `response_message_id` pojawił się dopiero po kilku liniach tekstu, standardowy generator zaczynał od `remaining_it`, tracąc wcześniejsze linie.
* **Rozwiązanie:**
  1. Zastosowano `itertools.chain(pre_lines, remaining_it)` oraz mechanizm `[FALLBACK] yielding N chars of pre-response text`, gwarantujący zerową utratę tokenów.

---

### BUG 26: Zrywanie Połączeń SSE przez Pośrednie Warstwy Sieciowe z Powodu Braku SSE Keep-Alive Heartbeat
* **Objawy:** Połączenia z klientem były zrywane z kodem `ECONNRESET` po 30–60 sekundach ciszy podczas długiego myślenia modelu (CoT) lub generowania dużych partii danych.
* **Przyczyna:** Pośredniczące zapory sieciowe, proxy systemowe lub klienty HTTP zrywają bezczynne połączenia SSE bez pakietów podtrzymujących.
* **Rozwiązanie:**
  1. Wprowadzono wysyłanie pustych komentarzy SSE `: keep-alive\n\n` co 15 sekund w trakcie oczekiwania na kolejne pakiety.

---

### BUG 27: Niespójność Typów Parametrów w Tagach XML (`true`/`false`/`123` jako Stringi zamiast Typów Natywnych)
* **Objawy:** Narzędzia takie jak `RunCommand(blocking=true)` lub `Read(limit=50)` rzucały w Trae błąd walidacji schematu JSON (`Expected boolean, got string "true"`).
* **Przyczyna:** Parser XML wyciągał wartości tagów zawsze jako stringi tekstowe (`"<limit>50</limit>" -> "50"`).
* **Rozwiązanie:**
  1. Zaimplementowano funkcję `_parse_param_value()`, która automatycznie rzutuje `"true"` -> `True`, `"false"` -> `False`, `"123"` -> `123`, a zagnieżdżone obiekty JSON parsuje do słowników Pythona.

---

### BUG 28: Zapętlenia Przełącznika Trybów Hybrydowych (`free_first` vs `official_fallback`)
* **Objawy:** Proxy w pętli przełączało się między kontem darmowym a płatnym API przy zapytaniach subagentów.
* **Przyczyna:** Brak izolacji subagentów od trybu fallback. Subagenty generują gigantyczny kontekst, który na płatnym API generowałby ogromne koszty lub błędy salda.
* **Rozwiązanie:**
  1. Wymuszenie `is_subagent` -> subagenty zawsze korzystają z puli darmowej (`free_first`), a fallback na oficjalne API jest zarezerwowany wyłącznie dla głównego wątku koordynatora.

---

### BUG 29: Niedopasowanie Identyfikatorów `tool_call_id` i Kolejności Ról Wiadomości w Protokole Trae
* **Objawy:** Błąd 400 Bad Request `Invalid message order: tool message must follow assistant message with tool_calls`.
* **Przyczyna:** Gdy Trae przesłało wyniki narzędzi w zmienionej kolejności lub gdy proxy przy rotacji pominęło pustego asystenta, protokół OpenAI rzucał błąd struktury.
* **Rozwiązanie:**
  1. Zaimplementowano funkcję sanityzacji historii `_normalize_messages()`, która automatycznie paruje `tool_call_id` i wstrzykuje brakujące wiadomości `assistant` przed powiązanymi wynikami `tool`.

### BUG 30: Crash Logera Konsoli Windows przez Znaki Unicode (`\u2192` / UnicodeEncodeError w stdout)
* **Objawy:** Całe żądanie z Trae nagle kończyło się błędem 500 Internal Server Error, a w pliku `data/server_errors.log` pojawiał się ślad:
  `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 126: character maps to <undefined>`.
* **Przyczyna:** Podczas wypisywania w konsoli strzałek migracji (`account 2 → account 3`) lub znaków specjalnych, standardowy strumień `sys.stdout` w Windows korzystał z kodowania `CP1250`, które nie posiadało mapowania dla znaku `\u2192`.
* **Rozwiązanie:**
  1. Wprowadzono bezpieczny logger z rekonfiguracją strumienia: `sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')`.

---

### BUG 31: Blokada Wątków i Wyścigi Pamięci Podręcznej PoW (Concurrent PoW Contention)
* **Objawy:** Przy równoczesnym starcie 4 subagentów, wszystkie wątki próbowały jednocześnie wyliczać i zapisywać token PoW dla tych samych kont, co powodowało unieważnianie cache i powtórne zapytania.
* **Przyczyna:** Brak granulacji blokad na poziomie pojedynczych slotów kont (`_pow_locks[account_idx]`).
* **Rozwiązanie:**
  1. Wprowadzono per-account lock oraz mechanizm prefetchingu tokenów PoW w tle (`[POW] prefetched for account=N`), dzięki czemu żądania nie czekają na obliczenia PoW w krytycznej ścieżce HTTP.

---

### BUG 32: Deserializacja Zagnieżdżonych Argumentów Narzędzi (Recursive JSON Serialization)
* **Objawy:** Narzędzia przyjmujące zagnieżdżone obiekty lub tablice (np. `TodoWrite(todos=[{"content": "..."}])` lub `SearchReplace`) przekazywały do Trae podwójnie zescape'owane stringi `"[{\"content\": ...}]"` zamiast właściwej tablicy JSON.
* **Przyczyna:** Podwójne wywołanie `json.dumps()` w trakcie scalania parametrów z formatów XML i JSON.
* **Rozwiązanie:**
  1. Zaimplementowano w `_parse_tool_calls` weryfikację typów przed serializacją — jeśli wartość jest już poprawnym słownikiem/listą, jest łączona bezpośrednio bez zbędnego podwójnego kodowania stringów.

---

## 4. Tabela 9 Formatów Wywołań Narzędzi w DeepSeek

| Nr | Nazwa Formatu | Przykładowa Składnia | Status w Proxy |
| :--- | :--- | :--- | :--- |
| **1** | Pełny XML Standardowy | `<tool_call name="LS"><path>...</path></tool_call>` | Obsługiwany |
| **2** | Skrócony XML | `<_call name="Read"><file_path>...</file_path></_call>` | Obsługiwany |
| **3** | Bezpośredni XML Narzędzia | `<Read><file_path>...</file_path></Read>` | Obsługiwany |
| **4** | DSML Tool Call | `<｜DSML｜><invoke name="Grep">...</invoke>` | Obsługiwany |
| **5** | Natywny DeepSeek Marker | `<｜tool call begin｜>function<｜tool sep｜>Read\n{...}` | Obsługiwany |
| **6** | Chiński Marker Wywołania | `[调用Read]{"file_path": "..."}` | Obsługiwany |
| **7** | XML z Zagnieżdżonym JSON | `<tool_call>{"name": "LS", "arguments": {...}}</tool_call>` | Obsługiwany |
| **8** | Styl CLI / Tekstowy | `Read file_path: "foo.py" limit: 50` | Obsługiwany |
| **9** | Blok Markdown JSON | ` ```json\n{"tool": "LS", "args": {"path": "..."}}\n``` ` | Obsługiwany (Zbalansowany depth `{}`) |

---

## 5. Przewodnik Diagnostyczny i Debugowanie Krok po Kroku

Gdy jakikolwiek proces agentowy wydaje się wisieć:

1. **Krok 1: Sprawdź stan portów i procesów:**
   ```powershell
   Get-NetTCPConnection | Where-Object { $_.OwningProcess -eq (Get-Process -Name python).Id } | Select-Object LocalPort, RemoteAddress, RemotePort, State
   ```
   * *`Established` na porcie 4570:* Trae jest połączone z proxy.
   * *`Established` do 3.173.x.x:443:* DeepSeek przesyła dane.
   * *`CloseWait`:* DeepSeek zakończył strumień (normalne między turami lub sygnał do Auto-Continue).

2. **Krok 2: Sprawdź najświeższy ogon logu proxy:**
   ```powershell
   Get-Content "c:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\deepseek-proxy-clean\proxy_output.log" -Tail 40
   ```

3. **Krok 3: Sprawdź obecność plików wynikowych:**
   ```powershell
   Get-ChildItem "c:\Users\Ksawier\Pictures\Screenshots\Projekty_autorskie\skrót"
   ```

---

## 6. Nienaruszalne Zasady Architektoniczne dla Kolejnych Agentów

1. **Zasada Pesymizmu i Determinizmu:** Zawsze sprawdzaj stan faktyczny w systemie (gniazda, logi, pliki) przed postawieniem hipotezy.
2. **Zakaz Blokujących Pętli Bez Watchdoga:** Żadna pętla `for line in iterator` nie może działać bez 60-sekundowego limitu bezczynności.
3. **Autonomia Ponad Wszystko:** Nigdy nie zwracaj do subagenta komunikatów tekstowych proszących o akcję człowieka — proxy musi rozwiązać problem transparentnie.
4. **Nienaruszalność Formatów Narzędzi:** Każdy nowy format wygenerowany przez LLM musi być natychmiast rejestrowany w `_parse_tool_calls` wraz z dedykowanym testem w `scratch/`.
