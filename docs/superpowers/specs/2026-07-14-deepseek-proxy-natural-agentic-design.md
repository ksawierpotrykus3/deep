# DeepSeek Proxy — Natural Prompt Architecture

**Date:** 2026-07-14
**Status:** Draft

## Context

DeepSeek V4 Pro web chat proxy (`deepseek-proxy/server/`) tłumaczy OpenAI-compatible API
(Trae IDE, Cline, Claude Code, etc.) na plaintext API DeepSeek web chat (`api/v0/chat/completion`).

**Kluczowe ograniczenia:**
- Web chat tylko (nie oficjalne API)
- Format wiadomości musi być naturalny — maszynowe znaczniki triggerują filtry → mute/ban
- Tool calls są wykrywane przez proxy i przesyłane do IDE przez SSE — proxy nie wykonuje narzędzi

**Problem:** Tool schema duplikacja (3 miejsca doklejają narzędzia) + niekompletna detekcja
tool calli w strumieniu → silent dropy.

## Zasady architektury

1. **Zero duplikacji** — narzędzia doklejane w jednym miejscu, tylko jeśli brak
2. **Słuchaj modelu, nie walcz** — model natywnie umie DSML, nie wymuszaj formatu
3. **Zero silent dropów** — każdy tool call jest wykryty lub zalogowany
4. **Naturalny format** — `[System]:` / `[User]:` / `[Assistant]:` bez DSML, CDATA, specjalnych tagów

## Komponenty

```
InputParser
  ↓ ParsedRequest
PromptBuilder
  ↓ plaintext (naturalny, dedup)
DeepSeekClient / AccountPool
  ↓ stream chunks
StreamHandler → ToolMgr → SSE
  ↓                    ↑
  └── StreamSieve ─────┘
  └── tool_parser (Tier 4 fallback)
```

### InputParser (`server/core/input_parser.py`)

Rozszerzona detekcja tool schemów w system prompt:

```python
_TOOL_IN_SYSTEM_RE = re.compile(
    r"<\s*tool_call[^>]*>|Available Tools:|<tools>|"
    r'"functions"|"tools"|"function"',  # format OpenAI w system prompt
    re.IGNORECASE,
)
```

### PromptBuilder (`server/core/prompt_builder.py`)

Usunąć:
- `_TOOL_CALL_INSTRUCTION` (DSML format instruction z CDATA)
- `_format_tool_schemas()` (dokleja pełne schemy)
- `needs_tool_injection()` zastąpić `_tools_not_in_system_prompt()`

Zostaje tylko naturalne formatowanie:

```python
def _format_tool_names(tools_schema: list[dict]) -> str:
    names = []
    for t in tools_schema:
        fn = t.get("function", t)
        name = fn.get("name", "")
        if name:
            names.append(name)
    if not names:
        return ""
    return f"Available tools: {', '.join(names)}"
```

Logika build:

**Nowa sesja (pierwsza wiadomość w rozmowie):**
- Jeśli `system_prompt` zawiera tool schemy → `has_tools = True`
- Jeśli `has_tools == True` → **nie doklejaj nic**
- Jeśli `has_tools == False` i `tools_schema` istnieje → doklej `Available tools: Read, Write, ...`
- Jeśli `history` zawiera `role: tool` lub `tool_calls` → przekaż jako `[Tool Result]:` / `[Assistant]:`

**Resume (kontynuacja istniejącej sesji DeepSeek):**
- `tools_schema = None` (narzędzia już są w sesji)
- `system_prompt = None` (system prompt już jest w sesji)
- Tylko delta: tool result + nowa wiadomość usera
- Żadnych narzędzi, instrukcji, system prompt — DeepSeek ma historię w chat_session

**Brak** `_TOOL_CALL_INSTRUCTION`, CDATA, DSML, specjalnych tagów w obu przypadkach.

### dsml_parser (`server/parser/dsml_parser.py`)

Usunąć `build_dsml_tool_prompt()` — parser nie buduje prompta.
Zostaje jako czysty parser DSML/XML/JSON.

### prompt_service (`server/services/prompt_service.py`)

Usunąć wołanie `build_dsml_tool_prompt()` z `build_prompt()`.
Zostaje tylko formatowanie `[System]:`, `[User]:`, `[Assistant]:`.

### dsml_sieve (`server/parser/dsml_sieve.py`)

Rozszerzyć `TOOL_STARTS`:

```python
TOOL_STARTS = [
    "<|DSML|tool_calls>", "|DSML|tool_calls>",
    "<|TOOL|tool_calls>", "|TOOL|tool_calls>",
    "<tool_calls>", "<tool_call>", "<tool_call ",
    "<toolcall>", "<toolcall ", "<tool_called ", "<tool_called>",
    "<invoke ", "<|DSML|invoke ", "|DSML|invoke ",
    "<|TOOL|invoke ", "|TOOL|invoke ",
    "<tool_use_json>",
    "<function_call>", "<function_calls>",
    "<argument ",                        # trained fallback format
    "<|begin▁of▁sentence｜>",           # BOS leak (thinking mode)
    "<|Assistant｜>",                    # role leak
]
```

