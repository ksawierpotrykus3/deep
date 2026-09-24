# Cascade Compression Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 4-level cascade (K0→K1:strip_tools→K2a/b/c:truncate→K3+:trim10%) with a simpler 3-level cascade (K0:full→K1:truncate@4K→K2+:trim30%) that protects `.md` content from truncation.

**Architecture:** Single-file change in `server.py`. Modify three cascade functions and the cascade flow inside `generate()`. Remove `_cascade_strip_tool_calls()`. Add new `_is_md_content()` helper.

**Tech Stack:** Python 3, server.py (single file)

---

### Task 1: Add `_is_md_content()` helper function

**Files:**
- Modify: `f:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py`

- [ ] **Step 1: Add `_is_md_content` function**

Insert this function near the existing cascade functions (around line 750, just before `_cascade_strip_tool_calls`):

```python
def _is_md_content(content: str) -> bool:
    """Check if message content references .md files (to protect from truncation)."""
    if not isinstance(content, str):
        return False
    return bool(re.search(r'[\w\-]+\.md', content))
```

- [ ] **Step 2: Verify the function works**

Create a quick test script or run in Python:

```python
# Test cases
assert _is_md_content("The file spec.md was written")
assert _is_md_content("f:\\path\\to\\design.md")
assert not _is_md_content("def foo():\n    pass")
assert not _is_md_content("")
assert not _is_md_content(123)
print("All assertions pass")
```

---

### Task 2: Modify `_cascade_truncate_content()` to skip .md content

**Files:**
- Modify: `f:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` (around line 776)

- [ ] **Step 1: Replace `_cascade_truncate_content`**

Replace the existing implementation with this version that checks `_is_md_content`:

```python
def _cascade_truncate_content(messages: list[dict], max_chars: int = 4000) -> list[dict]:
    """K1: Truncate each message's content to max_chars, but skip .md content."""
    result = []
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str) and len(content) > max_chars and not _is_md_content(content):
            m2 = dict(m)
            m2["content"] = content[:max_chars] + f"… [truncated, {len(content)} chars total]"
            result.append(m2)
        else:
            result.append(m)
    return result
```

- [ ] **Step 2: Verify**

Check the function handles these cases:
- Message with content >4000 chars containing `.md` → NOT truncated
- Message with content >4000 chars without `.md` → truncated to 4000 + truncated marker
- Message with content <4000 chars → left as-is

---

### Task 3: Modify `_cascade_trim_history()` ratio to 0.30

**Files:**
- Modify: `f:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` (around line 790)

- [ ] **Step 1: Change the default ratio parameter**

Change `ratio: float = 0.10` to `ratio: float = 0.30`:

```python
def _cascade_trim_history(messages: list[dict], protect_first: int = 10, ratio: float = 0.30) -> list[dict]:
    """K2+: Remove ratio fraction of oldest non-protected messages (30% by default)."""
    if len(messages) <= protect_first + 1:
        return messages
    protected = messages[:protect_first + 1]
    trimable = messages[protect_first + 1:]
    n_remove = max(1, int(len(trimable) * ratio))
    return protected + trimable[n_remove:]
```

- [ ] **Step 2: Update all callers of `_cascade_trim_history`**

Search for `_cascade_trim_history(` in server.py and ensure no callers pass `ratio=0.10`. The only caller is in the cascade block inside `generate()` (line 2354). Update if needed:

```python
# OLD:
working_msgs = _cascade_trim_history(working_msgs, protect_first=10, ratio=0.10)
# NEW:
working_msgs = _cascade_trim_history(working_msgs, protect_first=10, ratio=0.30)
```

Note: since the default is now 0.30, passing `ratio=0.30` explicitly is optional but recommended for clarity.

---

### Task 4: Update cascade flow in `generate()`

**Files:**
- Modify: `f:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` (around lines 2314-2360)

- [ ] **Step 1: Replace the K1/K2/K3+ block with new K1/K2+ block**

Locate the cascade block starting at line 2314. Remove the old K1→K2a→K2b→K2c→K3+ cascade and replace with the simplified version:

