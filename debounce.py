"""
DebounceHook v2 — intercepts duplicate tool calls BEFORE they waste tokens.
Persistent tracking in conv_state, sliding window of 3 turns, max 2 identical calls.

Per Deep Research recommendation:
- Hash tool_name + sorted arguments
- Track in conv_state.json (persistent)
- Sliding window: max 2 identical calls in last 3 turns
- When blocked: return "BLOCKED BY SYSTEM" fake tool result
"""
import hashlib
import json
from typing import Optional

# Sliding window params (per Deep Research)
MAX_DUPLICATE_CALLS = 2
WINDOW_TURNS = 3

# Tools to debounce (read-heavy, token-wasting)
DEBOUNCE_TOOLS = {"Read", "Glob", "Grep", "SearchCodebase", "LS"}


def _hash_tool_call(tool_name: str, arguments: dict) -> str:
    """Deterministic hash from tool name + sorted arguments."""
    serialized = json.dumps(arguments, sort_keys=True)
    return hashlib.md5(f"{tool_name}::{serialized}".encode()).hexdigest()[:16]


def record_tool_call(state: dict, tool_name: str, arguments: dict | str, turn_number: int):
    """
    Record a tool call in conv_state.
    Called after the AI successfully makes a tool call (we yielded it to Trae).
    """
    if tool_name not in DEBOUNCE_TOOLS:
        return

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            arguments = {"raw": arguments}

    call_hash = _hash_tool_call(tool_name, arguments)
    tracker = state.setdefault("debounce_tracker", {})

    if call_hash not in tracker:
        tracker[call_hash] = []
    if turn_number not in tracker[call_hash]:
        tracker[call_hash].append(turn_number)

    # Prune old entries outside window
    tracker[call_hash] = [t for t in tracker[call_hash] if turn_number - t <= WINDOW_TURNS]
    if not tracker[call_hash]:
        del tracker[call_hash]

    # Clean up empty hashes
    empty = [k for k, v in tracker.items() if not v]
    for k in empty:
        del tracker[k]


def is_duplicate_blocked(state: dict, tool_name: str, arguments: dict | str) -> bool:
    """
    Check if this tool call should be blocked.
    Returns True if the same call was already made >= MAX_DUPLICATE_CALLS
    times within the sliding window.
    """
    if tool_name not in DEBOUNCE_TOOLS:
        return False

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            return False

    call_hash = _hash_tool_call(tool_name, arguments)
    tracker = state.get("debounce_tracker", {})
    history = tracker.get(call_hash, [])

    return len(history) >= MAX_DUPLICATE_CALLS


def block_tool_result(tool_name: str, arguments: dict | str) -> dict:
    """
    Generate a fake tool result for a blocked call.
    This tells the AI to STOP re-reading and ACT.
    """
    if isinstance(arguments, str):
        try:
            args_dict = json.loads(arguments)
        except Exception:
            args_dict = {"raw": arguments}
    else:
        args_dict = arguments

    file_path = args_dict.get("file_path", args_dict.get("path", args_dict.get("pattern", "unknown")))
    
    return {
        "content": (
            f"BLOCKED BY SYSTEM PREVENTATIVE MEASURE: Duplicate Tool Call.\n"
            f"Tool: {tool_name}({file_path})\n"
            f"You have already extracted this file's context in the last {WINDOW_TURNS} turns.\n"
            f"Redundant reads are FORBIDDEN. You MUST synthesize the data you have and proceed to write code.\n"
            f"NEXT ACTION REQUIRED: Edit, Write, or use a subagent. Do NOT read this again."
        ),
        "is_error": True,
    }


def deduplicate_tool_results_in_prompt(messages: list[dict], state: dict) -> list[dict]:
    """
    Modify tool RESULT messages that correspond to blocked tool calls.
    Replaces full content with a short "BLOCKED" message to save tokens
    and force the AI to take action.

    Matches specifically by tool_call_id and tool call hash, ensuring
    normal tool results and file reads are never falsely blocked.
    """
    result = list(messages)
    tracker = state.get("debounce_tracker", {})
    if not tracker:
        return result

    # Build mapping from tool_call_id to call_hash from assistant messages
    call_id_to_hash = {}
    for msg in result:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                cid = tc.get("id")
                fn = tc.get("function") or {}
                name = fn.get("name")
                args_raw = fn.get("arguments", "{}")
                if cid and name:
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    except Exception:
                        args = {"raw": args_raw}
                    call_id_to_hash[cid] = _hash_tool_call(name, args)

    for i, msg in enumerate(result):
        if msg.get("role") != "tool":
            continue

        cid = msg.get("tool_call_id")
        call_hash = call_id_to_hash.get(cid)
        if not call_hash:
            continue

        turns = tracker.get(call_hash, [])
        if len(turns) >= MAX_DUPLICATE_CALLS:
            result[i] = dict(msg, content=(
                f"[BLOCKED: Duplicate tool call #{len(turns)}. "
                f"You already have this data. ACT now, don't re-read.]"
            ))

    return result


# ── Goal Injection (Clean Markdown Framing) ──────────────────────────────────

def extract_original_goal(messages: list[dict]) -> str:
    """Extract the PRIMARY user task from the real user input.

    Trae wraps the real user prompt in <user_input>...</user_input>. The rest of
    a user message (system reminders, tool-call echoes) must be ignored.
    """
    import re as _re
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if not isinstance(content, str) or not content.strip():
            continue

        # Usuń najpierw bloki <system-reminder>...</system-reminder> oraz <critical_directive>,
        # aby przypadkowe wystąpienie '<user_input>' wewnątrz instrukcji Trae
        # (np. 'relevant to the <user_input> intent') nie złamało wyrażenia regularnego!
        clean_content = _re.sub(r'<system-reminder>[\s\S]*?</system-reminder>', '', content)
        clean_content = _re.sub(r'<critical_directive>[\s\S]*?</critical_directive>', '', clean_content)

        m = _re.search(r'<user_input>\s*([\s\S]*?)\s*</user_input>', clean_content)
        if m:
            text = _re.sub(r'\s+', ' ', m.group(1).strip())
            if len(text) > 10:
                return text[:500]
        else:
            clean_text = clean_content.strip()
            if len(clean_text) > 10:
                return _re.sub(r'\s+', ' ', clean_text)[:500]
    return ""


def extract_goals_from_messages(messages: list[dict]) -> str:
    """Extract single original task goal. Returns clean string."""
    return extract_original_goal(messages)


def format_goals_context(goals) -> str:
    """Format goal using clean markdown framing without adversarial prompt-injection triggers."""
    if not goals:
        return ""
    if isinstance(goals, str):
        goal_text = goals
    elif isinstance(goals, list) and goals:
        goal_text = goals[0].get("text", str(goals[0])) if isinstance(goals[0], dict) else str(goals[0])
    else:
        return ""
    goal_text = goal_text.strip()
    if not goal_text:
        return ""
    return (
        "## Active User Goal\n"
        f"Primary objective to follow: {goal_text}\n"
    )

