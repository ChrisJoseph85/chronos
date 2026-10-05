"""Phase 3 app factory: create_app(db_path=None) -> FastAPI (frozen signature)."""

from __future__ import annotations

import os
import sqlite3
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from chronos.api.auth import extract_key, verify_key  # noqa: F401 (public seam)

_VERSION = "2.0.0"


def _ensure_db(db_path: str) -> None:
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    from chronos.db.bootstrap import init_db

    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        from chronos.db.buckets import seed_buckets

        seed_buckets(conn)
    finally:
        conn.close()


def _bootstrap_key(db_path: str) -> str | None:
    """Load the stored Argon2 hash; on first run mint, store, and print once."""
    conn = sqlite3.connect(db_path)
    try:
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = 'api_key_hash'").fetchone()
        except sqlite3.DatabaseError:
            row = None
        if row is not None:
            return str(row[0])
        import secrets as _secrets

        from chronos.api.auth import hash_key

        raw = _secrets.token_urlsafe(32)
        hashed = hash_key(raw)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('api_key_hash', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (hashed,),
        )
        conn.commit()
        print("Chronos instance key (printed once, keep it safe): %s" % raw, flush=True)
        return hashed
    finally:
        conn.close()


def create_app(db_path: str | None = None) -> FastAPI:
    """Build the Chronos FastAPI app opening exactly the file db_path names."""
    from chronos.realtime.hub import Hub

    resolved = db_path or os.environ.get("CHRONOS_DB") or os.path.expanduser("~/.chronos/chronos.db")
    _ensure_db(resolved)

    app = FastAPI(title="Chronos", version=_VERSION)
    app.state.db_path = resolved
    app.state.started_at = time.time()
    app.state.api_key_hash = _bootstrap_key(resolved)
    app.state.proposals = {}
    app.state.hub = Hub()

    # Auth middleware: /api/health only open route; WS + /mcp handled locally.
    # Unknown paths fall through so the router answers 404 (backend-only freeze).
    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path == "/api/health" or path.startswith("/mcp") or path.startswith("/ws"):
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)
        candidate = extract_key(request.headers, request.query_params)
        if not verify_key(candidate, getattr(request.app.state, "api_key_hash", None)):
            return JSONResponse(status_code=401, content={"detail": "Missing/Invalid key"})
        return await call_next(request)

    from chronos.api import routes as _routes

    app.include_router(_routes.router)
    app.add_api_websocket_route("/ws", _routes.websocket_endpoint)

    # CRITICAL SEAM: mount the MCP router (Phase 4 owns the module).
    try:
        from chronos.mcp.server import MCPServer  # noqa: PLC0415

        dispatcher = _routes._mcp_dispatcher(resolved)
        try:
            mcp_router = MCPServer(dispatcher=dispatcher).get_router()
        except TypeError:
            try:
                from chronos.mcp.server import create_server  # noqa: PLC0415

                mcp_router = create_server(dispatcher).get_router()
            except Exception:
                mcp_router = None
        if mcp_router is not None:
            app.include_router(mcp_router, prefix="/mcp")
    except ImportError:
        pass
    except Exception:
        pass

    return app
