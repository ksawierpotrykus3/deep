# Natural Agentic Proxy Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate DSML/XML from system prompts, deduplicate tool schema injection, expand tool call detection coverage, and fix resume behavior.

**Architecture:** PromptBuilder becomes sole tool injection point (plain text `Available tools: Read, Write, ...`); dsml_parser loses `build_dsml_tool_prompt()`; ToolMgr gets Tier 4 fallback via tool_parser; resume passes `tools_schema=None`/`system_prompt=None`.

**Tech Stack:** Python 3.11+, no new dependencies

---

### Task 1: InputParser — extend tool-in-system regex

**Files:**
- Modify: `server/core/input_parser.py:25-28`

- [ ] **Step 1: Expand `_TOOL_IN_SYSTEM_RE`** to also match `"functions"`, `"tools"`, `"function"` in system messages. Edit the regex.

```python
_TOOL_IN_SYSTEM_RE = re.compile(
    r"<\s*tool_call[^>]*>|Available Tools:|<tools>|"
    r"\"functions\"|\"tools\"|\"function\"",
    re.IGNORECASE,
)
```

- [ ] **Step 2: Run existing tests**

Run: `python -m pytest tests/test_prompt_builder.py tests/test_proxy_service_basic.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add server/core/input_parser.py
git commit -m "feat(input_parser): extend tool-in-system regex with functions/tools/function"
```

---

### Task 2: PromptBuilder — remove DSML injection, add `_format_tool_names`

**Files:**
- Modify: `server/core/prompt_builder.py` (entire file)

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_prompt_builder.py

class TestToolsNotInSystemPrompt:
    def test_returns_true_when_missing(self):
        assert PromptBuilder._tools_not_in_system_prompt("You are helpful.")

    def test_returns_false_when_tool_call_present(self):
        assert not PromptBuilder._tools_not_in_system_prompt(
            "You are helpful. Use <tool_call>"
        )

    def test_returns_false_when_available_tools_present(self):
        assert not PromptBuilder._tools_not_in_system_prompt(
            "Available tools:\n- Read\n- Write"
        )


class TestBuildWithToolNames:
    def test_no_dsml_in_tool_block(self):
        tools = [{"name": "Read", "description": "Read files"},
                 {"name": "Write", "description": "Write files"}]
        result = PromptBuilder.build(
            "Do something",
            system_prompt="You are helpful.",
            tools_schema=tools,
        )
        assert "[Available Tool]:" in result
        assert "<tool_call" not in result
        assert "DSML" not in result
        assert "CDATA" not in result

    def test_does_not_inject_when_tools_in_system(self):
        tools = [{"name": "Read", "description": "Read files"}]
        result = PromptBuilder.build(
            "Hi",
            system_prompt="You have access to the following tools.",
            tools_schema=tools,
        )
        assert "[Available Tool]:" not in result

    def test_resume_prompt_no_tools_no_system(self):
        result = PromptBuilder.build(
            "Continue",
            system_prompt=None,
            tools_schema=None,
        )
        assert "[System]:" not in result  # no system section at all
        assert "[User]:\nContinue" in result
        assert "[Assistant]:" in result
```

- [ ] **Step 2: Run tests to see them fail**

Run: `python -m pytest tests/test_prompt_builder.py -v`
Expected: New test failures, existing `test_tool_injection_when_needed` may also change

- [ ] **Step 3: Rewrite PromptBuilder**

Replace entire `prompt_builder.py` with:

```python
from __future__ import annotations

import re
from typing import Optional


_DSML_TOOL_PATTERNS = [
    re.compile(r'<tool_call', re.IGNORECASE),
    re.compile(r'Available Tools?:', re.IGNORECASE),
    re.compile(r'<tools>', re.IGNORECASE),
    re.compile(r'You have access to the following tools?', re.IGNORECASE),
    re.compile(r'You can use the following tool', re.IGNORECASE),
]


class PromptBuilder:
    PROMPT_PREFIX = "[System]:"
    USER_PREFIX = "[User]:"
    ASSISTANT_PREFIX = "[Assistant]:"

    @staticmethod
    def _tools_not_in_system_prompt(system_prompt: str) -> bool:
        if not system_prompt:
            return True
        for pat in _DSML_TOOL_PATTERNS:
            if pat.search(system_prompt):
                return False
        return True

    @staticmethod
    def build(
        user_message: str,
        *,
        system_prompt: Optional[str] = None,
        history: Optional[list[dict]] = None,
        tools_schema: Optional[list[dict]] = None,
    ) -> str:
        parts = []

        if system_prompt:
            parts.append(f"{PromptBuilder.PROMPT_PREFIX}\n{system_prompt}")

        if tools_schema and PromptBuilder._tools_not_in_system_prompt(system_prompt or ""):
            tool_block = PromptBuilder._format_tool_names(tools_schema)
            parts.append(tool_block)

        if history:
            for msg in history:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    parts.append(f"{PromptBuilder.USER_PREFIX}\n{content}")
                elif role == "assistant":
                    parts.append(f"{PromptBuilder.ASSISTANT_PREFIX}\n{content}")

        parts.append(f"{PromptBuilder.USER_PREFIX}\n{user_message}")
        parts.append(f"{PromptBuilder.ASSISTANT_PREFIX}\n")

        return "\n\n".join(parts)

    @staticmethod
    def _format_tool_names(tools_schema: list[dict]) -> str:
        names = []
        for tool in tools_schema:
            name = tool.get("name", tool.get("function", {}).get("name", ""))
            if name:
                names.append(name)
        if not names:
            return ""
        return "[Available Tool]: " + ", ".join(names)
