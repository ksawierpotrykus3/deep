# Infrastructure Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve codebase infrastructure with centralized configuration, structured logging, property-based testing for parser, and dashboard contract

**Architecture:** Four independent phases that can be executed in any order. Each phase produces working, testable improvements. No parser consolidation (deemed too risky).

**Tech Stack:** Pydantic Settings, structlog, hypothesis, gRPC/Protobuf, shared types package

---

## Phase 1: Centralna konfiguracja (Pydantic Settings)

**Estimated:** 1-2h  
**Files:** New `server/config/settings.py`, modify `server/config.py`, update all consumers

### Task 1.1: Create Pydantic Settings model

**Files:**
- Create: `deepseek-proxy/server/config/settings.py`
- Modify: `deepseek-proxy/server/config.py`
- Test: `deepseek-proxy/tests/test_config.py` (new)

- [ ] **Step 1: Write failing test for Settings model**

```python
# deepseek-proxy/tests/test_config.py
import pytest
from server.config.settings import Settings

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("MAX_ACCOUNTS", "5")
    monkeypatch.setenv("MIN_BASE_DELAY", "10.0")
    monkeypatch.setenv("MAX_CAPTURE_BUF_SIZE", "1000000")
    
    settings = Settings()
    assert settings.max_accounts == 5
    assert settings.min_base_delay == 10.0
    assert settings.max_capture_buf_size == 1_000_000

def test_settings_defaults():
    settings = Settings()
    assert settings.max_accounts == 3
    assert settings.min_base_delay == 8.0
    assert settings.max_capture_buf_size == 500_000
    assert settings.ttl == 86400
    assert settings.max_sessions_per_account == 5
    assert settings.max_parallel_tool_calls == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd deepseek-proxy && python -m pytest tests/test_config.py -v`
Expected: FAIL - module `server.config.settings` not found

- [object Object] **Step 3: Create Settings model with all magic numbers**

```python
# deepseek-proxy/server/config/settings.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Account pool
    max_accounts: int = Field(default=3, ge=1, le=10)
    max_sessions_per_account: int = Field(default=5, ge=1, le=20)
    max_parallel_tool_calls: int = Field(default=5, ge=1, le=20)

    # Rate limiting / throttling
    min_base_delay: float = Field(default=8.0, ge=0.1, le=60.0)
    max_jitter: float = Field(default=5.0, ge=0.0, le=30.0)
    stream_backoff_delays: list[int] = Field(default=[3, 6, 12, 20])
    rate_backoff_delays: list[int] = Field(default=[3, 6, 12, 25])

    # Stream sieve
    max_capture_buf_size: int = Field(default=500_000, ge=10_000, le=10_000_000)
    drain_timeout: float = Field(default=30.0, ge=1.0, le=300.0)

    # Conversation state
    ttl: int = Field(default=86400, ge=300, le=604800)  # 24h default
    dedup_ttl: float = Field(default=60.0, ge=1.0, le=3600.0)

    # Prompt limits
    max_prompt_len: int = Field(default=150_000, ge=1000, le=1_000_000)
    tool_result_max_chars: int = Field(default=10_000, ge=100, le=100_000)

    # Watermark
    watermark_enabled: bool = Field(default=False)

    # Dashboard
    dashboard_db_path: str = Field(default="dashboard.db")

    # Logging
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")  # json | console


# Global instance
settings = Settings()
```

- [ ] **Step 4: Update config.py to re-export from settings**

