# Design: DeepSeek Proxy OpenAI Compatibility and Precision Tool Calls

## Problem Statement
The current proxy server for DeepSeek (`server.py`) has two primary limitations:
1. **Aggressive JSON parsing of string arguments:** Parameters parsed from XML (e.g. `<parameter name="content">...</parameter>`) are passed to `_parse_param_value`, which attempts to parse them as JSON if they look like JSON literals. If a model writes code or JSON as a string, this parsing turns it into a Python `dict` or strips outer quotes, resulting in lost formatting, missing backslashes, and serialization errors when passing it to Trae IDE.
2. **Lack of non-streaming response support:** The `/v1/chat/completions` endpoint unconditionally returns a `StreamingResponse`. When clients request a non-streaming response (`stream: false`), they receive an SSE stream which fails validation.

---

## Proposed Solution

### 1. Schema-Aware Parameter Parsing
We will enhance `_parse_tool_calls` and parameter parsing to check the type of each parameter against the active tool schemas.
- If a parameter's schema specifies `type: "string"` (or if the parameter name matches common string/code properties), the raw stripped string will be returned.
- If the schema specifies `type: "integer"`, `type: "number"`, or `type: "boolean"`, the value will be converted to the appropriate python type.
- Only if the schema specifies an object or array will JSON parsing be performed.

### 2. OpenAI-Compatible `stream=False` Handling
Inside `/v1/chat/completions`, if `req.stream` is `False`:
- The server will consume the `generate()` async generator.
- All yielded text content chunks will be concatenated.
- All yielded tool calls will be collected.
- A standard OpenAI-compatible `chat.completion` JSON object will be returned.

### 3. Verbose Tool Call Logging
We will print a detailed debug log of the parsed tool calls showing:
- Tool name
- Arguments dictionary keys and types
- Raw arguments JSON sent to the client
This will allow easy verification of what Trae IDE is receiving.
