"""SQLite-backed request usage log for the local Laya server."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_INITIALIZED = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    question_count INTEGER NOT NULL DEFAULT 0,
    client_host TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_request_log_created_at ON request_log(created_at);
CREATE INDEX IF NOT EXISTS idx_request_log_model ON request_log(model);
"""


def db_path() -> Path:
    raw = (os.environ.get("LAYA_USAGE_DB") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    root = Path(__file__).resolve().parent.parent
    return (root / "data" / "usage.sqlite").resolve()


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> Path:
    """Ensure the database file and schema exist. Safe to call repeatedly."""
    global _INITIALIZED
    path = db_path()
    with _LOCK:
        if _INITIALIZED and path.exists():
            return path
        with _connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        _INITIALIZED = True
    return path


def record(
    *,
    status_code: int,
    duration_ms: float,
    model: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    question_count: int = 0,
    client_host: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Insert one predict request row. Failures are swallowed so logging never breaks inference."""
    try:
        init()
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with _LOCK:
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO request_log (
                        created_at, status_code, duration_ms, model,
                        input_tokens, output_tokens, question_count,
                        client_host, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        int(status_code),
                        float(duration_ms),
                        model,
                        int(input_tokens or 0),
                        int(output_tokens or 0),
                        int(question_count or 0),
                        client_host,
                        error,
                    ),
                )
                conn.commit()
    except Exception:
        # Usage logging must never take down the API.
        return


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status_code": row["status_code"],
        "duration_ms": row["duration_ms"],
        "model": row["model"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "question_count": row["question_count"],
        "client_host": row["client_host"],
        "error": row["error"],
    }


def stats(recent_limit: int = 25) -> dict[str, Any]:
    """Aggregate usage counters, per-model / per-day breakdowns, and recent rows."""
    init()
    limit = max(1, min(int(recent_limit), 200))
    with _LOCK:
        with _connect() as conn:
            totals_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS requests,
                    COALESCE(SUM(CASE WHEN status_code >= 200 AND status_code < 300 THEN 1 ELSE 0 END), 0) AS ok,
                    COALESCE(SUM(CASE WHEN status_code < 200 OR status_code >= 300 THEN 1 ELSE 0 END), 0) AS errors,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                    COALESCE(MAX(duration_ms), 0) AS max_duration_ms
                FROM request_log
                """
            ).fetchone()

            by_model = [
                {
                    "model": row["model"] or "unknown",
                    "requests": row["requests"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "avg_duration_ms": row["avg_duration_ms"],
                }
                for row in conn.execute(
                    """
                    SELECT
                        model,
                        COUNT(*) AS requests,
                        COALESCE(SUM(input_tokens), 0) AS input_tokens,
                        COALESCE(SUM(output_tokens), 0) AS output_tokens,
                        COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
                    FROM request_log
                    GROUP BY model
                    ORDER BY requests DESC
                    """
                ).fetchall()
            ]

            by_day = [
                {
                    "day": row["day"],
                    "requests": row["requests"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "errors": row["errors"],
                }
                for row in conn.execute(
                    """
                    SELECT
                        substr(created_at, 1, 10) AS day,
                        COUNT(*) AS requests,
                        COALESCE(SUM(input_tokens), 0) AS input_tokens,
                        COALESCE(SUM(output_tokens), 0) AS output_tokens,
                        COALESCE(SUM(CASE WHEN status_code < 200 OR status_code >= 300 THEN 1 ELSE 0 END), 0) AS errors
                    FROM request_log
                    GROUP BY day
                    ORDER BY day DESC
                    LIMIT 30
                    """
                ).fetchall()
            ]

            recent = [
                _row_to_dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM request_log
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]

    return {
        "db_path": str(db_path()),
        "totals": {
            "requests": int(totals_row["requests"] or 0),
            "ok": int(totals_row["ok"] or 0),
            "errors": int(totals_row["errors"] or 0),
            "input_tokens": int(totals_row["input_tokens"] or 0),
            "output_tokens": int(totals_row["output_tokens"] or 0),
            "avg_duration_ms": round(float(totals_row["avg_duration_ms"] or 0), 2),
            "max_duration_ms": round(float(totals_row["max_duration_ms"] or 0), 2),
        },
        "by_model": by_model,
        "by_day": list(reversed(by_day)),
        "recent": recent,
    }


def clear() -> dict[str, int]:
    """Delete all logged rows. Returns how many were removed."""
    init()
    with _LOCK:
        with _connect() as conn:
            cur = conn.execute("DELETE FROM request_log")
            conn.commit()
            return {"deleted": int(cur.rowcount or 0)}
