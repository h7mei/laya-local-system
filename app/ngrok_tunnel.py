"""Optional ngrok tunnel for exposing the local Laya server publicly."""

from __future__ import annotations

import os
import threading
from typing import Any

from app import keys

_lock = threading.Lock()
_state: dict[str, Any] = {
    "enabled": False,
    "public_url": None,
    "error": None,
    "autostart": False,
}


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def autostart_requested() -> bool:
    return _env_truthy("LAYA_NGROK")


def token_configured() -> bool:
    return bool(keys.get_ngrok_token())


def status() -> dict[str, Any]:
    with _lock:
        return {
            "enabled": bool(_state["public_url"]),
            "public_url": _state["public_url"],
            "error": _state["error"],
            "autostart": _state["autostart"] or autostart_requested(),
            "token_configured": token_configured(),
        }


def start(port: int) -> dict[str, Any]:
    """Open an HTTPS ngrok tunnel to the local server port."""
    token = keys.get_ngrok_token()
    if not token:
        raise RuntimeError(
            "NGROK_AUTHTOKEN is not set. Save it on the API page or add it to .env "
            "from https://dashboard.ngrok.com/get-started/your-authtoken"
        )

    with _lock:
        if _state["public_url"]:
            return {
                "enabled": True,
                "public_url": _state["public_url"],
                "error": _state["error"],
                "autostart": _state["autostart"] or autostart_requested(),
                "token_configured": True,
            }
        # Clear stale error while starting; do not hold the lock across
        # ngrok.connect() — that blocks /v1/integration and the UI.
        _state["error"] = None

    try:
        from pyngrok import conf, ngrok

        conf.get_default().auth_token = token
        # Free ngrok edges often need the browser warning skipped by clients;
        # the public URL itself is still the integration base.
        tunnel = ngrok.connect(addr=str(port), proto="http")
        public_url = tunnel.public_url
        if public_url.startswith("http://"):
            public_url = "https://" + public_url[len("http://") :]
        public_url = public_url.rstrip("/")
    except Exception as exc:  # noqa: BLE001 — surface start failures to the UI
        with _lock:
            _state["public_url"] = None
            _state["enabled"] = False
            _state["error"] = str(exc)
        raise RuntimeError(f"ngrok failed to start: {exc}") from exc

    with _lock:
        _state["public_url"] = public_url
        _state["error"] = None
        _state["enabled"] = True
        return {
            "enabled": True,
            "public_url": public_url,
            "error": None,
            "autostart": _state["autostart"] or autostart_requested(),
            "token_configured": True,
        }


def stop() -> dict[str, Any]:
    err: Any = None
    try:
        from pyngrok import ngrok

        ngrok.kill()
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
    with _lock:
        if err is not None:
            _state["error"] = err
        _state["public_url"] = None
        _state["enabled"] = False
        return {
            "enabled": False,
            "public_url": None,
            "error": _state["error"],
            "autostart": _state["autostart"] or autostart_requested(),
            "token_configured": token_configured(),
        }


def maybe_autostart(port: int) -> None:
    """Start ngrok during server boot when LAYA_NGROK=1."""
    if not autostart_requested():
        return
    with _lock:
        _state["autostart"] = True
    try:
        start(port)
        with _lock:
            url = _state["public_url"]
        print(f"ngrok public URL: {url}")
    except Exception as exc:  # noqa: BLE001 — do not block local serve
        print(f"ngrok autostart skipped: {exc}")
