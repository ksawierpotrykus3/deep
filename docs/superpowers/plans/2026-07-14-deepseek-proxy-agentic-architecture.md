# DeepSeek Proxy — Agentic Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor DeepSeek proxy into clean layered architecture with tool dedup, silent recovery, and Tier 3 tool call repair.

**Architecture:** InputParser extracts & deduplicates from raw Trae request → PromptBuilder builds stealth prompt → StreamHandler+ToolMgr wraps DeepSeek stream with repair → ProxyService orchestrates only.

**Tech Stack:** Python 3.11+, FastAPI, curl_cffi, pytest

---

## File Structure

| File | Responsibility |
|---|---|
| `server/core/input_parser.py` | Parse raw JSON body, filter messages, detect tool presence |
| `server/core/stream_handler.py` | Consume DS stream, detect tool calls via StreamSieve, Tier 3 repair, yield SSE |
| `server/repair/repair_tier3.py` | Context-aware tool call reconstruction when Tier 1-2 fail |
| `server/services/prompt_service.py` | Build prompt with dedup logic (NO tool schema duplication) |
| `server/core/proxy.py` | Orchestrate the 4-step flow, centralized `_recover()`, <300 lines |
| `server/repair/__init__.py` | Add Tier 3 to pipeline |
| `_archive/debug-scripts/legacy_server.py` | Archived monolith `server.py` |
| `tests/core/test_input_parser.py` | InputParser tests |
| `tests/core/test_stream_handler.py` | StreamHandler + ToolMgr tests |
| `tests/services/test_prompt_dedup.py` | PromptBuilder dedup tests |
| `tests/repair/test_repair_tier3.py` | Tier 3 repair tests |

---

### Task 1: Create InputParser

**Files:**
- Create: `server/core/input_parser.py`
- Test: `tests/core/test_input_parser.py`

- [ ] **Step 1: Write `ParsedRequest` dataclass**

```python
# server/core/input_parser.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedRequest:
    messages: list[dict]
    tools: list[dict] | None = None
    has_tools_in_system_prompt: bool = False
    is_resume: bool = False
    is_vision: bool = False
    model_type: str = "default"
    chat_id: str | None = None
    stream: bool = True
    max_tokens: int = 8192
    temperature: float = 1.0
    top_p: float = 1.0
    reasoning_effort: str | None = None
    tool_choice: str | dict | None = None
    parallel_tool_calls: bool = False
```

- [ ] **Step 2: Write the failing test — detect tools in system prompt**

```python
# tests/core/test_input_parser.py
import json
import pytest
from server.core.input_parser import InputParser, ParsedRequest


class TestDetectToolsInSystem:
    def test_tools_detected_in_system_prompt(self):
        raw = {
            "messages": [
                {"role": "system", "content": "You are a helper.\n\n<tool_call name=\"Read\">\n  <file_path>test.txt</file_path>\n</tool_call>\n\nAvailable tools:\n\n<tools>\n  <tool_call name=\"Read\">\n    <file_path type=\"string\" required=\"true\"/>\n  </tool_call>\n</tools>"},
                {"role": "user", "content": "hello"},
            ],
            "tools": [{"function": {"name": "Read", "description": "Read a file"}}],
        }
        result = InputParser.parse(raw)
        assert result.has_tools_in_system_prompt is True
```

Run: `pytest tests/core/test_input_parser.py::TestDetectToolsInSystem::test_tools_detected_in_system_prompt -v`
Expected: FAIL (InputParser does not exist)

- [ ] **Step 3: Implement `InputParser.parse()` with tool detection**

