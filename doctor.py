"""
doctor.py - Autonomiczny moduł Self-Healing Supervisor / Doctor dla DeepSeek Proxy.

Działa jako "doktor" w tle:
- NIE uruchamia się przy normalnych zapytaniach ani przy timeoutach/pacingu.
- Uruchamia się WYŁĄCZNIE wtedy, gdy nastąpi rzeczywisty, krytyczny błąd strumienia
  (np. ucięty/uszkodzony blok narzędzia, pętla tokenów bez domknięcia, błąd auto-continue).
- Może korzystać z:
  1. "custom_http" - zewnętrznego/lokalnego proxy (np. passthrough 4571, Gemini proxy, Claude, inne proxy OpenAI-compatible)
  2. "official_api" - oficjalnego API DeepSeek (jeśli jest klucz)
  3. "internal_pool" - wolnego konta DeepSeek z puli
- Analizuje zrzut awaryjny (ostatnie wiadomości, urwany bufor, błąd) i:
  a) Naprawia i domyka wywołanie narzędzia, odsyłając je do Trae w ułamku sekundy
  b) W razie braku możliwości naprawy narzędzia — generuje czystą, instruktywną odpowiedź
"""

import json
import os
import re
import time
from pathlib import Path
import urllib.request
import urllib.error

CONFIG_PATH = Path(__file__).resolve().parent / "data" / "doctor_config.json"
PROXY_DIR = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "enabled": False,
    "provider": "custom_http",
    "endpoint": "",
    "model": "deepseek-chat",
    "api_key": "",
    "timeout_seconds": 30.0,
    "max_repair_attempts": 1,
    "trigger_on": {
        "unclosed_tool_call": True,
        "auto_continue_failed": True,
        "loop_aborted_without_tool": True,
        "stream_zero_tokens": True,
        "unexpected_error": True
    },
    "ignored_errors": [
        "timeout",
        "readtimeout",
        "connecttimeout",
        "pacing",
        "rate_limit",
        "client disconnected",
        "generatorexit"
    ]
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return DEFAULT_CONFIG
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    except Exception as e:
        print(f"[DOCTOR] Failed to load config: {e}", flush=True)
        return DEFAULT_CONFIG


def should_trigger(reason: str, error: str = "") -> bool:
    cfg = load_config()
    if not cfg.get("enabled", False):
        return False

    combined = f"{reason} {error}".lower()
    for ign in cfg.get("ignored_errors", []):
        if ign in combined:
            return False

    triggers = cfg.get("trigger_on", {})
    if triggers.get("unclosed_tool_call") and "unclosed tool call" in combined:
        return True
    if triggers.get("auto_continue_failed") and "auto-continue failed" in combined:
        return True
    if triggers.get("loop_aborted_without_tool") and "loop" in combined:
        return True
    if triggers.get("stream_zero_tokens") and ("zero tokens" in combined or "_wait" in combined):
        return True
    if triggers.get("unexpected_error") and any(k in combined for k in ("upstream error", "exception", "failed")):
        return True

    return False


def _call_http(endpoint: str, model: str, messages: list[dict], api_key: str = "", timeout: float = 30.0) -> str:
    """Wysyła zapytanie do dowolnego endpointu OpenAI-compatible (np. Gemini proxy, passthrough proxy, oficjalny DeepSeek)."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DeepSeek-Doctor/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
        "stream": False
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        choices = res_data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            return msg.get("content", "") or ""
    return ""


def diagnose_and_repair(
    conv_key: str,
    reason: str,
    error: str,
    partial_content: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    parse_tool_calls_fn=None,
    ap=None
) -> dict:
    """
    Główna funkcja naprawcza:
    - Analizuje nieudane zapytanie
    - Odpytuje skonfigurowany model supervisora
    - Zwraca słownik:
      {"repaired": True, "type": "tool_calls", "tools": [...], "raw": "..."}
      lub
      {"repaired": True, "type": "content", "content": "..."}
      lub
      {"repaired": False, "error": "..."}
    """
    if not should_trigger(reason, error):
        return {"repaired": False, "skipped": True}

    cfg = load_config()
    provider = cfg.get("provider", "custom_http")
    endpoint = cfg.get("endpoint") or "http://127.0.0.1:4571/v1/chat/completions"
    model = cfg.get("model", "deepseek-chat")
    api_key = cfg.get("api_key", "")
    timeout = float(cfg.get("timeout_seconds", 30.0))

    print(f"[DOCTOR] Triggered on fatal error: '{reason}' (conv={conv_key[:20]}...)", flush=True)

    # 1. Przygotuj listę dostępnych narzędzi (nazwy + parametry)
    tools_summary = []
    if tools:
        for t in tools:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            name = fn.get("name", "")
            params = list(fn.get("parameters", {}).get("properties", {}).keys())
            tools_summary.append(f"- {name}({', '.join(params)})")
    tools_str = "\n".join(tools_summary) if tools_summary else "Brak narzędzi w zapytaniu."

    # 2. Ostatnie wiadomości z kontekstu (ostatnia instrukcja usera)
    last_user_prompt = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            last_user_prompt = str(c)[-2000:]
            break

    doctor_system = f"""Jesteś autonomicznym Doktorem i Nadzorcą (Supervisor Agent) dla lokalnego proxy kodowania DeepSeek/Trae.
