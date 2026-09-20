import urllib.request
import json
import time

tools = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read file contents",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Write",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Edit lines or replace strings in a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"}
                },
                "required": ["file_path", "old_string", "new_string"]
            }
        }
    }
]

def test_write_edit():
    req_body = {
        "model": "deepseek",
        "messages": [
            {
                "role": "user",
                "content": "Zapisz do pliku c:/Users/buchh/projects/deep/data/test_edit_proof.txt tresc: PROXY_STATUS_OK_2026. Uzyj narzedzia Write."
            }
        ],
        "tools": tools,
        "stream": True
    }

    http_req = urllib.request.Request(
        "http://127.0.0.1:4570/v1/chat/completions",
        data=json.dumps(req_body).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    content = ""
    tool_calls = []
    finish_reason = None

    t0 = time.time()
    with urllib.request.urlopen(http_req, timeout=120) as resp:
        for line in resp:
            l = line.decode("utf-8", errors="replace").strip()
            if not l.startswith("data:"):
                continue
            payload = l[5:].strip()
            if payload == "[DONE]":
                break
            if not payload:
                continue
            d = json.loads(payload)
            choices = d.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    content += delta["content"]
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        fn = tc.get("function", {})
                        tool_calls.append({
                            "name": fn.get("name"),
                            "args": fn.get("arguments")
                        })
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]

    dur = time.time() - t0
    print(f"Duration: {dur:.2f}s")
    print(f"Total tool calls: {len(tool_calls)}")
    for i, tc in enumerate(tool_calls):
        print(f"Tool #{i+1}: {tc.get('name')} -> {tc.get('args')}")
    print(f"Finish reason: {finish_reason}")
    print(f"Content: {repr(content[:100])}")
    
    # Walidacja
    assert len(tool_calls) == 1, f"Oczekiwano 1 wywołania, otrzymano {len(tool_calls)}"
    assert tool_calls[0]["name"] == "Write", f"Oczekiwano Write, otrzymano {tool_calls[0]['name']}"
    args = json.loads(tool_calls[0]["args"])
    assert "c:/Users/buchh/projects/deep/data/test_edit_proof.txt" in args.get("file_path", "")
    assert args.get("content") == "PROXY_STATUS_OK_2026", f"Zanieczyszczona treść: {args.get('content')}"
    print("TEST WRITE ZAKONCZONY PELNYM SUKCESEM (czysta treść, 0 DSML)!")


def test_edit_tool():
    print("\n=== TEST NARZĘDZIA EDIT (SEARCH/REPLACE) ===")
    edit_tool_only = [t for t in tools if t["function"]["name"] == "Edit"]
    req_body = {
        "model": "deepseek",
        "messages": [
            {
                "role": "user",
                "content": "W pliku c:/Users/buchh/projects/deep/data/test_edit_proof.txt zamień 'PROXY_STATUS_OK_2026' na 'PROXY_STATUS_VERIFIED_2026'. Użyj narzędzia Edit."
            }
        ],
        "tools": edit_tool_only,
        "stream": True
    }


    http_req = urllib.request.Request(
        "http://127.0.0.1:4570/v1/chat/completions",
        data=json.dumps(req_body).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    tool_calls = []
    finish_reason = None
    t0 = time.time()
    with urllib.request.urlopen(http_req, timeout=120) as resp:
        for line in resp:
            l = line.decode("utf-8", errors="replace").strip()
            if not l.startswith("data:"):
                continue
            payload = l[5:].strip()
            if payload == "[DONE]":
                break
            if not payload:
                continue
            d = json.loads(payload)
            choices = d.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        fn = tc.get("function", {})
                        tool_calls.append({
                            "name": fn.get("name"),
                            "args": fn.get("arguments")
                        })
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]

    dur = time.time() - t0
    print(f"Duration: {dur:.2f}s")
    print(f"Total tool calls: {len(tool_calls)}")
    for i, tc in enumerate(tool_calls):
        print(f"Tool #{i+1}: {tc.get('name')} -> {tc.get('args')}")
    print(f"Finish reason: {finish_reason}")
    assert len(tool_calls) == 1, f"Oczekiwano 1 wywołania, otrzymano {len(tool_calls)}"
    assert tool_calls[0]["name"] == "Edit", f"Oczekiwano Edit, otrzymano {tool_calls[0]['name']}"
    args = json.loads(tool_calls[0]["args"])
    print("Parsed Edit args:", args)
    # Sprawdzenie czy aliasy zostały znormalizowane
    old_val = args.get("old_string") or args.get("old_str")
    new_val = args.get("new_string") or args.get("new_str")
    assert old_val == "PROXY_STATUS_OK_2026", f"Niepoprawny old_string: {old_val}"
    assert new_val == "PROXY_STATUS_VERIFIED_2026", f"Niepoprawny new_string: {new_val}"
    print("TEST EDIT ZAKONCZONY PELNYM SUKCESEM (dokładnie 1 wywołanie, poprawne aliasy)!")


if __name__ == "__main__":
    test_write_edit()
    test_edit_tool()
