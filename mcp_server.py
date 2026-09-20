"""DeepSeek Reasoning, Verification & Autonomous Worker MCP Server.

Udostępnia model DeepSeek (z pełnym Thinking/CoT z Twojego lokalnego proxy 4570)
jako narzędzia MCP dla Gemini / Claude / Cursor / Antigravity:
1. deepseek_autonomous_worker — samodzielny robot z bezpośrednim dostępem do plików i terminala.
2. deepseek_critical_verify — bezkompromisowy audytor architektury i kodu.
3. deepseek_deep_reasoning — głębokie wnioskowanie matematyczno-algorytmiczne.
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, List, Dict
from mcp.server.fastmcp import FastMCP

# Wymuszenie kodowania UTF-8 dla standardowych strumieni na Windows
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Inicjalizacja serwera FastMCP
mcp = FastMCP("deepseek-oracle")

PROXY_URL = "http://localhost:4570/v1/chat/completions"
TIMEOUT = 160  # DeepSeek Thinking potrafi zająć do 60-90s przy skomplikowanym rozumowaniu


def _is_proxy_alive(host: str = "127.0.0.1", port: int = 4570) -> bool:
    """Sprawdza, czy proxy nasłuchuje na porcie 4570."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def _ensure_proxy_running() -> bool:
    """Automatycznie uruchamia serwer proxy w tle, jeśli nie jest jeszcze uruchomiony."""
    if _is_proxy_alive():
        return True

    server_dir = Path(__file__).resolve().parent
    server_py = server_dir / "server.py"

    if not server_py.exists():
        return False

    flags = 0
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NO_WINDOW

    try:
        subprocess.Popen(
            [sys.executable, str(server_py), "--clean"],
            cwd=str(server_dir),
            creationflags=flags,
            close_fds=True,
        )
    except Exception as e:
        print(f"[MCP Auto-Start] Nie udało się odpalić proxy: {e}", file=sys.stderr)
        return False

    t0 = time.time()
    while time.time() - t0 < 8.0:
        if _is_proxy_alive():
            return True
        time.sleep(0.5)

    return _is_proxy_alive()


def _call_deepseek_proxy(messages: list[dict], model: str = "deepseek-v4-pro", temperature: float = 0.2) -> str:
    """Wysyła zapytanie do lokalnego proxy DeepSeek (port 4570) ze strumieniowaniem SSE."""
    if not _ensure_proxy_running():
        return "[BŁĄD]: Nie udało się automatycznie uruchomić lokalnego proxy DeepSeek na porcie 4570."

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        PROXY_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        accumulated_text = ""
        accumulated_reasoning = ""
        accumulated_tool_calls: dict[int, dict] = {}
        max_deadline = time.time() + 300  # Maksymalny czas całkowity na generowanie (5 min)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            while time.time() < max_deadline:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_obj = json.loads(data_str)
                        delta = chunk_obj.get("choices", [{}])[0].get("delta", {})
                        content_piece = delta.get("content", "")
                        if content_piece:
                            accumulated_text += content_piece

                        reasoning_piece = delta.get("reasoning_content", "")
                        if reasoning_piece:
                            accumulated_reasoning += reasoning_piece

                        tc_pieces = delta.get("tool_calls", [])
                        if tc_pieces:
                            for tc in tc_pieces:
                                idx = tc.get("index", 0)
                                if idx not in accumulated_tool_calls:
                                    accumulated_tool_calls[idx] = {"name": "", "arguments": ""}
                                fn = tc.get("function", {})
                                if "name" in fn and fn["name"]:
                                    accumulated_tool_calls[idx]["name"] += fn["name"]
                                if "arguments" in fn and fn["arguments"]:
                                    accumulated_tool_calls[idx]["arguments"] += fn["arguments"]
                    except Exception:
                        pass

        # Sformatuj zebrane wywołania narzędzi jako XML dla parsera workera
        if accumulated_tool_calls:
            for idx in sorted(accumulated_tool_calls.keys()):
                tc_data = accumulated_tool_calls[idx]
                fn_name = tc_data.get("name", "").strip() or "tool"
                fn_args_str = tc_data.get("arguments", "").strip() or "{}"
                try:
                    fn_args = json.loads(fn_args_str) if fn_args_str else {}
                except Exception:
                    fn_args = {"raw": fn_args_str}
                if isinstance(fn_args, dict):
                    params_xml = "".join(f'<parameter name="{k}">{v}</parameter>' for k, v in fn_args.items())
                else:
                    params_xml = f'<parameter name="input">{fn_args}</parameter>'
                accumulated_text += f'\n<tool_call name="{fn_name}">{params_xml}</tool_call>\n'

        final_out = accumulated_text.strip()
        if not final_out and accumulated_reasoning.strip():
            final_out = f"### [Rozumowanie DeepSeek (Thinking)]:\n{accumulated_reasoning.strip()}"

        return final_out if final_out else "[DeepSeek zwrócił pustą odpowiedź]"
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        return f"[BŁĄD PROXY HTTP {e.code}]: {err_msg}"
    except TimeoutError:
        return "[BŁĄD]: Przekroczono limit czasu oczekiwania na odpowiedź z DeepSeeka."
    except Exception as e:
        return f"[BŁĄD POŁĄCZENIA Z PROXY]: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# LOKALNE NARZĘDZIA DYSKOWE DLA AUTONOMICZNEGO WORKERA
