# DeepSeek V4-Pro Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single-file OpenAI-compatible proxy server that authenticates through chat.deepseek.com free web chat (Expert Mode = V4-Pro) and exposes HTTP API on port 4570 for IDE integration.

**Architecture:** FastAPI server with embedded PoW solver (DeepSeekHashV1 via WASM). Playwright Firefox for one-time authentication. curl_cffi for HTTP with TLS impersonation. Custom DeepSeek SSE → OpenAI SSE translation.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, curl-cffi, playwright (Firefox), pydantic

---

### Task 1: Project scaffold + requirements

**Files:**
- Create: `deepseek-proxy/requirements.txt`
- Create: `deepseek-proxy/start.bat`
- Create: `deepseek-proxy/.gitignore`

- [ ] **Step 1: Create project directory and requirements.txt**

Create `deepseek-proxy/requirements.txt`:
```
curl-cffi>=0.14.0
fastapi>=0.115.0
uvicorn>=0.34.0
playwright>=1.52.0
pydantic>=2.0.0
```

- [ ] **Step 2: Create start.bat**

Create `deepseek-proxy/start.bat`:
```bat
@echo off
cd /d "%~dp0"
echo Starting DeepSeek V4-Pro Proxy on http://localhost:4570
echo.
echo IDE config: http://localhost:4570/v1  |  API Key: anything
echo Model: deepseek-v4-pro
echo.
echo First time? Run: python -m playwright install firefox
echo.
python server.py
pause
```

- [ ] **Step 3: Create .gitignore**

Create `deepseek-proxy/.gitignore`:
```
session.json
__pycache__/
*.pyc
.env
```

- [ ] **Step 4: Create directory structure**

```bash
mkdir -p deepseek-proxy/wasm
```

- [ ] **Step 5: Commit**

```bash
git add deepseek-proxy/
git commit -m "feat: project scaffold with requirements and launcher"
```

---

### Task 2: Copy PoW solver + WASM binary

**Files:**
- Copy: `temp_deepseek/dsk/pow.py` → `deepseek-proxy/pow.py`
- Copy: `temp_deepseek/dsk/wasm/sha3_wasm_bg.7b9ca65ddd.wasm` → `deepseek-proxy/wasm/sha3_wasm_bg.7b9ca65ddd.wasm`

- [ ] **Step 1: Copy pow.py**

```bash
cp temp_deepseek/dsk/pow.py deepseek-proxy/pow.py
```

- [ ] **Step 2: Copy WASM binary**

```bash
cp temp_deepseek/dsk/wasm/sha3_wasm_bg.7b9ca65ddd.wasm deepseek-proxy/wasm/sha3_wasm_bg.7b9ca65ddd.wasm
```

- [ ] **Step 3: Update WASM path in pow.py**

Edit `deepseek-proxy/pow.py` line ~14 to point to the local wasm path:
```python
WASM_PATH = f'{os.path.dirname(__file__)}/wasm/sha3_wasm_bg.7b9ca65ddd.wasm'
```

Verify this path is already correct relative to the file (it uses `os.path.dirname(__file__)` which will work from the new location).

- [ ] **Step 4: Install Firefox for Playwright**

```bash
python -m playwright install firefox
```

- [ ] **Step 5: Commit**

```bash
git add deepseek-proxy/pow.py deepseek-proxy/wasm/
git commit -m "feat: add PoW solver (DeepSeekHashV1) with WASM binary"
```

---

### Task 3: Session manager module

**Files:**
- Create: `deepseek-proxy/server.py` (session management section, top ~80 lines)

This adds the `SessionManager` class that loads/saves `session.json` and validates session health.

- [ ] **Step 1: Write SessionManager class**