```python
# deepseek-proxy/server/config.py
"""All proxy constants in one place - now backed by Pydantic Settings."""

from server.config.settings import settings

# Re-export all constants for backward compatibility
MAX_ACCOUNTS = settings.max_accounts
MAX_SESSIONS_PER_ACCOUNT = settings.max_sessions_per_account
MAX_PARALLEL_TOOL_CALLS = settings.max_parallel_tool_calls

_MIN_BASE_DELAY = settings.min_base_delay
_MAX_JITTER = settings.max_jitter
_STREAM_BACKOFF = settings.stream_backoff_delays
_BACKOFF_DELAYS = settings.rate_backoff_delays

_MAX_CAPTURE_BUF_SIZE = settings.max_capture_buf_size
_DRAIN_TIMEOUT = settings.drain_timeout

_TTL = settings.ttl
DEDUP_TTL = settings.dedup_ttl

MAX_PROMPT_LEN = settings.max_prompt_len
TOOL_RESULT_MAX_CHARS = settings.tool_result_max_chars

WATERMARK_ENABLED = settings.watermark_enabled

# Dashboard
DB_PATH = settings.dashboard_db_path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd deepseek-proxy && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite to ensure no regressions**

Run: `cd deepseek-proxy && python -m pytest tests/ -x -q`
Expected: 404 passed, 2 xfailed

- [ ] **Step 7: Commit**

```bash
git add deepseek-proxy/server/config/settings.py deepseek-proxy/server/config.py deepseek-proxy/tests/test_config.py
git commit -m "feat: add Pydantic Settings for centralized configuration"
```

---

## Phase 2: Strukturalne logowanie (structlog)

**Estimated:** 1-2h  
**Files:** New `server/logging.py`, modify 15+ files with `print(..., flush=True)`

### Task 2.1: Create structlog configuration

**Files:**
- Create: `deepseek-proxy/server/logging.py`
- Modify: `deepseek-proxy/server/config/settings.py` (add log config)
- Test: `deepseek-proxy/tests/test_logging.py` (new)

- [ ] **Step 1: Write failing test for logger**

```python
# deepseek-proxy/tests/test_logging.py
import pytest
import structlog
from server.logging import get_logger, configure_logging

def test_logger_returns_structlog_logger():
    configure_logging(log_level="DEBUG", log_format="console")
    logger = get_logger("test.module")
    assert isinstance(logger, structlog.BoundLogger)

