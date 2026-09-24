# DeepSeek Proxy — Agentic Architecture Redesign

**Date:** 2026-07-14
**Status:** Draft

## Context

DeepSeek V4 Pro web chat proxy (`deepseek-proxy/server/`) służy jako translator
między OpenAI-compatible API (Trae IDE) a plaintext API DeepSeek web chat (`api/v0/chat/completion`).

Obecna architektura:
- `server.py` (monolit, ~2000 linii) — legacy, do archiwizacji
- `server/main.py` (modularny) — aktywny, importuje `server.api.routes` → `core.proxy.ProxyService`
- `proxy.py` (998 linii) — robi wszystko: parsowanie, prompt building, streaming, recovery
- `services/prompt_service.py` — buduje prompt, dokleja tool schemy zawsze na końcu

### Problem

1. **Tool schema duplication**: Trae IDE wysyła system prompt z narzędziami. Proxy dokleja drugi zestaw → model dostaje sprzeczne instrukcje
2. **Silent tool call drops**: StreamSieve + parser cicho dropują nieparsowalne tool calle → model degraduje się do chatbota
3. **Rozsmarowana logika recovery**: retry/rate-limit/migration w 3 miejscach
4. **proxy.py za duży**: 998 linii, miesza orkiestrację z logiką

### Cel

Czysta, warstwowa architektura gdzie każda warstwa ma jedną odpowiedzialność.
Zero duplication tool schemów. Niezawodna detekcja i naprawa tool calli.

## Architecture

```
Trae IDE
   │
   ▼
┌────────────────────────────────────────┐
│  api/routes.py + deps.py               │
│  (cienkie endpointy, DI)               │
├────────────────────────────────────────┤
│  core/proxy.py                         │
│  (ORKIESTRATOR — tylko klejenie)      │
│     │                                   │
│     ├── InputParser  → ParsedRequest    │
│     ├── PromptBuilder → plaintext       │
│     ├── DeepSeek.stream_completion()    │
│     └── StreamHandler + ToolMgr → SSE  │
├────────────────────────────────────────┤
│  core/deepseek_client.py (bez zmian)   │
│  services/state_service.py (bez zmian) │
│  parser/, repair/ (Tier 3 nowy)        │
└────────────────────────────────────────┘
```

### InputParser (`core/input_parser.py`) — NOWY

Odpowiedzialność: przyjąć raw JSON z Trae, wyfiltrować, zwrócić ParsedRequest.

```
Wejście: raw JSON body (messages, tools, stream, model, ...)
Wyjście: ParsedRequest {
    messages: list[dict]          # wyczyszczone
    tools: list[dict] | None
    has_tools_in_system_prompt: bool  # czy Trae już wysłał narzędzia
    is_resume: bool                   # czy to kontynuacja sesji
    model_type: str                   # expert / default / vision
    params: {...}                     # temperature, top_p, etc.
}
```

Filtrowanie:
- `<system-reminder>` — zachowaj **ostatni** (aktualny kontekst IDE). Usuń archiwalne z historii
- `role: tool` nowa sesja — ostatnie 3 wyniki w pełni, starsze → `[Tool result: N chars]`
- `role: tool` resume — pełna treść (DeepSeek ma historię, wysyłamy tylko deltę)
- Cap: 8000 znaków na tool result
- Puste messages → usuń
- Detekcja "czy Trae już wysłał narzędzia": skanuj `[System]:` w poszukiwaniu `<tool_call` lub `Available Tools:` lub `<tools>`

### PromptBuilder (`services/prompt_service.py`) — REFAKTOR

Odpowiedzialność: zbudować plaintext prompt dla DeepSeek.

```
Wejście: ParsedRequest
Wyjście: str (prompt)
```

Format: `[System]:`, `[User]:`, `[Assistant]:` (bez zmian, sprawdzony, nie triggeruje filtrów)

Logika dedupu:
1. Jeśli `has_tools_in_system_prompt == True` → **nie doklejaj** tool schemów, tylko sprawdź czy jest instrukcja formatowania
2. Jeśli brak instrukcji formatowania → doklej lekką wersję

Stealth tool call instruction (tylko gdy brak):

```
When using tools, use this format:
<tool_call name="ToolName">
  <parameter1>value1</parameter1>
</tool_call>
```