```python
# server/core/input_parser.py

_TOOL_IN_SYSTEM_RE = re.compile(
    r"<\s*tool_call[^>]*>|Available Tools:|<tools>",
    re.IGNORECASE,
)

_SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>",
    re.DOTALL | re.IGNORECASE,
)

_MODEL_TYPE_MAP = {
    "deepseek-v4-pro": "expert",
    "deepseek-v4-flash": "default",
    "deepseek-chat": "default",
    "deepseek-reasoner": "expert",
    "deepseek-vision": "vision",
}


class InputParser:

    @staticmethod
    def parse(raw: dict, state: dict | None = None) -> ParsedRequest:
        messages = list(raw.get("messages", []))
        tools = raw.get("tools")
        model = raw.get("model", "deepseek-v4-pro")

        # Detect if tools are already in system prompt
        has_tools = False
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                if isinstance(content, str) and _TOOL_IN_SYSTEM_RE.search(content):
                    has_tools = True
                    break

        # Filter: keep last system-reminder, remove archived ones
        seen_reminders = []
        cleaned = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str) and "<system-reminder>" in content:
                # Keep only the last one per unique content
                seen_reminders.append(m)
                continue
            cleaned.append(m)
        if seen_reminders:
            # Keep only the last system-reminder
            cleaned += seen_reminders[-1:]

        # Determine resume
        is_resume = state is not None and state.get("parent_id") is not None

        return ParsedRequest(
            messages=cleaned,
            tools=tools,
            has_tools_in_system_prompt=has_tools,
            is_resume=is_resume,
            is_vision=model == "deepseek-vision",
            model_type=_MODEL_TYPE_MAP.get(model, "default"),
            stream=raw.get("stream", True),
            max_tokens=raw.get("max_completion_tokens") or raw.get("max_tokens", 8192),
            temperature=raw.get("temperature", 1.0),
            top_p=raw.get("top_p", 1.0),
            reasoning_effort=raw.get("reasoning_effort"),
            tool_choice=raw.get("tool_choice"),
            parallel_tool_calls=raw.get("parallel_tool_calls", False),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_input_parser.py::TestDetectToolsInSystem::test_tools_detected_in_system_prompt -v`
Expected: PASS

- [ ] **Step 5: Write test — tools NOT detected when absent**

```python
# Same file

class TestToolsNotInSystem:
    def test_tools_not_detected_when_absent(self):
        raw = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hello"},
            ],
            "tools": [{"function": {"name": "Read"}}],
        }
        result = InputParser.parse(raw)
        assert result.has_tools_in_system_prompt is False
        assert result.tools is not None
        assert result.tools[0]["function"]["name"] == "Read"
```

- [ ] **Step 6: Run test**

Run: `pytest tests/core/test_input_parser.py::TestToolsNotInSystem -v`
Expected: PASS

- [ ] **Step 7: Write test — system-reminder dedup (last kept)**

```python
# Same file

class TestSystemReminderFilter:
    def test_only_last_reminder_kept(self):
        raw = {
            "messages": [
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "<system-reminder>old context</system-reminder>"},
                {"role": "user", "content": "hello"},
                {"role": "user", "content": "<system-reminder>current context</system-reminder>"},
            ],
        }
        result = InputParser.parse(raw)
        reminders = [
            m for m in result.messages
            if isinstance(m.get("content", ""), str) and "<system-reminder>" in m["content"]
        ]
        assert len(reminders) == 1
        assert "current" in reminders[0]["content"]
```

- [ ] **Step 8: Run test**

Run: `pytest tests/core/test_input_parser.py::TestSystemReminderFilter -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add server/core/input_parser.py tests/core/test_input_parser.py
git commit -m "feat: add InputParser with tool dedup and reminder filtering"
```

---

### Task 2: Add Tier 3 repair

**Files:**
- Create: `server/repair/repair_tier3.py`
- Modify: `server/repair/__init__.py`

- [ ] **Step 1: Write failing test — Tier 3 reconstructs partial tool call**

```python
# tests/repair/test_repair_tier3.py
import pytest
from server.repair.repair_tier3 import repair_tier3


class TestTier3Repair:
    def test_reconstruct_partial_tool_call(self):
        # Model emitted <tool_call name="Read" but stream ended before closing
        fragment = '<tool_call name="Read"><parameter name="file_path">/tmp/test.txt</parameter>'
        tool_names = ["Read", "Write", "Bash"]
        result = repair_tier3(fragment, tool_names)
        assert result is not None
        assert "name=\"Read\"" in result
        assert "file_path" in result
        assert "</tool_call>" in result
```

Run: `pytest tests/repair/test_repair_tier3.py::TestTier3Repair -v`
Expected: FAIL

- [ ] **Step 2: Implement Tier 3 repair**

