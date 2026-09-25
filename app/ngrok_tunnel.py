"""Optional ngrok tunnel for exposing the local Laya server publicly."""

from __future__ import annotations

import os
import threading
from typing import Any

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
    return bool((os.environ.get("NGROK_AUTHTOKEN") or "").strip())


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
    token = (os.environ.get("NGROK_AUTHTOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "NGROK_AUTHTOKEN is not set. Add it to .env from https://dashboard.ngrok.com/get-started/your-authtoken"
        )

    with _lock:
        if _state["public_url"]:
            return status()
        try:
            from pyngrok import conf, ngrok

            conf.get_default().auth_token = token
            # Free ngrok edges often need the browser warning skipped by clients;
            # the public URL itself is still the integration base.
            tunnel = ngrok.connect(addr=str(port), proto="http")
            public_url = tunnel.public_url
            if public_url.startswith("http://"):
                public_url = "https://" + public_url[len("http://") :]
            _state["public_url"] = public_url.rstrip("/")
            _state["error"] = None
            _state["enabled"] = True
        except Exception as exc:  # noqa: BLE001 — surface start failures to the UI
            _state["public_url"] = None
            _state["enabled"] = False
            _state["error"] = str(exc)
            raise RuntimeError(f"ngrok failed to start: {exc}") from exc
        return status()


def stop() -> dict[str, Any]:
    with _lock:
        try:
            from pyngrok import ngrok

            ngrok.kill()
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)
        _state["public_url"] = None
        _state["enabled"] = False
        return status()


def maybe_autostart(port: int) -> None:
    """Start ngrok during server boot when LAYA_NGROK=1."""
    if not autostart_requested():
        return
    _state["autostart"] = True
    try:
        start(port)
        print(f"ngrok public URL: {_state['public_url']}")
    except Exception as exc:  # noqa: BLE001 — do not block local serve
        print(f"ngrok autostart skipped: {exc}")
