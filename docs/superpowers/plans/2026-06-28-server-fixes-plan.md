# Server Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wdrożyć 9 poprawek do `server.py` — thread-safety, poprawne klucze konwersacji, obsługa `tool_choice`, parametry modelu, usage, fingerprint.

**Architecture:** Wszystkie zmiany w jednym pliku `deepseek-proxy/server.py`. Każda poprawka niezależna, każda z własnym commitem.

**Tech Stack:** Python 3.11+, standard library (threading, json, hashlib, re, time)

## Global Constraints

- Wszystkie zmiany w `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py`
- Każdy task kończy się commitem
- Testy manualne: restart serwera + wysłanie requestu przez Trae
- Kod produkcyjny — tylko to co konieczne, bez refaktoringu pobocznego

---

### Task 1: Thread-safety dla `_conv_state`

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py`

**Interfaces:**
- Produces: `_conv_lock = threading.Lock()` — używane przez wszystkie pozostałe taski

- [ ] **Step 1: Dodaj lock**

Znajdź linię 634 (`_auth_lock = threading.Lock()`). Po niej dodaj:

```python
_conv_lock = threading.Lock()
```

- [ ] **Step 2: Opakuj operacje na `_conv_state` w lock**

Znajdź wszystkie miejsca gdzie `_conv_state` jest odczytywany lub modyfikowany i opakuj w `with _conv_lock:`.

Lokalizacje do opakowania:

**(a) Odczyt stanu konwersacji** — linia ~826:
```python
# przed:
state = _conv_state.get(conv_key)
# po:
with _conv_lock:
    state = _conv_state.get(conv_key)
```

**(b) Czyszczenie stanu przy [new chat]** — linia ~840:
```python
# przed:
_conv_state.pop(conv_key, None)
# po:
with _conv_lock:
    _conv_state.pop(conv_key, None)
```

**(c) Zapis nowego stanu sesji** — linia ~889:
```python
# przed:
_conv_state[conv_key] = state
# po:
with _conv_lock:
    _conv_state[conv_key] = state
```

**(d) Aktualizacja parent_id i msgs_len w ścieżce non-stream** — linia ~939-942:
```python
# przed:
state["parent_id"] = new_parent
if tools or full_text.strip():
    state["msgs_len"] = len(req.messages)
# po:
with _conv_lock:
    state["parent_id"] = new_parent
    if tools or full_text.strip():
        state["msgs_len"] = len(req.messages)
```

**(e) Aktualizacja po streamingu** — linia ~1040-1049:
```python
# przed:
old_parent = state.get("parent_id")
new_parent = result_meta.get("resp_msg_id") or old_parent
state["parent_id"] = new_parent
if tools_yielded > 0 or full.strip():
    state["msgs_len"] = len(req.messages)
elif old_parent and not result_meta.get("resp_msg_id"):
    _conv_state.pop(conv_key, None)
# po:
with _conv_lock:
    old_parent = state.get("parent_id")
    new_parent = result_meta.get("resp_msg_id") or old_parent
    state["parent_id"] = new_parent
    if tools_yielded > 0 or full.strip():
        state["msgs_len"] = len(req.messages)
    elif old_parent and not result_meta.get("resp_msg_id"):
        _conv_state.pop(conv_key, None)
```

**(f) Czyszczenie przy context limit** — linia ~1034:
```python
# przed:
_conv_state.pop(conv_key, None)
# po:
with _conv_lock:
    _conv_state.pop(conv_key, None)
```

- [ ] **Step 3: Zweryfikuj poprawność składni**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: add thread-safety for _conv_state with _conv_lock"
```

---

### Task 2: `_get_conv_key()` — użycie JWT z acl-token

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — funkcja `_get_conv_key` (linie 747-763) i jej wywołanie (linia 810)

**Interfaces:**
- Consumes: `_conv_lock` (Task 1)
- Produces: `_get_conv_key(messages, acl_payload)` — nowa sygnatura

- [ ] **Step 1: Zmień sygnaturę i logikę `_get_conv_key`**

