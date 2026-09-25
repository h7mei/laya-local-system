"""Local Laya HTTP server with a web UI at ``/`` and API docs at ``/api``.

Keeps the stock ``laya-serve`` surface (``GET /health``, ``POST /v1/systemone``)
and adds integration helpers plus optional ngrok tunneling.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from laya.serve import _resolve_port, create_app

from app import ngrok_tunnel

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
API_HTML = STATIC_DIR / "api.html"

app = create_app()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _local_base() -> str:
    host = os.environ.get("LAYA_HOST", "127.0.0.1")
    # Browsers cannot use 0.0.0.0 as a client address.
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = _resolve_port()
    return f"http://{host}:{port}"


def _auth_required() -> bool:
    return bool((os.environ.get("LAYA_API_KEY") or "").strip())


def _check_tunnel_auth(authorization: Optional[str]) -> None:
    """Reuse LAYA_API_KEY for tunnel start/stop when configured."""
    api_key = (os.environ.get("LAYA_API_KEY") or "").strip()
    if not api_key:
        return
    expected = f"Bearer {api_key}"
    if (authorization or "") != expected:
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/api")
def api_docs() -> FileResponse:
    return FileResponse(API_HTML, media_type="text/html; charset=utf-8")


@app.get("/v1/integration")
def integration() -> dict[str, Any]:
    tunnel = ngrok_tunnel.status()
    public = tunnel.get("public_url")
    return {
        "base_url": _local_base(),
        "public_url": public,
        "effective_base_url": public or _local_base(),
        "auth_required": _auth_required(),
        "ngrok": tunnel,
        "endpoints": {
            "health": "GET /health",
            "predict": "POST /v1/systemone",
            "integration": "GET /v1/integration",
            "tunnel_start": "POST /v1/tunnel/start",
            "tunnel_stop": "POST /v1/tunnel/stop",
        },
    }


@app.post("/v1/tunnel/start")
def tunnel_start(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_tunnel_auth(authorization)
    try:
        return ngrok_tunnel.start(_resolve_port())
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/tunnel/stop")
def tunnel_stop(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_tunnel_auth(authorization)
    return ngrok_tunnel.stop()


def main() -> None:
    import uvicorn

    port = _resolve_port()
    ngrok_tunnel.maybe_autostart(port)
    uvicorn.run(
        app,
        host=os.environ.get("LAYA_HOST", "127.0.0.1"),
        port=port,
        log_level=os.environ.get("LAYA_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