```

- [ ] **Step 4: Update old `test_tool_injection_when_needed` expectation**

The old test expects `[Available Tool]: Read` + `"When you need to use a tool"` text. Now it should only expect `[Available Tool]: Read` (comma-separated, no instruction text).

Update test:

```python
    def test_tool_injection_when_needed(self):
        tools = [{"name": "Read", "description": "Read files"}]
        result = PromptBuilder.build(
            "List files",
            system_prompt="You are an assistant.",
            tools_schema=tools,
        )
        assert "[Available Tool]: Read" in result
        assert "When you need to use a tool" not in result
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_prompt_builder.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/core/prompt_builder.py tests/test_prompt_builder.py
git commit -m "feat(prompt_builder): remove DSML injection, add _format_tool_names, fix resume path"
```

---

### Task 3: dsml_parser — remove `build_dsml_tool_prompt()`

**Files:**
- Modify: `server/parser/dsml_parser.py:541-593`

- [ ] **Step 1: Remove the `build_dsml_tool_prompt` function**

Delete lines 541-593 (entire function body). Keep `clean_tool_text()` which ends at line 538.

- [ ] **Step 2: Run existing dsml parser tests**

Run: `python -m pytest tests/test_dsml_parser.py -v`
Expected: The `test_build_dsml_tool_prompt` test should FAIL (function removed). All other tests PASS.

- [ ] **Step 3: Remove the `test_build_dsml_tool_prompt` test**

In `tests/test_dsml_parser.py`, remove the `test_build_dsml_tool_prompt` function (lines around 77-100) and remove `build_dsml_tool_prompt` from the import on line 9.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_dsml_parser.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/parser/dsml_parser.py tests/test_dsml_parser.py
git commit -m "refactor(dsml_parser): remove build_dsml_tool_prompt()"
```

---

### Task 4: prompt_service — remove `build_dsml_tool_prompt` call

**Files:**
- Modify: `server/services/prompt_service.py:35,39-42`

- [ ] **Step 1: Remove DSML tool prompt injection from `build_prompt()`**

Delete line 35 (`from server.parser.dsml_parser import build_dsml_tool_prompt`).
Replace lines 38-42 with a simpler approach — just list available tool names.

```python
    if tools:
        names = [t.get("function", t).get("name", "") for t in tools if t.get("function", t).get("name")]
        if names:
            parts.append(f"[Available Tool]: {', '.join(names)}")
```

- [ ] **Step 2: Run existing prompt_service tests**

Run: `python -m pytest tests/test_prompt_service.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add server/services/prompt_service.py
git commit -m "refactor(prompt_service): remove DSML tool prompt injection"
```

---

### Task 5: proxy_service — fix resume to strip tools/system

**Files:**
- Modify: `server/services/proxy_service.py:516-524` (resume path for PromptBuilder.build call)

- [ ] **Step 1: Write failing resume test**

In `tests/test_proxy_service_basic.py`, add:

```python
class TestResumePromptBuild:
    def test_resume_passes_no_tools_no_system(self):
        """On resume, PromptBuilder.build should get tools_schema=None and system_prompt=None."""
        msgs = [
            {"role": "user", "content": "List files"},
            {"role": "assistant", "content": "Here are the files", "tool_calls": []},
            {"role": "user", "content": "Now read one"},
        ]
        sp, hist, um = _extract_prompt_parts(msgs)
        # Simulate resume: system_prompt already in DeepSeek session, tools already defined
        prompt = PromptBuilder.build(
            user_message=um,
            system_prompt=None,  # resume: no re-injection
            history=hist if hist else None,
            tools_schema=None,  # resume: no re-injection
        )
        assert "[System]:" not in prompt
        assert "tool_call" not in prompt
```

Wait — `_extract_prompt_parts` is a module-level function in `proxy_service.py`, not exported. Let me adjust the test to test through ProxyService instead.

Actually, looking more carefully at the code, the `_extract_prompt_parts` function is used in the `chat_completions` method. The key fix is in the resume path at line 519-524. Currently:

```python
prompt = PromptBuilder.build(
    user_message=user_message or "",
    system_prompt=system_prompt,
    history=history if history else None,
    tools_schema=tools if tools else None,
)
```

On resume, `tools` still has the full tool schemas from the original request. We need to pass `tools_schema=None` on resume. Similarly, `system_prompt` is the system message content — on resume, DeepSeek already has it in the session, so we should pass `None`.

The fix: change the resume block (around lines 482-496) to clear tools/system before building the prompt.

Let me look at the code flow more carefully:

Lines 482-496: If `is_resume`, build `msgs_to_send` from delta messages.
Lines 517-524: `system_prompt, history, user_message = _extract_prompt_parts(msgs_to_send)` then `PromptBuilder.build(...)` with `tools_schema=tools`.

The fix: in the resume path, set `tools = []` (or pass `tools_schema=None`) and don't include system in the prompt.

Actually, looking at it more carefully, the simplest fix is: if `parsed.is_resume` is True, pass `tools_schema=None` and `system_prompt=None` explicitly.

But we need to keep the system_prompt extraction for the non-resume case. The change should be:

At line 517-524, add condition for resume:

```python
if parsed.is_resume:
    prompt = PromptBuilder.build(
        user_message=user_message or "",
        system_prompt=None,
        history=history if history else None,
        tools_schema=None,
    )
else:
    prompt = PromptBuilder.build(
        user_message=user_message or "",
        system_prompt=system_prompt,
        history=history if history else None,
        tools_schema=tools if tools else None,
    )
```

This is cleaner because:
1. `system_prompt=None` → no `[System]:` section in the prompt → DeepSeek uses its session memory
2. `tools_schema=None` → no tool list re-injection → avoids duplicate/filter-triggering content

- [ ] **Step 2: Apply the fix in proxy_service.py**

Replace lines 517-524:

```python
        if parsed.is_resume:
            prompt = PromptBuilder.build(
                user_message=user_message or "",
                system_prompt=None,
                history=history if history else None,
                tools_schema=None,
            )
        else:
            prompt = PromptBuilder.build(
                user_message=user_message or "",
                system_prompt=system_prompt,
                history=history if history else None,
                tools_schema=tools if tools else None,
            )
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_prompt_builder.py tests/test_proxy_service_basic.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add server/services/proxy_service.py
git commit -m "fix(proxy_service): resume passes tools_schema=None, system_prompt=None"
```

---

### Task 6: dsml_sieve — expand TOOL_STARTS

**Files:**
- Modify: `server/parser/dsml_sieve.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dsml_sieve.py`:

```python
class TestExpandedToolStarts:
    def test_detects_tool_use_json(self):
        sieve = StreamSieve()
        events = sieve.feed('<tool_use_json>{"tool_name":"Read","arguments":{"file_path":"/tmp/x"}}</tool_use_json>')
        tc = [e for e in events if e.type == "tool_calls"]
        assert len(tc) >= 1

    def test_detects_function_call(self):
        sieve = StreamSieve()
        events = sieve.feed('<function_call>{"name":"Read","arguments":{"file_path":"/tmp/x"}}</function_call>')
        tc = [e for e in events if e.type == "tool_calls"]
        assert len(tc) >= 1

    def test_detects_function_calls(self):
        sieve = StreamSieve()
        events = sieve.feed('<function_calls>[{"name":"Read","arguments":{"file_path":"/tmp/x"}}]</function_calls>')
        tc = [e for e in events if e.type == "tool_calls"]
        assert len(tc) >= 1

    def test_detects_argument_tag(self):
        sieve = StreamSieve()
        events = sieve.feed('<Read><file_path>/tmp/x</file_path></Read>')
        tc = [e for e in events if e.type == "tool_calls"]
        assert len(tc) >= 1

    def test_thinking_tag_not_mistaken_as_tool(self):
        sieve = StreamSieve()
        events = sieve.feed('<thinking>Let me think about this...</thinking>')
        tc = [e for e in events if e.type == "tool_calls"]
        assert len(tc) == 0
        text = [e for e in events if e.type == "text"]
        assert len(text) > 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_dsml_sieve.py -v -k "TestExpandedToolStarts"`
Expected: Some failures because TOOL_STARTS may not yet match these patterns

- [ ] **Step 3: Expand `TOOL_STARTS` list**

Add to `TOOL_STARTS` (before `CLOSE_TAGS`):

```python
    "<tool_use_json>",
    "<tool_use_json ",
    "<function_call>",
    "<function_call ",
    "<function_calls>",
    "<function_calls ",
    "<argument ",                 # parameter tags like <file_path>
    "<|begin▁of▁sentence｜>",     # BOS token leak
    "<|Assistant｜>",             # role leak
    "<|assistant｜>",
    "<thinking>",                 # deepseek thinking tag (but only if followed by tool content)
]
```

