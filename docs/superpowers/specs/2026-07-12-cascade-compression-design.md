# Cascade Compression Redesign

Date: 2026-07-12

## Problem

When DeepSeek rejects a prompt as too long (context window limit), the proxy falls through a cascade of compression levels (K0 → K1 → K2 → K3+). The current cascade has several problems:

1. **K1 strips all tool calls** — removes `role=tool` messages and replaces assistant tool_call turns with `[tool call omitted]` stubs. This loses visibility into what tools were called and what results came back.
2. **K2 truncates all messages equally** — a 5000-char `.md` spec document gets truncated the same as a 5000-char code block, breaking the document and making it unparseable.
3. **K3+ trims only 10% per iteration** — takes up to 20 iterations to find an acceptable size, wasting time.
4. **Too many levels** — K2a (4000), K2b (2000), K2c (800) are three separate API calls before trimming even starts.

The result: after cascade compression, the model frequently loses context and responds as if starting a new conversation.

## Design

### Cascade Levels (New)

Replace the 4-level cascade (K0 → K1 → K2a/b/c → K3+) with a simpler 3-level cascade:

| Level | Action | Details |
|-------|--------|---------|
| **K0:full** | Send full history | Same as today. No compression. |
| **K1:truncate@4K** | Truncate long messages | Each message >4000 chars is cut to 4000. **Messages containing `.md` file references are skipped.** |
| **K2+:trim30%** | Remove oldest messages | Iteratively remove ~30% of oldest non-protected messages until DeepSeek accepts. |

### Functions

#### `_is_md_content(content: str) -> bool`

Detects if a message's content references `.md` files, protecting it from truncation.

```python
def _is_md_content(content: str) -> bool:
    if not isinstance(content, str):
        return False
    return bool(re.search(r'[\w\-]+\.md', content))
```

Rationale: when the model calls `Write` or `Read` on a `.md` file, the tool result includes the file path (e.g. `f:\path\to\spec.md`). This regex catches such references.

#### `_cascade_truncate_content(messages, max_chars=4000)` (modified)

Truncates each message's content to `max_chars` characters, **skipping messages that contain `.md` references**.

```python
def _cascade_truncate_content(messages, max_chars=4000):
    result = []
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, str) and len(content) > max_chars and not _is_md_content(content):
            m2 = dict(m)
            m2["content"] = content[:max_chars] + f"... [truncated, {len(content)} chars total]"
            result.append(m2)
        else:
            result.append(m)
    return result
```

#### `_cascade_trim_history(messages, protect_first=10, ratio=0.30)` (modified)

Removes `ratio` fraction of oldest messages beyond the protected first N.

```python
def _cascade_trim_history(messages, protect_first=10, ratio=0.30):
    if len(messages) <= protect_first + 1:
        return messages
    protected = messages[:protect_first + 1]
    trimable = messages[protect_first + 1:]
    n_remove = max(1, int(len(trimable) * ratio))
    return protected + trimable[n_remove:]
```

### Cascade flow in `generate()`

```python
# K0 — full history, no compression
try:
    stream_gen, stream_meta = _try_send(base_msgs, "K0:full")
    _k0_context_reset = (...)
    if not stream_meta.get("no_data") and not _k0_context_reset:
        succeeded = True
except ...

# K1 — truncate long messages (protect .md content)
if not succeeded:
    try:
        k1_msgs = _cascade_truncate_content(base_msgs, 4000)
        stream_gen, stream_meta = _try_send(k1_msgs, "K1:truncate@4K")
        if not stream_meta.get("no_data"):
            succeeded = True
    except Exception as e:
        if is_rate_err: handle_rate
        elif not is_len_err: raise

# K2+ — iteratively trim 30% of oldest messages
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
            if is_rate_err and handle_rate(e): continue
            elif not is_len_err(e): raise

if not succeeded:
    raise HTTPException(502, "All cascade compression levels exhausted.")
```

### Removed Functions

- `_cascade_strip_tool_calls()` — no longer needed. Tool calls and results are kept intact in the history; only content length is reduced.

### Edge Cases

1. **Message with both .md and non-.md content**: if `_is_md_content()` returns True, the entire message is protected. This is intentional — a tool result containing a spec.md path likely has the file content inline.
2. **False positive on .md detection**: a message like `"see file.txt.md"` would match. This is extremely rare and harmless — at most one extra message is left untruncated.
3. **Conversations with no .md files**: cascade works identically to before, except tool calls are preserved in K1.
4. **Rate limiting mid-cascade**: handled by the existing `_handle_rate` / `_is_rate_err` logic — switches accounts or raises 429.
