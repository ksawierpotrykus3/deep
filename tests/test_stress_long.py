"""Realistyczny stress test: dlugie sesje kodujace (duzy kontekst + wiele tur + DLUGA generacja).

Odwzorowuje realny chat w Trae:
  - wielotysieczny kontekst (jak wynik Read duzego pliku),
  - wiele tur w TEJ SAMEJ sesji DeepSeek (sciezka RESUME, nie nowa sesja),
  - DLUGA generacja (max_tokens 16000 jak w Trae), czyli tury trwajace minuty,
  - wywolania narzedzi z wynikami.
"""
import base64
import json
import pathlib
import sys
import time
import requests

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
PROXY = "http://127.0.0.1:4570/v1/chat/completions"
LOG = BASE_DIR / "proxy_output.log"

SYS = (
    "You are an interactive agent in TraeCode that helps the USER with software engineering tasks.\n"
    "# Doing tasks\n- Be thorough. Produce complete, runnable code with docstrings and type hints.\n"
    "- NEVER abbreviate with '...' or 'reszta analogicznie'. Write every function in full.\n"
)
TOOLS = [
    {"type": "function", "function": {"name": "Read", "description": "Read a file",
        "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "Write", "description": "Write a file",
        "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["file_path", "content"]}}},
    {"type": "function", "function": {"name": "SearchReplace", "description": "Replace text in a file",
        "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "old_str": {"type": "string"},
                                                        "new_str": {"type": "string"}},
                       "required": ["file_path", "old_str", "new_str"]}}},
    {"type": "function", "function": {"name": "RunCommand", "description": "Run a shell command",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

BIG_FILE = "\n".join(
    f"def funkcja_{i}(x, y):\n    \"\"\"Operacja nr {i}.\"\"\"\n    return (x + y) * {i}\n"
    for i in range(900)
)

TURN_PROMPTS = [
    "Napisz kompletny plik Pythona: biblioteka `textkit` z 60 funkcjami do obrobki tekstu. "
    "KAZDA funkcja ma pelny docstring (opis, argumenty, zwracana wartosc), type hints i obsluge bledow. "
    "Nie uzywaj skrotow ani '...'. Zwroc CALY kod w jednym bloku.",
    "Napisz kompletny plik testow pytest dla biblioteki z poprzedniej odpowiedzi: "
    "po 3 przypadki testowe na KAZDA z 60 funkcji (razem ~180 testow), kazdy z asercjami. "
    "Nie skracaj, nie pisz 'reszta analogicznie'. Zwroc CALY kod w jednym bloku.",
    "Napisz kompletna dokumentacje API (Markdown) dla calej biblioteki: dla KAZDEJ z 60 funkcji "
    "osobna sekcja z opisem, parametrami, zwrotka i przykladem uzycia. Bez skrotow.",
]


def token(user: str) -> str:
    h = base64.b64encode(json.dumps({"alg": "none"}).encode()).decode()
    p = base64.b64encode(json.dumps({"sub": "x", "legid": {"user": user}}).encode()).decode()
    return f"{h}.{p}.sig"


def log_lines() -> list[str]:
    try:
        return LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def run_session(sid: int, turns: int) -> tuple[bool, str]:
    msgs = [
        {"role": "system", "content": SYS},
        {"role": "user", "content": "<user_input>Oto plik do analizy (wynik Read ponizej).</user_input>"},
        {"role": "tool",
         "content": f"<toolcall_status>done</toolcall_status>\n<toolcall_result>\n{BIG_FILE}\n</toolcall_result>"},
    ]
    durations = []
    for t in range(turns):
        msgs.append({"role": "user", "content": f"<user_input>{TURN_PROMPTS[t % len(TURN_PROMPTS)]}</user_input>"})
        start = len(log_lines())
        t0 = time.time()
        try:
            r = requests.post(PROXY, json={"model": "deepseek", "messages": msgs, "tools": TOOLS,
                                           "max_tokens": 16000, "stream": False},
                               headers={"acl-token": token(f"zzlong{sid}"), "Content-Type": "application/json"},
                               timeout=1800)
        except Exception as e:
            return False, f"tura{t+1}: EXC {type(e).__name__} {str(e)[:90]}"
        dt = time.time() - t0
        durations.append(dt)
        if r.status_code != 200:
            return False, f"tura{t+1} ({dt:.0f}s): HTTP {r.status_code} {r.text[:110]}"
        try:
            msg = r.json()["choices"][0]["message"]
        except Exception:
            return False, f"tura{t+1} ({dt:.0f}s): zly JSON"
        content = msg.get("content") or ""
        tcs = msg.get("tool_calls") or []

        delta = log_lines()[start:]
        finals = [ln for ln in delta if "[TURN] FINAL" in ln]
        if not any("outcome=complete finished=True" in ln for ln in finals):
            print(f"    [debug] tura{t+1}: " + " || ".join(ln[-160:] for ln in finals) if finals else "    [debug] brak FINAL")
            return False, f"tura{t+1} ({dt:.0f}s): brak complete na turze najwyzszego poziomu"

        if tcs:
            msgs.append({"role": "assistant", "content": content, "tool_calls": tcs})
            for tc in tcs:
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "content": "<toolcall_result>OK: operacja wykonana poprawnie.</toolcall_result>"})
            continue
        if len(content.strip()) < 200:
            return False, f"tura{t+1} ({dt:.0f}s): odpowiedz za krotka ({len(content)} znakow)"
        if content.count("```") % 2 != 0:
            return False, f"tura{t+1} ({dt:.0f}s): urwany blok kodu ({len(content)} znakow)"
        msgs.append({"role": "assistant", "content": content})
        print(f"    tura{t+1}: {dt:.0f}s, {len(content)} znakow", flush=True)

    return True, "tury: " + ", ".join(f"{d:.0f}s" for d in durations)


def main() -> int:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    turns = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    pace = float(sys.argv[3]) if len(sys.argv) > 3 else 25.0
    print(f"START: target={target} tur/sesje={turns} odstep miedzy sesjami={pace:.0f}s", flush=True)
    streak = 0
    attempt = 0
    while streak < target and attempt < target + 5:
        attempt += 1
        ok, info = run_session(attempt, turns)
        if ok:
            streak += 1
            print(f"[sesja {attempt:02d}] OK   streak={streak}/{target} | {info}", flush=True)
        else:
            streak = 0
            print(f"[sesja {attempt:02d}] FAIL streak=0 | {info}", flush=True)
        if streak < target:
            time.sleep(pace)
    print(f"\nWYNIK DLUGICH SESJI: streak={streak}/{target} po {attempt} sesjach")
    return 0 if streak >= target else 1


if __name__ == "__main__":
    sys.exit(main())