Folder roboczy projektu proxy: {PROXY_DIR}
Zadanie głównego agenta zostało przerwane błędem: "{reason}".

Dostępne narzędzia w IDE:
{tools_str}

ZASADY NAPRAWY:
1. Przeanalizuj ostatnie żądanie użytkownika oraz URWANY/USZKODZONY fragment odpowiedzi modelu.
2. Jeśli model próbował wywołać narzędzie (np. Read, Write, Grep, RunCommand, LS itp.), wyemituj WYŁĄCZNIE poprawne, kompletne wywołanie tego narzędzia w formacie:
<tool_call name="NazwaNarzędzia">
  <parameter name="nazwa_parametru">wartość</parameter>
</tool_call>
(Dla Write/Edit parametr "file_path" musi być ZAWSZE na pierwszym miejscu przed "content").
3. Nie pisz zbędnych wstępów ani komentarzy. Jeśli wywołanie narzędzia jest możliwe do zrekonstruowania — wyemituj tylko blok <tool_call>...</tool_call>.
4. Jeśli model nie planował narzędzia lub błąd jest czysto logiczny, podaj zwięzłą, konkretną odpowiedź po polsku, wyjaśniającą sytuację użytkownikowi."""

    user_repair_request = f"""--- OSTATNIA WIADOMOŚĆ UŻYTKOWNIKA ---
{last_user_prompt}

--- URWANA / USZKODZONA ODPOWIEDŹ MODELU (PRZYCZYNA AWARII) ---
{partial_content[:6000]}

--- BŁĄD / POWÓD ---
Powód: {reason}
Błąd: {error}

Zrekonstruuj i napraw odpowiedź (preferuj wyemitowanie gotowego bloku narzędzia):"""

    try:
        t0 = time.time()
        doctor_reply = ""

        # Wywołanie dostawcy:
        if provider == "custom_http":
            doctor_reply = _call_http(
                endpoint=endpoint,
                model=model,
                messages=[
                    {"role": "system", "content": doctor_system},
                    {"role": "user", "content": user_repair_request}
                ],
                api_key=api_key,
                timeout=timeout
            )
        elif provider == "official_api":
            key_file = PROXY_DIR / "data" / "deepseek_api_key.txt"
            off_key = key_file.read_text(encoding="utf-8").strip() if key_file.exists() else api_key
            if off_key:
                doctor_reply = _call_http(
                    endpoint="https://api.deepseek.com/v1/chat/completions",
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": doctor_system},
                        {"role": "user", "content": user_repair_request}
                    ],
                    api_key=off_key,
                    timeout=timeout
                )
        elif provider == "internal_pool" and ap is not None:
            # Rezerwacja wolnego slotu z puli na szybki one-shot repair
            try:
                free_slot = ap.pick_for_conv()
                print(f"[DOCTOR] Using internal pool slot {free_slot} for repair", flush=True)
            except Exception as pe:
                print(f"[DOCTOR] Internal pool pick failed: {pe}", flush=True)

        elapsed = time.time() - t0
        print(f"[DOCTOR] Response received in {elapsed:.1f}s ({len(doctor_reply)} chars)", flush=True)

        if not doctor_reply.strip():
            return {"repaired": False, "error": "Doctor returned empty response"}

        parsed_tools = []
        if parse_tool_calls_fn is not None:
            parsed_tools = parse_tool_calls_fn(doctor_reply)

        if parsed_tools:
            print(f"[DOCTOR] Successfully synthesized {len(parsed_tools)} repaired tool call(s)!", flush=True)
            return {
                "repaired": True,
                "type": "tool_calls",
                "tools": parsed_tools,
                "raw": doctor_reply
            }
        else:
            print(f"[DOCTOR] Doctor provided text recovery explanation", flush=True)
            return {
                "repaired": True,
                "type": "content",
                "content": doctor_reply
            }

    except Exception as e:
        print(f"[DOCTOR] Repair failed with exception: {e}", flush=True)
        return {"repaired": False, "error": str(e)}