Add this at the top of `server.py`:
```python
import json, os, time
from pathlib import Path
from curl_cffi import requests
from dataclasses import dataclass

SESSION_FILE = Path(__file__).parent / "session.json"

@dataclass
class Session:
    auth_token: str
    cookies: dict
    user_agent: str = ""
    created_at: float = 0.0
    last_validated_at: float = 0.0

class SessionManager:
    def __init__(self):
        self.session: Session | None = None
        self._load()

    def _load(self):
        if SESSION_FILE.exists():
            try:
                data = json.loads(SESSION_FILE.read_text())
                self.session = Session(**data)
            except Exception:
                self.session = None

    def save(self):
        if self.session:
            SESSION_FILE.write_text(json.dumps({
                "auth_token": self.session.auth_token,
                "cookies": self.session.cookies,
                "user_agent": self.session.user_agent,
                "created_at": self.session.created_at,
                "last_validated_at": self.session.last_validated_at,
            }, indent=2))

    def is_valid(self) -> bool:
        if not self.session:
            return False
        if not self.session.auth_token or not self.session.cookies:
            return False
        return True

    def validate_remote(self) -> bool:
        if not self.is_valid():
            return False
        try:
            r = requests.get(
                "https://chat.deepseek.com/api/v0/users/current",
                headers={
                    "authorization": f"Bearer {self.session.auth_token}",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "x-client-platform": "web",
                    "x-client-version": "2.0.0",
                    "x-app-version": "2.0.0",
                },
                cookies=self.session.cookies,
                impersonate="chrome120",
                timeout=15,
            )
            if r.status_code == 200:
                self.session.last_validated_at = time.time()
                self.save()
                return True
        except Exception:
            pass
        return False

    def reset(self):
        self.session = None
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
```

- [ ] **Step 2: Quick integration check**

Run a quick Python check that the module imports cleanly:
```python
python -c "import sys; sys.path.insert(0, 'deepseek-proxy'); from server import SessionManager; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: add session manager with load/save/validate"
```

---

### Task 4: DS Client (DeepSeek API wrapper)

**Files:**
- Modify: `deepseek-proxy/server.py` (add DSClient class after SessionManager)

This adds the `DSClient` class that handles:
- Creating chat sessions
- Solving PoW challenges via WASM
- Streaming completions from DeepSeek API

- [ ] **Step 1: Write DSClient class**

Add after SessionManager in `server.py`:
```python
from curl_cffi import requests
from pow import DeepSeekPOW

BASE_URL = "https://chat.deepseek.com/api/v0"

class DSClient:
    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.pow = DeepSeekPOW()

    def _headers(self, pow_resp: str | None = None) -> dict:
        h = {
            "accept": "*/*",
            "authorization": f"Bearer {self.sm.session.auth_token}",
            "content-type": "application/json",
            "origin": "https://chat.deepseek.com",
            "referer": "https://chat.deepseek.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "x-app-version": "2.0.0",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-version": "2.0.0",
        }
        if pow_resp:
            h["x-ds-pow-response"] = pow_resp
        return h

    def _get_challenge(self) -> dict:
        r = requests.post(
            f"{BASE_URL}/chat/create_pow_challenge",
            headers=self._headers(),
            json={"target_path": "/api/v0/chat/completion"},
            cookies=self.sm.session.cookies,
            impersonate="chrome120",
            timeout=30,
        )
        return r.json()["data"]["biz_data"]["challenge"]

    def create_session(self) -> str:
        r = requests.post(
            f"{BASE_URL}/chat_session/create",
            headers=self._headers(),
            json={"character_id": None},
            cookies=self.sm.session.cookies,
            impersonate="chrome120",
            timeout=30,
        )
        return r.json()["data"]["biz_data"]["chat_session"]["id"]

    def stream_completion(self, chat_session_id: str, prompt: str):
        challenge = self._get_challenge()
        pow_resp = self.pow.solve_challenge(challenge)

        r = requests.post(
            f"{BASE_URL}/chat/completion",
            headers=self._headers(pow_resp),
            json={
                "chat_session_id": chat_session_id,
                "parent_message_id": None,
                "model_type": "expert",
                "prompt": prompt,
                "ref_file_ids": [],
                "thinking_enabled": True,
                "search_enabled": False,
                "action": None,
                "preempt": False,
            },
            cookies=self.sm.session.cookies,
            impersonate="chrome120",
            stream=True,
            timeout=300,
        )

        if r.status_code == 401:
            return None  # session expired
        if r.status_code != 200:
            error_text = next(r.iter_lines(), b"").decode("utf-8", "ignore")
            raise Exception(f"DeepSeek API error {r.status_code}: {error_text}")

        content_buffer = ""
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8", "ignore")

            # Parse DeepSeek SSE format:
            # {"p":"response/fragments/-1/content","o":"APPEND","v":"text"}
            # {"v":{"response":{...,"status":"WIP",...}}}
            # {"p":"response/status","o":"SET","v":"FINISHED"}
            if decoded.startswith("data: "):
                payload = decoded[6:]
                # Skip metadata events
                if payload.startswith('{"v":{"response"'):
                    continue
                if payload.startswith('{"p":"response/fragments') or payload.startswith('{"p":"response/status"'):
                    # Extract content from APPEND or SET operations
                    data = json.loads(payload)
                    if data.get("o") == "APPEND" and "v" in data:
                        content_buffer += str(data["v"])
                        yield content_buffer
                    elif "v" in data and isinstance(data["v"], str):
                        content_buffer += data["v"]
                        yield content_buffer
                    if "FINISHED" in payload:
                        break
```