```python
# server/repair/repair_tier3.py
from __future__ import annotations

import re
from typing import Optional


_TOOL_CALL_OPEN_RE = re.compile(
    r'<tool_call\s+name\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_PARAM_OPEN_RE = re.compile(
    r'<parameter\s+name\s*=\s*["\']([^"\']+)["\']\s*>',
    re.IGNORECASE,
)

_TOOL_NAMES_PATTERN = re.compile(
    r'(?i)<(tool_call|tool_called|invoke)\b[^>]*>',
)


def _contains_any_tool_tag(text: str, tool_names: list[str]) -> bool:
    if _TOOL_NAMES_PATTERN.search(text):
        return True
    for name in tool_names:
        if f'name="{name}"' in text or f"name='{name}'" in text:
            return True
    return False


def repair_tier3(text: str, tool_names: Optional[list[str]] = None) -> Optional[str]:
    """Reconstruct broken tool calls from partial text fragments.

    Handles:
    - Truncated opening tag: <tool_call name="X"><parameter...
    - Missing closing tags
    - Abandoned parameter values
    """
    if not text or not text.strip():
        return None

    tool_names = tool_names or []

    if not _contains_any_tool_tag(text, tool_names):
        return None

    # Close unclosed tool_call
    tool_calls = list(_TOOL_CALL_OPEN_RE.finditer(text))
    if tool_calls:
        last_call = tool_calls[-1]
        name = last_call.group(1)
        before = text[:last_call.start()]
        after = text[last_call.start():]

        # Count opening vs closing tool_call
        opens = after.count("<tool_call")
        closes = after.count("</tool_call")
        missing = opens - closes

        result = before + after
        for _ in range(missing):
            result += f"</tool_call>"

        # Close unclosed parameters inside the last tool_call
        params = list(_PARAM_OPEN_RE.finditer(after))
        for p in params:
            p_open = after.count(f'<parameter name="{p.group(1)}"')
            p_close = after.count(f'</parameter>')
            if p_open > p_close:
                result += "</parameter>"

        if result != text:
            return result

    # Bare partial: <tool_call name="X"> without any param -> add empty
    m = re.match(r'<tool_call\s+name\s*=\s*["\']([^"\']+)["\']\s*>$', text.strip())
    if m:
        return f"{text.strip()}</tool_call>"

    return None
```

- [ ] **Step 3: Run test**

Run: `pytest tests/repair/test_repair_tier3.py -v`
Expected: PASS

- [ ] **Step 4: Update `repair/__init__.py` to include Tier 3**

```python
# server/repair/__init__.py
from __future__ import annotations

from typing import Callable, Optional

from server.repair.repair_tier1 import repair_tier1
from server.repair.repair_tier2 import repair_tier2
from server.repair.repair_tier3 import repair_tier3


def repair_pipeline(
    capture_buf: str,
    tool_names: Optional[list[str]] = None,
    tier3_callback: Optional[Callable[[str], str]] = None,
) -> str | None:
    if capture_buf is None:
        return None

    repaired = repair_tier1(capture_buf)
    if repaired is not None:
        return repaired

    repaired = repair_tier2(capture_buf, tool_names)
    if repaired is not None:
        return repaired

    # Tier 3: context-aware reconstruction
    # (tier3_callback fallback remains for legacy callers)
    repaired = repair_tier3(capture_buf, tool_names)
    if repaired is not None:
        return repaired

    if tier3_callback is not None:
        repaired = tier3_callback(capture_buf)
        if repaired and len(repaired.strip()) > 0:
            return repaired

    return None
```

- [ ] **Step 5: Run existing repair tests to verify no regression**

Run: `pytest tests/repair/ -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add server/repair/repair_tier3.py server/repair/__init__.py tests/repair/test_repair_tier3.py
git commit -m "feat: add Tier 3 tool call repair for truncated fragments"
```

---

### Task 3: Create StreamHandler + ToolMgr

**Files:**
- Create: `server/core/stream_handler.py`
- Test: `tests/core/test_stream_handler.py`

- [ ] **Step 1: Write failing test — StreamHandler wraps DS stream correctly**

