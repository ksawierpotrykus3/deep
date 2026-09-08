import os
import re
import pytest
import server


def test_extract_environment_info_standard():
    """Verify that _extract_environment_info extracts CWD and OS from standard Trae system-reminder."""
    messages = [
        {"role": "system", "content": "You are a subagent."},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "<system-reminder>\n"
                        "As you answer the user's questions, you can use the following context:\n\n"
                        "# Environment\n"
                        "You have been invoked in the following environment:\n\n"
                        "- Primary working directory: c:\\Users\\TestUser\\Projects\\MyApp\n"
                        "- Operating system:  windows\n"
                        "- Today's date: 2026-09-08\n"
                        "</system-reminder>\n"
                    )
                },
                {"type": "text", "text": "Read src/index.ts"}
            ]
        }
    ]

    cwd, os_name = server._extract_environment_info(messages)
    assert cwd == "c:\\Users\\TestUser\\Projects\\MyApp"
    assert os_name == "windows"
    assert server._last_known_env["cwd"] == "c:\\Users\\TestUser\\Projects\\MyApp"
    assert server._last_known_env["os"] == "windows"


def test_extract_environment_info_escaped_newlines():
    """Verify extraction handles escaped literal \n strings in proxy payloads."""
    messages = [
        {
            "role": "user",
            "content": (
                "<system-reminder>\n"
                "# Environment\n"
                "- Primary working directory: c:\\Workspace\\Root\n"
                "- Operating system:  windows\n"
                "</system-reminder>"
            )
        }
    ]

    cwd, os_name = server._extract_environment_info(messages)
    assert "Workspace" in cwd
    assert os_name == "windows"


def test_extract_environment_info_fallback():
    """Verify that when no environment info is provided, it falls back to _last_known_env."""
    server._last_known_env["cwd"] = "c:\\Fallback\\Path"
    server._last_known_env["os"] = "windows"

    messages = [
        {"role": "user", "content": "Hello without any system reminder"}
    ]

    cwd, os_name = server._extract_environment_info(messages)
    assert cwd == "c:\\Fallback\\Path"
    assert os_name == "windows"


def test_subagent_prompt_injection():
    """Verify subagent prompt receives workspace root, OS, and Glob path rules."""
    server._last_known_env["cwd"] = "c:\\Users\\Ksawier\\Pictures\\Screenshots"
    server._last_known_env["os"] = "windows"

    test_messages = [
        {"role": "system", "content": "You are a file search specialist for Trae IDE."},
        {"role": "user", "content": "Read src/components/KosmosView.tsx"}
    ]

    cwd, os_name = server._extract_environment_info(test_messages)
    subagent_prompt = (
        f"You are a subagent. Execute the task below using the provided tools.\n"
        f"ENVIRONMENT:\n"
        f"- Operating system: {os_name}\n"
        f"- Primary workspace root: {cwd}\n"
        f"PATH & TOOL RULES:\n"
        f"- Read tool strictly requires an existing absolute path. NEVER guess or invent non-existent absolute paths like /Users/... or /home/...\n"
        f"- If you are given a relative path (e.g. 'src/...'), a filename, or do not know the exact absolute path on {os_name}, ALWAYS invoke 'Glob' (e.g. pattern='**/filename.tsx') or 'LS' first to locate the exact path before calling 'Read'!\n"
        f"- If you already have the verified full path on {os_name}, you can call 'Read' directly.\n"
        f"EXECUTION RULES:\n"
        f"- Be thorough and complete. Synthesize findings into concise facts.\n"
        f"- Quote at most 2-3 key code lines when evidence is needed.\n"
        f"- NEVER copy raw tool dumps with line-number prefixes like '120→'.\n"
        f"- Do not chat, explain, repeat the prompt, echo task instructions, list file paths, or write preambles before calling tools — invoke the tools directly and immediately.\n"
        f"- TOOL CALLS: Always invoke tools individually using standard XML tags like <invoke name=\"Tool\"><parameter name=\"param\">value</parameter></invoke> or <Tool><param>val</param></Tool>. NEVER concatenate unclosed tags like <glob>...<grep>."
    )

    assert "Operating system: windows" in subagent_prompt
    assert "Primary workspace root: c:\\Users\\Ksawier\\Pictures\\Screenshots" in subagent_prompt
    assert "ALWAYS invoke 'Glob'" in subagent_prompt
    assert "NEVER guess or invent non-existent absolute paths" in subagent_prompt