### stream_handler (`server/core/stream_handler.py`)

ToolMgr z Tier 4 fallbackiem:

```python
class ToolMgr:
    @staticmethod
    def try_parse(text: str, tool_names: list[str]) -> list[dict]:
        # Tier 1-3 (existing repair pipeline)
        # Tier 4: legacy tool_parser fallback
        if not calls:
            from server.parser.tool_parser import _parse_tool_calls
            parsed = _parse_tool_calls(text, ...)
            if parsed:
                calls = [{"name": name, "arguments": args} for ... in parsed]
        return calls
```

### tool_parser (`server/parser/tool_parser.py`)

Zmiana statusu: DEPRECATED → `ToolMgr._legacy_fallback()`.
Żadna funkcja nie jest usuwana.

## Resume flow (szczegółowo)

```
IDE → POST /v1/chat/completions (wszystkie messages od początku)
  │
  ▼
state_service.get_conv(messages) → hash ostatnich N wiadomości
  │
  ├── hash MATCH (konwersacja istnieje) → resume
  │     ├── chat_id, parent_id z conv_state
  │     ├── delta_msgs = messages[last_assistant_idx+1:]
  │     │   (tool results + nowa wiadomość usera)
  │     ├── PromptBuilder.build(
  │     │     user_message = ostatnia user wiadomość z delta,
  │     │     system_prompt = None,     # nie wysyłaj, DeepSeek ma
  │     │     history = tool resulty z delta,
  │     │     tools_schema = None,      # nie wysyłaj, DeepSeek ma
  │     │   )
  │     ├── ds.stream_completion(slot, chat_id, prompt_delta, parent_id)
  │     └── parent_id → stream → tool calls → SSE
  │
  └── hash MISS → nowa sesja
        ├── new chat_id = ds.create_session(slot)
        ├── prompt = PromptBuilder.build(
        │     user_message,
        │     system_prompt,
        │     history (opcjonalnie),
        │     tools_schema (tylko jeśli brak w system),
        │   )
        ├── ds.stream_completion(slot, chat_id, prompt, None)
        └── parent_id = None → stream → tool calls → SSE
```

**Przykład resume:**

Turn 1 (nowa sesja):
```
Prompt: [System]:\nYou are...
        [Available Tool]: Read\n  Description: ...
        [User]:\nread file foo.py
        [Assistant]:
```
→ DeepSeek tworzy chat_session `sid_abc`
→ stream: tool_calls [Read(file="foo.py")]
→ conv_state: {hash: {chat_id: "sid_abc", parent_id: "msg_1", account: 0}}

Turn 2 (resume, IDE wysyła wszystkie messages od początku):
```
hash(ostatnie wiadomości) → match → sid_abc, msg_1

Delta prompt (tylko):
  [Tool Result]:\ncontents of foo.py
  [User]:\nnow edit it
  [Assistant]:
```
→ `ds.stream_completion(0, "sid_abc", delta_prompt, "msg_1")`
→ DeepSeek ma historię, dostaje tylko deltę
→ stream: tool_calls [Edit(file="foo.py", ...)]

**Kluczowe:** przy resumie nigdy nie wysyłamy tool schemów, system prompt, ani historii którą DeepSeek już ma.

## Pliki bez zmian

- `deepseek_client.py` — AccountPool, PoW, streaming
- `state_service.py` — conv_state
- `auth_service.py` — Chrome login
- `account_service.py` — slot management
- `proxy_service.py` — orkiestracja (tylko importy zmiana)
- `repair/` — repair tier1-3

## Error handling

| Sytuacja | Reakcja |
|---|---|
| Tool call nierozpoznawalny | log + yield text (nie silent drop) |
| Tool schemat duplikacja w requestcie | log warning + przetwarzaj raz |
| Mute / rate limit | obecny mechanizm migracji konta |
| Stream chunk z BOS leak | StreamSieve wykrywa, przepuszcza jako text |
| Tool call detect timeout | zwiększyć `_DRAIN_TIMEOUT` z 30s do 60s |

## Testing

- `test_prompt_builder.py` — dedup w nowej sesji, brak DSML, `_format_tool_names`
- `test_prompt_builder.py` — resume: tool_schema = None, system_prompt = None
- `test_dsml_sieve.py` — rozszerzone `TOOL_STARTS`
- `test_stream_handler.py` — ToolMgr Tier 4 fallback z tool_parser
- `test_proxy_service_basic.py` — integracja: cały cykl bez duplikacji
- `test_proxy_service_basic.py` — resume: tool result + nowa wiadomość → delta prompt
- `test_tool_parser_legacy.py` — legacy formaty jako Tier 4 fallback
