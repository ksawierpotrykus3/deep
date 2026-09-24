# DeepSeek V4-Pro OpenAI-Compatible Proxy

## Problem

DeepSeek V4-Pro is available for free through chat.deepseek.com, but IDE tools (Cline, Continue.dev, etc.) require an OpenAI-compatible API endpoint. The official DeepSeek API requires a paid API key. This project provides a local proxy server that authenticates through the free web chat and exposes an OpenAI-compatible interface.

## Architecture

One-file FastAPI server with embedded PoW solver and Playwright-based auth.

### Project structure

```
deepseek-proxy/
├── server.py              # FastAPI server, port 4570
├── pow.py                 # PoW solver (DeepSeekHashV1 via WASM)
├── wasm/
│   └── sha3_wasm_bg.7b9ca65ddd.wasm
├── session.json           # Persisted session (cookies + token, auto-managed)
├── requirements.txt
├── .gitignore
└── start.bat              # Desktop launcher
```

### Components

- **Auth middleware** – checks Bearer token and cookies on every request. Returns 401 if missing or expired.
- **Session Manager** – loads/saves `session.json`. Validates session health via `GET /api/v0/users/current`. Automatically re-opens Playwright if session dies during use.
- **DS Client** – curl_cffi wrapper that creates chat sessions, solves PoW challenges, and streams completions from `chat.deepseek.com/api/v0`.
- **PoW Solver** – DeepSeekHashV1 WASM solver (copied from deepseek4free repo, with `sha3_wasm_bg.wasm` binary).
- **Playwright Auth** – launches Firefox (headless=False), navigates to chat.deepseek.com, waits for user login, captures `userToken` and cookies, then closes the browser.

### Data flow (chat completion)

```
IDE → POST /v1/chat/completions
  → server.py: validate session
  → DS Client: POST /api/v0/chat_session/create
  → DS Client: POST /api/v0/chat/create_pow_challenge
  → PoW Solver: solve challenge via WASM
  → DS Client: POST /api/v0/chat/completion (streaming, model_type="expert")
  → server.py: translate custom SSE → OpenAI SSE format
  → IDE: stream response
```

## API Endpoints

### `GET /v1/models`

Returns a static list with only `deepseek-v4-pro`.

### `POST /v1/chat/completions`

OpenAI-compatible chat completions. Maps to DeepSeek web API with `model_type: "expert"`.

**Request body:**
```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role": "user", "content": "hello"}],
  "stream": true,
  "max_tokens": 8192,
  "temperature": 1.0,
  "top_p": 1.0
}
```

**Streaming response (SSE, OpenAI format):**
```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant"},"index":0}]}
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"},"index":0}]}
data: [DONE]
```

**Non-streaming response:**
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello"}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60}
}
```

**Error responses:**
- `401` – no session / session expired
- `502` – DeepSeek API error

### `POST /v1/login`

Opens Playwright Firefox for manual authentication.

**Response:**
```json
{"status": "ok", "message": "Browser opened. Log in and close the browser window."}
```

Returns error if browser is closed without successful login.

## Session management

### Session file (`session.json`)

```json
{
  "auth_token": "np/fQSb+...",
  "cookies": {
    "aws-waf-token": "...",
    "smidV2": "..."
  },
  "user_agent": "Mozilla/5.0...",
  "created_at": 1782497000,
  "last_validated_at": 1782497300
}
```

### Validation loop

- Every request: check if `session.json` exists and has valid token + cookies
- Background task: ping `GET /api/v0/users/current` every 30 minutes
- If any response contains Cloudflare HTML (`<!DOCTYPE html>`) or 401: trigger re-auth

### Re-auth on failure

1. If a completion request gets Cloudflare/401 mid-stream, abort the stream and return a 401 to the client
2. Automatically open Playwright for re-login
3. Once new session is captured, the next client request proceeds normally

## Auth flow via Playwright

1. Launch Firefox with `headless=False`
2. Navigate to `https://chat.deepseek.com/sign_in`
3. Poll URL every 2 seconds until it changes to `https://chat.deepseek.com/a/chat/*`
4. Extract `localStorage.userToken.value` and all cookies
5. Close browser
6. Save to `session.json`
7. If browser closes without successful login, return error

## Dependencies

- `curl-cffi` – HTTP with TLS fingerprint impersonation
- `fastapi` + `uvicorn` – web server
- `playwright` (Firefox) – browser auth
- `pydantic` – request validation

## Desktop shortcut

`start.bat`:
```bat
@echo off
cd /d "%~dp0"
python server.py
pause
```

## Out of scope (first version)

- Multiple model types (only expert/V4-Pro)
- Conversation history storage (stateless, each request starts a new session)
- `temperature`/`top_p` parameter mapping (web API ignores these)
- Authentication persistence across Windows reboot without re-login
- PyInstaller executable
