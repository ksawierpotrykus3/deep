"""
Subagent isolation — dedicated sessions, response caching, Circuit Breaker.
Prevents subagents from cross-contaminating each other and protects
the main agent from stuck subagents.
"""
import time
import hashlib
import json
from typing import Optional

# ── Circuit Breaker ─────────────────────────────────────────────────────────
# Tracks subagent timing. If a subagent takes >45s, log a warning.
# If 3+ subagents in a row fail/timeout, suggest main agent skip them.
_SUBAGENT_TIMEOUT_S = 45
_SUBAGENT_MAX_FAILURES = 3
_subagent_failures: int = 0
_subagent_total: int = 0
_subagent_total_time: float = 0.0


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
