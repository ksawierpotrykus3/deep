"""document_attachment_service.py — Document Attachment Strategy & Token Sanitizer.

Converts oversized prompt components (massive tool execution results, project rules,
or prior conversation history exceeding DeepSeek Web per-request limits) into native
semantically-named text/markdown file attachments (e.g. tool_result_{id}.md,
project_rules.md, conversation_history.md), eliminating multi-part chunking delays,
truncation, and prompt clutter.

Also provides token sanitization to protect against DeepSeek WAF bans triggered by
raw tokenizer control tokens (<｜...｜> / DSML).
"""

from __future__ import annotations

import re
from typing import TypedDict


# DeepSeek Web Chat official attachment limits: "Max 50, 100MB each"
MAX_DOCUMENT_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB (104,857,600 bytes)
MAX_ATTACHMENTS_PER_REQUEST = 50

# Threshold of prompt length to trigger attachment extraction
PROMPT_ATTACHMENT_THRESHOLD = 35_000

# Minimum tool result content length to extract into an attachment
MIN_TOOL_RESULT_FOR_ATTACHMENT = 2_000

# Minimum rules block length to extract into project_rules.md
MIN_RULES_SIZE_FOR_ATTACHMENT = 2_000

# Minimum history section length to extract into conversation_history.md
MIN_HISTORY_SIZE_FOR_ATTACHMENT = 3_000


class DocumentAttachment(TypedDict):
    filename: str
    data: bytes
    mime_type: str


_TOOL_RESULT_BLOCK_RE = re.compile(
    r"<tool_result\b[^>]*>.*?</tool_result\s*>",
    re.DOTALL | re.IGNORECASE,
)
_ID_RE = re.compile(r"<id>\s*([^<]+?)\s*</id>", re.IGNORECASE)
_CONTENT_RE = re.compile(r"(<content>)(.*?)(</content>)", re.DOTALL | re.IGNORECASE)