```python
# tests/core/test_stream_handler.py
import pytest
from server.core.stream_handler import StreamHandler, ToolMgr


class TestStreamHandler:
    def test_detects_tool_calls(self):
        chunks = [
            'Hello',
            '<tool_call name="Read">',
            '<parameter name="file_path">/tmp/test.txt</parameter>',
            '</tool_call>',
            'Done',
        ]
        handler = StreamHandler(tool_names=["Read"])
        events = []
        for chunk in chunks:
            evts = handler.feed(chunk)
            events.extend(evts)
        evts = handler.flush()
        events.extend(evts)

        tool_events = [e for e in events if e.get("type") == "tool_calls"]
        assert len(tool_events) >= 1
        calls = tool_events[0]["data"]
        assert len(calls) >= 1
        assert calls[0]["name"] == "Read"
        assert "/tmp/test.txt" in calls[0].get("arguments", "")
```

Run: `pytest tests/core/test_stream_handler.py -v`
Expected: FAIL

- [ ] **Step 2: Implement StreamHandler + ToolMgr**

```python
# server/core/stream_handler.py
from __future__ import annotations

import json
import time
from typing import Any, Generator, Optional

from server.parser.dsml_sieve import StreamSieve
from server.parser.dsml_parser import parse_dsml_tool_calls, parse_json_tool_calls, clean_tool_text
from server.repair import repair_pipeline
from server.config import MAX_PARALLEL_TOOL_CALLS


class ToolMgr:
    """Manages tool call parsing with Tier 3 fallback."""

    @staticmethod
    def try_parse(text: str, tool_names: list[str]) -> list[dict]:
        """Try to parse tool calls with progressively more aggressive repair."""
        calls, _ = parse_dsml_tool_calls(text, tool_names)
        if calls:
            return calls

        calls, _ = parse_json_tool_calls(text)
        if calls:
            return calls

        repaired = repair_pipeline(text, tool_names)
        if repaired is not None:
            calls, _ = parse_dsml_tool_calls(repaired, tool_names)
            if calls:
                return calls

        return []

    @staticmethod
    def validate(calls: list[dict], tool_names: list[str]) -> list[dict]:
        if not tool_names or not calls:
            return calls
        valid_set = set(tool_names)
        return [tc for tc in calls if tc.get("name", "") in valid_set]


class StreamHandler:
    """Wraps StreamSieve + ToolMgr, yields dict events."""

    def __init__(self, tool_names: Optional[list[str]] = None):
        self._sieve = StreamSieve(tool_names=tool_names)
        self._tool_names = tool_names or []
        self._text_buffer = ""

    def feed(self, chunk: str) -> list[dict]:
        """Consume a text chunk and return list of event dicts.

        Event types: {"type": "text", "data": str} | {"type": "tool_calls", "data": [...]}
        """
        if not chunk:
            return []

        events = []
        for se in self._sieve.feed(chunk):
            if se.type == "text":
                cleaned = clean_tool_text(se.data)
                if cleaned:
                    self._text_buffer += cleaned
                    events.append({"type": "text", "data": cleaned})
            elif se.type == "tool_calls":
                validated = ToolMgr.validate(list(se.data), self._tool_names)
                if validated:
                    events.append({"type": "tool_calls", "data": validated})

        return events

    def flush(self) -> list[dict]:
        """Flush remaining buffer through sieve + ToolMgr repair."""
        events = []
        for se in self._sieve.flush():
            if se.type == "text":
                cleaned = clean_tool_text(se.data)
                if cleaned:
                    events.append({"type": "text", "data": cleaned})
            elif se.type == "tool_calls":
                validated = ToolMgr.validate(list(se.data), self._tool_names)
                if validated:
                    events.append({"type": "tool_calls", "data": validated})

        # Tier 3 repair on anything remaining in sieve
        if self._sieve._capture_buf:
            calls = ToolMgr.try_parse(self._sieve._capture_buf, self._tool_names)
            if calls:
                events.append({"type": "tool_calls", "data": calls})
            self._sieve._capture_buf = ""
            self._sieve._capturing = False

        return events
```

- [ ] **Step 3: Run test**

Run: `pytest tests/core/test_stream_handler.py -v`
Expected: PASS

- [ ] **Step 4: Write test — ToolMgr Tier 3 recovers broken tool call**

```python
# Same file

class TestToolMgr:
    def test_tier3_recovers_broken(self):
        # Fragment missing closing tags
        broken = '<tool_call name="Bash"><parameter name="command">ls</parameter>'
        calls = ToolMgr.try_parse(broken, ["Bash", "Read"])
        assert len(calls) >= 1
        assert calls[0]["name"] == "Bash"
```

