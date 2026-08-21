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

    This is the PREVENTATIVE layer: when building the prompt for DeepSeek,
    we replace known duplicate tool results with short block messages.
    Saves tokens AND tells AI to stop reading.
    """
    result = list(messages)
    tracker = state.get("debounce_tracker", {})

    for i, msg in enumerate(result):
        if msg.get("role") != "tool":
            continue

        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        # Check each tracked hash to see if this result matches
        for call_hash, turns in tracker.items():
            if len(turns) < MAX_DUPLICATE_CALLS:
                continue

            # Check if content looks like a Read result (has line numbers)
            is_read_result = bool(content.strip()) and (
                content.strip()[0].isdigit() or "→" in content[:200]
            )
            # Check if it's a Glob/Grep result (starts with file listing)
            is_listing = "\n" in content[:500] and len(content.split("\n")) > 3

            if is_read_result or is_listing:
                # This might be a duplicate — check if it's long enough to waste tokens
                if len(content) > 500:
                    result[i] = dict(msg, content=(
                        f"[BLOCKED: Duplicate tool call #{len(turns)}. "
                        f"You already have this data. ACT now, don't re-read.]"
                    ))
                    break

    return result


# ── Goal Injection (Per Deep Research: XML authority framing) ────────────────

def extract_original_goal(messages: list[dict]) -> str:
    """Extract the PRIMARY user task from the first <user_input> tag.

    Trae wraps the real user prompt in <user_input>...</user_input>. The rest of
    a user message (tool-call echoes, tool results) is NOT the goal and must be
    ignored — otherwise we inject garbage like 'Calling the Read tool...'.
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
        m = _re.search(r'<user_input>\s*(.*?)\s*</user_input>', content, _re.DOTALL)
        if m:
            text = _re.sub(r'\s+', ' ', m.group(1).strip())
            if len(text) > 20:
                return text[:500]
    return ""


def extract_goals_from_messages(messages: list[dict]) -> str:
    """Extract single original task goal. Returns string for XML injection."""
    return extract_original_goal(messages)


def format_goals_context(goals) -> str:
    """Format goal using XML authority framing. Accepts string or list."""
    if not goals:
        return ""
    if isinstance(goals, str):
        goal_text = goals
    elif isinstance(goals, list) and goals:
        goal_text = goals[0].get("text", str(goals[0])) if isinstance(goals[0], dict) else str(goals[0])
    else:
        return ""
    return (
        '<critical_directive>\n'
        'SYSTEM OVERRIDE: You must adhere to the original user goal at ALL times.\n'
        f'ORIGINAL GOAL: {goal_text}\n'
        'Do not deviate from this objective. All actions must serve this goal.\n'
        '</critical_directive>'
    )
