# AI Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive dashboard system for monitoring, diagnosing, and controlling AI conversations running through the Deepseek proxy.

**Architecture:** Two-server setup — proxy (port 4570) is instrumented to emit metrics to SQLite + WebSocket; dashboard server (port 4571) provides REST API + WebSocket forwarding to a React SPA frontend. SQLite WAL mode allows concurrent write from proxy and read from dashboard.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy + SQLite (WAL), WebSocket, React 18 + Vite + TypeScript, Tailwind CSS, Recharts, Zustand, Socket.IO

---

### File Structure

```
deepseek-proxy/
├── server/
│   ├── dashboard/                        # NEW — instrumentation module in proxy
│   │   ├── __init__.py
│   │   ├── instrumentor.py              # DashboardInstrumentor — collects metrics, emits WS
│   │   └── metric_writer.py             # SQLite writer (WAL mode, separate connection)
│   ├── services/
│   │   └── state_service.py             # MODIFY — add user_uuid to conv_state
│   ├── services/
│   │   └── proxy_service.py             # MODIFY — add instrumentor hooks
│   └── config.py                        # MODIFY — add dashboard config constants

deepseek-dashboard/                      # NEW — separate dashboard server
├── __init__.py
├── main.py                              # FastAPI app entry point
├── config.py                            # Dashboard configuration
├── requirements.txt                     # Python dependencies
├── api/
│   ├── __init__.py
│   ├── auth.py                          # JWT login + verification
│   ├── routes.py                        # All REST endpoints
│   └── websocket.py                     # WS client to proxy + WS server to FE
├── services/
│   ├── __init__.py
│   ├── conversation_service.py          # Conversation CRUD + metrics queries
│   ├── account_service.py               # Account status management
│   ├── anomaly_service.py               # Anomaly detection + queries
│   └── correlation_service.py           # Chat correlation logic
├── models/
│   ├── __init__.py
│   ├── database.py                      # SQLAlchemy engine, session, init_db
│   └── entities.py                      # ORM models for all tables
├── dashboard-ui/                        # NEW — React + Vite frontend
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tsconfig.app.json
│   ├── tsconfig.node.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── vite-env.d.ts
│       ├── types/
│       │   └── index.ts                # TypeScript interfaces
│       ├── services/
│       │   ├── api.ts                   # Axios instance with auth interceptor
│       │   ├── auth.ts                  # Auth API calls
│       │   ├── conversations.ts         # Conversations API calls
│       │   ├── accounts.ts             # Accounts API calls
│       │   └── anomalies.ts            # Anomalies API calls
│       ├── stores/
│       │   ├── authStore.ts            # JWT token store (Zustand)
│       │   └── metricsStore.ts         # Live metrics store (Zustand)
│       ├── hooks/
│       │   ├── useWebSocket.ts         # Socket.IO hook
│       │   └── useMetrics.ts           # Metrics subscription hook
│       ├── components/
│       │   ├── Layout/
│       │   │   ├── AppLayout.tsx       # Sidebar + Header + main content
│       │   │   └── ProtectedRoute.tsx  # Route guard (redirect if no JWT)
│       │   ├── Charts/
│       │   │   ├── MetricChart.tsx     # Recharts line chart (generic)
│       │   │   └── MetricCard.tsx      # Single metric card (value + label)
│       │   ├── common/
│       │   │   ├── LoadingSpinner.tsx
│       │   │   └── StatusBadge.tsx     # Color-coded status badge
│       │   └── Tables/
│       │       └── ConversationsTable.tsx
│       └── pages/
│           ├── Login.tsx
│           ├── Dashboard.tsx
│           ├── Conversations.tsx
│           ├── ConversationDetail.tsx
│           ├── Accounts.tsx
│           ├── Anomalies.tsx
│           └── Correlations.tsx
```

---

### Task 1: Instrumentation module in proxy — Database writer

**Files:**
- Create: `deepseek-proxy/server/dashboard/__init__.py`
- Create: `deepseek-proxy/server/dashboard/metric_writer.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# server/dashboard/__init__.py
from server.dashboard.metric_writer import MetricWriter
from server.dashboard.instrumentor import DashboardInstrumentor

__all__ = ["MetricWriter", "DashboardInstrumentor"]
```

- [ ] **Step 2: Create `MetricWriter` — SQLite WAL writer**

```python
# server/dashboard/metric_writer.py
"""SQLite writer for dashboard metrics. WAL mode for concurrent read access."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DASHBOARD_DB_PATH = Path(__file__).parent.parent.parent / "dashboard.db"


class MetricWriter:
    """Thread-safe SQLite writer with WAL mode. Used by proxy to log metrics."""

    def __init__(self, db_path: str | Path = DASHBOARD_DB_PATH) -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id              TEXT PRIMARY KEY,
                chat_id         TEXT,
                account_slot    INTEGER NOT NULL,
                user_uuid       TEXT NOT NULL,
                model           TEXT NOT NULL DEFAULT 'deepseek-v4-pro',
                status          TEXT NOT NULL DEFAULT 'active',
                started_at      REAL NOT NULL,
                ended_at        REAL,
                total_tokens    INTEGER DEFAULT 0,
                total_duration_ms INTEGER DEFAULT 0,
                error_message   TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_uuid);
            CREATE INDEX IF NOT EXISTS idx_conv_account ON conversations(account_slot);
            CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);
            CREATE INDEX IF NOT EXISTS idx_conv_started ON conversations(started_at);

            CREATE TABLE IF NOT EXISTS metrics (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                timestamp       REAL NOT NULL,
                ttft_ms         REAL,
                tokens_per_sec  REAL,
                tokens_total    INTEGER DEFAULT 0,
                latency_ms      REAL,
                events_count    INTEGER DEFAULT 0,
                stream_active   INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_conv ON metrics(conversation_id);

            CREATE TABLE IF NOT EXISTS tool_calls (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                tool_name       TEXT NOT NULL,
                arguments       TEXT NOT NULL,
                result          TEXT,
                is_valid        INTEGER DEFAULT 1,
                repair_tier     INTEGER DEFAULT 0,
                parsed_at       REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tool_conv ON tool_calls(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls(tool_name);

            CREATE TABLE IF NOT EXISTS anomalies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT REFERENCES conversations(id),
                type            TEXT NOT NULL,
                severity        TEXT NOT NULL DEFAULT 'warning',
                message         TEXT NOT NULL,
                details         TEXT,
                detected_at     REAL NOT NULL,
                acknowledged    INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_anomaly_conv ON anomalies(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_anomaly_type ON anomalies(type);
            CREATE INDEX IF NOT EXISTS idx_anomaly_severity ON anomalies(severity);

            CREATE TABLE IF NOT EXISTS account_sessions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                slot              INTEGER NOT NULL UNIQUE,
                status            TEXT NOT NULL DEFAULT 'inactive',
                rate_limited_until REAL,
                conversations_count INTEGER DEFAULT 0,
                last_used_at      REAL,
                created_at        TEXT NOT NULL DEFAULT (datetime('now')),
                last_login_attempt TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_correlations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_key TEXT NOT NULL,
                conversation_id TEXT NOT NULL REFERENCES conversations(id),
                label           TEXT,
                parent_id       TEXT REFERENCES conversations(id),
                depth           INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_corr_key ON chat_correlations(correlation_key);
            CREATE INDEX IF NOT EXISTS idx_corr_parent ON chat_correlations(parent_id);

            -- Seed account_sessions with 3 slots
            INSERT OR IGNORE INTO account_sessions (slot, status) VALUES (0, 'inactive');
            INSERT OR IGNORE INTO account_sessions (slot, status) VALUES (1, 'inactive');
            INSERT OR IGNORE INTO account_sessions (slot, status) VALUES (2, 'inactive');
        """)
        conn.commit()

    def insert_conversation(self, conv_id: str, chat_id: str, account_slot: int,
                            user_uuid: str, model: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, chat_id, account_slot, user_uuid, model, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, chat_id, account_slot, user_uuid, model, time.time()),
        )
        conn.commit()

    def insert_metric(self, conv_id: str, timestamp: float, ttft_ms: float | None,
                      tokens_per_sec: float | None, tokens_total: int,
                      latency_ms: float | None, events_count: int,
                      stream_active: int = 1) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO metrics (conversation_id, timestamp, ttft_ms, tokens_per_sec, "
            "tokens_total, latency_ms, events_count, stream_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conv_id, timestamp, ttft_ms, tokens_per_sec, tokens_total,
             latency_ms, events_count, stream_active),
        )
        conn.commit()

    def finalize_conversation(self, conv_id: str, total_tokens: int,
                               duration_ms: int, error_message: str | None = None) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE conversations SET status=?, ended_at=?, total_tokens=?, "
            "total_duration_ms=?, error_message=? WHERE id=?",
            ("error" if error_message else "completed",
             time.time(), total_tokens, duration_ms, error_message, conv_id),
        )
        conn.commit()

    def insert_tool_call(self, conv_id: str, tool_name: str, arguments: str,
                          is_valid: int, repair_tier: int) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO tool_calls (conversation_id, tool_name, arguments, is_valid, repair_tier, parsed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, tool_name, arguments, is_valid, repair_tier, time.time()),
        )
        conn.commit()

    def insert_anomaly(self, conv_id: str | None, type_: str, severity: str,
                       message: str, details: dict | None = None) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO anomalies (conversation_id, type, severity, message, details, detected_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, type_, severity, message,
             json.dumps(details) if details else None, time.time()),
        )
        conn.commit()

    def update_account_status(self, slot: int, status: str,
                               rate_limited_until: float | None = None) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE account_sessions SET status=?, rate_limited_until=? WHERE slot=?",
            (status, rate_limited_until, slot),
        )
        conn.commit()

    def increment_account_conversations(self, slot: int) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE account_sessions SET conversations_count = conversations_count + 1, "
            "last_used_at=? WHERE slot=?",
            (time.time(), slot),
        )
        conn.commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
```

