# Protokół DeepSeek Web (inżynieria wsteczna)

To jest wiedza o tym, jak `chat.deepseek.com` zachowuje się „pod spodem" — format strumienia,
fazy myślenia/odpowiedzi, wywołania narzędzi, sygnały zakończenia, PoW, limity i błędy.
Wszystko potwierdzone na logach `proxy_output.log` i surowym zrzucie `data/raw_stream_capture.jsonl`.

## 1. Sesja i Proof-of-Work (PoW)

- Pula **6 darmowych kont** (`session_0.json` – `session_5.json` w katalogu głównym projektu), sticky per konwersacja (`conv_key`).
- Każde żądanie wymaga tokenu **PoW** w nagłówku `x-ds-pow-response`. Trudność widywana w logach:
  `difficulty=144000`. Tokeny są cache'owane/prefetchowane per konto.
- Token PoW potrafi wygasnąć (`INVALID_POW_RESPONSE`, AWS WAF TTL) → wtedy czyścimy cache i retry.
- Warstwa transportu: `curl_cffi` z podszywaniem się pod Chrome (JA3 fingerprint evasion), `timeout=300`.
- `create_session` zwraca `chat_session` z `id`, `seq_id` i `ttl_seconds: 259200` (~3 dni).

## 2. Format strumienia SSE

- Endpoint zwraca `text/event-stream`. Każda linia `data: {json}` to jeden pakiet.
- **Preamble**: pierwszy istotny pakiet to `{"response_message_id": N}` → ustawia `resp_msg_id`
  (potrzebne jako `parent_message_id` do auto-continue).
- Pakiet `{"v": { "response": { ... } }}` niesie stan odpowiedzi. Ważne pola `response`:
  - `message_id`, `parent_id`, `role`, `thinking_enabled` (bool), `status` (`WIP` → `FINISHED`),
  - `fragments` — lista fragmentów fazowych.

### 2.1. Tokeny treści (deltas)

Tokeny przychodzą **trzema** ścieżkami:

| Ścieżka (`p`) | Znaczenie |
|---|---|
| `""` (puste `p`) | delta tekstu bieżącej fazy (THINK lub RESPONSE) |
| `response/fragments/-1/content` (+ `o:"APPEND"`) | append do treści **ostatniego** fragmentu (`-1`) |
| `response/fragments` | re-deklaracja listy fragmentów |

- Fragmenty mają `type` ∈ {`THINK`, `RESPONSE`} i początkowy `content`.
- `response/fragments/-1/content` to najważniejsza, łatwa do przeoczenia ścieżka — wcześniej
  była ignorowana i gubiła tokeny.

### 2.2. Sygnały zakończenia (FINISHED)

DeepSeek sygnalizuje koniec na **jeden z 3 sposobów**:

1. `v.response.status` / `v.response.state` zawiera `FINISHED` / `COMPLETED` / `DONE`.
2. `o == "BATCH"` i `v` = lista zawierająca `{"p": "quasi_status", "v": "FINISHED"}`.
3. `p == "response/status"` i `o == "SET"` i `v == "FINISHED"`.

**Kluczowe**: gdy model dojedzie do limitu długości odpowiedzi, DeepSeek **po prostu kończy SSE
bez żadnego z tych sygnałów**. To jest główna przyczyna „urwanych" odpowiedzi — rozpoznajemy to
po braku `FINISHED` i wtedy odpalamy auto-continue.

## 3. Fazy THINK / RESPONSE (izolacja myślenia)

- `thinking_enabled` włącza fazę myślenia (reasoning / CoT).
- **THINK** = tok myślenia modelu (NIE może trafić do klienta / Trae).
- **RESPONSE** = właściwa odpowiedź + wywołania narzędzi (to jedyne, co idzie do klienta).
- Reguła parsera: token bez deklaracji fazy = RESPONSE (tryb bez myślenia). Myślenie jest tłumione
  **tylko** gdy DeepSeek jawnie zadeklarował fragment `THINK` przed tokenami.

## 4. Format wywołań narzędzi

Narzędzia to zwykły tekst w fazie RESPONSE, w jednym z wielu formatów (parser `_parse_tool_calls`):

1. `<_call name="Tool">...</_call>` — **główny format Web**; argumenty mogą zawierać zagnieżdżone
   tagi, np. `<file_path>plik.md</file_path>`.
2. `<tool_call name="Tool">`, `<invoke name="Tool">`, `<tool_capability>`, `<call>`, `<tool>`.
3. Warianty DSML: `<| |DSML| |name="Tool">...</| |DSML| |>` oraz luźne `| |DSML| |name="Tool">`.
4. Natywny DeepSeek: `<｜tool call begin｜>function<｜tool sep｜>name` + blok `json`.

- Argumenty: `<parameter name="x">wartość</parameter>` albo wbudowany JSON `{...}`.
- Detektor urwanego tagu `_has_unclosed_tool_call` szuka otwarć i zamknięć dla:
  `tool_call | invoke | tool_capability | _call | call | tool`.
- **Pułapka**: liczenie tagów w fallbacku używało tylko `"<tool_call>"`, a realny format to
  `<_call>` — stąd fałszywe „0==0" (zbalansowane).

## 5. Limity, błędy i retry

- **Kontekst / chunked ingestion**: próg `CHUNK_THRESHOLD = 50000` znaków. Prompt powyżej progu
  dzielony na chunki i wstrzykiwany łańcuchem `parent_message_id`.
- **Limit tur**: Web ma limit długości rozmowy (~50–60 tur) — dlatego dla głównego agenta istnieje
  oficjalne API (bez tego limitu).
- **Błędy rozpoznawane po treści**: `too frequent`, `server is busy`, `message is being generated`,
  `parallel_chat_limit`, `Content is too long`, `input_exceeds_limit`, `length limit`, `start a new chat`.
- **Reakcja na rate limit**: backoff 60±random sekund, retry, potem migracja na inne konto (429 / server busy).
- `max_tokens` żądania = 8192; oficjalne API używa `max_completion_tokens or max_tokens`.