Zamień funkcję (linie 747-763):

```python
def _get_conv_key(messages: list[dict], acl_payload: dict | None = None) -> str:
    """Unique key per conversation: JWT sub/session, or last user message fingerprint."""
    # Prefer JWT identity from acl-token
    if acl_payload:
        for key in ("sub", "session", "conv", "chat", "jid", "sid"):
            val = acl_payload.get(key)
            if val:
                return f"jwt_{key}_{val}"

    sys_hash = _get_sys_hash(messages)
    user_fp = ""
    # Use LAST user message (iterate from end)
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            if isinstance(c, str) and c.strip():
                user_fp = hashlib.md5(c.strip().encode()).hexdigest()[:8]
                break

    if user_fp:
        return f"{sys_hash}_{user_fp}" if sys_hash else user_fp
    return sys_hash
```

- [ ] **Step 2: Zaktualizuj wywołanie**

Znajdź linię ~810:
```python
conv_key = _get_conv_key(req.messages)
```

Zamień na:

```python
# Extract acl-token payload (decoded earlier at line ~793-804)
acl_payload = None
if acl_token and acl_token.count(".") == 2:
    try:
        payload_b64 = acl_token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        acl_payload = json.loads(base64.b64decode(payload_b64))
    except Exception:
        pass
conv_key = _get_conv_key(req.messages, acl_payload)
```

Uwaga: kod JWT już istnieje w handlerze (linie 793-804). Wyciągnij dekodowanie przed wywołanie `_get_conv_key` i przekaż wynik. Unikaj duplikacji — jeśli dekodowanie już jest, użyj zmiennej.

- [ ] **Step 3: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: use JWT acl-token for conv_key, fallback to last user message"
```

---

### Task 3: Obsługa `tool_choice`

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — handler `/v1/chat/completions`

**Interfaces:**
- Consumes: `req.tool_choice` (pole ChatRequest, linia 625)
- Produces: zmodyfikowane `tools` i/lub prompt przed przekazaniem do `_build_prompt`

- [ ] **Step 1: Dodaj logikę tool_choice przed budowaniem prompta**

Znajdź linię ~847 (po `_get_conv_key`, przed blokiem `if resume`). Dodaj:

```python
# Handle tool_choice
if req.tool_choice:
    if req.tool_choice == "none":
        tools = None
        print(f"[TOOL_CHOICE] 'none' — tools disabled", flush=True)
    elif req.tool_choice == "required":
        # DeepSeek nie wspiera tool_choice natywnie; wymuszamy przez prompt
        print(f"[TOOL_CHOICE] 'required' — will append instruction to prompt", flush=True)
    elif isinstance(req.tool_choice, dict) and tools:
        fn_name = req.tool_choice.get("function", {}).get("name", "")
        if fn_name:
            tools = [t for t in tools if t.get("function", {}).get("name") == fn_name]
            print(f"[TOOL_CHOICE] filtered to '{fn_name}' — {len(tools)} tool(s) remaining", flush=True)
```

- [ ] **Step 2: Dodaj required instruction do prompta**

Przy budowaniu prompta (linia ~858 dla resume, ~887 dla nowej sesji), po `_build_prompt` dodaj:

```python
if req.tool_choice == "required":
    prompt += "\n\nYou MUST call at least one tool in your response."
```

Dla obu ścieżek (resume i nowa sesja).

- [ ] **Step 3: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: honor tool_choice (none, required, specific function)"
```

---

### Task 4: Warunek resume `>=` zamiast `>`

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — linia 844

**Interfaces:**
- Consumes: `state`, `req.messages`
- Produces: zmieniony warunek `resume`

- [ ] **Step 1: Zmień warunek**

Znajdź linię ~844:

```python
# przed:
resume = state and state.get("parent_id") is not None and len(req.messages) > state.get("msgs_len", 0)
# po:
resume = state and state.get("parent_id") is not None and len(req.messages) >= state.get("msgs_len", 0)
```

