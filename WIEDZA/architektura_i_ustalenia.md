# Architektura proxy, mechanizmy i ustalenia (fixy)

Jak działa proxy i co już ustaliliśmy / naprawiliśmy. Pełny katalog 32 bugów z post-mortem jest
w `../DOKUMENTACJA_BUGOW_I_POSTMORTEM.md` — tu jest skondensowany obraz + najnowsze ustalenia.

## 1. Architektura (pliki i role)

- `server.py` — główny serwer (FastAPI/uvicorn), cała logika proxy. Port 4570.
- `official_api.py` — klient oficjalnego API `api.deepseek.com/v1/chat/completions` (dla main agenta).
- `pow.py` — solver Proof-of-Work; `login.py` / `login_slot.bat` — logowanie kont; `CloudflareBypasser.py` — omijanie Cloudflare.
- `debounce.py`, `conversation_tracker.py`, `subagent_isolation.py` — stan rozmów / debounce / izolacja subagentów.
- `session_*.json` (w katalogu głównym) — ciasteczka kont; `data/proxy_mode.txt` — tryb; `data/conv_state.json` — stan rozmów;
  `data/raw_stream_capture.jsonl` — nadpisywany surowy zrzut strumienia (diagnostyka).

## 2. Routing hybrydowy

Decyzja w `_handle_chat` (okolice `use_official_api`):

- `_is_actual_subagent()`: dokładnie **2 wiadomości** i brak wzorców systemowych Trae
  (`"You are an interactive agent in TraeCode"`, `"# Doing tasks"`, `"TraeCode"`).
- **Web** (darmowy) gdy: tryb ∈ {`web`, `free`, `biedny`, `free_first`} LUB `--clean` LUB vision LUB
  `model_type != "expert"`.
- **Official API** (płatne, `deepseek-chat`, natywne JSON tool_calls) tylko w trybie `auto` dla
  main agenta (nie-subagent, nie-vision, klucz dostępny).
- Tryb `free_first`: main agent najpierw Web, a przy `Content is too long` przełącza na official.
- **Profil `model_type`**: `vision` | `expert` | `default` (ten ostatni usunięty 2026-08-15).
  Subagent był zmuszany do `default` (Flash); teraz `expert` (jak główny agent). Gałąź nazw
  modeli `fast`/`flash` również → Expert. W efekcie `model_type="default"` nie istnieje w kodzie.

## 3. Mechanizmy

- **Parser stanowy `_stream()`** — serce strumienia. Osobne bufory:
  - `content_buffer` — tylko RESPONSE → idzie do Trae.
  - `thinking_buffer` — tylko THINK → tłumione (nie wycieka).
  - `_begin_phase()` (deklaracja fragmentu) i `_route_token()` (routing tokenu) + fallback
    dla tokenów bez deklaracji fazy (= RESPONSE).
- **Auto-continue** — gdy brak `FINISHED` lub urwany tag narzędzia:
  - wysyła `KONTYNUUJ` z `parent_message_id` w tej samej sesji, budżet = 2.
  - warunek: `(not finished_normally or _has_unclosed_tool_call(content_buffer)) and budget>0 and content_buffer.strip()`.
- **Loop guard `_detect_loop()`** — wykrywa powtarzający się 15–50-znakowy wzór ≥4× w ostatnich 300 znakach.
- **Heartbeat SSE `_heartbeat_iter()`** — co 15 s wysyła `: keep-alive` w trakcie ciszy (myślenie).
- **Watchdog `_iter_lines_with_watchdog()`** — timeout 60 s bezczynności.
- **Chunked ingestion** — prompt > 50000 znaków dzielony na chunki (łańcuch `parent_message_id`).
- **Crash dump `_write_crash_dump()`** — awaryjny zrzut stanu do `data/crashed_chats/`.

## 4. Najnowsze ustalenia i fixy (2026-08-15)

To są rzeczy, których **nie ma** w starej `DOKUMENTACJA_BUGOW_I_POSTMORTEM.md`:

1. **Przedwczesne zakończenie głównego agenta (naprawione).**
   Fallback po strumieniu uznawał ucięty strumień (bez `FINISHED`) za „kompletny" na podstawie
   heurystyk długości (`len(buf) > 500` itd.). To ustawiało `finished_normally=True` i **blokowało
   auto-continue**. Dowód: jedyne `[STREAM] Fallback: marked complete (110329 chars, tools=0/0)`
   w całym logu (linia 37665) — wszystkie inne urwane strumienie poprawnie odpalały auto-continue.
   **Fix**: usunięto cały blok fallback. Teraz brak `FINISHED` → zawsze auto-continue.

2. **Błędny odczyt `cont_finished` (naprawione).**
   `cont_finished` był czytany z `cont_meta` **przed** skonsumowaniem generatora kontynuacji, a jest
   ustawiany dopiero na końcu `_stream()` → zawsze `False`. Skutek: gdy `KONTYNUUJ` zwracał samo
   `FINISHED` bez nowej treści, proxy retry'owało zamiast uznać koniec. **Fix**: odczyt przeniesiony
   po pętlę konsumującą generator.

3. **Wyciek reasoning i gubione tokeny subagentów (naprawione wcześniej w tej sesji).**
   Naprawa parsera: osobne bufory THINK/RESPONSE + obsługa ścieżki `response/fragments/-1/content`.

4. **Błąd liczenia tagów w fallbacku (usunięty razem z fallbackiem).**
   Fallback liczył `"<tool_call>"`, a realny format to `<_call>` → `0==0` zawsze „zbalansowane".

5. **Wyciek watermarku `<!-- PROXY_SID:...-->` (naprawione 2026-08-15).**
   Watermark był wstrzykiwany na końcu treści w 3 miejscach: `generate_official` (stream official),
   non-stream (`msg["content"] += ...`) i web `generate` (blok `tools_yielded == 0`). Przeciekał do UI
   Trae i psuł wyświetlanie (pierwsza odpowiedź nie pokazywała się, choć proxy ją wysłało).
   **Fix**: usunięto wszystkie 3 wstrzyknięcia. `WM_PATTERN` / `_extract_watermark()` (odczyt) zostawiono
   dla wstecznej zgodności starych rozmów. Uwaga: BUG 24 w `DOKUMENTACJA_BUGOW_I_POSTMORTEM.md` fałszywie
   twierdził, że istnieje filtr `_strip_leak()` — nie istniał.

6. **Niestabilny `conv_key` (naprawione 2026-08-15).**
   `_get_conv_key()` używał pełnego `legid` z ACL jako części klucza (`jwt_leg_{legid}_{user_fp}`),
   ale `legid` to dict z polami zmiennymi między turami (`expireTime`, `extension.physical_cluster`),
   więc klucz zmieniał się co turę → rozmowa się nie sklejała. Watermark był protezą na to.
   **Dowód**: `data/diag_headers.jsonl` — Trae nie wysyła ŻADNEGO `chat_id`/`conversation_id`/`thread_id`;
   body = `max_tokens, messages, model, stream, tools`; w ACL stałe `sub`, `legid.user`, `legid.psm`,
   zmienne `legid.expireTime`, `legid.extension.physical_cluster`.
   **Fix**: `_get_conv_key` używa `legid.user` (fallback `legid.sub`) + `user_fp` (hash pierwszego
   `<user_input>`). Tożsamość rozmowy w Trae = resend całej historii co turę, więc `user_fp` (pierwsze
   `<user_input>`) jest stabilny. Usunięto też martwe aliasy `_conv_state[f"wm_{watermark_uuid}"]`
   (4 bloki zapisu + 2 `pop`).

7. **Symptom „echo tool-calli" ≠ watermark.**
   Darmowy Flash wypisywał surowe parametry tool-calla (`def _get_conv_key ... <parameter name`) zamiast
   wykonać narzędzie. To osobny objaw od wycieku watermarku — wynika ze słabego modelu i/lub parsera
   tool-calli, NIE z tożsamości sesji. Nie naprawia go ani watermark, ani `conv_key`.

## 5. Testy regresyjne

- `scratch/test_auto_continue_e2e.py` — 5 testów (auto-continue, loop guard, detekcja urwanego tagu,
  auto-continue przy urwanym tagu, **duży content bez FINISHED → auto-continue**).
- `scratch/test_thinking_stream.py` — 2 testy (thinking vs response, bare tokens).
- `scratch/test_heartbeat.py` — heartbeat SSE.

Uruchomienie: `python scratch/<plik>.py` z katalogu projektu.