def test_json_output_format(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    configure_logging()
    logger = get_logger("test")
    logger.info("test message", key="value")
    captured = capsys.readouterr()
    assert '"key": "value"' in captured.out
    assert '"event": "test message"' in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd deepseek-proxy && python -m pytest tests/test_logging.py -v`
Expected: FAIL - module `server.logging` not found

- [ ] **Step 3: Create logging module**

```python
# deepseek-proxy/server/logging.py
"""Structured logging configuration using structlog."""

from __future__ import annotations

import sys
import structlog
from structlog.types import EventDict, WrappedLogger

from server.config.settings import settings


def _add_service_name(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add service name to all log entries."""
    event_dict["service"] = "deepseek-proxy"
    return event_dict


def _add_timestamp(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Add ISO timestamp to all log entries."""
    from datetime import datetime, timezone
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def configure_logging(log_level: str | None = None, log_format: str | None = None) -> None:
    """Configure structlog for the application."""
    level = (log_level or settings.log_level).upper()
    fmt = (log_format or settings.log_format).lower()

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_service_name,
        _add_timestamp,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    if fmt == "json":
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(structlog, level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a logger instance for the given module name."""
    return structlog.get_logger(name)


# Convenience functions for common log patterns
def log_proxy_request(logger: structlog.BoundLogger, **kwargs) -> None:
    logger.info("proxy_request", **kwargs)


def log_stream_start(logger: structlog.BoundLogger, **kwargs) -> None:
    logger.info("stream_start", **kwargs)


def log_stream_end(logger: structlog.BoundLogger, **kwargs) -> None:
    logger.info("stream_end", **kwargs)


def log_rate_limit(logger: structlog.BoundLogger, **kwargs) -> None:
    logger.warning("rate_limit", **kwargs)


def log_tool_call(logger: structlog.BoundLogger, **kwargs) -> None:
    logger.info("tool_call", **kwargs)


def log_error(logger: structlog.BoundLogger, **kwargs) -> None:
    logger.error("error", **kwargs)
```

- [ ] **Step 4: Update settings.py with log config fields**

```python
# In deepseek-proxy/server/config/settings.py, add to Settings class:
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")  # json | console
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd deepseek-proxy && python -m pytest tests/test_logging.py -v`
Expected: PASS

### Task 2.2: Replace print statements in core files

**Files:** Modify 15+ files - replace `print(f"[TAG] ...", flush=True)` with structured logger

- [ ] **Step 1: Create a mapping of all print statements to replace**

Run: `cd deepseek-proxy && grep -rn 'print.*flush=True' server/ --include="*.py" | grep -v test | grep -v __pycache__`

- [ ] **Step 2: Replace in each file (example for deepseek_client.py)**

```python
# deepseek-proxy/server/core/deepseek_client.py
from server.logging import get_logger

logger = get_logger(__name__)

# Replace:
# print(f"[POW] account={slot} solved in {elapsed:.1f}s", flush=True)
# With:
logger.info("pow_solved", account=slot, elapsed_seconds=elapsed)
```

- [ ] **Step 3: Run full test suite after each file**

Run: `cd deepseek-proxy && python -m pytest tests/ -x -q`
Expected: 404 passed, 2 xfailed

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server/logging.py deepseek-proxy/server/config/settings.py deepseek-proxy/tests/test_logging.py
# ... add all modified files
git commit -m "feat: add structured logging with structlog"
```

---

## Phase 3: Property-based testing dla parsera (hypothesis)

**Estimated:** 2-4h  
**Files:** New `deepseek-proxy/tests/property/test_parser_properties.py`

### Task 3.1: Add hypothesis dependency and create property tests

**Files:**
- Modify: `deepseek-proxy/requirements.txt` (add hypothesis)
- Create: `deepseek-proxy/tests/property/test_parser_properties.py`
- Create: `deepseek-proxy/tests/property/strategies.py`

- [ ] **Step 1: Add hypothesis to requirements**

```text
# deepseek-proxy/requirements.txt
hypothesis>=6.100.0
```

- [ ] **Step 2: Create strategy module for generating valid tool call formats**

```python
# deepseek-proxy/tests/property/strategies.py
"""Hypothesis strategies for generating tool call test data."""

from __future__ import annotations

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy


# Valid tool names from the codebase
TOOL_NAMES = [
    "Read", "Write", "Edit", "SearchReplace", "Glob", "Grep",
    "Bash", "RunCommand", "WebSearch", "WebFetch", "Task",
    "AskUserQuestion", "TodoWrite", "NotifyUser", "Skill",
]

# XML-safe strings (no control chars, valid for CDATA)
XML_SAFE_CHARS = st.characters(
    min_codepoint=32,
    max_codepoint=0x10FFFF,
    blacklist_categories=("Cc", "Cs"),  # control chars, surrogates
    blacklist_characters="&<]>",
)

# Valid parameter names
PARAM_NAMES = st.sampled_from([
    "file_path", "path", "pattern", "query", "command", "content",
    "old_string", "new_string", "replacement", "target", "url",
    "name", "description", "title", "message", "question",
])

# JSON-serializable values
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(alphabet=XML_SAFE_CHARS, max_size=100),
    lambda children: st.lists(children, max_size=5) | st.dictionaries(st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=1, max_size=20), children, max_size=5),
    max_leaves=10,
)


@st.composite
def tool_call_dsml(draw) -> str:
    """Generate a valid DSML tool call block."""
    name = draw(st.sampled_from(TOOL_NAMES))
    num_params = draw(st.integers(min_value=0, max_value=5))
    
    params = []
    for _ in range(num_params):
        param_name = draw(PARAM_NAMES)
        param_value = draw(JSON_VALUES)
        if isinstance(param_value, (dict, list)):
            import json
            param_value = json.dumps(param_value, ensure_ascii=False)
        elif isinstance(param_value, bool):
            param_value = str(param_value).lower()
        elif param_value is None:
            param_value = ""
        params.append(f'      <parameter name="{param_name}"><![CDATA[{param_value}]]>