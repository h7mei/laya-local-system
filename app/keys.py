"""SQLite-backed secrets for the local Laya server (API key + ngrok token).

Values live in the same DB file as usage stats. Environment variables are used
as a bootstrap seed when the DB row is empty; once set via the web UI, SQLite
is the source of truth for runtime auth and tunnels.
"""

from __future__ import annotations

import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from app import usage_db

API_KEY = "api_key"
NGROK_TOKEN = "ngrok_authtoken"

_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_INITIALIZED = False


def init() -> None:
    global _INITIALIZED
    usage_db.init()
    with usage_db._LOCK:
        if _INITIALIZED:
            return
        with usage_db._connect() as conn:
            conn.executescript(_SETTINGS_SCHEMA)
            conn.commit()
        _INITIALIZED = True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def get_raw(key: str) -> Optional[str]:
    init()
    with usage_db._LOCK:
        with usage_db._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
    if row is None:
        return None
    value = (row["value"] or "").strip()
    return value or None


def set_raw(key: str, value: str) -> None:
    init()
    cleaned = (value or "").strip()
    if not cleaned:
        clear_raw(key)
        return
    with usage_db._LOCK:
        with usage_db._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, cleaned, _now()),
            )
            conn.commit()


def clear_raw(key: str) -> None:
    init()
    with usage_db._LOCK:
        with usage_db._connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()


def bootstrap_from_env() -> None:
    """Copy env keys into SQLite when the DB row is still empty."""
    init()
    env_api = (os.environ.get("LAYA_API_KEY") or "").strip()
    if env_api and not get_raw(API_KEY):
        set_raw(API_KEY, env_api)
    env_ngrok = (os.environ.get("NGROK_AUTHTOKEN") or "").strip()
    if env_ngrok and not get_raw(NGROK_TOKEN):
        set_raw(NGROK_TOKEN, env_ngrok)


def sync_env() -> None:
    """Mirror SQLite values into process env for libraries that read os.environ."""
    api = get_raw(API_KEY)
    if api:
        os.environ["LAYA_API_KEY"] = api
    else:
        os.environ.pop("LAYA_API_KEY", None)

    ngrok = get_raw(NGROK_TOKEN)
    if ngrok:
        os.environ["NGROK_AUTHTOKEN"] = ngrok


def get_api_key() -> Optional[str]:
    return get_raw(API_KEY) or ((os.environ.get("LAYA_API_KEY") or "").strip() or None)


def get_ngrok_token() -> Optional[str]:
    return get_raw(NGROK_TOKEN) or ((os.environ.get("NGROK_AUTHTOKEN") or "").strip() or None)


def set_api_key(value: str) -> str:
    set_raw(API_KEY, value)
    cleaned = (value or "").strip()
    if cleaned:
        os.environ["LAYA_API_KEY"] = cleaned
    else:
        os.environ.pop("LAYA_API_KEY", None)
    return cleaned


def clear_api_key() -> None:
    clear_raw(API_KEY)
    os.environ.pop("LAYA_API_KEY", None)


def generate_api_key() -> str:
    token = secrets.token_urlsafe(32)
    set_api_key(token)
    return token


def set_ngrok_token(value: str) -> str:
    set_raw(NGROK_TOKEN, value)
    cleaned = (value or "").strip()
    if cleaned:
        os.environ["NGROK_AUTHTOKEN"] = cleaned
    else:
        os.environ.pop("NGROK_AUTHTOKEN", None)
    return cleaned


def clear_ngrok_token() -> None:
    clear_raw(NGROK_TOKEN)
    os.environ.pop("NGROK_AUTHTOKEN", None)


def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def status() -> dict[str, Any]:
    api = get_api_key()
    ngrok = get_ngrok_token()
    return {
        "api_key": {
            "configured": bool(api),
            "masked": _mask(api),
            "source": "sqlite" if get_raw(API_KEY) else ("env" if api else None),
        },
        "ngrok_authtoken": {
            "configured": bool(ngrok),
            "masked": _mask(ngrok),
            "source": "sqlite" if get_raw(NGROK_TOKEN) else ("env" if ngrok else None),
        },
        "db_path": str(usage_db.db_path()),
    }


def api_key_matches(authorization: Optional[str]) -> bool:
    """Constant-time compare of Authorization header against the configured API key."""
    api_key = get_api_key()
    if not api_key:
        return True
    expected = f"Bearer {api_key}".encode("utf-8", "surrogateescape")
    supplied = (authorization or "").encode("utf-8", "surrogateescape")
    return hmac.compare_digest(supplied, expected)