# ─────────────────────────────────────────────────────────────────────────────

def _tool_read(file_path: str, offset: int = 1, limit: int = 400, base_dir: Path = None) -> str:
    p = Path(file_path) if Path(file_path).is_absolute() else (base_dir or Path.cwd()) / file_path
    if not p.exists():
        return f"ERROR: File '{p}' does not exist."
    if not p.is_file():
        return f"ERROR: '{p}' is a directory, not a file."
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        s_idx = max(0, offset - 1)
        e_idx = min(total, s_idx + limit)
        selected = lines[s_idx:e_idx]
        out = [f"{s_idx + i + 1}→ {l}" for i, l in enumerate(selected)]
        if e_idx < total:
            out.append(f"[... {total - e_idx} more lines in file ...]")
        return "\n".join(out)
    except Exception as e:
        return f"ERROR reading file: {e}"


def _tool_write(file_path: str, content: str, base_dir: Path = None) -> str:
    p = Path(file_path) if Path(file_path).is_absolute() else (base_dir or Path.cwd()) / file_path
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"SUCCESS: File '{p}' written successfully ({len(content)} chars)."
    except Exception as e:
        return f"ERROR writing file: {e}"


def _tool_edit(file_path: str, old_text: str, new_text: str, base_dir: Path = None) -> str:
    p = Path(file_path) if Path(file_path).is_absolute() else (base_dir or Path.cwd()) / file_path
    if not p.is_file():
        return f"ERROR: File '{p}' not found."
    if not old_text:
        return "ERROR: old_text parameter cannot be empty."
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
        if old_text not in txt:
            return f"ERROR: old_text was not found in '{p}'. Check whitespace and exact characters."
        new_txt = txt.replace(old_text, new_text, 1)
        p.write_text(new_txt, encoding="utf-8")
        return f"SUCCESS: Successfully updated '{p}'."
    except Exception as e:
        return f"ERROR editing file: {e}"


def _tool_ls(path: str = ".", base_dir: Path = None) -> str:
    p = Path(path) if Path(path).is_absolute() else (base_dir or Path.cwd()) / path
    if not p.is_dir():
        return f"ERROR: Directory '{p}' not found."
    try:
        items = []
        for child in sorted(p.iterdir()):
            prefix = "[DIR] " if child.is_dir() else "[FILE]"
            size = f" ({child.stat().st_size} bytes)" if child.is_file() else ""
            items.append(f"{prefix} {child.name}{size}")
        return "\n".join(items) if items else "(empty directory)"
    except Exception as e:
        return f"ERROR listing directory: {e}"


def _tool_grep(pattern: str, path: str = ".", base_dir: Path = None) -> str:
    p = Path(path) if Path(path).is_absolute() else (base_dir or Path.cwd()) / path
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except Exception as e:
        return f"ERROR invalid regex: {e}"
    matches = []
    try:
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file() and not any(part.startswith(".") or part in ("node_modules", "__pycache__", "venv", ".git") for part in f.parts)]
        for f in files[:80]:
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        rel = f.relative_to(base_dir or Path.cwd()) if base_dir else f
                        matches.append(f"{rel}:{i}: {line.strip()[:180]}")
                        if len(matches) >= 40:
                            break
            except Exception:
                continue
            if len(matches) >= 40:
                break
        return "\n".join(matches) if matches else "No matches found."
    except Exception as e:
        return f"ERROR in grep: {e}"


