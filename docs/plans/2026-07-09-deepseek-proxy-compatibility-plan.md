# DeepSeek Proxy OpenAI Compatibility and Precision Tool Calls Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Make the proxy server fully OpenAI compatible by implementing correct `stream=False` responses, extracting tool parameters precisely according to the tool's schema type (avoiding JSON formatting corruption of code), and adding verbose debug logs.

**Architecture:**
- Create a `_get_param_type` helper and `_parse_param` wrapper to inspect parameter types in the active tools schema. If a parameter is expected to be a string, do not parse it as JSON.
- Enhance `/v1/chat/completions` to check `req.stream`. If `False`, consume the generator `generate()`, concatenate content, collect tool calls, and return a `JSONResponse`.
- Log the parsed tool call name and arguments in detail before formatting them for the response.

**Tech Stack:** Python, FastAPI, Pydantic, pytest

---

## Proposed Changes

### deepseek-proxy

#### [MODIFY] [server.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/server.py)
We will:
1. Define a helper `_get_param_type(tool_name: str, param_name: str, tools: list[dict] | None) -> str | None`.
2. Define a helper `_parse_param(raw: str, tool_name: str, param_name: str, tools: list[dict] | None)`.
3. Update `_parse_tool_calls` to accept `tools: list[dict] | None = None` and use `_parse_param` instead of `_parse_param_value`.
4. Update `generate()` inside `/v1/chat/completions` to pass `tools` to `_parse_tool_calls`.
5. Update `/v1/chat/completions` to handle `req.stream == False` by collecting SSE chunks and returning a standard `JSONResponse` with choices and tool_calls.
6. Add logging to print the exact tool call and arguments when tool calls are generated.

#### [MODIFY] [test_server.py](file:///f:/PROJEKTY/DEEPSEEK_FRYTA/deepseek-proxy/test_server.py)
We will add test cases to test schema-aware parameter parsing and `stream=False` JSONResponse conversion.

---

## Verification Plan

### Automated Tests
Run pytest in the `deepseek-proxy` directory:
- `pytest -v`

### Manual Verification
- Start the server using `watch_server.py` or python `server.py` and run a cURL request with `stream: false` to verify it returns a standard JSON object.
- Make a tool call request with code containing braces `{}` to verify it is passed as a string parameter without formatting changes.
