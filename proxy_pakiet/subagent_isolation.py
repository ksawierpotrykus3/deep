"""
Subagent isolation — dedicated sessions, response caching, Circuit Breaker.
Prevents subagents from cross-contaminating each other and protects
the main agent from stuck subagents.
"""
import time
import hashlib
import json
from typing import Optional

# ── Subagent Cache ──────────────────────────────────────────────────────────
# Stores (result_text, timestamp) keyed by task hash.
# Prevents re-running identical subagent tasks.
_SUBAGENT_CACHE: dict[str, tuple[str, float]] = {}
_MAX_CACHE_ENTRIES = 50
_CACHE_TTL = 300  # 5 minutes

# ── Circuit Breaker ─────────────────────────────────────────────────────────
# Tracks subagent timing. If a subagent takes >45s, log a warning.
# If 3+ subagents in a row fail/timeout, suggest main agent skip them.
_SUBAGENT_TIMEOUT_S = 45
_SUBAGENT_MAX_FAILURES = 3
_subagent_failures: int = 0
_subagent_total: int = 0
_subagent_total_time: float = 0.0


def subagent_task_hash(messages: list[dict]) -> str:
    """
    Create a hash from the subagent task content.
    Used for deduplication and caching.
    """
    task_text = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            task_text += content
        elif m.get("role") == "system" and len(messages) <= 3:
            # For 2-msg subagents, the system msg is our simplified prompt — skip it
            continue
    return hashlib.md5(task_text.encode()).hexdigest()[:16]


def cache_subagent_result(task_hash: str, result_text: str):
    """Store subagent result in cache."""
    global _SUBAGENT_CACHE
    _SUBAGENT_CACHE[task_hash] = (result_text, time.time())
    # Prune old entries
    if len(_SUBAGENT_CACHE) > _MAX_CACHE_ENTRIES:
        now = time.time()
        expired = [k for k, (_, ts) in _SUBAGENT_CACHE.items() if now - ts > _CACHE_TTL]
        for k in expired:
            del _SUBAGENT_CACHE[k]
        # If still too many, remove oldest
        if len(_SUBAGENT_CACHE) > _MAX_CACHE_ENTRIES:
            sorted_keys = sorted(_SUBAGENT_CACHE.keys(), key=lambda k: _SUBAGENT_CACHE[k][1])
            for k in sorted_keys[:len(sorted_keys) - _MAX_CACHE_ENTRIES]:
                del _SUBAGENT_CACHE[k]


def get_cached_subagent_result(task_hash: str) -> Optional[str]:
    """Get cached subagent result if still valid."""
    entry = _SUBAGENT_CACHE.get(task_hash)
    if not entry:
        return None
    result_text, ts = entry
    if time.time() - ts > _CACHE_TTL:
        del _SUBAGENT_CACHE[task_hash]
        return None
    return result_text


def record_subagent_start() -> str:
    """Called when a subagent starts. Returns a timing key."""
    global _subagent_total
    _subagent_total += 1
    return f"subagent_{_subagent_total}"


def record_subagent_done(timing_key: str, elapsed: float, success: bool):
    """
    Called when a subagent completes.
    Tracks failures and timing for Circuit Breaker.
    """
    global _subagent_failures, _subagent_total_time
    _subagent_total_time += elapsed

    if not success or elapsed > _SUBAGENT_TIMEOUT_S:
        _subagent_failures += 1
        if elapsed > _SUBAGENT_TIMEOUT_S:
            print(f"[SUBAGENT CB] {timing_key} timeout: {elapsed:.1f}s > {_SUBAGENT_TIMEOUT_S}s (failures={_subagent_failures})", flush=True)
        else:
            print(f"[SUBAGENT CB] {timing_key} failed after {elapsed:.1f}s (failures={_subagent_failures})", flush=True)
    else:
        _subagent_failures = max(0, _subagent_failures - 1)  # Success resets counter
        print(f"[SUBAGENT] {timing_key} done in {elapsed:.1f}s", flush=True)

    if _subagent_failures >= _SUBAGENT_MAX_FAILURES:
        print(f"[SUBAGENT CB] CIRCUIT OPEN — {_subagent_failures} consecutive failures/timeouts. "
              f"Consider stopping subagents for this conversation.", flush=True)


def get_subagent_stats() -> dict:
    """Return subagent timing stats."""
    avg = _subagent_total_time / max(1, _subagent_total)
    return {
        "total": _subagent_total,
        "failures": _subagent_failures,
        "avg_time": round(avg, 2),
        "circuit_open": _subagent_failures >= _SUBAGENT_MAX_FAILURES,
    }