- [ ] **Step 5: Run test**

Run: `pytest tests/core/test_stream_handler.py::TestToolMgr -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/core/stream_handler.py tests/core/test_stream_handler.py
git commit -m "feat: add StreamHandler + ToolMgr with Tier 3 repair"
```

---

### Task 4: Refactor PromptBuilder with dedup

**Files:**
- Modify: `server/services/prompt_service.py`
- Test: `tests/services/test_prompt_dedup.py`

- [ ] **Step 1: Write failing test — dedup when tools already in system prompt**

```python
# tests/services/test_prompt_dedup.py
import pytest
from server.services.prompt_service import build_prompt


class TestDedup:
    def test_skips_tools_when_already_in_system(self):
        messages = [
            {
                "role": "system",
                "content": "You are helpful.\n\n<tool_call name=\"Read\">\n  <file_path type=\"string\"/>\n</tool_call>",
            },
            {"role": "user", "content": "hello"},
        ]
        # tools are provided but should NOT be added because system prompt already has them
        prompt = build_prompt(messages, tools=[{"function": {"name": "Read"}}])
        # Only one <tool_call> reference (the one already in system)
        assert prompt.count("<tool_call") == 1
        # No "Available tools:" section appended
        assert "Available tools:" not in prompt
```

Run: `pytest tests/services/test_prompt_dedup.py -v`
Expected: FAIL (current build_prompt always appends)

- [ ] **Step 2: Implement dedup in `build_prompt`**

```python
# server/services/prompt_service.py — modified build_prompt function

import re

_TOOL_IN_SYSTEM_RE = re.compile(
    r"<\s*tool_call[^>]*>|Available Tools:|<tools>",
    re.IGNORECASE,
)

# Add this at the start of build_prompt(), before any prompt building:

def build_prompt(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    **_kwargs,
) -> str:
    from server.parser.dsml_parser import build_dsml_tool_prompt
    parts: list[str] = []

    # Dedup: check if system prompt already contains tool schemas
    tools_to_inject = tools
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and _TOOL_IN_SYSTEM_RE.search(content):
                tools_to_inject = None
                break
            elif isinstance(content, list):
                text = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                if _TOOL_IN_SYSTEM_RE.search(text):
                    tools_to_inject = None
                    break

    # Inject tool schemas only if not already present
    if tools_to_inject:
        tool_block = build_dsml_tool_prompt(tools_to_inject)
        if tool_block:
            parts.append(tool_block)

    # ... rest of the function unchanged (message formatting) ...
```

- [ ] **Step 3: Run test**

Run: `pytest tests/services/test_prompt_dedup.py -v`
Expected: PASS

- [ ] **Step 4: Write test — tools still injected when NOT in system prompt**

```python
# Same file

class TestInjection:
    def test_injects_tools_when_not_in_system(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hello"},
        ]
        prompt = build_prompt(messages, tools=[{"function": {"name": "Read"}}])
        assert "Available tools:" in prompt or "<tools>" in prompt
```

- [ ] **Step 5: Run test**

Run: `pytest tests/services/test_prompt_dedup.py::TestInjection -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/services/prompt_service.py tests/services/test_prompt_dedup.py
git commit -m "feat: add tool schema dedup to PromptBuilder"
```

---

### Task 5: Refactor ProxyService — orchestration only

**Files:**
- Modify: `server/core/proxy.py`
- Modify: `server/api/deps.py` (update ProxyService instantiation if needed)

- [ ] **Step 1: Strip `proxy.py` to orchestration core**

The refactored `proxy.py` should:
- Remove all inline message filtering logic → delegate to `InputParser`
- Remove inline tool call parsing → delegate to `StreamHandler` + `ToolMgr`
- Remove inline `_validate_*` helpers → delegate to `InputParser`
- Keep only: parse → build prompt → call DeepSeek → wrap stream → return