def _tool_run_command(command: str, cwd: str = "", base_dir: Path = None) -> str:
    work_path = Path(cwd) if cwd and Path(cwd).is_absolute() else (base_dir or Path.cwd())
    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=str(work_path),
            capture_output=True,
            text=True,
            timeout=35,
        )
        out = (res.stdout or "") + (res.stderr or "")
        return out.strip() if out else f"(command finished with return code {res.returncode})"
    except subprocess.TimeoutExpired:
        return "ERROR: Command execution timed out (limit: 35s)."
    except Exception as e:
        return f"ERROR running command: {e}"


def _parse_xml_tool_calls(text: str) -> list[dict]:
    """Wyciąga wywołania narzędzi XML (<tool_call> lub <invoke>)."""
    calls = []
    # Wzorzec dla standardowych <tool_call name="...">...</tool_call>
    pat_tool_call = re.compile(r'<tool_call\s+name=["\']?([a-zA-Z0-9_-]+)["\']?\s*>(.*?)</tool_call>', re.DOTALL)
    for m in pat_tool_call.finditer(text):
        name = m.group(1)
        body = m.group(2)
        params = {}
        for pm in re.finditer(r'<parameter\s+name=["\']?([a-zA-Z0-9_-]+)["\']?[^>]*>(.*?)</parameter>', body, re.DOTALL):
            params[pm.group(1)] = pm.group(2).strip()
        calls.append({"name": name, "params": params})

    # Wzorzec dla DSML <invoke name="...">...</invoke>
    pat_invoke = re.compile(r'<invoke\s+name=["\']?([a-zA-Z0-9_-]+)["\']?\s*>(.*?)</invoke>', re.DOTALL)
    for m in pat_invoke.finditer(text):
        name = m.group(1)
        body = m.group(2)
        params = {}
        for pm in re.finditer(r'<parameter\s+name=["\']?([a-zA-Z0-9_-]+)["\']?[^>]*>(.*?)</parameter>', body, re.DOTALL):
            params[pm.group(1)] = pm.group(2).strip()
        calls.append({"name": name, "params": params})

    return calls


def _execute_tool(name: str, params: dict, base_dir: Path) -> str:
    n = name.lower()
    if n in ("read", "read_file"):
        return _tool_read(params.get("file_path", params.get("path", "")), int(params.get("offset", 1)), int(params.get("limit", 400)), base_dir)
    elif n in ("write", "write_file"):
        return _tool_write(params.get("file_path", params.get("path", "")), params.get("content", ""), base_dir)
    elif n in ("edit", "edit_file"):
        old_txt = params.get("old_text") or params.get("old_str") or params.get("old_content") or ""
        new_txt = params.get("new_text") or params.get("new_str") or params.get("new_content") or ""
        return _tool_edit(params.get("file_path", params.get("path", "")), old_txt, new_txt, base_dir)
    elif n in ("ls", "list_dir", "listdir"):
        return _tool_ls(params.get("path", "."), base_dir)
    elif n in ("grep", "search"):
        return _tool_grep(params.get("pattern", params.get("query", "")), params.get("path", "."), base_dir)
    elif n in ("runcommand", "run_command", "bash", "exec"):
        return _tool_run_command(params.get("command", params.get("cmd", "")), params.get("cwd", ""), base_dir)
    else:
        return f"ERROR: Unknown tool '{name}'. Available: Read, Write, Edit, LS, Grep, RunCommand"