- [ ] **Step 2: Obsłuż retry (len == msgs_len)**

W bloku `if resume:` (linia ~853-859), dodaj logikę:

```python
if resume:
    chat_id = state["ds_session"]
    parent_id = state["parent_id"]
    if len(req.messages) == state["msgs_len"]:
        # Retry: wysyłamy tylko ostatnią wiadomość jako kontynuację
        new_msgs = req.messages[-1:]
        print(f"[RESUME] RETRY detected (same msgs_len={state['msgs_len']}), sending last msg only", flush=True)
    else:
        new_msgs = req.messages[state["msgs_len"]:]
        print(f"[RESUME] ds_session={chat_id} parent={parent_id} skip={state['msgs_len']} send={len(new_msgs)} new msgs", flush=True)
    prompt = _build_prompt(new_msgs, tools=tools)
```

- [ ] **Step 3: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: resume on len>=msgs_len, retry sends last msg only"
```

---

### Task 5: Race condition w `_ensure_auth()`

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — funkcja `_ensure_auth` (linie 636-657)

**Interfaces:**
- Consumes: `_auth_lock` (już istnieje)
- Produces: poprawiona funkcja `_ensure_auth()`

- [ ] **Step 1: Przenieś walidację pod lock**

Zamień funkcję (linie 636-657):

```python
def _ensure_auth():
    global _auth_in_progress
    # Fast path: already authenticated (no lock needed for read)
    if sm.is_valid() and time.time() - sm.session.last_validated_at <= 60:
        return

    with _auth_lock:
        # Re-check under lock
        if _auth_in_progress:
            raise HTTPException(401, "Login in progress – complete the sign-in in Chrome, then retry")
        if sm.is_valid() and sm.validate_remote():
            return
        sm.reset()
        _auth_in_progress = True

    def _background_auth():
        global _auth_in_progress
        try:
            authenticate_via_playwright(sm)
        finally:
            _auth_in_progress = False

    t = threading.Thread(target=_background_auth, daemon=True)
    t.start()
    raise HTTPException(401, "Not authenticated – Chrome opened for login. Sign in and retry the request.")
```

- [ ] **Step 2: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: move auth validation under _auth_lock to prevent race condition"
```

---

### Task 6: Tools w ścieżce resume

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — linia ~858

**Interfaces:**
- Consumes: `tools`, `state`
- Produces: poprawne przekazanie tools do `_build_prompt` w resume

- [ ] **Step 1: Dodaj fallback do state.get("tools")**

Znajdź linię ~858 (w bloku `if resume:`):

```python
# przed:
prompt = _build_prompt(new_msgs, tools=tools)
# po:
prompt = _build_prompt(new_msgs, tools=tools or state.get("tools"))
```

- [ ] **Step 2: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: propagate tools from state in resume path when req.tools is empty"
```

---

### Task 7: Przekazywanie `max_tokens`, `temperature`, `top_p` do DeepSeek

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — metoda `stream_completion` (linie 141-167) i jej wywołanie (linia ~895)

**Interfaces:**
- Consumes: `req.max_tokens`, `req.temperature`, `req.top_p` (ChatRequest)
- Produces: `stream_completion(chat_session_id, prompt, parent_message_id, max_tokens, temperature, top_p)` — rozszerzona sygnatura

- [ ] **Step 1: Rozszerz sygnaturę `stream_completion`**

Znajdź linię ~141-142:

```python
def stream_completion(self, chat_session_id: str, prompt: str,
                      parent_message_id: int | None = None,
                      max_tokens: int = 8192, temperature: float = 1.0, top_p: float = 1.0):