Key changes in `chat_completions()`:
```python
async def chat_completions(self, raw_request: Request) -> Any:
    t0 = time.time()

    # 1. Parse & validate
    body_bytes = await raw_request.body()
    body_str = body_bytes.decode("utf-8", "ignore")
    try:
        raw_json = json.loads(body_str)
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON body: {e}")

    # Get conversation state
    state = get_conv(raw_json.get("messages", [])) if raw_json.get("model") != "deepseek-vision" else None

    # 2. InputParser
    parsed = InputParser.parse(raw_json, state)
    req = ChatRequest(**raw_json)

    # 3. PromptBuilder (with dedup)
    prompt = build_prompt(parsed.messages, tools=parsed.tools)

    # 4. Account + session
    account_idx = self._pick_account(parsed, state)
    chat_id, parent_id = self._resolve_session(state, account_idx, parsed.is_resume)

    # 5. Call DeepSeek
    stream_gen, stream_meta = ds.stream_completion(
        account_idx, chat_id, prompt, parent_id,
        model_type=parsed.model_type,
        reasoning_effort=parsed.reasoning_effort,
        max_tokens=parsed.max_tokens,
        temperature=parsed.temperature,
        top_p=parsed.top_p,
    )

    # 6. StreamHandler wrapper
    tool_names = [t.get("function", t).get("name", "") for t in (parsed.tools or [])]
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = raw_json.get("model", "deepseek-chat")

    def _chunk(delta: dict, fr: str | None = None) -> str:
        c = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta}],
        }
        if fr:
            c["choices"][0]["finish_reason"] = fr
        if delta.get("content") or delta.get("tool_calls") or fr:
            return f"data: {json.dumps(c, ensure_ascii=False)}\n\n"
        return ""

    def _generate():
        handler = StreamHandler(tool_names=tool_names)
        yield_buffer = ""
        try:
            for text_chunk in stream_gen:
                for event in handler.feed(text_chunk):
                    if event["type"] == "text":
                        yield_buffer += event["data"]
                    elif event["type"] == "tool_calls":
                        if yield_buffer:
                            yield _chunk({"content": yield_buffer})
                            yield_buffer = ""
                        tc_list = _build_tc_list(event["data"], conv_uuid)
                        yield _chunk({"tool_calls": tc_list})
                        yield _chunk({}, fr="tool_calls")
                        yield "data: [DONE]\n\n"
                        return
            for event in handler.flush():
                if event["type"] == "text":
                    yield_buffer += event["data"]
                elif event["type"] == "tool_calls":
                    if yield_buffer:
                        yield _chunk({"content": yield_buffer})
                        yield_buffer = ""
                    tc_list = _build_tc_list(event["data"], conv_uuid)
                    yield _chunk({"tool_calls": tc_list})
                    yield _chunk({}, fr="tool_calls")
                    yield "data: [DONE]\n\n"
                    return
            if yield_buffer:
                yield _chunk({"content": yield_buffer})
            yield _chunk({}, fr="stop")
            yield "data: [DONE]\n\n"
        finally:
            _release_session_slot(account_idx)

    return StreamingResponse(_generate(), media_type="text/event-stream")
```

- [ ] **Step 2: Implement `_pick_account` helper**

```python
# In proxy.py, add to ProxyService class:

def _pick_account(self, parsed: ParsedRequest, state: dict | None) -> int:
    import hashlib as _hl
    if state and "account" in state:
        account_idx = state["account"]
        now = time.time()
        if now < rate_limited_until.get(account_idx, 0):
            alts = [i for i in range(MAX_ACCOUNTS)
                    if i != account_idx and ap.is_valid(i) and now >= rate_limited_until.get(i, 0)]
            if alts:
                return alts[0]
        return account_idx
    _key = json.dumps(parsed.messages[-1], sort_keys=True, ensure_ascii=False) if parsed.messages else ""
    return int(_hl.md5(_key.encode()).hexdigest(), 16) % MAX_ACCOUNTS
```

- [ ] **Step 3: Implement `_resolve_session` helper**

```python
# In proxy.py:

def _resolve_session(self, state: dict | None, account_idx: int, is_resume: bool) -> tuple[str, str | None]:
    if is_resume and state:
        return state["chat_id"], state["parent_id"]
    if not _acquire_session_slot(account_idx):
        raise HTTPException(503, f"Account {account_idx} session pool full")
    chat_id = ds.create_session(account_idx)
    return chat_id, None
```

- [ ] **Step 4: Implement `_recover()` centralized error recovery**