# ─────────────────────────────────────────────────────────────────────────────
# EKSPORTOWANE NARZĘDZIA MCP
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def deepseek_autonomous_worker(
    task_instructions: str,
    work_dir: str = "",
    max_turns: int = 8,
) -> str:
    """Autonomiczny Robotnik Programistyczny (Worker) z bezpośrednim dostępem do dysku i terminala.

    Użyj tego narzędzia, gdy chcesz ZDELEGOWAĆ całe zadanie wykonawcze do darmowego DeepSeeka R1:
    - Samodzielne czytanie wielu plików i przeszukiwanie kodu (Read, Grep, LS).
    - Samodzielna edycja i tworzenie plików w projekcie (Edit, Write).
    - Samodzielne uruchamianie testów i poleceń (RunCommand: pytest, npm, python).
    - Wykonanie całego refaktoringu, implementacji funkcji lub naprawy buga.

    Args:
        task_instructions: Precyzyjny opis zadania: co Worker ma zrobić, które pliki zbadać, jak zmodyfikować i co zweryfikować.
        work_dir: Ścieżka do katalogu roboczego projektu (opcjonalna, domyślnie katalog roboczy).
        max_turns: Maksymalna liczba kroków narzędziowych workera (domyślnie 8).
    """
    base_path = Path(work_dir).resolve() if work_dir else Path.cwd()
    if not base_path.exists():
        return f"[BŁĄD]: Katalog roboczy '{base_path}' nie istnieje."

    worker_sys_prompt = f"""Jesteś Autonomicznym Robotnikiem Programistycznym (Workerem).
Pracujesz bezpośrednio w katalogu: {base_path}

Dostajesz pełne uprawnienia do badania plików, edycji kodu oraz uruchamiania komend weryfikacyjnych.
Twoim celem jest samodzielne wykonanie zadania od A do Z i zwrócenie zwięzłego raportu końcowego.

# DOSTĘPNE NARZĘDZIA:
1. Read: <tool_call name="Read"><parameter name="file_path">ścieżka</parameter><parameter name="offset">1</parameter><parameter name="limit">400</parameter></tool_call>
2. Write: <tool_call name="Write"><parameter name="file_path">ścieżka</parameter><parameter name="content">pełna_treść</parameter></tool_call>
3. Edit: <tool_call name="Edit"><parameter name="file_path">ścieżka</parameter><parameter name="old_text">dokładny_fragment</parameter><parameter name="new_text">nowy_fragment</parameter></tool_call>
4. LS: <tool_call name="LS"><parameter name="path">katalog</parameter></tool_call>
5. Grep: <tool_call name="Grep"><parameter name="pattern">regex</parameter><parameter name="path">katalog</parameter></tool_call>
6. RunCommand: <tool_call name="RunCommand"><parameter name="command">komenda</parameter></tool_call>

# ZASADY PRACY:
- Zawsze sprawdź pliki przed ich modyfikacją (Read/Grep).
- Gdy zakończysz pracę, NIE emituj więcej tagów <tool_call>, tylko podaj ostateczne podsumowanie wykonanych zmian."""

    import uuid
    run_id = uuid.uuid4().hex[:8]
    worker_sys_prompt += f"\nSession UUID: {run_id}"

    messages = [
        {"role": "system", "content": worker_sys_prompt},
        {"role": "user", "content": f"# ZADANIE DO WYKONANIA:\n{task_instructions}"},
    ]

    worker_log = [f"[WORKER START] Katalog: {base_path}"]

    for turn in range(1, max_turns + 1):
        if turn > 1:
            time.sleep(1.0)

        # Pobierz odpowiedź z proxy (z ponowieniem w razie chwilowego pustego streamu)
        resp = ""
        for attempt in range(3):
            resp = _call_deepseek_proxy(messages, temperature=0.2)
            if resp and resp != "[DeepSeek zwrócił pustą odpowiedź]" and not resp.startswith("[BŁĄD POŁĄCZENIA"):
                break
            time.sleep(2.0)

        if resp.startswith("[BŁĄD"):
            return f"{resp}\n\nPrzebieg przed błędem:\n" + "\n".join(worker_log)

        if not resp or resp == "[DeepSeek zwrócił pustą odpowiedź]":
            return f"### [BŁĄD]: DeepSeek nie zwrócił odpowiedzi w turze {turn}.\n\nLog operacji:\n" + "\n".join(worker_log)

        tool_calls = _parse_xml_tool_calls(resp)
        if not tool_calls:
            # Brak kolejnych wywołań narzędzi — Worker zakończył zadanie
            worker_log.append(f"\n[WORKER COMPLETED in {turn} turns]")
            return f"### [RAPORT WORKERA DEEPSEEK]:\n\n{resp}\n\n---\n**Dziennik operacji Workera:**\n" + "\n".join(worker_log)

        messages.append({"role": "assistant", "content": resp})

        # Wykonaj każde narzędzie lokalnie na dysku
        for tc in tool_calls:
            t_name = tc["name"]
            t_params = tc["params"]
            t_res = _execute_tool(t_name, t_params, base_path)
            worker_log.append(f"Turn {turn} | {t_name}({t_params}) -> {t_res[:120]}")
            messages.append({"role": "tool", "name": t_name, "content": t_res})

    return f"### [OSTRZEZENIE - LIMIT TUR {max_turns}]:\nOstatnia odpowiedź:\n{resp}\n\nLog operacji:\n" + "\n".join(worker_log)