```

- [ ] **Step 2: Dodaj parametry do JSON body**

Znajdź linię ~152-162 (dict z parametrami). Dodaj:

```python
json={
    "chat_session_id": chat_session_id,
    "parent_message_id": parent_message_id,
    "model_type": "expert",
    "prompt": prompt,
    "ref_file_ids": [],
    "thinking_enabled": True,
    "search_enabled": False,
    "action": None,
    "preempt": False,
    "max_tokens": max_tokens,
    "temperature": temperature,
    "top_p": top_p,
},
```

- [ ] **Step 3: Zaktualizuj wywołanie**

Znajdź linię ~895:

```python
# przed:
result = ds.stream_completion(chat_id, prompt, parent_id)
# po:
result = ds.stream_completion(chat_id, prompt, parent_id, req.max_tokens, req.temperature, req.top_p)
```

- [ ] **Step 4: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 5: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: forward max_tokens, temperature, top_p to DeepSeek API"
```

---

### Task 8: `usage` — estymacja tokenów

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — odpowiedzi non-stream i stream

**Interfaces:**
- Consumes: `full_text` (non-stream) / `full` (stream)
- Produces: `usage` z estymowanymi wartościami zamiast zer

- [ ] **Step 1: Non-stream usage**

Znajdź linię ~947:

```python
# przed:
"usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
# po:
"usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": max(1, len(full_text) // 4), "total_tokens": (len(prompt) + len(full_text)) // 4},
```

- [ ] **Step 2: Stream usage**

W funkcji `generate()`, na końcu przed yield `[DONE]`, dodaj usage do ostatniego chunka z `finish_reason`. Znajdź linię ~1057:

```python
# przed:
yield _chunk({}, fr)
# po (dodaj usage do chunka):
c = _chunk({}, fr)
# Wstrzyknij usage do ostatniego chunka
import json as _json
chunk_data = _json.loads(c[6:].strip())  # skip "data: " and trailing \n\n
chunk_data["usage"] = {"prompt_tokens": len(prompt) // 4, "completion_tokens": max(1, len(full) // 4), "total_tokens": (len(prompt) + len(full)) // 4}
yield f"data: {_json.dumps(chunk_data)}\n\n"
```

Uwaga: `prompt` nie jest dostępny w domknięciu `generate()`. Przekaż go jako argument lub oblicz usage w handlerze przed zwróceniem `StreamingResponse`. Alternatywnie — uproszczone podejście: dodaj `usage` tylko do non-stream response, a w stream zostaw zera (DeepSeek i tak nie zwraca usage w strumieniu, więc klienci nie powinni na tym polegać).

**Uproszczona wersja (zalecana):**

Dla non-stream (linia ~947):
```python
"usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": max(1, len(full_text) // 4), "total_tokens": (len(prompt) + len(full_text)) // 4},
```

Dla stream — zostaw bez usage (zera są akceptowalne, OpenAI też nie zawsze zwraca usage w strumieniu).

- [ ] **Step 2: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: estimate token usage instead of returning zeros"
```

---

### Task 9: `system_fingerprint`

**Files:**
- Modify: `F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py` — odpowiedzi non-stream i stream

**Interfaces:**
- Consumes: nic
- Produces: `system_fingerprint` w każdej odpowiedzi

- [ ] **Step 1: Non-stream fingerprint**

Znajdź linię ~943-948 (return dict dla non-stream). Dodaj:

```python
"system_fingerprint": "fp_deepseek_proxy_v1",
```

Przed `"usage"` lub po `"object"`.

- [ ] **Step 2: Stream fingerprint**

Znajdź funkcję `_chunk` (linia ~954-959). Dodaj `system_fingerprint`:

```python
def _chunk(delta: dict, fr: str | None = None) -> str:
    c = {"id": completion_id, "object": "chat.completion.chunk", "created": _created, "model": _model,
         "system_fingerprint": "fp_deepseek_proxy_v1",
         "choices": [{"index": 0, "delta": delta}]}
    if fr is not None:
        c["choices"][0]["finish_reason"] = fr
    return f"data: {json.dumps(c)}\n\n"
```

- [ ] **Step 3: Zweryfikuj składnię**

```powershell
python -c "exec(open(r'F:\PROJEKTY\DEEPSEEK_FRYTA\deepseek-proxy\server.py').read().split('if __name__')[0]); print('syntax OK')"
```

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: add system_fingerprint to OpenAI-compatible responses"
```