```python
# In proxy.py:

def _recover(self, exc: Exception, context: dict) -> tuple:
    """Centralized error recovery. Returns (stream_gen, stream_meta) or raises."""
    err_str = str(exc)
    account_idx = context["account_idx"]
    chat_id = context["chat_id"]
    prompt = context["prompt"]
    model_type = context.get("model_type", "default")

    # Rate limit
    if any(t in err_str for t in ("busy after", "rate_limit", "too frequent")):
        _jitter = 60 + random.randint(-10, 15)
        rate_limited_until[account_idx] = time.time() + _jitter
        alts = [i for i in range(MAX_ACCOUNTS)
                if i != account_idx and ap.is_valid(i) and time.time() >= rate_limited_until.get(i, 0)]
        if alts:
            new_acct = alts[0]
            new_chat_id = ds.create_session(new_acct)
            return ds.stream_completion(new_acct, new_chat_id, prompt, None, model_type=model_type)

    # Length limit
    if any(t in err_str.lower() for t in ("length limit", "start a new chat", "context_length")):
        new_chat_id = ds.create_session(account_idx)
        return ds.stream_completion(account_idx, new_chat_id, prompt, None, model_type=model_type)

    # Session expired (empty resume)
    if "no_data" in err_str or "EMPTY" in err_str:
        # Clear conv_state entry, create fresh session
        new_chat_id = ds.create_session(account_idx)
        return ds.stream_completion(account_idx, new_chat_id, prompt, None, model_type=model_type)

    raise  # Re-raise if nothing handled
```

- [ ] **Step 5: Verify existing tests pass**

Run: `pytest tests/ -v`
Expected: all existing tests pass

- [ ] **Step 6: Commit**

```bash
git add server/core/proxy.py server/api/deps.py
git commit -m "refactor: ProxyService orchestration-only, centralized recovery"
```

---

### Task 6: Archive legacy server.py

**Files:**
- Move: `deepseek-proxy/server.py` → `_archive/debug-scripts/legacy_server.py`

- [ ] **Step 1: Move the file**

```bash
mkdir -p _archive/debug-scripts
git mv deepseek-proxy/server.py _archive/debug-scripts/legacy_server.py
```

- [ ] **Step 2: Update any remaining references to `server.py`** (check import paths)

Grep for `import server` or `from server import` in all `.py` files outside `deepseek-proxy/server/`.

- [ ] **Step 3: Commit**

```bash
git add _archive/debug-scripts/legacy_server.py
git commit -m "chore: archive legacy monolith server.py"
```

---

### Task 7: Integration test — full cycle

**Files:**
- Create: `tests/integration/test_proxy_cycle.py`

- [ ] **Step 1: Write integration test with mocked DeepSeek client**

```python
# tests/integration/test_proxy_cycle.py
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from server.core.proxy import ProxyService


class TestFullCycle:
    @patch("server.core.deepseek_client.ds.create_session")
    @patch("server.core.deepseek_client.ds.stream_completion")
    async def test_basic_chat_text_response(self, mock_stream, mock_create):
        mock_create.return_value = "chat_123"
        mock_stream.return_value = (
            iter(["Hello", " world"]),
            {"resp_msg_id": 42},
        )

        # Build a mock FastAPI Request
        from fastapi import Request
        from starlette.datastructures import Headers

        body = json.dumps({
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Say hello"},
            ],
            "stream": True,
        })

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [(b"content-type", b"application/json")],
        }
        req = Request(scope, receive=AsyncMock())
        req._body = body.encode()

        proxy = ProxyService()
        resp = await proxy.chat_completions(req)
        assert resp is not None

        # Consume the streaming response
        content = b""
        async for chunk in resp.body_iterator:
            content += chunk if isinstance(chunk, bytes) else chunk.encode()

        assert b"Hello world" in content or b"Hello" in content
```

- [ ] **Step 2: Implement test with fake raw_request**

- [ ] **Step 3: Run integration test**

Run: `pytest tests/integration/ -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_proxy_cycle.py
git commit -m "test: add integration test for full proxy cycle"
```

---

### Task 8: Test pinning — verify no regression on legacy server.py behavior

**Files:** (run only, no changes)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: all tests pass

- [ ] **Step 2: Run server startup smoke test**

Run: `python -c "from server import app; print('OK')"`
Expected: `OK` (server imports without error)

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git commit -m "fix: post-refactor cleanup"
```