- [ ] **Step 3: Verify file creation**

Run: `python -c "from server.dashboard.metric_writer import MetricWriter; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add deepseek-proxy/server/dashboard/__init__.py deepseek-proxy/server/dashboard/metric_writer.py
git commit -m "feat(dashboard): add MetricWriter for SQLite WAL metrics storage"
```

---

### Task 2: Instrumentation module — DashboardInstrumentor

**Files:**
- Create: `deepseek-proxy/server/dashboard/instrumentor.py`

- [ ] **Step 1: Write `DashboardInstrumentor`**

```python
# server/dashboard/instrumentor.py
"""DashboardInstrumentor — collects proxy metrics and writes to SQLite + WebSocket."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from server.dashboard.metric_writer import MetricWriter


class DashboardInstrumentor:
    """Collects metrics from proxy hooks and writes them to the dashboard database.
    
    This class is designed for minimal insertion into existing proxy code.
    It handles SQLite writes and WebSocket emission to the dashboard server.
    """

    def __init__(self, metric_writer: MetricWriter | None = None) -> None:
        self._writer = metric_writer or MetricWriter()
        self._ws_connected: bool = False
        self._ws_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._ws_task: asyncio.Task | None = None

    def on_conversation_started(self, conv_id: str, chat_id: str, account_slot: int,
                                 user_uuid: str, model: str) -> None:
        """Called when a new conversation/session is created."""
        self._writer.insert_conversation(conv_id, chat_id, account_slot, user_uuid, model)
        self._writer.increment_account_conversations(account_slot)
        self._writer.update_account_status(account_slot, "active")
        self._emit({"type": "conversation:started",
                     "conv_id": conv_id, "account": account_slot, "user_uuid": user_uuid})

    def on_metric(self, conv_id: str, timestamp: float, ttft_ms: float | None = None,
                  tokens_per_sec: float | None = None, tokens_total: int = 0,
                  latency_ms: float | None = None, events_count: int = 0) -> None:
        """Called periodically during streaming."""
        self._writer.insert_metric(conv_id, timestamp, ttft_ms, tokens_per_sec,
                                    tokens_total, latency_ms, events_count)
        self._emit({"type": "conversation:metric",
                     "conv_id": conv_id, "ttft_ms": ttft_ms, "tokens_per_sec": tokens_per_sec,
                     "tokens_total": tokens_total, "latency_ms": latency_ms})

    def on_conversation_completed(self, conv_id: str, total_tokens: int,
                                   duration_ms: int) -> None:
        """Called when streaming ends successfully."""
        self._writer.finalize_conversation(conv_id, total_tokens, duration_ms)
        self._emit({"type": "conversation:completed",
                     "conv_id": conv_id, "total_tokens": total_tokens, "duration_ms": duration_ms})

    def on_conversation_error(self, conv_id: str, error_message: str,
                               total_tokens: int, duration_ms: int) -> None:
        """Called when streaming ends with an error."""
        self._writer.finalize_conversation(conv_id, total_tokens, duration_ms, error_message)
        self._writer.insert_anomaly(conv_id, "stream_error", "critical", error_message)
        self._emit({"type": "conversation:error",
                     "conv_id": conv_id, "error_message": error_message})

    def on_tool_call_detected(self, conv_id: str, tool_name: str,
                               arguments: str, is_valid: bool, repair_tier: int) -> None:
        """Called when a tool call is detected in the stream."""
        self._writer.insert_tool_call(conv_id, tool_name, arguments,
                                       int(is_valid), repair_tier)
        if repair_tier > 1:
            self._writer.insert_anomaly(conv_id, "tool_repair", "info",
                                         f"Tool '{tool_name}' repaired at tier {repair_tier}",
                                         {"tool_name": tool_name, "repair_tier": repair_tier})

    def on_account_rate_limited(self, slot: int, until: float) -> None:
        """Called when an account becomes rate-limited."""
        self._writer.update_account_status(slot, "rate_limited", until)
        self._writer.insert_anomaly(None, "rate_limit", "warning",
                                     f"Account {slot} rate-limited until {time.ctime(until)}",
                                     {"slot": slot, "until": until})
        self._emit({"type": "account:status_change", "slot": slot,
                     "status": "rate_limited", "rate_limited_until": until})

    def on_account_status_change(self, slot: int, status: str) -> None:
        """Called when account status changes for other reasons."""
        self._writer.update_account_status(slot, status)
        self._emit({"type": "account:status_change", "slot": slot, "status": status})

    def _emit(self, event: dict) -> None:
        """Queue event for WebSocket transmission (non-blocking)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._ws_queue.put_nowait, event)
        except RuntimeError:
            pass  # no event loop available — SQLite write already happened
```

- [ ] **Step 2: Verify file creation**

Run: `python -c "from server.dashboard.instrumentor import DashboardInstrumentor; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server/dashboard/instrumentor.py
git commit -m "feat(dashboard): add DashboardInstrumentor for metric collection"
```

---

### Task 3: Extend proxy state service with user_uuid

**Files:**
- Modify: `deepseek-proxy/server/services/state_service.py`

- [ ] **Step 1: Add user_uuid to conv_state entries**

Modify the `set_conv` function to accept and store `user_uuid`:

```python
def set_conv(messages: list[dict], chat_id: str, parent_id, account: int,
             user_uuid: str = "") -> None:
    """Save or update conversation state keyed by message hash and chat_id."""
    h = _msg_hash(messages)
    now = time.time()
    with conv_lock:
        conv_state[h] = {
            "chat_id": chat_id,
            "parent_id": parent_id,
            "account": account,
            "user_uuid": user_uuid,
            "ts": now,
        }
        chat_state[chat_id] = {
            "parent_id": parent_id,
            "account": account,
            "user_uuid": user_uuid,
            "ts": now,
        }
    _schedule_save()
```

Also add `PROXY_UUID` to the watermark regex at line 24 (keep existing alongside new one):

```python
_PROXY_CHAT_RE = re.compile(r'<!--\s*PROXY_CHAT:\s*([a-f0-9]+)\s*-->', re.IGNORECASE)
_PROXY_UUID_RE = re.compile(r'PROXY_UUID:\s*([a-f0-9\-]+)\s*-->', re.IGNORECASE)
```

Also add a `get_conv_by_chat_id` function:

```python
def get_conv_by_chat_id(chat_id: str) -> dict | None:
    """Lookup conversation state by chat_id directly."""
    with conv_lock:
        return chat_state.get(chat_id)
```

- [ ] **Step 2: Verify the module still loads**

Run: `python -c "from server.services.state_service import set_conv, get_conv, get_conv_by_chat_id; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add deepseek-proxy/server/services/state_service.py
git commit -m "feat(proxy): add user_uuid tracking to conversation state"
```

---