- [ ] **Step 2: Verify import works**

```python
python -c "import sys; sys.path.insert(0, 'deepseek-proxy'); from server import DSClient; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: add DS Client with PoW solving and streaming"
```

---

### Task 5: Playwright auth flow

**Files:**
- Modify: `deepseek-proxy/server.py` (add auth function)

This adds the function that opens Playwright Firefox, waits for login, and captures session data.

- [ ] **Step 1: Add Playwright auth function**

Add to `server.py` after DSClient:
```python
from playwright.sync_api import sync_playwright

def authenticate_via_playwright(sm: SessionManager) -> str:
    """Opens Firefox, waits for login, captures session. Returns status message."""
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        page = browser.new_page()
        page.goto("https://chat.deepseek.com/sign_in")

        # Wait for URL to change to chat page (user logged in)
        page.wait_for_url(lambda url: "/a/chat/" in url, timeout=300000)

        # Extract token and cookies
        token = page.evaluate("""
            () => JSON.parse(localStorage.getItem('userToken')).value
        """)
        cookies_raw = page.context.cookies()
        cookies = {c["name"]: c["value"] for c in cookies_raw}
        user_agent = page.evaluate("() => navigator.userAgent")

        browser.close()

    sm.session = Session(
        auth_token=token,
        cookies=cookies,
        user_agent=user_agent,
        created_at=time.time(),
        last_validated_at=time.time(),
    )
    sm.save()
    return "Authenticated successfully"
```

- [ ] **Step 2: Test the auth flow manually**

```bash
python -c "
import sys; sys.path.insert(0, 'deepseek-proxy')
from server import SessionManager, authenticate_via_playwright
sm = SessionManager()
msg = authenticate_via_playwright(sm)
print(msg)
print(f'Token: {sm.session.auth_token[:20]}...')
print(f'Cookies: {list(sm.session.cookies.keys())}')
"
```
Expected: Firefox opens, you log in, then it prints token and cookie names.

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: add Playwright Firefox auth flow"
```

---

### Task 6: FastAPI server + OpenAI-compatible endpoints

**Files:**
- Modify: `deepseek-proxy/server.py` (add FastAPI app, routes, startup)

This adds the full server with endpoints and ties everything together.

- [ ] **Step 1: Add server code (bottom of server.py)**

Replace the bottom of `server.py` with:
```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn, uuid, json

app = FastAPI(title="DeepSeek V4-Pro Proxy")
sm = SessionManager()
ds = DSClient(sm)

class ChatRequest(BaseModel):
    model: str = "deepseek-v4-pro"
    messages: list[dict]
    stream: bool = True
    max_tokens: int = 8192
    temperature: float = 1.0
    top_p: float = 1.0

def _ensure_auth():
    if not sm.is_valid():
        raise HTTPException(401, "Not authenticated. Hit POST /v1/login first")
    if not sm.validate_remote():
        sm.reset()
        raise HTTPException(401, "Session expired. Hit POST /v1/login to re-authenticate")

def _extract_last_prompt(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg["role"] == "user":
            return msg["content"]
    return messages[-1]["content"] if messages else ""

@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{
            "id": "deepseek-v4-pro",
            "object": "model",
            "created": 1745452800,
            "owned_by": "deepseek",
        }]
    }

@app.post("/v1/login")
def login():
    msg = authenticate_via_playwright(sm)
    return {"status": "ok", "message": msg}