```python
        # K1 — truncate long messages (protect .md content)
        if not succeeded:
            try:
                k1_msgs = _cascade_truncate_content(base_msgs, 4000)
                stream_gen, stream_meta = _try_send(k1_msgs, "K1:truncate@4K")
                if not stream_meta.get("no_data"):
                    succeeded = True
            except Exception as e:
                if _is_rate_err(e) and _handle_rate(e):
                    pass
                elif not _is_len_err(e):
                    raise HTTPException(status_code=502, detail=f"K1 failed: {e}")

        # K2+ — iteratively trim 30% of oldest messages until it fits (max 20 iterations)
        if not succeeded:
            working_msgs = _cascade_truncate_content(base_msgs, 4000)
            for iteration in range(20):
                working_msgs = _cascade_trim_history(working_msgs, protect_first=10, ratio=0.30)
                try:
                    stream_gen, stream_meta = _try_send(working_msgs, f"K2+iter{iteration}:trim30pct")
                    if not stream_meta.get("no_data"):
                        succeeded = True
                        break
                except Exception as e:
                    if _is_rate_err(e) and _handle_rate(e):
                        continue
                    elif not _is_len_err(e):
                        raise HTTPException(status_code=502, detail=f"K2+iter{iteration} failed: {e}")
                    # still too long — next iteration removes another 30%
```

- [ ] **Step 2: Verify the old K1/K2/K3+ code is replaced**

Ensure these old blocks are gone:
- `k1_msgs = _cascade_strip_tool_calls(base_msgs)` — removed
- `for max_chars, label in [(4000, "K2a"), (2000, "K2b"), (800, "K2c")]:` — removed
- `working_msgs = _cascade_strip_tool_calls(base_msgs)` — removed
- `working_msgs = _cascade_truncate_content(working_msgs, 800)` — removed (redundant, truncation already done at K1)

---

### Task 5: Remove `_cascade_strip_tool_calls()` function

**Files:**
- Modify: `f:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` (around line 753)

- [ ] **Step 1: Delete `_cascade_strip_tool_calls` function**

Remove the entire function definition (lines 753-773):

```python
# DELETE this entire block:
def _cascade_strip_tool_calls(messages: list[dict]) -> list[dict]:
    """K1: Remove role=tool messages and replace assistant tool_call messages with plain text stubs."""
    ...
```

- [ ] **Step 2: Verify no remaining references**

Run `grep -n "_cascade_strip_tool_calls" server.py` and confirm there are 0 matches.

---

### Task 6: Test and verify

- [ ] **Step 1: Restart the server**

```bash
# Find and stop existing server
Get-Process python | Where-Object { $_.CommandLine -like "*server.py*" } | Stop-Process -Force
# Start new server
cd f:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\
python server.py
```

Check the console output for any startup errors (import errors, syntax errors).

- [ ] **Step 2: Verify cascade logic with a test request**

Send a small test request to ensure the server responds:

```bash
curl -s http://localhost:4570/v1/models
```

Expected: `{"object":"list","data":[{"id":"deepseek-v4-pro",...}]}`

- [ ] **Step 3: Monitor logs for cascade behavior**

Watch the server output for cascade messages:
- `[CASCADE K0:full]` — should appear for any new-session request
- `[CASCADE K1:truncate@4K]` — if K0 fails due to length
- `[CASCADE K2+iterN:trim30pct]` — if K1 also fails

---

### Task 7: Commit

- [ ] **Step 1: Commit the changes**

```bash
git add deepseek-proxy/server.py docs/superpowers/specs/2026-07-12-cascade-compression-design.md docs/superpowers/plans/2026-07-12-cascade-compression-plan.md
git commit -m "refactor(proxy): simplify cascade compression, protect .md content

Replace the 4-level cascade (K0→K1:strip_tools→K2a/b/c:truncate→K3+:trim10%)
with a simpler 3-level cascade:
- K0:full — unchanged
- K1:truncate@4K — truncates messages >4K chars, but skips .md content
- K2+:trim30% — removes 30% of oldest messages iteratively

Remove _cascade_strip_tool_calls(). Add _is_md_content() helper.
Also fix retry path to force new session with full history instead of
sending only the last message."
```