Also add corresponding close tags to `CLOSE_TAGS`:

```python
    "</tool_use_json>",
    "</function_call>",
    "</function_calls>",
```

Also update `_find_tool_start` generic prefix list and `_split_safe` prefix list to include new prefixes.

Add to the generic prefix tuples in `_find_tool_start` and `_split_safe`:
```python
"<tool_use_json", "<function_call", "<function_calls", "<argument", "<|begin▁of▁sentence", "<|Assistant", "<|assistant"
```

- [ ] **Step 4: Add content-based filtering to avoid thinking false positives**

In `_is_capture_complete`, after the `<thinking>` detection, verify that the buffer actually contains tool call content, not just thinking text. Add a check:

```python
    if "<thinking" in buf:
        # Only treat as tool capture if it contains actual tool markup
        if not any(x in buf for x in ("<tool_use_json", "<function_call", "<function_calls",
                                       "<invoke ", "<tool_call", "<toolcall")):
            return False
        return "</thinking>" in buf
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest tests/test_dsml_sieve.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/parser/dsml_sieve.py tests/test_dsml_sieve.py
git commit -m "feat(dsml_sieve): expand TOOL_STARTS with function_call, tool_use_json, argument tags, thinking"
```

---

### Task 7: stream_handler + tool_parser — ToolMgr Tier 4 fallback

**Files:**
- Modify: `server/parser/tool_parser.py` (add `legacy_fallback` public function)
- Modify: `server/core/stream_handler.py` (add Tier 4 to `ToolMgr.try_parse`)

- [ ] **Step 1: Write failing tests**

In `tests/test_stream_handler.py`, add to `TestToolMgr`:

```python
    def test_tier4_legacy_fallback_catches_function_call(self):
        text = '<function_call>{"name":"Read","arguments":{"file_path":"/tmp/x"}}</function_call>'
        calls = ToolMgr.try_parse(text, ["Read"])
        assert len(calls) >= 1
        assert calls[0]["name"] == "Read"

    def test_tier4_legacy_fallback_catches_tool_use_json(self):
        text = '<tool_use_json>{"tool_name":"Read","arguments":{"file_path":"/tmp/x"}}</tool_use_json>'
        calls = ToolMgr.try_parse(text, ["Read"])
        assert len(calls) >= 1
        assert calls[0]["name"] == "Read"

    def test_tier4_legacy_fallback_catches_bare_xml_tool(self):
        text = '<Read><file_path>/tmp/x</file_path></Read>'
        calls = ToolMgr.try_parse(text, ["Read"])
        assert len(calls) >= 1
        assert calls[0]["name"] == "Read"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_stream_handler.py -v -k "tier4"`
Expected: FAIL — ToolMgr returns []

- [ ] **Step 3: Add `legacy_fallback` to `tool_parser.py`**

At the end of `tool_parser.py` (after the existing code, before any EOF), add:

```python
# Public API for Tier 4 fallback — parses legacy/native formats
# that dsml_sieve + repair_tier3 may miss.


def legacy_fallback(text: str, tool_names: list[str] | None = None) -> list[dict]:
    """Parse tool calls using legacy formats (function_call, tool_use_json, raw XML, etc.).

    Returns list of dicts with "name" and "arguments" keys, or [] if none found.
    """
    tools = None
    if tool_names:
        tools = [{"function": {"name": n}} for n in tool_names]
    found = _parse_tool_calls(text, tools)
    if not found:
        return []
    # Convert to standard format
    results = []
    seen = set()
    for _, _, name, args_json in found:
        key = f"{name}:{args_json}"
        if key not in seen:
            seen.add(key)
            results.append({"name": name, "arguments": args_json})
    return results
```

- [ ] **Step 4: Add Tier 4 fallback to `ToolMgr.try_parse`**

In `stream_handler.py`, after the existing Tier 3 code and before `return []`, add:

```python
        # Tier 4: legacy format fallback (function_call, tool_use_json, raw XML)
        from server.parser.tool_parser import legacy_fallback
        calls = legacy_fallback(text, tool_names)
        if calls:
            return calls
```

Add the import at the top of the file too (or keep it inline). Let's keep it inline to avoid import cycles.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_stream_handler.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/parser/tool_parser.py server/core/stream_handler.py tests/test_stream_handler.py
git commit -m "feat(stream_handler): add Tier 4 legacy fallback via tool_parser.legacy_fallback"
```

---

### Task 8: Run all tests — final verification

**Files:** (none — run tests)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short 2>&1`
Expected: All tests PASS. If any fail, fix and re-run.

- [ ] **Step 2: Commit any remaining fixes**

```bash
git add -A
git commit -m "fix: final adjustments after full test suite verification"
```
