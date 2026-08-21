"""
Conversation tracker — builds a structured summary of what happened.
Instead of raw truncation, this extracts key facts and injects them
during session rotation so the AI doesn't lose context.

Also handles proactive rotation: warns at 45 web chat turns.
"""
import re
import time
import json
from typing import Optional

# ── Proactive Rotation ──────────────────────────────────────────────────────
# Web chat limit is ~50-60 turns. Rotate proactively at 45.
WEB_CHAT_SOFT_LIMIT = 45
WEB_CHAT_HARD_LIMIT = 55


def should_rotate_proactively(msgs_sent: int) -> bool:
    """Check if we're approaching the web chat turn limit."""
    return msgs_sent >= WEB_CHAT_SOFT_LIMIT


def get_rotation_warning(msgs_sent: int) -> str:
    """Get warning text about approaching turn limit."""
    remaining = max(0, WEB_CHAT_HARD_LIMIT - msgs_sent)
    if msgs_sent >= WEB_CHAT_SOFT_LIMIT:
        return (
            f"## WARNING: WEB CHAT TURN LIMIT APPROACHING\n"
            f"You have sent {msgs_sent} messages. The web chat limit is ~{WEB_CHAT_HARD_LIMIT} turns.\n"
            f"~{remaining} turns remaining. Be efficient.\n"
            f"Focus on the most critical actions. Use subagents for research.\n\n"
        )
    return ""


# ── Semantic Summary ──────────────────────────────────────────────────────

def build_conversation_summary(messages: list[dict]) -> str:
    """
    Extract a structured summary from conversation history.
    Used when rotating sessions — the summary preserves context better
    than raw truncation.
    
    Tracks:
    - Files explored/read
    - Files modified/created/deleted
    - Key decisions made
    - Errors encountered
    - Completed and pending tasks
    """
    files_read: set[str] = set()
    files_modified: set[str] = set()
    files_created: set[str] = set()
    files_deleted: set[str] = set()
    decisions: list[str] = []
    errors: list[str] = []
    user_goals: list[str] = []
    
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ).strip()
        if not isinstance(content, str):
            content = ""
        
        if role == "user":
            # Track user goals (simplified — just first sentence)
            clean = re.sub(r'<[^>]+>', ' ', content).strip()
            sentences = re.split(r'[.!?]\s+', clean)
            if sentences and len(sentences[0]) > 20:
                user_goals.append(sentences[0][:200])
        
        elif role == "assistant":
            tc = msg.get("tool_calls", [])
            for call in tc:
                fn = call.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except Exception:
                    args = {}
                
                fp = args.get("file_path", args.get("path", args.get("filePath", "")))
                pattern = args.get("pattern", args.get("regex", ""))
                
                if name in ("Read", "read", "read_file") and fp:
                    files_read.add(fp)
                elif name in ("Glob", "glob", "Grep", "grep", "SearchCodebase"):
                    if fp:
                        files_read.add(fp)
                    if pattern:
                        files_read.add(f"pattern:{pattern}")
                elif name in ("Edit", "edit", "SearchReplace", "Write", "write", "create_file"):
                    if fp:
                        files_modified.add(fp)
                elif name in ("Write", "write", "create_file"):
                    if fp:
                        files_created.add(fp)
                elif name in ("DeleteFile", "delete_file", "delete"):
                    file_paths = args.get("file_paths", [args.get("file_path", "")])
                    if isinstance(file_paths, list):
                        for p in file_paths:
                            files_deleted.add(p)
                    elif file_paths:
                        files_deleted.add(file_paths)
        
        elif role == "tool":
            # Detect errors in tool results
            if any(err in content.lower() for err in ["error", "failed", "exception", "traceback", "denied"]):
                err_snippet = content[:200].strip()
                if err_snippet:
                    errors.append(f"[msg #{i}] {err_snippet}")
    
    # Build summary
    parts = ["## CONVERSATION SUMMARY (auto-generated for session rotation)\n"]
    
    if user_goals:
        parts.append("### User Goals:")
        for g in user_goals[-5:]:  # Last 5 goals
            parts.append(f"- {g}")
        parts.append("")
    
    if files_read:
        parts.append(f"### Files Explored ({len(files_read)}):")
        for f in sorted(files_read)[:20]:
            parts.append(f"- {f}")
        if len(files_read) > 20:
            parts.append(f"- ... and {len(files_read) - 20} more")
        parts.append("")
    
    if files_modified:
        parts.append(f"### Files Modified ({len(files_modified)}):")
        for f in sorted(files_modified)[:20]:
            parts.append(f"- {f}")
        parts.append("")
    
    if files_created:
        parts.append(f"### Files Created ({len(files_created)}):")
        for f in sorted(files_created)[:20]:
            parts.append(f"- {f}")
        parts.append("")
    
    if files_deleted:
        parts.append(f"### Files Deleted ({len(files_deleted)}):")
        for f in sorted(files_deleted)[:20]:
            parts.append(f"- {f}")
        parts.append("")
    
    if errors:
        parts.append(f"### Errors Encountered ({len(errors)}):")
        for e in errors[-5:]:  # Last 5 errors
            parts.append(f"- {e[:200]}")
        parts.append("")
    
    if not any([files_read, files_modified, files_created, files_deleted, errors]):
        return ""  # Nothing worth summarizing
    
    parts.append("Use this summary to continue work without re-exploring files.")
    return "\n".join(parts)