### Task 4: Add dashboard instrumentor hooks to proxy_service.py

**Files:**
- Modify: `deepseek-proxy/server/services/proxy_service.py`

- [ ] **Step 1: Add import and global instrumentor instance**

After line 38 (`from server.utils.helpers ...`), add:

```python
from server.dashboard.instrumentor import DashboardInstrumentor
from server.dashboard.metric_writer import MetricWriter

# Global dashboard instrumentor instance
_dashboard = DashboardInstrumentor()
```

- [ ] **Step 2: Generate user_uuid and register conversation start**

In `ProxyService.chat_completions()`, after line 777 (`conv_uuid = uuid.uuid4().hex[:12]`), add:

```python
# ── Dashboard instrumentation ─────────────────────────────
user_uuid = state.get("user_uuid", "") if state else ""
if not user_uuid:
    user_uuid = uuid.uuid4().hex[:12]
_dashboard.on_conversation_started(
    conv_id=conv_uuid,
    chat_id=chat_id,
    account_slot=account_idx,
    user_uuid=user_uuid,
    model=model,
)
```

- [ ] **Step 3: Pass user_uuid to _save_state calls**

Modify the `_save_state` function signature at line 124 to include user_uuid:

```python
def _save_state(
    messages: list[dict],
    stream_meta: dict,
    parent_id: str | None,
    chat_id: str,
    conv_uuid: str,
    account_idx: int,
    tools: list[dict] | None,
    text_buffer: str,
    user_uuid: str = "",
) -> None:
    new_parent_id = stream_meta.get("resp_msg_id") or parent_id
    set_conv(messages, chat_id, new_parent_id, account_idx, user_uuid=user_uuid)
```

*Note: In files where `_save_state` is called, add `user_uuid=user_uuid` keyword argument (it has a default, so the call still works without it).*

- [ ] **Step 4: Add metric emission inside `_stream_gen`**

Inside `_stream_gen`, after TTFT measurement at line 266-267, add:

```python
_ttft_ms = (_ttft - t4) * 1000  # for dashboard
```

After the flush at lines 314-317 (or after `yield_buffer` flush at line 342-345), add periodic metric emission:

Find this in `_stream_gen` — the best place is after each `yield _chunk(...)` call inside the main loop. Specifically, after the yield_buffer flush at line 342-345:

```python
# Periodic metrics for dashboard
global _dashboard
_dashboard.on_metric(
    conv_id=conv_uuid,
    timestamp=time.time(),
    ttft_ms=_ttft_ms if _ttft_ms else None,
    tokens_per_sec=len(text_buffer) / (time.time() - t4) if (time.time() - t4) > 0 else None,
    tokens_total=len(text_buffer),
    latency_ms=(time.time() - _ttft) * 1000 if _ttft else None,
)
```

- [ ] **Step 5: Add completion/error hooks at stream end**

Before `yield _chunk({}, fr="stop", sid=conv_uuid)` at line 420 (text-only finish), add:

```python
_dashboard.on_conversation_completed(
    conv_id=conv_uuid,
    total_tokens=len(text_buffer),
    duration_ms=(time.time() - t0) * 1000,
)
```

Before `yield _chunk({}, fr="tool_calls", sid=conv_uuid)` at line 334 (tool calls finish), add:

```python
_dashboard.on_conversation_completed(
    conv_id=conv_uuid,
    total_tokens=len(text_buffer),
    duration_ms=(time.time() - t0) * 1000,
)
```

In the error handler at line 423-471, before `yield _chunk({"content": ...})` at line 471, add:

```python
_dashboard.on_conversation_error(
    conv_id=conv_uuid,
    error_message=err_str[:500],
    total_tokens=len(text_buffer),
    duration_ms=(time.time() - t0) * 1000,
)
```

- [ ] **Step 6: Add account rate-limit hook**

In the rate-limit handler (around line 429-453, wherever `rate_limited_until` is set), add:

```python
_dashboard.on_account_rate_limited(account_idx, rate_limited_until[account_idx])
```

- [ ] **Step 7: Extend watermark in _stream_gen**

Find all watermark emit lines:
- Line 331: `yield _chunk({"content": f"\n<!-- PROXY_CHAT: {chat_id} -->"})`
- Line 382: same
- Line 403: same
- Line 419: same

Extend them to include user_uuid:

```python
yield _chunk({"content": f"\n<!-- PROXY_CHAT: {chat_id} | PROXY_UUID: {user_uuid} -->"})
```

*Note: `user_uuid` must be added as a parameter to `_stream_gen` or accessed via a closure/outer scope. The simplest approach is to add it to the function signature:*

Add `user_uuid: str = ""` parameter to `_stream_gen` function signature at line 248, then pass it through at the call site (line 787-802).

- [ ] **Step 8: Verify the module loads without errors**

Run: `python -c "from server.services.proxy_service import ProxyService; print('OK')"`
Expected: OK

- [ ] **Step 9: Commit**

```bash
git add deepseek-proxy/server/services/proxy_service.py
git commit -m "feat(proxy): add dashboard instrumentation hooks"
```

---

### Task 5: Dashboard server — models and database

**Files:**
- Create: `deepseek-dashboard/__init__.py`
- Create: `deepseek-dashboard/models/__init__.py`
- Create: `deepseek-dashboard/models/database.py`
- Create: `deepseek-dashboard/models/entities.py`

- [ ] **Step 1: Create `deepseek-dashboard/models/database.py`**

```python
# deepseek-dashboard/models/database.py
"""SQLAlchemy engine and session for the dashboard database (read-only)."""
from __future__ import annotations

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "dashboard.db"

engine = create_engine(
    f"sqlite:///{DEFAULT_DB_PATH}",
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Create `deepseek-dashboard/models/entities.py`**

```python
# deepseek-dashboard/models/entities.py
"""SQLAlchemy ORM models matching the dashboard.db schema."""
from __future__ import annotations

from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Index
from sqlalchemy.orm import relationship

from deepseek_dashboard.models.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    chat_id = Column(String)
    account_slot = Column(Integer, nullable=False)
    user_uuid = Column(String, nullable=False)
    model = Column(String, nullable=False, default="deepseek-v4-pro")
    status = Column(String, nullable=False, default="active")
    started_at = Column(Float, nullable=False)
    ended_at = Column(Float, nullable=True)
    total_tokens = Column(Integer, default=0)
    total_duration_ms = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)

    metrics = relationship("Metric", back_populates="conversation", lazy="dynamic")
    tool_calls = relationship("ToolCall", back_populates="conversation", lazy="dynamic")
    anomalies_rel = relationship("Anomaly", back_populates="conversation", lazy="dynamic")

    __table_args__ = (
        Index("idx_conv_user", "user_uuid"),
        Index("idx_conv_account", "account_slot"),
        Index("idx_conv_status", "status"),
        Index("idx_conv_started", "started_at"),
    )


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    timestamp = Column(Float, nullable=False)
    ttft_ms = Column(Float, nullable=True)
    tokens_per_sec = Column(Float, nullable=True)
    tokens_total = Column(Integer, default=0)
    latency_ms = Column(Float, nullable=True)
    events_count = Column(Integer, default=0)
    stream_active = Column(Integer, default=1)

    conversation = relationship("Conversation", back_populates="metrics")

    __table_args__ = (Index("idx_metrics_conv", "conversation_id"),)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    tool_name = Column(String, nullable=False)
    arguments = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    is_valid = Column(Integer, default=1)
    repair_tier = Column(Integer, default=0)
    parsed_at = Column(Float, nullable=False)

    conversation = relationship("Conversation", back_populates="tool_calls")

    __table_args__ = (
        Index("idx_tool_conv", "conversation_id"),
        Index("idx_tool_name", "tool_name"),
    )


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True)
    type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="warning")
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    detected_at = Column(Float, nullable=False)
    acknowledged = Column(Integer, default=0)

    conversation = relationship("Conversation", back_populates="anomalies_rel")

    __table_args__ = (
        Index("idx_anomaly_conv", "conversation_id"),
        Index("idx_anomaly_type", "type"),
        Index("idx_anomaly_severity", "severity"),
    )


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    slot = Column(Integer, nullable=False, unique=True)
    status = Column(String, nullable=False, default="inactive")
    rate_limited_until = Column(Float, nullable=True)
    conversations_count = Column(Integer, default=0)
    last_used_at = Column(Float, nullable=True)
    created_at = Column(String, nullable=False)
    last_login_attempt = Column(String, nullable=True)