_RULES_BLOCK_RE = re.compile(
    r"(<rules\b[^>]*>)(.*?)(</rules\s*>)",
    re.DOTALL | re.IGNORECASE,
)
_WORKSPACE_RULES_RE = re.compile(
    r"(<always_applied_workspace_rules\b[^>]*>)(.*?)(</always_applied_workspace_rules\s*>)",
    re.DOTALL | re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# DSML & Token Sanitization (Prevents WAF Bans)
# ─────────────────────────────────────────────────────────────────────────────
# Raw fullwidth tokens used by DeepSeek tokenizer internally.
# Sending these via Web chat triggers WAF prompt-injection heuristic.
_DSML_RAW_TOKEN_RE = re.compile(r"<[｜|]{1,2}(?:DSML|TOOL|pad|begin|end)[^>]*[｜|]{1,2}>", re.IGNORECASE)
_SPECIAL_TOKEN_RE = re.compile(r"<[｜|][^>]+[｜|]>")


def sanitize_system_tokens(text: str) -> str:
    """Sanitize raw tokenizer tokens and malformed DSML tags before sending to DeepSeek Web.

    Neutralizes internal tokens like <｜tool call begin｜> or <｜｜DSML｜｜> so they appear
    as safe natural text or clean XML to DeepSeek's Web WAF firewall, preventing account mutes.
    """
    if not text or ("｜" not in text and "<|" not in text):
        return text

    # Replace malformed <｜｜DSML｜｜ calls> or standalone <｜｜DSML｜｜> with clean <tool_calls> / <invoke>
    text = re.sub(r"<[｜|]{1,2}DSML[｜|]{1,2}\s*calls?>", "<tool_calls>", text, flags=re.IGNORECASE)
    text = re.sub(r"</[｜|]{1,2}DSML[｜|]{1,2}\s*calls?>", "</tool_calls>", text, flags=re.IGNORECASE)
    text = re.sub(r"<[｜|]{1,2}DSML[｜|]{1,2}\s*>", "<invoke name=\"action\">", text, flags=re.IGNORECASE)
    text = re.sub(r"</[｜|]{1,2}DSML[｜|]{1,2}\s*>", "</invoke>", text, flags=re.IGNORECASE)

    # Neutralize any remaining raw tokenizer control sequences <｜...｜> to escaped brackets [token: ...]
    def _escape_token(match: re.Match) -> str:
        inner = match.group(0).replace("｜", "").replace("|", "").strip("<>")
        return f"[token: {inner}]"

    text = _SPECIAL_TOKEN_RE.sub(_escape_token, text)
    return text


def _split_bytes_to_chunks(data: bytes, chunk_size: int = MAX_DOCUMENT_SIZE_BYTES) -> list[bytes]:
    """Split bytes payload into chunks not exceeding chunk_size (up to 100 MB each)."""
    if len(data) <= chunk_size:
        return [data]
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


def extract_oversized_blocks_to_attachments(
    prompt: str,
    threshold: int = PROMPT_ATTACHMENT_THRESHOLD,
    max_file_size: int = MAX_DOCUMENT_SIZE_BYTES,
    min_tool_result_size: int = MIN_TOOL_RESULT_FOR_ATTACHMENT,
    min_rules_size: int = MIN_RULES_SIZE_FOR_ATTACHMENT,
    min_history_size: int = MIN_HISTORY_SIZE_FOR_ATTACHMENT,
) -> tuple[str, list[DocumentAttachment]]:
    """Inspect prompt for oversized tool results, project rules, or conversation history.
    Extracts them into clean, semantically named DocumentAttachment objects (e.g.
    tool_result_{call_id}.md, project_rules.md, conversation_history.md).

    Returns:
        tuple[str, list[DocumentAttachment]]: The modified lean prompt and the list of attachments.
    """
    if not prompt or len(prompt) <= threshold:
        return prompt, []

    attachments: list[DocumentAttachment] = []
    current_prompt = prompt

    # ─────────────────────────────────────────────────────────────────────────
    # 1. First pass: extract oversized <tool_result> blocks
    # ─────────────────────────────────────────────────────────────────────────
    def _replace_tool_result(match: re.Match) -> str:
        nonlocal attachments
        if len(attachments) >= MAX_ATTACHMENTS_PER_REQUEST:
            return match.group(0)

        full_block = match.group(0)
        content_match = _CONTENT_RE.search(full_block)
        if not content_match:
            return full_block

        body = content_match.group(2)
        if len(body) < min_tool_result_size:
            return full_block

        id_match = _ID_RE.search(full_block)
        raw_call_id = id_match.group(1).strip() if id_match else "result"
        call_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_call_id)[:40]
        body_bytes = body.strip().encode("utf-8")

        byte_chunks = _split_bytes_to_chunks(body_bytes, chunk_size=max_file_size)
        file_references = []

        if len(byte_chunks) == 1:
            fname = f"tool_result_{call_id}.md"
            attachments.append({
                "filename": fname,
                "data": byte_chunks[0],
                "mime_type": "text/markdown",
            })
            file_references.append(fname)
        else:
            for p_idx, p_bytes in enumerate(byte_chunks):
                if len(attachments) >= MAX_ATTACHMENTS_PER_REQUEST:
                    break
                fname = f"tool_result_{call_id}_part{p_idx + 1}.md"
                attachments.append({
                    "filename": fname,
                    "data": p_bytes,
                    "mime_type": "text/markdown",
                })
                file_references.append(fname)

        ref_str = ", ".join(file_references)
        replacement_content = f"<content>\n[Full output provided in attached document(s): {ref_str}]\n</content>"
        return full_block[:content_match.start()] + replacement_content + full_block[content_match.end():]

    current_prompt = _TOOL_RESULT_BLOCK_RE.sub(_replace_tool_result, current_prompt)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Second pass: extract oversized project rules into project_rules.md
    # ─────────────────────────────────────────────────────────────────────────
    if len(current_prompt) > threshold and len(attachments) < MAX_ATTACHMENTS_PER_REQUEST:
        def _replace_rules_block(match: re.Match) -> str:
            nonlocal attachments
            if len(attachments) >= MAX_ATTACHMENTS_PER_REQUEST:
                return match.group(0)

            open_tag = match.group(1)
            rules_body = match.group(2)
            close_tag = match.group(3)

            if len(rules_body) < min_rules_size:
                return match.group(0)

            rules_bytes = rules_body.strip().encode("utf-8")
            byte_chunks = _split_bytes_to_chunks(rules_bytes, chunk_size=max_file_size)
            file_references = []

            for p_idx, p_bytes in enumerate(byte_chunks):
                if len(attachments) >= MAX_ATTACHMENTS_PER_REQUEST:
                    break
                fname = f"project_rules_part{p_idx + 1}.md" if len(byte_chunks) > 1 else "project_rules.md"
                attachments.append({
                    "filename": fname,
                    "data": p_bytes,
                    "mime_type": "text/markdown",
                })
                file_references.append(fname)

            ref_str = ", ".join(file_references)
            return (
                f"{open_tag}\n"
                f"[Project rules and coding instructions provided in attached document(s): {ref_str}. "
                f"Strictly adhere to all guidelines defined in the document.]\n"
                f"{close_tag}"
            )

        # Check <always_applied_workspace_rules> first
        current_prompt = _WORKSPACE_RULES_RE.sub(_replace_rules_block, current_prompt)
        # Check <rules> if still oversized
        if len(current_prompt) > threshold:
            current_prompt = _RULES_BLOCK_RE.sub(_replace_rules_block, current_prompt)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Third pass: extract prior conversation history into conversation_history.md
    # ─────────────────────────────────────────────────────────────────────────
    if len(current_prompt) > threshold and len(attachments) < MAX_ATTACHMENTS_PER_REQUEST:
        asst_idx = current_prompt.find("[Assistant]:")
        last_user_idx = current_prompt.rfind("[User]:")

        if asst_idx != -1 and last_user_idx != -1 and last_user_idx > asst_idx:
            history_section = current_prompt[asst_idx:last_user_idx].strip()
            if len(history_section) >= min_history_size:
                hist_bytes = (
                    f"# Previous Conversation History\n\n{history_section}\n"
                ).encode("utf-8")
                byte_chunks = _split_bytes_to_chunks(hist_bytes, chunk_size=max_file_size)

                file_references = []
                for p_idx, p_bytes in enumerate(byte_chunks):
                    if len(attachments) >= MAX_ATTACHMENTS_PER_REQUEST:
                        break
                    fname = (
                        f"conversation_history_part{p_idx + 1}.md"
                        if len(byte_chunks) > 1
                        else "conversation_history.md"
                    )
                    attachments.append({
                        "filename": fname,
                        "data": p_bytes,
                        "mime_type": "text/markdown",
                    })
                    file_references.append(fname)

                ref_str = ", ".join(file_references)
                replacement_history = (
                    f"[Prior conversation history is provided in attached document(s): {ref_str}]\n\n"
                )
                current_prompt = (
                    current_prompt[:asst_idx]
                    + replacement_history
                    + current_prompt[last_user_idx:]
                )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Final fallback pass: if prompt is STILL oversized
    # ─────────────────────────────────────────────────────────────────────────
    if len(current_prompt) > threshold and len(attachments) < MAX_ATTACHMENTS_PER_REQUEST:
        keep_chars = min(15_000, threshold // 2)
        preamble = current_prompt[:keep_chars]
        remainder = current_prompt[keep_chars:]
        rem_bytes = remainder.encode("utf-8")
        byte_chunks = _split_bytes_to_chunks(rem_bytes, chunk_size=max_file_size)

        file_references = []
        for p_idx, p_bytes in enumerate(byte_chunks):
            if len(attachments) >= MAX_ATTACHMENTS_PER_REQUEST:
                break
            fname = f"context_payload_part{p_idx + 1}.md" if len(byte_chunks) > 1 else "context_payload.md"
            attachments.append({
                "filename": fname,
                "data": p_bytes,
                "mime_type": "text/markdown",
            })
            file_references.append(fname)

        ref_str = ", ".join(file_references)
        current_prompt = (
            f"{preamble}\n\n"
            f"[SYSTEM NOTE: The remaining context ({len(remainder)} chars) is attached in referenced document(s): {ref_str}. "
            f"Please review the attached documents to fulfill the request.]"
        )

    return current_prompt, attachments


def format_history_to_markdown(history: list[dict]) -> str:
    """Formats a list of history turns into a comprehensive, readable Markdown log."""
    total_turns = len(history)
    formatted_turns: list[str] = []

    for idx, m in enumerate(history, 1):
        role = m.get("role", "unknown").capitalize()
        content = str(m.get("content", "") or "").strip()
        tool_calls = m.get("tool_calls", [])
        tool_name = m.get("name", "")
        is_recent = (idx > total_turns - 15)

        if not is_recent and len(content) > 400:
            content = content[:400] + "... [truncated for brevity]"

        t_lines = [f"## Turn {idx} - {role}" + (f" ({tool_name})" if tool_name else "")]

        if tool_calls:
            t_lines.append("### Tool Calls:")
            for tc in tool_calls:
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                fname = func.get("name") or tc.get("name", "tool")
                fargs = func.get("arguments") or tc.get("arguments", "")
                if not is_recent and len(fargs) > 250:
                    fargs = fargs[:250] + "... [truncated for brevity]"
                call_id = tc.get("id") or tc.get("tool_call_id", "")
                id_str = f" [id: {call_id}]" if call_id else ""
                t_lines.append(f"- **{fname}**{id_str}:\n```json\n{fargs}\n```")

        if content:
            t_lines.append(content)

        t_lines.append("\n---\n")
        formatted_turns.append("\n".join(t_lines))

    header = "# Full Conversation History from IDE\n\n"
    return header + "".join(formatted_turns)