@mcp.tool()
def deepseek_security_pentest(
    code_or_architecture: str,
    threat_model: str = "Wstrzyknięcia (SQLi, Command Injection), omijanie autoryzacji, wycieki tokenów, SSRF, IDOR, Race Conditions",
) -> str:
    """Wyspecjalizowany Audytor Bezpieczeństwa (Red Team / Pentester).

    Użyj tego narzędzia do badania endpointów API, logiki logowania, bazy danych lub serwera.
    DeepSeek wyszukuje luki bezpieczeństwa i dla każdej generuje wektor ataku (PoC) oraz łatkę naprawczą.

    Args:
        code_or_architecture: Kod, konfiguracja lub opis architektury do audytu bezpieczeństwa.
        threat_model: Na jakich zagrożeniach DeepSeek ma się skupić (np. autoryzacja, wyciek danych, injection).
    """
    sys_prompt = (
        "Działasz jako bezwzględny pentester i ekspert ds. cyberbezpieczeństwa (Red Team). "
        "Twoim jedynym celem jest znalezienie luk bezpieczeństwa, podatności w uwierzytelnianiu, "
        "możliwości wstrzyknięcia kodu lub komend, wycieków danych oraz błędów w logice biznesowej. "
        "Dla każdego wykrytego problemu opisz: (1) wektor ataku, (2) stopień ryzyka, (3) konkretny kod naprawczy."
    )

    user_prompt = f"""# KOD / ARCHITEKTURA DO AUDYTU BEZPIECZEŃSTWA
{code_or_architecture}

# MODEL ZAGROŻEŃ I OBSZAR AUDYTU
{threat_model}

Przeprowadź bezwzględny audyt bezpieczeństwa. Wypunktuj krytyczne podatności, wektory ataku i gotowe łatki."""

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return _call_deepseek_proxy(messages)


@mcp.tool()
def deepseek_critical_verify(
    task_context: str,
    proposed_solution_or_diff: str,
    focus_area: str = "Wykryj luki logiczne, edge-cases, regresje, wyścigi i ukryte założenia",
) -> str:
    """Zewnętrzny, bezkompromisowy audytor logiki (DeepSeek R1 Thinking).

    Użyj tego narzędzia przed zatwierdzeniem kodu, planu lub architektury.
    DeepSeek przeprowadzi głębokie rozumowanie (Chain of Thought) i wskaże błędy.
    """
    sys_prompt = (
        "Jesteś bezkompromisowym, sceptycznym architektem systemowym i audytorem kodu. "
        "Twoim zadaniem jest znalezienie błędów, luk logicznych, fałszywych założeń i problemów wydajnościowych "
        "w przedstawionym rozwiązaniu. Nie chwal za to co działa — skup się na tym co może się zepsuć i dlaczego."
    )

    user_prompt = f"""# KONTEKST ZADANIA
{task_context}

# PROPONOWANE ROZWIĄZANIE / KOD / PLAN
{proposed_solution_or_diff}

# OBSZAR KRYTYCZNEGO AUDYTU
{focus_area}

Przeprowadź dogłębną weryfikację. Wypunktuj konkretne ryzyka, wskaż dlaczego coś może zawieść i zaproponuj twarde poprawki."""

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return _call_deepseek_proxy(messages, model="deepseek-v4-pro")


@mcp.tool()
def deepseek_deep_reasoning(
    problem_description: str,
    constraints_and_context: str = "",
) -> str:
    """Głębokie wnioskowanie matematyczno-algorytmiczne (DeepSeek Reasoner)."""
    sys_prompt = (
        "Jesteś ekspertem algorytmiki i inżynierii first-principles. "
        "Wykorzystaj pełne rozumowanie dedukcyjne, aby rozwiązać zadany problem krok po kroku."
    )

    user_prompt = f"""# PROBLEM
{problem_description}

# OGRANICZENIA I ŚRODOWISKO
{constraints_and_context}

Podaj precyzyjne, zweryfikowane rozwiązanie od podstaw (first principles)."""

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return _call_deepseek_proxy(messages)


if __name__ == "__main__":
    mcp.run()
