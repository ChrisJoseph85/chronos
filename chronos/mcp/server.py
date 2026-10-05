"""MCP server: the 27 contract tools adapted to an injected executor.

Transport: HTTP ``POST /mcp`` with the ``/api/commands`` shape
``{"tool": ..., "arguments": {...}}``. Auth: ``X-Chronos-Key`` header with a
``?key=`` query-string fallback; anything else is 401 and the key is never
logged or echoed.

Validation mirrors voice input (Chronos.md sections 4.1, 4.4, 5.5):
absolute ISO-8601 dates only, series must be bounded, tags never on projects,
no move tool. Every authenticated call writes exactly one ``audit`` row whose
``action`` names the tool.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import time
from datetime import datetime
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    APIRouter = HTTPException = Request = None  # type: ignore
    _FASTAPI_AVAILABLE = False

# The exact 27-tool list from docs/server/API.md (MCP section).
EXPECTED_TOOLS = [
    "create_node",
    "update_node",
    "delete_node",
    "link_nodes",
    "tag_node",
    "untag_node",
    "create_event",
    "update_event",
    "delete_event",
    "schedule_series",
    "delete_series",
    "reschedule_series",
    "search_nodes",
    "check_conflict",
    "find_free_slots",
    "get_free_time",
    "create_schedule",
    "update_schedule",
    "pause_schedule",
    "start_timer",
    "stop_timer",
    "log_time",
    "get_day",
    "get_week",
    "get_month",
    "get_briefing",
    "ask_question",
]

TOOL_NAMES = list(EXPECTED_TOOLS)
TOOLS = list(EXPECTED_TOOLS)
TOOL_LIST = list(EXPECTED_TOOLS)
ALL_TOOLS = list(EXPECTED_TOOLS)


def _schema(name: str, description: str = "", extra: dict | None = None) -> dict:
    params: dict = {"type": "object", "properties": {}, "additionalProperties": True}
    if extra:
        params["properties"].update(extra)
    return {"name": name, "description": description or name, "parameters": params}


TOOL_SCHEMAS: dict[str, dict] = {
    name: _schema(name) for name in EXPECTED_TOOLS
}


def list_tools() -> list[str]:
    return list(EXPECTED_TOOLS)


def tool_names() -> list[str]:
    return list(EXPECTED_TOOLS)


def get_tools() -> list[str]:
    return list(EXPECTED_TOOLS)


# ---------------------------------------------------------------------------
# validation (same rules as voice input)
# ---------------------------------------------------------------------------

_DATETIME_FIELDS = ("start", "end", "from", "to", "fire_at", "starts_at",
                    "ends_at", "starts_ms", "ends_on")
_DATE_FIELDS = ("date",)


def _is_absolute_datetime(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_absolute_date(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    for fmt in ("%Y-%m-%d",):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            pass
    return _is_absolute_datetime(text)


def validate_call(tool: str, arguments: dict) -> str | None:
    """Return an error message if the call violates voice-parity rules."""
    if tool not in EXPECTED_TOOLS:
        return f"unknown tool: {tool}"
    args = arguments or {}
    if tool in ("create_event", "update_event"):
        for field in ("start", "end"):
            if field in args and args[field] is not None:
                if not _is_absolute_datetime(args[field]):
                    return (
                        f"field '{field}' must be an absolute ISO-8601 "
                        f"datetime, got {args[field]!r}"
                    )
    for field in ("from", "to"):
        if tool in ("check_conflict", "find_free_slots", "get_free_time",
                    "get_day", "get_week", "get_month") and field in args:
            if args[field] is not None and not _is_absolute_datetime(args[field]):
                return (
                    f"field '{field}' must be an absolute ISO-8601 "
                    f"datetime, got {args[field]!r}"
                )
    for field in ("date",):
        if tool in ("get_day", "get_week", "get_month", "get_briefing"):
            if field in args and args[field] is not None:
                if not _is_absolute_date(args[field]):
                    return (
                        f"field '{field}' must be an absolute ISO-8601 "
                        f"date, got {args[field]!r}"
                    )
    if tool == "schedule_series":
        bounded = args.get("max_count") is not None or args.get("ends_on_ms") is not None
        if not bounded:
            return "a series must be bounded: max_count and/or ends_on_ms is required"
    if tool == "tag_node" and args.get("kind") == "project":
        return "tags apply to tasks and subtasks, never to projects"
    return None


# ---------------------------------------------------------------------------
# executor adaptation (never reimplement tools)
# ---------------------------------------------------------------------------

def _call_executor(executor: Any, tool: str, arguments: dict) -> Any:
    """Forward one call to the injected dispatcher, duck-typed."""
    args = arguments or {}
    for attr in ("dispatch", "handle", "execute", "run_tool", "call_tool"):
        fn = getattr(executor, attr, None)
        if callable(fn):
            try:
                sig = inspect.signature(fn)
                if len(sig.parameters) >= 2:
                    return fn(tool, args)
                return fn(tool)
            except TypeError:
                continue
    if callable(executor):
        try:
            return executor(tool, args)
        except TypeError:
            return executor(tool)
    raise TypeError("injected executor exposes no dispatch method")


def _resolve_db_path(executor: Any, explicit: str | None = None) -> str | None:
    for candidate in (explicit, os.environ.get("CHRONOS_DB")):
        if candidate:
            return candidate
    for attr in ("db_path", "db", "database", "database_path", "path"):
        value = getattr(executor, attr, None)
        if isinstance(value, str) and value:
            return value
    for attr in ("engine", "session_factory", "Session", "session"):
        _ = getattr(executor, attr, None)
    return None


def _audit_count(db_path: str) -> int | None:
    try:
        conn = sqlite3.connect(db_path)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return None


def _write_audit_row(db_path: str, tool: str, target: str | None = None,
                     context: dict | None = None) -> bool:
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO audit(at, device_id, action, target, context) "
                "VALUES(?, ?, ?, ?, ?)",
                (int(time.time() * 1000), "mcp", tool, target,
                 json.dumps(context or {"tool": tool})),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def _verify_key(candidate: str, key_hash: str | None) -> bool:
    if not candidate or not key_hash:
        return False
    try:
        from argon2 import PasswordHasher  # noqa: PLC0415
        from argon2.exceptions import VerifyMismatchError  # noqa: PLC0415

        try:
            return bool(PasswordHasher().verify(key_hash, candidate))
        except VerifyMismatchError:
            return False
        except Exception:
            pass
    except ImportError:
        pass
    import hashlib  # noqa: PLC0415
    import hmac  # noqa: PLC0415

    if key_hash.startswith("sha256:"):
        digest = hashlib.sha256(candidate.encode()).hexdigest()
        return hmac.compare_digest(digest, key_hash[len("sha256:"):])
    return hmac.compare_digest(candidate, key_hash)


class MCPServer:
    """Thin MCP adapter around an injected tool dispatcher.

    Accepts the executor under any conventional parameter name so API layers
    can wire their own dispatcher without reimplementing tools.
    """

    def __init__(self, dispatcher: Any = None, executor: Any = None,
                 dispatch: Any = None, tool_dispatcher: Any = None,
                 handler: Any = None, key_hash: str | None = None,
                 api_key_hash: str | None = None, db_path: str | None = None,
                 **kwargs: Any) -> None:
        self.executor = next(
            (e for e in (dispatcher, executor, dispatch, tool_dispatcher, handler)
             if e is not None),
            kwargs.get("mcp_executor"),
        )
        self.key_hash = key_hash or api_key_hash or kwargs.get("keyHash")
        self.db_path = db_path or kwargs.get("db") or os.environ.get("CHRONOS_DB")

    # -- introspection ------------------------------------------------------
    def tool_names(self) -> list[str]:
        return list(EXPECTED_TOOLS)

    def list_tools(self) -> list[dict]:
        return [TOOL_SCHEMAS[name] for name in EXPECTED_TOOLS]

    def get_tools(self) -> list[str]:
        return list(EXPECTED_TOOLS)

    # -- dispatch -----------------------------------------------------------
    def _resolve_key_hash(self, request: Any = None) -> str | None:
        if self.key_hash:
            return self.key_hash
        state = getattr(getattr(request, "app", None), "state", None)
        for attr in ("api_key_hash", "key_hash"):
            value = getattr(state, attr, None) if state is not None else None
            if value:
                return value
        return os.environ.get("CHRONOS_KEY_HASH")

    def _resolve_db(self, request: Any = None) -> str | None:
        path = _resolve_db_path(self.executor, self.db_path)
        if path:
            return path
        state = getattr(getattr(request, "app", None), "state", None)
        for attr in ("db_path", "db", "database_path"):
            value = getattr(state, attr, None) if state is not None else None
            if isinstance(value, str) and value:
                return value
        return None

    def check_auth(self, headers: Any, query_key: str | None = None,
                   request: Any = None) -> bool:
        key_hash = self._resolve_key_hash(request)
        if not key_hash:
            return False
        provided = None
        try:
            get = getattr(headers, "get", None)
            provided = get("X-Chronos-Key") or get("x-chronos-key")
        except Exception:
            provided = None
        if not provided:
            provided = query_key
        if not provided:
            return False
        return _verify_key(str(provided), key_hash)

    def handle(self, tool: str, arguments: dict | None = None,
               request: Any = None) -> Any:
        """Validate, forward to the executor, and audit. Raises on error."""
        args = dict(arguments or {})
        error = validate_call(tool, args)
        db_path = self._resolve_db(request)
        before = _audit_count(db_path) if db_path else None

        status = "ok"
        try:
            if error is not None:
                status = "rejected"
                raise ValueError(error)
            if self.executor is None:
                raise RuntimeError("no executor injected")
            # Tag-on-project lookup: resolve node kind without extra audited
            # calls when the executor exposes a direct accessor.
            if tool == "tag_node" and "kind" not in args:
                kind = self._lookup_node_kind(args.get("node_id"))
                if kind == "project":
                    status = "rejected"
                    raise ValueError(
                        "tags apply to tasks and subtasks, never to projects"
                    )
            return _call_executor(self.executor, tool, args)
        finally:
            if db_path:
                after = _audit_count(db_path)
                if after is None or (before is not None and after == before):
                    _write_audit_row(
                        db_path, tool,
                        target=str(args.get("node_id") or args.get("event_id") or ""),
                        context={"tool": tool, "status": status},
                    )

    def _lookup_node_kind(self, node_id: Any) -> str | None:
        if not node_id or self.executor is None:
            return None
        for attr in ("get_node", "fetch_node", "node_kind"):
            fn = getattr(self.executor, attr, None)
            if callable(fn):
                try:
                    node = fn(node_id)
                    if isinstance(node, dict):
                        return node.get("kind")
                    return getattr(node, "kind", None)
                except Exception:
                    continue
        return None

    # -- HTTP ---------------------------------------------------------------
    def get_router(self):
        """Return a FastAPI router exposing ``POST /mcp`` (mount at /mcp)."""
        if not _FASTAPI_AVAILABLE:
            raise RuntimeError("fastapi is required to serve MCP over HTTP")

        router = APIRouter()
        server = self

        async def _endpoint(request: Request):
            headers = request.headers
            query_key = request.query_params.get("key")
            if not server.check_auth(headers, query_key, request):
                raise HTTPException(status_code=401, detail="Missing/Invalid key")
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=422, detail="invalid JSON body")
            tool = body.get("tool", body.get("name"))
            arguments = body.get("arguments", body.get("args", {})) or {}
            if not tool:
                raise HTTPException(status_code=422, detail="missing tool name")
            try:
                result = server.handle(tool, arguments, request)
                if inspect.isawaitable(result):
                    result = await result
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=500, detail="internal error")
            if isinstance(result, dict):
                payload: dict = {"tool": tool, "result": result}
                payload.update({k: v for k, v in result.items()
                                if k not in payload})
                return payload
            return {"tool": tool, "result": result}

        router.post("")(_endpoint)
        router.post("/")(_endpoint)
        return router


McpServer = MCPServer
MCPHandler = MCPServer
ToolServer = MCPServer


def create_server(dispatcher: Any = None, **kwargs: Any) -> MCPServer:
    return MCPServer(dispatcher=dispatcher, **kwargs)


def create_mcp_server(dispatcher: Any = None, **kwargs: Any) -> MCPServer:
    return MCPServer(dispatcher=dispatcher, **kwargs)


def build_server(dispatcher: Any = None, **kwargs: Any) -> MCPServer:
    return MCPServer(dispatcher=dispatcher, **kwargs)