@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    _ensure_auth()
    prompt = _extract_last_prompt(req.messages)
    chat_id = ds.create_session()

    if not req.stream:
        # Non-streaming: collect all content
        full_text = ""
        for chunk in ds.stream_completion(chat_id, prompt):
            if chunk:
                full_text = chunk
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # Streaming mode
    chat_id_for_stream = chat_id

    def generate():
        chat_id_val = chat_id_for_stream
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        prev_len = 0

        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'delta': {'role': 'assistant'}, 'index': 0}]})}\n\n"

        for chunk in ds.stream_completion(chat_id_val, prompt):
            if chunk and len(chunk) > prev_len:
                delta = chunk[prev_len:]
                prev_len = len(chunk)
                yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'delta': {'content': delta}, 'index': 0}]})}\n\n"

        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'delta': {}, 'index': 0, 'finish_reason': 'stop'}]})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/health")
def health():
    return {"status": "ok", "session_valid": sm.is_valid()}

if __name__ == "__main__":
    print("Checking saved session...")
    if sm.is_valid():
        if sm.validate_remote():
            print("Session valid. Ready for requests.")
        else:
            print("Session expired. Use POST /v1/login to re-authenticate.")
            sm.reset()
    else:
        print("No session found. Use POST /v1/login to authenticate.")

    uvicorn.run(app, host="0.0.0.0", port=4570)
```

- [ ] **Step 2: Verify server starts**

```bash
python deepseek-proxy/server.py
```
Expected: Server starts on port 4570. Ctrl+C to stop.

- [ ] **Step 3: Test health endpoint**

```bash
# In another terminal:
curl http://localhost:4570/health
```
Expected: `{"status":"ok","session_valid":false}`

- [ ] **Step 4: Test models endpoint**

```bash
curl http://localhost:4570/v1/models
```
Expected: Returns model list with deepseek-v4-pro.

- [ ] **Step 5: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "feat: add FastAPI server with OpenAI-compatible endpoints"
```

---

### Task 7: Integration test (full flow)

**Files:**
- None (manual integration test)

- [ ] **Step 1: Login via API**

```bash
curl -X POST http://localhost:4570/v1/login
```
Expected: Firefox opens. Log in to chat.deepseek.com, close browser. API returns `{"status":"ok","message":"Authenticated successfully"}`.

- [ ] **Step 2: Test chat completion (non-streaming)**

```bash
curl -X POST http://localhost:4570/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Say hello in Polish"}],"stream":false}'
```
Expected: Returns JSON with assistant response containing Polish greeting.

- [ ] **Step 3: Test streaming**

```bash
curl -X POST http://localhost:4570/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Count to 5"}],"stream":true}'
```
Expected: SSE stream with token-by-token content.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: working proxy with auth, chat completions, streaming"
```

---

### Task 8: Polish + final cleanup

**Files:**
- Modify: `deepseek-proxy/server.py`

- [ ] **Step 1: Handle browser close without login in Playwright auth**

Add error handling for when user closes browser before logging in:
```python
def authenticate_via_playwright(sm: SessionManager) -> str:
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        page = browser.new_page()
        page.goto("https://chat.deepseek.com/sign_in")

        try:
            page.wait_for_url(lambda url: "/a/chat/" in url, timeout=300000)
        except Exception:
            browser.close()
            raise HTTPException(400, "Login cancelled or timed out. Close was not after login.")

        # ... rest of the function
```

- [ ] **Step 2: Add re-auth on auth failure during streaming**

In `DSClient.stream_completion`, handle 401 by triggering re-auth:
```python
    if r.status_code == 401:
        sm.reset()
        return None  # caller should check and return 401
```

Add to `chat_completions` endpoint:
```python
    try:
        stream = ds.stream_completion(chat_id, prompt)
        if stream is None:
            raise HTTPException(401, "Session expired during request. Use POST /v1/login")
    except Exception as e:
        if "401" in str(e) or "Authentication" in str(e):
            raise HTTPException(401, "Session expired. Use POST /v1/login")
        raise HTTPException(502, f"Upstream error: {str(e)}")
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server.py
git commit -m "fix: handle browser close without login and re-auth on 401"
```