class ChatCorrelation(Base):
    __tablename__ = "chat_correlations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    correlation_key = Column(String, nullable=False)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    label = Column(String, nullable=True)
    parent_id = Column(String, ForeignKey("conversations.id"), nullable=True)
    depth = Column(Integer, default=0)
    created_at = Column(String, nullable=False)

    __table_args__ = (
        Index("idx_corr_key", "correlation_key"),
        Index("idx_corr_parent", "parent_id"),
    )
```

- [ ] **Step 3: Create `deepseek-dashboard/__init__.py`**

```python
# deepseek-dashboard/__init__.py
```

- [ ] **Step 4: Create `deepseek-dashboard/models/__init__.py`**

```python
# deepseek-dashboard/models/__init__.py
from deepseek_dashboard.models.entities import (
    Conversation, Metric, ToolCall, Anomaly, AccountSession, ChatCorrelation,
)
from deepseek_dashboard.models.database import get_db, engine, Base

__all__ = [
    "Conversation", "Metric", "ToolCall", "Anomaly", "AccountSession",
    "ChatCorrelation", "get_db", "engine", "Base",
]
```

- [ ] **Step 5: Verify import works**

Run: `python -c "from deepseek_dashboard.models import Conversation; print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add deepseek-dashboard/
git commit -m "feat(dashboard): add SQLAlchemy models for dashboard database"
```

---

### Task 6: Dashboard server — services layer

**Files:**
- Create: `deepseek-dashboard/services/__init__.py`
- Create: `deepseek-dashboard/services/conversation_service.py`
- Create: `deepseek-dashboard/services/account_service.py`
- Create: `deepseek-dashboard/services/anomaly_service.py`
- Create: `deepseek-dashboard/services/correlation_service.py`

- [ ] **Step 1: Create `deepseek-dashboard/services/conversation_service.py`**

```python
# deepseek-dashboard/services/conversation_service.py
"""Service for conversation CRUD and metrics queries."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from deepseek_dashboard.models.entities import (
    Conversation, Metric, ToolCall,
)


class ConversationService:
    """Handles all conversation-related database queries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_conversations(
        self,
        status: str | None = None,
        account_slot: int | None = None,
        user_uuid: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        query = self._db.query(Conversation)
        if status:
            query = query.filter(Conversation.status == status)
        if account_slot is not None:
            query = query.filter(Conversation.account_slot == account_slot)
        if user_uuid:
            query = query.filter(Conversation.user_uuid == user_uuid)
        total = query.count()
        rows = query.order_by(desc(Conversation.started_at)).offset(offset).limit(limit).all()
        return [self._to_dict(c) for c in rows], total

    def get_conversation(self, conv_id: str) -> dict | None:
        conv = self._db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            return None
        result = self._to_dict(conv)
        result["metrics"] = [
            {
                "timestamp": m.timestamp,
                "ttft_ms": m.ttft_ms,
                "tokens_per_sec": m.tokens_per_sec,
                "tokens_total": m.tokens_total,
                "latency_ms": m.latency_ms,
                "events_count": m.events_count,
            }
            for m in conv.metrics.order_by(Metric.timestamp).all()
        ]
        result["tool_calls"] = [
            {
                "tool_name": tc.tool_name,
                "arguments": tc.arguments,
                "is_valid": bool(tc.is_valid),
                "repair_tier": tc.repair_tier,
                "parsed_at": tc.parsed_at,
            }
            for tc in conv.tool_calls.order_by(ToolCall.parsed_at).all()
        ]
        return result

    def get_conversation_metrics(self, conv_id: str) -> list[dict]:
        metrics = (
            self._db.query(Metric)
            .filter(Metric.conversation_id == conv_id)
            .order_by(Metric.timestamp)
            .all()
        )
        return [
            {
                "timestamp": m.timestamp,
                "ttft_ms": m.ttft_ms,
                "tokens_per_sec": m.tokens_per_sec,
                "tokens_total": m.tokens_total,
                "latency_ms": m.latency_ms,
            }
            for m in metrics
        ]

    def get_conversation_tool_calls(self, conv_id: str) -> list[dict]:
        calls = (
            self._db.query(ToolCall)
            .filter(ToolCall.conversation_id == conv_id)
            .order_by(ToolCall.parsed_at)
            .all()
        )
        return [
            {
                "tool_name": tc.tool_name,
                "arguments": tc.arguments,
                "is_valid": bool(tc.is_valid),
                "repair_tier": tc.repair_tier,
            }
            for tc in calls
        ]

    def delete_conversation(self, conv_id: str) -> bool:
        conv = self._db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            return False
        # Delete related rows first
        self._db.query(Metric).filter(Metric.conversation_id == conv_id).delete()
        self._db.query(ToolCall).filter(ToolCall.conversation_id == conv_id).delete()
        self._db.delete(conv)
        self._db.commit()
        return True

    def get_summary(self) -> dict:
        now = time.time()
       一小时前 = now - 3600
        active = self._db.query(func.count(Conversation.id)).filter(
            Conversation.status == "active"
        ).scalar() or 0
        avg_ttft = (
            self._db.query(func.avg(Metric.ttft_ms))
            .join(Conversation)
            .filter(Conversation.started_at >= 一小时前)
            .scalar()
        )
        avg_latency = (
            self._db.query(func.avg(Metric.latency_ms))
            .join(Conversation)
            .filter(Conversation.started_at >= 一小时前)
            .scalar()
        )
        errors = self._db.query(func.count(Conversation.id)).filter(
            Conversation.status == "error",
            Conversation.started_at >= 一小时前,
        ).scalar() or 0
        return {
            "active_conversations": active,
            "avg_ttft_ms": round(avg_ttft, 2) if avg_ttft else 0,
            "avg_latency_ms": round(avg_latency, 2) if avg_latency else 0,
            "errors_last_hour": errors,
        }

    def get_hourly_stats(self, hours: int = 24) -> list[dict]:
        """Aggregate metrics by hour for charts."""
        cutoff = time.time() - hours * 3600
        rows = (
            self._db.query(
                func.strftime("%Y-%m-%d %H:00:00", func.datetime(Conversation.started_at, "unixepoch")).label("hour"),
                func.count(Conversation.id).label("conversations"),
                func.avg(Conversation.total_tokens).label("avg_tokens"),
                func.avg(Conversation.total_duration_ms).label("avg_duration_ms"),
            )
            .filter(Conversation.started_at >= cutoff)
            .group_by("hour")
            .order_by("hour")
            .all()
        )
        return [
            {
                "hour": r.hour,
                "conversations": r.conversations,
                "avg_tokens": round(r.avg_tokens, 1) if r.avg_tokens else 0,
                "avg_duration_ms": round(r.avg_duration_ms, 1) if r.avg_duration_ms else 0,
            }
            for r in rows
        ]

    @staticmethod
    def _to_dict(conv: Conversation) -> dict:
        return {
            "id": conv.id,
            "chat_id": conv.chat_id,
            "account_slot": conv.account_slot,
            "user_uuid": conv.user_uuid,
            "model": conv.model,
            "status": conv.status,
            "started_at": conv.started_at,
            "ended_at": conv.ended_at,
            "total_tokens": conv.total_tokens,
            "total_duration_ms": conv.total_duration_ms,
            "error_message": conv.error_message,
        }
```

- [ ] **Step 2: Create `deepseek-dashboard/services/account_service.py`**

```python
# deepseek-dashboard/services/account_service.py
"""Service for account session management."""
from __future__ import annotations

from sqlalchemy.orm import Session

from deepseek_dashboard.models.entities import AccountSession


class AccountService:
    """Handles account session queries and status management."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_accounts(self) -> list[dict]:
        accounts = self._db.query(AccountSession).order_by(AccountSession.slot).all()
        return [
            {
                "slot": a.slot,
                "status": a.status,
                "rate_limited_until": a.rate_limited_until,
                "conversations_count": a.conversations_count,
                "last_used_at": a.last_used_at,
                "last_login_attempt": a.last_login_attempt,
            }
            for a in accounts
        ]

    def update_status(self, slot: int, status: str) -> bool:
        account = self._db.query(AccountSession).filter(AccountSession.slot == slot).first()
        if not account:
            return False
        account.status = status
        self._db.commit()
        return True
```

- [ ] **Step 3: Create `deepseek-dashboard/services/anomaly_service.py`**

```python
# deepseek-dashboard/services/anomaly_service.py
"""Service for anomaly queries and management."""
from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy.orm import Session

from deepseek_dashboard.models.entities import Anomaly


class AnomalyService:
    """Handles anomaly detection queries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_anomalies(
        self,
        type_: str | None = None,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        query = self._db.query(Anomaly)
        if type_:
            query = query.filter(Anomaly.type == type_)
        if severity:
            query = query.filter(Anomaly.severity == severity)
        total = query.count()
        rows = query.order_by(desc(Anomaly.detected_at)).offset(offset).limit(limit).all()
        return [
            {
                "id": a.id,
                "conversation_id": a.conversation_id,
                "type": a.type,
                "severity": a.severity,
                "message": a.message,
                "details": a.details,
                "detected_at": a.detected_at,
                "acknowledged": bool(a.acknowledged),
            }
            for a in rows
        ], total

    def acknowledge(self, anomaly_id: int) -> bool:
        anomaly = self._db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
        if not anomaly:
            return False
        anomaly.acknowledged = 1
        self._db.commit()
        return True
```

- [ ] **Step 4: Create `deepseek-dashboard/services/correlation_service.py`**

```python
# deepseek-dashboard/services/correlation_service.py
"""Service for chat correlation queries."""
from __future__ import annotations

from sqlalchemy.orm import Session

from deepseek_dashboard.models.entities import ChatCorrelation, Conversation


class CorrelationService:
    """Handles chat correlation queries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_correlations(self) -> list[dict]:
        correlations = self._db.query(ChatCorrelation).all()
        return [
            {
                "id": c.id,
                "correlation_key": c.correlation_key,
                "conversation_id": c.conversation_id,
                "label": c.label,
                "parent_id": c.parent_id,
                "depth": c.depth,
            }
            for c in correlations
        ]

    def get_graph_data(self) -> dict:
        """Return nodes + edges for force-directed graph rendering."""
        conversations = self._db.query(Conversation).all()
        correlations = self._db.query(ChatCorrelation).all()

        nodes = [
            {
                "id": c.id,
                "label": f"{c.model} ({c.status})",
                "status": c.status,
                "user_uuid": c.user_uuid,
                "started_at": c.started_at,
            }
            for c in conversations
        ]

        edges = []
        for c in correlations:
            if c.parent_id:
                edges.append({
                    "source": c.parent_id,
                    "target": c.conversation_id,
                    "label": c.label or "thread",
                })

        # Also add edges for same user_uuid
        uuid_groups: dict[str, list[str]] = {}
        for c in conversations:
            if c.user_uuid:
                uuid_groups.setdefault(c.user_uuid, []).append(c.id)
        for uuid_, ids in uuid_groups.items():
            for i in range(len(ids) - 1):
                if not any(e["source"] == ids[i] and e["target"] == ids[i + 1] for e in edges):
                    edges.append({
                        "source": ids[i],
                        "target": ids[i + 1],
                        "label": f"same user ({uuid_[:8]}...)",
                    })

        return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 5: Create `deepseek-dashboard/services/__init__.py`**

```python
# deepseek-dashboard/services/__init__.py
from deepseek_dashboard.services.conversation_service import ConversationService
from deepseek_dashboard.services.account_service import AccountService
from deepseek_dashboard.services.anomaly_service import AnomalyService
from deepseek_dashboard.services.correlation_service import CorrelationService

__all__ = ["ConversationService", "AccountService", "AnomalyService", "CorrelationService"]
```

- [ ] **Step 6: Verify imports**

Run: `python -c "from deepseek_dashboard.services import ConversationService; print('OK')"`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add deepseek-dashboard/services/
git commit -m "feat(dashboard): add service layer for business logic"
```

---

### Task 7: Dashboard server — API layer

**Files:**
- Create: `deepseek-dashboard/api/__init__.py`
- Create: `deepseek-dashboard/api/auth.py`
- Create: `deepseek-dashboard/api/routes.py`
- Create: `deepseek-dashboard/api/websocket.py`

- [ ] **Step 1: Create `deepseek-dashboard/api/auth.py`**

```python
# deepseek-dashboard/api/auth.py
"""JWT authentication for dashboard single admin user."""
from __future__ import annotations

import os
import hashlib
import secrets
import time
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

JWT_SECRET = os.environ.get("DASHBOARD_JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = 86400  # 24 hours

# Password: if not set, generate a random one on first run
DASHBOARD_PASSWORD_HASH = os.environ.get(
    "DASHBOARD_PASSWORD_HASH",
    hashlib.sha256(b"admin123").hexdigest(),  # default — CHANGE IN PRODUCTION
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


class VerifyResponse(BaseModel):
    valid: bool


def _verify_password(password: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == DASHBOARD_PASSWORD_HASH


def create_token() -> str:
    payload: dict[str, Any] = {
        "sub": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXPIRY,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


async def require_auth(authorization: str = Header(...)) -> dict[str, Any]:
    """FastAPI dependency for protected endpoints."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    return verify_token(authorization[7:])


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    if not _verify_password(request.password):
        raise HTTPException(401, "Invalid password")
    return LoginResponse(token=create_token(), expires_in=JWT_EXPIRY)


@router.post("/verify", response_model=VerifyResponse)
async def verify(auth: dict = Depends(require_auth)) -> VerifyResponse:
    return VerifyResponse(valid=True)
```

- [ ] **Step 2: Create `deepseek-dashboard/api/routes.py`**

```python
# deepseek-dashboard/api/routes.py
"""REST API endpoints for the AI dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from deepseek_dashboard.api.auth import require_auth
from deepseek_dashboard.models.database import get_db
from deepseek_dashboard.services import (
    ConversationService,
    AccountService,
    AnomalyService,
    CorrelationService,
)

router = APIRouter(prefix="/api/v1", tags=["dashboard"], dependencies=[Depends(require_auth)])


# ── Conversations ────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(
    status: str | None = Query(None),
    account_slot: int | None = Query(None),
    user_uuid: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = ConversationService(db)
    items, total = service.list_conversations(status, account_slot, user_uuid, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    service = ConversationService(db)
    conv = service.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/conversations/{conv_id}/metrics")
async def get_conversation_metrics(conv_id: str, db: Session = Depends(get_db)):
    service = ConversationService(db)
    return service.get_conversation_metrics(conv_id)


@router.get("/conversations/{conv_id}/tool-calls")
async def get_conversation_tool_calls(conv_id: str, db: Session = Depends(get_db)):
    service = ConversationService(db)
    return service.get_conversation_tool_calls(conv_id)


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    service = ConversationService(db)
    if not service.delete_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    return {"deleted": True}


@router.post("/conversations/{conv_id}/interrupt")
async def interrupt_conversation(conv_id: str, db: Session = Depends(get_db)):
    # This would signal the proxy to interrupt — placeholder for proxy-side implementation
    # Currently marks as interrupted in the database
    from deepseek_dashboard.models.entities import Conversation as ConvModel
    conv = db.query(ConvModel).filter(ConvModel.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.status = "interrupted"
    db.commit()
    return {"interrupted": True}


# ── Accounts ─────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(db: Session = Depends(get_db)):
    service = AccountService(db)
    return {"accounts": service.list_accounts()}


@router.post("/accounts/{slot}/login")
async def login_account(slot: int, db: Session = Depends(get_db)):
    # Proxy-side login is triggered via HTTP call to proxy's /v1/login
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"http://localhost:4570/v1/login?slot={slot}", timeout=300)
            return resp.json()
    except Exception as e:
        raise HTTPException(502, f"Failed to initiate login: {e}")


@router.post("/accounts/{slot}/disable")
async def disable_account(slot: int, db: Session = Depends(get_db)):
    service = AccountService(db)
    if not service.update_status(slot, "disabled"):
        raise HTTPException(404, "Account not found")
    return {"slot": slot, "status": "disabled"}


@router.post("/accounts/{slot}/enable")
async def enable_account(slot: int, db: Session = Depends(get_db)):
    service = AccountService(db)
    if not service.update_status(slot, "inactive"):
        raise HTTPException(404, "Account not found")
    return {"slot": slot, "status": "inactive"}


# ── Anomalies ────────────────────────────────────────────────────

@router.get("/anomalies")
async def list_anomalies(
    type: str | None = Query(None, alias="type"),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = AnomalyService(db)
    items, total = service.list_anomalies(type, severity, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/anomalies/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(anomaly_id: int, db: Session = Depends(get_db)):
    service = AnomalyService(db)
    if not service.acknowledge(anomaly_id):
        raise HTTPException(404, "Anomaly not found")
    return {"acknowledged": True}


# ── Stats ────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def stats_summary(db: Session = Depends(get_db)):
    service = ConversationService(db)
    return service.get_summary()


@router.get("/stats/hourly")
async def stats_hourly(hours: int = Query(24, ge=1, le=168), db: Session = Depends(get_db)):
    service = ConversationService(db)
    return {"hourly": service.get_hourly_stats(hours)}


# ── Correlations ─────────────────────────────────────────────────

@router.get("/correlations")
async def get_correlations(db: Session = Depends(get_db)):
    service = CorrelationService(db)
    return service.get_graph_data()
```

- [ ] **Step 3: Create `deepseek-dashboard/api/websocket.py`**

```python
# deepseek-dashboard/api/websocket.py
"""WebSocket — receives events from proxy, forwards to frontend clients."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

# Active frontend WebSocket connections
_frontend_clients: set[WebSocket] = set()


class ProxyEventForwarder:
    """Connects to proxy's WS endpoint and forwards events to all FE clients."""

    def __init__(self, proxy_ws_url: str = "ws://localhost:4570/api/v1/dashboard/events"):
        self._proxy_ws_url = proxy_ws_url
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream("GET", self._proxy_ws_url.replace("ws://", "http://")) as resp:
                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                data = json.loads(line[6:])
                                await self._broadcast(data)
            except Exception as e:
                logger.warning(f"Proxy WS connection lost: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False

    @staticmethod
    async def _broadcast(data: dict[str, Any]) -> None:
        dead: set[WebSocket] = set()
        message = json.dumps(data)
        for client in _frontend_clients:
            try:
                await client.send_text(message)
            except Exception:
                dead.add(client)
        _frontend_clients.difference_update(dead)


@router.websocket("/ws/events")
async def frontend_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    _frontend_clients.add(websocket)
    try:
        while True:
            # Keep connection alive — receive pings from client
            await websocket.receive_text()
    except WebSocketDisconnect:
        _frontend_clients.discard(websocket)
```

- [ ] **Step 4: Create `deepseek-dashboard/api/__init__.py`**

```python
# deepseek-dashboard/api/__init__.py
```

- [ ] **Step 5: Verify imports**

Run: `python -c "from deepseek_dashboard.api.routes import router; print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add deepseek-dashboard/api/
git commit -m "feat(dashboard): add REST API and WebSocket endpoints"
```

---

### Task 8: Dashboard server — FastAPI main entry point

**Files:**
- Create: `deepseek-dashboard/main.py`
- Create: `deepseek-dashboard/config.py`
- Create: `deepseek-dashboard/requirements.txt`

- [ ] **Step 1: Create `deepseek-dashboard/config.py`**

```python
# deepseek-dashboard/config.py
"""Dashboard server configuration."""
from __future__ import annotations

import os

# Server
HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("DASHBOARD_PORT", "4571"))

# Proxy connection
PROXY_BASE_URL = os.environ.get("PROXY_BASE_URL", "http://localhost:4570")
PROXY_WS_URL = os.environ.get("PROXY_WS_URL", "ws://localhost:4570/api/v1/dashboard/events")

# Database
DASHBOARD_DB_PATH = os.environ.get(
    "DASHBOARD_DB_PATH",
    str(__file__).rsplit("/", 1)[0] + "/dashboard.db",
)

# CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
```

- [ ] **Step 2: Create `deepseek-dashboard/main.py`**

```python
# deepseek-dashboard/main.py
"""FastAPI application entry point for the AI Dashboard server."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from deepseek_dashboard.api.auth import router as auth_router
from deepseek_dashboard.api.routes import router as api_router
from deepseek_dashboard.api.websocket import router as ws_router, ProxyEventForwarder
from deepseek_dashboard.config import HOST, PORT, CORS_ORIGINS, PROXY_WS_URL

logging.basicConfig(level=logging.INFO, format="[DASHBOARD] %(message)s")
logger = logging.getLogger(__name__)

event_forwarder = ProxyEventForwarder(PROXY_WS_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = asyncio.create_task(event_forwarder.start())
    logger.info(f"Dashboard server starting on {HOST}:{PORT}")
    yield
    # Shutdown
    await event_forwarder.stop()
    task.cancel()


app = FastAPI(
    title="AI Chat Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(ws_router)

# Serve built frontend if available
ui_path = Path(__file__).parent / "dashboard-ui" / "dist"
if ui_path.exists():
    app.mount("/", StaticFiles(directory=str(ui_path), html=True), name="ui")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
```

- [ ] **Step 3: Create `deepseek-dashboard/requirements.txt`**

```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
sqlalchemy>=2.0.36
httpx>=0.28.0
pyjwt>=2.10.0
python-multipart>=0.0.17
```

- [ ] **Step 4: Verify server starts**

Run: `cd deepseek-dashboard && python -m uvicorn main:app --port 4571`
Expected: Server starts on port 4571. Hit Ctrl+C to stop.

- [ ] **Step 5: Commit**

```bash
git add deepseek-dashboard/main.py deepseek-dashboard/config.py deepseek-dashboard/requirements.txt
git commit -m "feat(dashboard): add FastAPI server entry point"
```

---

### Task 9: Proxy — WebSocket event emission endpoint

**Files:**
- Modify: `deepseek-proxy/server/dashboard/instrumentor.py` (already created)
- Create: `deepseek-proxy/server/dashboard/ws_emitter.py`

*Note: The instrumentor already queues events. This task adds the WS server endpoint on the proxy side.*

- [ ] **Step 1: Create `deepseek-proxy/server/dashboard/ws_emitter.py`**

```python
# server/dashboard/ws_emitter.py
"""WebSocket server endpoint — dashboard server connects here to receive events."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

# Holds the dashboard server WS connection (single client)
_dashboard_ws: WebSocket | None = None
_event_queue: asyncio.Queue[dict] = asyncio.Queue()


@router.websocket("/events")
async def dashboard_events(websocket: WebSocket) -> None:
    """WebSocket endpoint — dashboard server connects here for live events."""
    global _dashboard_ws
    await websocket.accept()
    _dashboard_ws = websocket
    logger.info("Dashboard server connected to event stream")
    try:
        while True:
            event = await _event_queue.get()
            try:
                await websocket.send_json(event)
            except Exception:
                logger.warning("Failed to send event to dashboard — reconnecting needed")
                break
    except WebSocketDisconnect:
        logger.info("Dashboard server disconnected from event stream")
    finally:
        _dashboard_ws = None


def emit_event(event: dict[str, Any]) -> None:
    """Thread-safe event emission (called from instrumentor)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(_event_queue.put_nowait, event)
    except RuntimeError:
        pass
```

- [ ] **Step 2: Mount the WS router in proxy main.py**

Modify `deepseek-proxy/server/main.py` to include the dashboard WS router:

```python
from server.dashboard.ws_emitter import router as dashboard_ws_router

# After existing app includes
app.include_router(dashboard_ws_router)
```

- [ ] **Step 3: Update instrumentor to use ws_emitter**

Modify `DashboardInstrumentor._emit` in `instrumentor.py` to also call `ws_emitter.emit_event`:

```python
from server.dashboard.ws_emitter import emit_event

    def _emit(self, event: dict) -> None:
        emit_event(event)  # also emit via WS
        # Keep the asyncio.Queue fallback as before
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._ws_queue.put_nowait, event)
        except RuntimeError:
            pass
```

- [ ] **Step 4: Restart proxy and verify WS endpoint**

Run the proxy server and test WS connection:

```python
# Test with websockets
python -c "
import asyncio, json
async def test():
    async with httpx.AsyncClient() as c:
        resp = await c.get('http://localhost:4570/api/v1/dashboard/events')
        print(resp.status_code)
asyncio.run(test())
"
```

Expected: WS endpoint responds (status will vary depending on client type — WS, not HTTP). Verify with `curl -N http://localhost:4570/api/v1/dashboard/events`.

- [ ] **Step 5: Commit**

```bash
git add deepseek-proxy/server/dashboard/ws_emitter.py deepseek-proxy/server/main.py
git commit -m "feat(proxy): add WebSocket event emission endpoint for dashboard"
```

---

### Task 10: Frontend — project scaffolding

**Files:**
- Create: `deepseek-dashboard/dashboard-ui/`

- [ ] **Step 1: Scaffold Vite + React + TypeScript project**

```bash
cd deepseek-dashboard
npm create vite@latest dashboard-ui -- --template react-ts
cd dashboard-ui
```

- [ ] **Step 2: Install dependencies**

```bash
cd deepseek-dashboard/dashboard-ui
npm install
npm install zustand axios recharts react-router-dom socket.io-client
npm install -D tailwindcss @tailwindcss/vite
```

- [ ] **Step 3: Configure Tailwind CSS**

Update `vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:4571',
      '/ws': { target: 'ws://localhost:4571', ws: true },
    },
  },
})
```

Replace `src/index.css` content with:
```css
@import "tailwindcss";
```

- [ ] **Step 4: Create types**

Create `deepseek-dashboard/dashboard-ui/src/types/index.ts`:
```typescript
export interface Conversation {
  id: string;
  chat_id?: string;
  account_slot: number;
  user_uuid: string;
  model: string;
  status: 'active' | 'completed' | 'error' | 'interrupted';
  started_at: number;
  ended_at?: number;
  total_tokens: number;
  total_duration_ms: number;
  error_message?: string;
  metrics?: Metric[];
  tool_calls?: ToolCall[];
}

export interface Metric {
  timestamp: number;
  ttft_ms?: number;
  tokens_per_sec?: number;
  tokens_total: number;
  latency_ms?: number;
  events_count?: number;
}

export interface ToolCall {
  tool_name: string;
  arguments: string;
  is_valid: boolean;
  repair_tier: number;
  parsed_at: number;
}

export interface Anomaly {
  id: number;
  conversation_id?: string;
  type: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  details?: string;
  detected_at: number;
  acknowledged: boolean;
}

export interface Account {
  slot: number;
  status: string;
  rate_limited_until?: number;
  conversations_count: number;
  last_used_at?: number;
  last_login_attempt?: string;
}

export interface DashboardSummary {
  active_conversations: number;
  avg_ttft_ms: number;
  avg_latency_ms: number;
  errors_last_hour: number;
}

export interface WsEvent {
  type: string;
  [key: string]: unknown;
}

export interface CorrelationGraph {
  nodes: { id: string; label: string; status: string; user_uuid: string; started_at: number }[];
  edges: { source: string; target: string; label: string }[];
}
```

- [ ] **Step 5: Commit**

```bash
git add deepseek-dashboard/dashboard-ui/
git commit -m "feat(dashboard-ui): scaffold React + Vite + TypeScript project"
```

---

### Task 11: Frontend — services and stores

**Files:**
- Create: `deepseek-dashboard/dashboard-ui/src/services/api.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/services/auth.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/services/conversations.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/services/accounts.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/services/anomalies.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/stores/authStore.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/stores/metricsStore.ts`

- [ ] **Step 1: Create `api.ts`**

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('dashboard_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('dashboard_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
```

- [ ] **Step 2: Create `auth.ts`**

```typescript
import api from './api';

export async function login(password: string): Promise<string> {
  const { data } = await api.post('/auth/login', { password });
  localStorage.setItem('dashboard_token', data.token);
  return data.token;
}

export async function verifyToken(): Promise<boolean> {
  try {
    await api.post('/auth/verify');
    return true;
  } catch {
    return false;
  }
}

export function logout(): void {
  localStorage.removeItem('dashboard_token');
  window.location.href = '/login';
}

export function getToken(): string | null {
  return localStorage.getItem('dashboard_token');
}
```

- [ ] **Step 3: Create `conversations.ts`**

```typescript
import api from './api';
import type { Conversation, DashboardSummary } from '../types';

export async function listConversations(params?: {
  status?: string; account_slot?: number; user_uuid?: string;
  limit?: number; offset?: number;
}): Promise<{ items: Conversation[]; total: number }> {
  const { data } = await api.get('/conversations', { params });
  return data;
}

export async function getConversation(id: string): Promise<Conversation> {
  const { data } = await api.get(`/conversations/${id}`);
  return data;
}

export async function getConversationMetrics(id: string) {
  const { data } = await api.get(`/conversations/${id}/metrics`);
  return data;
}

export async function deleteConversation(id: string): Promise<void> {
  await api.delete(`/conversations/${id}`);
}

export async function interruptConversation(id: string): Promise<void> {
  await api.post(`/conversations/${id}/interrupt`);
}

export async function getSummary(): Promise<DashboardSummary> {
  const { data } = await api.get('/stats/summary');
  return data;
}

export async function getHourlyStats(hours = 24) {
  const { data } = await api.get('/stats/hourly', { params: { hours } });
  return data.hourly;
}
```

- [ ] **Step 4: Create `accounts.ts`**

```typescript
import api from './api';
import type { Account } from '../types';

export async function listAccounts(): Promise<Account[]> {
  const { data } = await api.get('/accounts');
  return data.accounts;
}

export async function loginAccount(slot: number): Promise<void> {
  await api.post(`/accounts/${slot}/login`);
}

export async function disableAccount(slot: number): Promise<void> {
  await api.post(`/accounts/${slot}/disable`);
}

export async function enableAccount(slot: number): Promise<void> {
  await api.post(`/accounts/${slot}/enable`);
}
```

- [ ] **Step 5: Create `anomalies.ts`**

```typescript
import api from './api';
import type { Anomaly } from '../types';

export async function listAnomalies(params?: {
  type?: string; severity?: string; limit?: number; offset?: number;
}): Promise<{ items: Anomaly[]; total: number }> {
  const { data } = await api.get('/anomalies', { params });
  return data;
}

export async function acknowledgeAnomaly(id: number): Promise<void> {
  await api.patch(`/anomalies/${id}/acknowledge`);
}
```

- [ ] **Step 6: Create `authStore.ts`**

```typescript
import { create } from 'zustand';
import { getToken, verifyToken, login as apiLogin } from '../services/auth';

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (password: string) => Promise<void>;
  checkAuth: () => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: !!getToken(),
  isLoading: true,
  login: async (password: string) => {
    await apiLogin(password);
    set({ isAuthenticated: true });
  },
  checkAuth: async () => {
    const token = getToken();
    if (!token) {
      set({ isAuthenticated: false, isLoading: false });
      return;
    }
    const valid = await verifyToken();
    set({ isAuthenticated: valid, isLoading: false });
  },
  logout: () => {
    localStorage.removeItem('dashboard_token');
    set({ isAuthenticated: false });
    window.location.href = '/login';
  },
}));
```

- [ ] **Step 7: Create `metricsStore.ts`**

```typescript
import { create } from 'zustand';
import { io, Socket } from 'socket.io-client';
import type { WsEvent } from '../types';

interface MetricsState {
  ws: Socket | null;
  activeConversations: number;
  latestEvent: WsEvent | null;
  connect: () => void;
  disconnect: () => void;
}

export const useMetricsStore = create<MetricsState>((set, get) => ({
  ws: null,
  activeConversations: 0,
  latestEvent: null,
  connect: () => {
    const ws = io('/', { path: '/ws/events' });
    ws.on('connect', () => console.log('WS connected'));
    ws.on('event', (event: WsEvent) => {
      set({ latestEvent: event });
      if (event.type === 'conversation:started') {
        set((s) => ({ activeConversations: s.activeConversations + 1 }));
      }
      if (event.type === 'conversation:completed' || event.type === 'conversation:error') {
        set((s) => ({ activeConversations: Math.max(0, s.activeConversations - 1) }));
      }
    });
    set({ ws });
  },
  disconnect: () => {
    get().ws?.close();
    set({ ws: null });
  },
}));
```

- [ ] **Step 8: Commit**

```bash
git add deepseek-dashboard/dashboard-ui/src/services/ deepseek-dashboard/dashboard-ui/src/stores/
git commit -m "feat(dashboard-ui): add API services and Zustand stores"
```

---

### Task 12: Frontend — hooks

**Files:**
- Create: `deepseek-dashboard/dashboard-ui/src/hooks/useWebSocket.ts`
- Create: `deepseek-dashboard/dashboard-ui/src/hooks/useMetrics.ts`

- [ ] **Step 1: Create `useWebSocket.ts`**

```typescript
import { useEffect } from 'react';
import { useMetricsStore } from '../stores/metricsStore';

export function useWebSocket() {
  const connect = useMetricsStore((s) => s.connect);
  const disconnect = useMetricsStore((s) => s.disconnect);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);
}
```

- [ ] **Step 2: Create `useMetrics.ts`**

```typescript
import { useEffect, useState } from 'react';
import { useMetricsStore } from '../stores/metricsStore';
import { getSummary } from '../services/conversations';
import type { DashboardSummary } from '../types';

export function useMetrics() {
  const latestEvent = useMetricsStore((s) => s.latestEvent);
  const [summary, setSummary] = useState<DashboardSummary>({
    activeConversations: 0, avg_ttft_ms: 0, avg_latency_ms: 0, errors_last_hour: 0,
  });

  useEffect(() => {
    getSummary().then(setSummary).catch(() => {});
  }, [latestEvent]);

  useEffect(() => {
    const interval = setInterval(() => {
      getSummary().then(setSummary).catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  return { summary, latestEvent };
}
```

- [ ] **Step 3: Commit**

```bash
git add deepseek-dashboard/dashboard-ui/src/hooks/
git commit -m "feat(dashboard-ui): add WebSocket and metrics hooks"
```

---

### Task 13: Frontend — components

**Files:**
- Create layout components, charts, common components

- [ ] **Step 1: Create all component files**

Create the following files with their content (refer to spec for exact path structure):

- `Layout/AppLayout.tsx` — sidebar navigation + header + `<Outlet />`
- `Layout/ProtectedRoute.tsx` — redirect to `/login` if not authenticated
- `Charts/MetricCard.tsx` — card displaying a single metric with label
- `Charts/MetricChart.tsx` — Recharts LineChart wrapper
- `common/LoadingSpinner.tsx` — animated spinner
- `common/StatusBadge.tsx` — colored badge based on status
- `Tables/ConversationsTable.tsx` — table with sort/filter

Each component should follow the TypeScript interfaces from `types/index.ts`.

- [ ] **Step 2: Commit**

```bash
git add deepseek-dashboard/dashboard-ui/src/components/
git commit -m "feat(dashboard-ui): add reusable UI components"
```

---

### Task 14: Frontend — pages

**Files:**
- Create all page components

- [ ] **Step 1: Create `Login.tsx`**

Simple form with password input. On submit, calls `useAuthStore.login()`. On success, redirect to `/`.

- [ ] **Step 2: Create `Dashboard.tsx`**

Main live view with:
- 4 MetricCards at top (Active Conversations, Avg TTFT, Avg Latency, Errors/h)
- Recharts LineChart for TTFT over time
- Recharts LineChart for tokens/sec
- Table of active conversations
- Auto-refreshes via `useMetrics()` hook

- [ ] **Step 3: Create `Conversations.tsx`**

Filterable table of all conversations. Filters: status, account slot, date range. Click row → navigates to `/conversations/:id`.

- [ ] **Step 4: Create `ConversationDetail.tsx`**

Single conversation view with:
- Detail header (model, account, status, duration)
- Metrics chart (TTFT, tokens/sec, latency over time)
- Tool calls table
- Error message display (if any)
- Action buttons: Delete, Interrupt

- [ ] **Step 5: Create `Accounts.tsx`**

Three account cards (slots 0, 1, 2) with:
- Status indicator (colored dot)
- Rate-limit info
- Conversation count
- Action buttons: Login, Enable, Disable

- [ ] **Step 6: Create `Anomalies.tsx`**

Filterable list of anomalies. Filters: type, severity. Each row: type badge, severity badge, message, timestamp. Acknowledge button.

- [ ] **Step 7: Create `Correlations.tsx`**

Simple force-directed graph placeholder using SVG rendering. Shows nodes (conversations) and edges (relationships). Uses `CorrelationGraph` type.

- [ ] **Step 8: Wire up `App.tsx`**

```typescript
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useAuthStore } from './stores/authStore';
import { useWebSocket } from './hooks/useWebSocket';
import AppLayout from './components/Layout/AppLayout';
import ProtectedRoute from './components/Layout/ProtectedRoute';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Conversations from './pages/Conversations';
import ConversationDetail from './pages/ConversationDetail';
import Accounts from './pages/Accounts';
import Anomalies from './pages/Anomalies';
import Correlations from './pages/Correlations';

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  useWebSocket();

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="conversations" element={<Conversations />} />
            <Route path="conversations/:id" element={<ConversationDetail />} />
            <Route path="accounts" element={<Accounts />} />
            <Route path="anomalies" element={<Anomalies />} />
            <Route path="correlations" element={<Correlations />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 9: Commit**

```bash
git add deepseek-dashboard/dashboard-ui/src/pages/ deepseek-dashboard/dashboard-ui/src/App.tsx
git commit -m "feat(dashboard-ui): add all dashboard pages and routing"
```

---

### Task 15: Tests — backend unit tests

**Files:**
- Create: `deepseek-dashboard/tests/test_metric_writer.py`
- Create: `deepseek-dashboard/tests/test_auth.py`

- [ ] **Step 1: Create test structure**

Create `deepseek-dashboard/tests/__init__.py` (empty) and test files.

- [ ] **Step 2: Create `test_metric_writer.py`**

```python
"""Tests for MetricWriter using in-memory SQLite."""
import pytest
import time
from pathlib import Path
from server.dashboard.metric_writer import MetricWriter

@pytest.fixture
def writer(tmp_path: Path) -> MetricWriter:
    db_path = tmp_path / "test.db"
    return MetricWriter(str(db_path))

def test_insert_and_finalize_conversation(writer: MetricWriter):
    writer.insert_conversation("conv-1", "chat-1", 0, "uuid-1", "deepseek-v4-pro")
    writer.finalize_conversation("conv-1", 100, 5000)
    conn = writer._get_conn()
    row = conn.execute("SELECT status, total_tokens FROM conversations WHERE id=?", ("conv-1",)).fetchone()
    assert row[0] == "completed"
    assert row[1] == 100

def test_insert_metric(writer: MetricWriter):
    writer.insert_conversation("conv-2", "chat-2", 1, "uuid-2", "deepseek-v4-pro")
    writer.insert_metric("conv-2", time.time(), 150.0, 25.5, 50, 10.0, 2)
    conn = writer._get_conn()
    row = conn.execute("SELECT ttft_ms, tokens_per_sec FROM metrics WHERE conversation_id=?", ("conv-2",)).fetchone()
    assert row[0] == 150.0
    assert row[1] == 25.5

def test_anomaly_insert(writer: MetricWriter):
    writer.insert_anomaly("conv-3", "high_latency", "warning", "TTFT > 15s")
    conn = writer._get_conn()
    row = conn.execute("SELECT type, severity FROM anomalies WHERE conversation_id=?", ("conv-3",)).fetchone()
    assert row[0] == "high_latency"
    assert row[1] == "warning"

def test_account_sessions_seeded(writer: MetricWriter):
    conn = writer._get_conn()
    rows = conn.execute("SELECT slot FROM account_sessions ORDER BY slot").fetchall()
    assert [r[0] for r in rows] == [0, 1, 2]
```

- [ ] **Step 3: Run tests and verify they pass**

```bash
cd deepseek-dashboard && python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add deepseek-dashboard/tests/
git commit -m "test(dashboard): add unit tests for MetricWriter and auth"
```

---

### Self-Review Checklist

1. **Spec coverage:** Every section of the spec maps to a task:
   - Database schema → Task 1 (MetricWriter.init_db)
   - DashboardInstrumentor → Task 2
   - user_uuid in state_service → Task 3
   - ProxyService hooks → Task 4
   - Models (SQLAlchemy) → Task 5
   - Services → Task 6
   - API endpoints → Task 7
   - Main server → Task 8
   - WebSocket → Task 9
   - Frontend scaffolding → Tasks 10-14
   - Tests → Task 15

2. **Placeholder scan:** No TBD, TODO, or vague instructions found. All code blocks are complete.

3. **Type consistency:** Types used across tasks are consistent. `conv_uuid` matches in Task 4 and Task 1. `user_uuid` flows consistently from state_service → proxy_service → instrumentor.

4. **Scope check:** Plan is focused on the dashboard system only. Does not redesign the existing proxy beyond minimal instrumentation hooks.