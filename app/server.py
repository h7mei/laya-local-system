"""Local Laya HTTP server with a web UI at ``/`` and API docs at ``/api``.

Keeps the stock ``laya-serve`` surface (``GET /health``, ``POST /v1/systemone``)
and adds integration helpers, optional ngrok tunneling, SQLite usage monitor,
and SQLite-backed API / ngrok keys managed from the web UI.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from laya.serve import _resolve_port, create_app
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from app import keys, ngrok_tunnel, usage_db

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
API_HTML = STATIC_DIR / "api.html"
MONITOR_HTML = STATIC_DIR / "monitor.html"
FAVICON_SVG = STATIC_DIR / "favicon.svg"

usage_db.init()
keys.init()
keys.bootstrap_from_env()

# Stock laya-serve bakes LAYA_API_KEY into a closure at create_app() time.
# Clear it so predict auth stays dynamic via SQLite (ApiKeyAuthMiddleware).
os.environ.pop("LAYA_API_KEY", None)

app = create_app()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
keys.sync_env()


class KeyValueBody(BaseModel):
    value: str = Field(min_length=1, max_length=4096)


async def _read_response_body(response: Response) -> tuple[bytes, Response]:
    """Consume a Starlette streaming middleware response and rebuild a buffered one."""
    iterator = getattr(response, "body_iterator", None)
    if iterator is None:
        return (getattr(response, "body", None) or b""), response

    chunks: list[bytes] = []
    async for chunk in iterator:
        if isinstance(chunk, memoryview):
            chunks.append(chunk.tobytes())
        elif isinstance(chunk, bytes):
            chunks.append(chunk)
        elif isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
    body = b"".join(chunks)
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() != "content-length"
    }
    rebuilt = Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
        background=response.background,
    )
    return body, rebuilt


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Enforce the SQLite/env API key on predict when one is configured."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method == "POST" and request.url.path == "/v1/systemone":
            if not keys.api_key_matches(request.headers.get("authorization")):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid or missing bearer token"},
                )
        return await call_next(request)


class UsageLogMiddleware(BaseHTTPMiddleware):
    """Record each ``POST /v1/systemone`` call into SQLite after the response completes."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method != "POST" or request.url.path != "/v1/systemone":
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0
        body, response = await _read_response_body(response)

        model: Optional[str] = None
        input_tokens = 0
        output_tokens = 0
        question_count = 0
        error: Optional[str] = None

        if body:
            try:
                payload = json.loads(body)
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                if response.status_code >= 200 and response.status_code < 300:
                    model = payload.get("model")
                    usage = payload.get("usage") or {}
                    if isinstance(usage, dict):
                        input_tokens = int(usage.get("input_tokens") or 0)
                        output_tokens = int(usage.get("output_tokens") or 0)
                    answers = payload.get("answers") or {}
                    if isinstance(answers, dict):
                        question_count = len(answers)
                else:
                    detail = payload.get("detail")
                    if isinstance(detail, str):
                        error = detail
                    elif detail is not None:
                        error = str(detail)

        client_host = request.client.host if request.client else None
        usage_db.record(
            status_code=response.status_code,
            duration_ms=duration_ms,
            model=str(model) if model is not None else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            question_count=question_count,
            client_host=client_host,
            error=error,
        )
        return response


# Last added = outermost. Auth should run before usage logging sees the response.
app.add_middleware(UsageLogMiddleware)
app.add_middleware(ApiKeyAuthMiddleware)


def _local_base() -> str:
    host = os.environ.get("LAYA_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = _resolve_port()
    return f"http://{host}:{port}"


def _auth_required() -> bool:
    return bool(keys.get_api_key())


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def _check_api_auth(authorization: Optional[str]) -> None:
    """Require bearer when an API key is configured."""
    if not keys.api_key_matches(authorization):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def _require_key_admin(authorization: Optional[str]) -> None:
    """Mutating key settings requires the current API key once one exists."""
    if keys.get_api_key() and not keys.api_key_matches(authorization):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(FAVICON_SVG, media_type="image/svg+xml")


@app.get("/api")
def api_docs() -> FileResponse:
    return FileResponse(API_HTML, media_type="text/html; charset=utf-8")


@app.get("/monitor")
def monitor() -> FileResponse:
    return FileResponse(MONITOR_HTML, media_type="text/html; charset=utf-8")


@app.get("/v1/usage")
def usage_stats(limit: int = 25) -> dict[str, Any]:
    return usage_db.stats(recent_limit=limit)


@app.post("/v1/usage/clear")
def usage_clear(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_api_auth(authorization)
    return usage_db.clear()


@app.get("/v1/keys")
def keys_status() -> dict[str, Any]:
    return keys.status()


@app.get("/v1/keys/api-key/local")
def keys_local_api(request: Request) -> dict[str, Any]:
    """Return the plaintext API key only to loopback clients (local web UI)."""
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="loopback only")
    value = keys.get_api_key()
    return {"configured": bool(value), "value": value or ""}


@app.post("/v1/keys/api-key/generate")
def keys_generate_api(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _require_key_admin(authorization)
    value = keys.generate_api_key()
    out = keys.status()
    out["generated"] = value
    return out


@app.put("/v1/keys/api-key")
def keys_set_api(
    body: KeyValueBody,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_key_admin(authorization)
    keys.set_api_key(body.value)
    return keys.status()


@app.delete("/v1/keys/api-key")
def keys_clear_api(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _require_key_admin(authorization)
    keys.clear_api_key()
    return keys.status()


@app.put("/v1/keys/ngrok-token")
def keys_set_ngrok(
    body: KeyValueBody,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_key_admin(authorization)
    keys.set_ngrok_token(body.value)
    return keys.status()


@app.delete("/v1/keys/ngrok-token")
def keys_clear_ngrok(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _require_key_admin(authorization)
    keys.clear_ngrok_token()
    return keys.status()


@app.get("/v1/integration")
def integration() -> dict[str, Any]:
    tunnel = ngrok_tunnel.status()
    public = tunnel.get("public_url")
    return {
        "base_url": _local_base(),
        "public_url": public,
        "effective_base_url": public or _local_base(),
        "auth_required": _auth_required(),
        "keys": keys.status(),
        "ngrok": tunnel,
        "endpoints": {
            "health": "GET /health",
            "predict": "POST /v1/systemone",
            "integration": "GET /v1/integration",
            "keys": "GET /v1/keys",
            "usage": "GET /v1/usage",
            "usage_clear": "POST /v1/usage/clear",
            "tunnel_start": "POST /v1/tunnel/start",
            "tunnel_stop": "POST /v1/tunnel/stop",
        },
    }


@app.post("/v1/tunnel/start")
def tunnel_start(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_api_auth(authorization)
    try:
        return ngrok_tunnel.start(_resolve_port())
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/tunnel/stop")
def tunnel_stop(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _check_api_auth(authorization)
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
