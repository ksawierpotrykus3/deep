# -*- coding: utf-8 -*-
"""Test _build_prompt: czy pelna tresc pierwszej wiadomosci user przetrwa czyszczenie tagow.

Dokonczenie zadania z sesji "Unknown Request" (problem #7): weryfikacja, czy proxy gubi
tresc pierwszej wiadomosci nowego czatu na etapie budowania promptu (czyszczenie
<system-reminder> / <user_input> w _format_msgs / _clean_system_reminders).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

PAYLOAD = "siema pull zrob tego projektu z gita. ' folder Mvp nie src teraz main jest' seior pisze"


def make_msgs_list_content():
    sys_reminder = (
        "<system-reminder>\nThis is a reminder that your todo list is currently empty.\n</system-reminder>"
    )
    env_reminder = (
        "<system-reminder>\nAs you answer the user's questions, you can use the following context:\n"
        "# Environment\n- Primary working directory: c:\\Users\\Ksawier\\Pictures\\Screenshots\n</system-reminder>"
    )
    user_block = "\n<user_input>\n" + PAYLOAD + "\n</user_input>\n\n"
    return [
        {"role": "system", "content": "You are a coding assistant."},
        {"role": "user", "content": [
            {"type": "text", "text": sys_reminder},
            {"type": "text", "text": env_reminder},
            {"type": "text", "text": user_block},
        ]},
    ]


FAKE_TOOLS = [
    {"type": "function", "function": {"name": "Read", "description": "Read a file",
     "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "Grep", "description": "Search",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}},
]


def check(label, prompt, full_ok, tail_ok):
    status = "PASS" if (full_ok and tail_ok) else "FAIL"
    print(f"[{status}] {label}")
    print(f"        prompt_len={len(prompt)}  pelna_tresc={'TAK' if full_ok else 'NIE'}  koncowka('seior pisze')={'TAK' if tail_ok else 'NIE'}")


def main():
    msgs = make_msgs_list_content()
    p1 = server._build_prompt(msgs, tools=FAKE_TOOLS, state={})   # sciezka Trae (tools obecne)
    p2 = server._build_prompt(msgs, tools=None, state={})         # sciezka subagent/resume (strip_reminders=True)
    print("=" * 64)
    print("TEST _build_prompt — pierwsza wiadomosc nowego czatu (content = lista czesci)")
    print("=" * 64)
    check("tools=2 schematy (sciezka Trae)", p1, PAYLOAD in p1, "seior pisze" in p1)
    check("tools=None (subagent/resume)", p2, PAYLOAD in p2, "seior pisze" in p2)
    for label, p in (("tools=TAK", p1), ("tools=NIE", p2)):
        idx = p.find("[User]")
        seg = p[idx:idx + 200] if idx != -1 else "(brak [User] w prompcie!)"
        print(f"\n--- {label}: fragment [User] ---\n{seg}")

    # wariant: content jako zwykly string (nie lista)
    msgs_str = [{"role": "system", "content": "You are a coding assistant."},
                {"role": "user", "content": "\n<user_input>\n" + PAYLOAD + "\n</user_input>\n"}]
    p3 = server._build_prompt(msgs_str, tools=FAKE_TOOLS, state={})
    p4 = server._build_prompt(msgs_str, tools=None, state={})
    print("\n" + "=" * 64)
    print("TEST — wariant content=string")
    print("=" * 64)
    check("content=string, tools=TAK", p3, PAYLOAD in p3, "seior pisze" in p3)
    check("content=string, tools=None", p4, PAYLOAD in p4, "seior pisze" in p4)

    # wariant: wiadomosc zlozona wylacznie z reminderow -> czy giniemy ja calkowicie?
    msgs_empty = [{"role": "system", "content": "You are a coding assistant."},
                  {"role": "user", "content": [
                      {"type": "text", "text": "<system-reminder>\nfoo\n</system-reminder>"},
                      {"type": "text", "text": "<system-reminder>\nbar\n</system-reminder>"},
                  ]}]
    p5 = server._build_prompt(msgs_empty, tools=None, state={})
    lost = "[User]" not in p5
    print(f"\n[{'PASS' if lost else 'FAIL'}] wiadomosc user = same remindery, tools=None -> user usuniety z promptu: {'TAK (zgodnie z logika)' if lost else 'NIE'}")


if __name__ == "__main__":
    main()