Bez "Available Tool Schemas" bloku (Trae już go wysłał).
Bez DSML tokenów. Bez CDATA.

### StreamHandler + ToolMgr (`core/stream_handler.py`) — NOWY

Odpowiedzialność: konsumować strumień z DeepSeek, wykrywać tool calle, naprawiać, emitować SSE.

**StreamHandler:**
- Wrapper wokół generatora z `deepseek_client.py`
- Przekazuje chunk do StreamSieve
- Gdy StreamSieve znajdzie tool calle → waliduj + SSE
- Gdy strumień skończony → flush + ToolMgr

**ToolMgr — Tier 3 repair (NOWY):**
- Tier 1-2 (istniejące) — naprawa XML i JSON
- Tier 3 — gdy repair nie da rady:
  1. Wyodrębnij tool name z kontekstu (ostatnie narzędzia w historii lub nazwy z tools listy)
  2. Zgadnij parametry z fragmentów XML (np. `command"="` → `command`)
  3. Jeśli nadal nie → loguj + emituj co się da zamiast silent drop
- Loguje wszystkie przypadki do `tool_repair_log.txt` dla debugowania

### ProxyService (`core/proxy.py`) — REFAKTOR

Odpowiedzialność: tylko orkiestracja, <300 linii.

```
async def chat_completions(raw_request):
    parsed = InputParser.parse(raw_request)
    prompt = PromptBuilder.build(parsed)
    stream, meta = DeepSeek.stream_completion(...)
    result = StreamHandler.handle(stream, meta, parsed)
    return result  # StreamingResponse lub JSONResponse
```

Cała logika recovery (rate-limit, mute, empty resume, length limit) w jednej metodzie `_recover()`.

### Error Recovery — scentralizowany

```
_recover(exception, context) → (stream, meta):
    1. PoP fail → clear PoW cache, retry 3x
    2. Rate limit → mark slot, try next account
    3. Empty resume → clear conv_state, new session
    4. Length limit → new session, truncated history
    5. Mute → mark slot until mute_until, migrate
```

## Tool Call Flow

```
Trae → POST /v1/chat/completions (messages + tools)
  │
  ▼
InputParser.parse() → ParsedRequest
  │
  ▼
PromptBuilder.build() → plaintext prompt (z dedupem)
  │
  ▼
DeepSeek.stream_completion(slot, chat_id, prompt)
  │
  ▼ (stream chunks)
StreamHandler.handle():
  ├── StreamSieve.feed(chunk) → SieveEvent
  │     ├── type="text"     → yield SSE content chunk
  │     └── type="tool_calls" → yield SSE tool_calls chunk
  ├── flush() → ToolMgr.repair(remaining) → yield SSE tool_calls lub text
  └── Done
  │
  ▼
Trae otrzymuje tool_calls → wykonuje → wysyła z tool_results
  │
  ▼ (kolejny request z tym samym chat_id)
PromptBuilder.build() → tylko delta (ostatnie tool_results + nowy user message)
  │
  ▼
DeepSeek.resume(slot, chat_id, delta_prompt, parent_id)
```

## Co się zmienia — podsumowanie

| Komponent | Plik | Status |
|---|---|---|
| InputParser | `core/input_parser.py` | NOWY |
| PromptBuilder | `services/prompt_service.py` | REFAKTOR (dedup) |
| ProxyService | `core/proxy.py` | REFAKTOR (orkiestracja) |
| StreamHandler | `core/stream_handler.py` | NOWY |
| ToolMgr (Tier 3) | `repair/__init__.py` + `repair/repair_tier3.py` | NOWY |
| Recovery | w `proxy.py` | SCENTRALIZOWANY |
| `server.py` | `_archive/server.py` | ARCHIWUM |
| Parser/repair | istniejące | BEZ ZMIAN |

## Testing

- InputParser: testy filtrowania, dedupu, detekcji narzędzi w prompt
- PromptBuilder: testy dedupu, stealth instrukcji, capów
- StreamHandler: testy z symulowanym strumieniem + tool calls
- ToolMgr Tier 3: testy naprawy uszkodzonych bloków
- Integration: full cycle przez proxy + mock DeepSeek
