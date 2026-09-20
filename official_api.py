"""
Official DeepSeek API client — used for MAIN AGENT only.
Subagents continue using the free web chat proxy.

Advantages over web chat:
- No 50-60 turn limit
- No Cloudflare / PoW / JA3 fingerprinting
- Native JSON tool calls (stable, not XML)
- Stateless — no session management needed
- Cost: ~$0.015 per long conversation (user confirmed acceptable)

API docs: https://api-docs.deepseek.com/
"""
import json
import time
import os
import requests as http_requests
from typing import Generator, Optional


class DeepSeekOfficialAPI:
    """OpenAI-compatible client for api.deepseek.com"""

    BASE_URL = "https://api.deepseek.com"

    def __init__(self):
        self._api_key: Optional[str] = None
        self._load_key()

    def _load_key(self):
        """Load API key from environment or file."""
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if key:
            self._api_key = key
            print("[OFFICIAL API] Key loaded from DEEPSEEK_API_KEY env", flush=True)
            return

        # Try file in data dir
        import pathlib
        key_file = pathlib.Path(__file__).parent / "data" / "deepseek_api_key.txt"
        if key_file.exists():
            self._api_key = key_file.read_text(encoding="utf-8").strip()
            print(f"[OFFICIAL API] Key loaded from {key_file}", flush=True)
            return

        print("[OFFICIAL API] No API key found — main agent will fall back to web chat", flush=True)

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def chat_completion(
        self,
        messages: list[dict],
        model: str = "deepseek-chat",
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        stream: bool = True,
        max_tokens: int = 8192,
        temperature: float = 1.0,
    ):
        """
        Call DeepSeek official API. Returns the raw requests.Response for streaming,
        or dict for non-streaming.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }

        body = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        t0 = time.time()
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                resp = http_requests.post(
                    f"{self.BASE_URL}/v1/chat/completions",
                    headers=headers,
                    json=body,
                    stream=stream,
                    timeout=300,
                )
                break
            except http_requests.exceptions.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 3
                    print(f"[OFFICIAL API] Retry {attempt+1}/{max_retries} after {type(e).__name__}: {e} — waiting {wait}s", flush=True)
                    time.sleep(wait)
                else:
                    raise Exception(f"Official DeepSeek API unreachable after {max_retries} retries: {last_error}")

        if resp.status_code != 200:
            error_text = resp.text[:500]
            raise Exception(f"Official DeepSeek API error {resp.status_code}: {error_text}")

        elapsed = time.time() - t0
        print(f"[OFFICIAL API] {model} stream={stream} {len(messages)} msgs — {elapsed:.1f}s", flush=True)

        return resp

    def stream_sse(self, response) -> Generator[dict, None, None]:
        """
        Parse official API SSE stream into dicts.
        Each yielded dict has keys from the OpenAI-compatible chunk format.
        """
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                yield chunk
            except json.JSONDecodeError:
                continue


# Singleton
official_api = DeepSeekOfficialAPI()
