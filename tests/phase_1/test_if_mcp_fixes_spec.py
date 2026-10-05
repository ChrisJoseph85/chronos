"""WAVE-2 FIXER D spec: MCP tag-on-project DB lookup + executor arity fixes.

Chronos.md sec 4.1: tags apply to tasks and subtasks, never to projects
  (same validation as voice path ToolDispatcher._do_tag_node).
Chronos.md sec 5.5: same validation as voice input; no move tool.
Chronos.md sec 8.4 / API.md MCP: HTTP POST /mcp with {tool, arguments},
  X-Chronos-Key header with ?key= fallback, one audit row per call.

Bugs fixed (chronos/mcp/server.py):
  1. validate_call checked args["kind"] only — spoofable. handle() now
     resolves the node's REAL kind by node_id via duck-typed store/repo
     accessors + sqlite fallback, and refuses tag_node on projects (422).
  2. signature probe `len(params)>=2 else fn(tool)` dropped arguments.
     _call_executor now always forwards (tool, arguments), adapting to
     executor arity via one inspect without ever dropping arguments.

Uses TestClient + real sqlite only (no network).
"""

import importlib
import secrets
import sqlite3

from fastapi.testclient import TestClient


def _boot_app(tmp_path):
    api_mod = importlib.import_module("chronos.api")
    app = api_mod.create_app(db_path=str(tmp_path / "mcp-fix-d.db"))
    key = secrets.token_urlsafe(32)
    from argon2 import PasswordHasher

    hashed = PasswordHasher().hash(key)
    state = app.state
    if hasattr(state, "api_key_hash"):
        state.api_key_hash = hashed
    else:
        state.key_hash = hashed
    return app, key, TestClient(app), str(tmp_path / "mcp-fix-d.db")


def _mcp_call(client, tool, arguments, key):
    return client.post(
        "/mcp",
        json={"tool": tool, "arguments": arguments},
        headers={"X-Chronos-Key": key},
    )


def _node_id(body):
    data = body.json()
    if "id" in data:
        return data["id"]
    return data["result"]["id"]


def test_tag_project_by_node_id_is_422_not_by_args_kind(tmp_path):
    """Chronos.md sec 4.1: tag_node on a project node_id (no kind arg) -> 422."""
    _app, key, client, _db = _boot_app(tmp_path)
    proj = _mcp_call(client, "create_node", {"kind": "project", "title": "P"}, key=key)
    assert proj.status_code == 200, proj.text[:1000]
    proj_id = _node_id(proj)
    # No "kind" in args at all: server must DB-lookup the REAL kind.
    r = _mcp_call(client, "tag_node", {"node_id": proj_id, "name": "x"}, key=key)
    assert r.status_code == 422, f"tag on project must be 422, got {r.status_code}: {r.text[:1000]}"


def test_tag_project_spoofed_kind_arg_still_422(tmp_path):
    """Chronos.md sec 4.1/5.5: kind='task' in args must not bypass the DB lookup."""
    _app, key, client, _db = _boot_app(tmp_path)
    proj = _mcp_call(client, "create_node", {"kind": "project", "title": "P2"}, key=key)
    assert proj.status_code == 200, proj.text[:1000]
    proj_id = _node_id(proj)
    r = _mcp_call(
        client, "tag_node", {"node_id": proj_id, "name": "x", "kind": "task"}, key=key
    )
    assert r.status_code == 422, f"spoofed kind must still be 422, got {r.status_code}: {r.text[:1000]}"


def test_tag_task_is_200_and_single_audit_row(tmp_path):
    """Chronos.md sec 4.1 (tasks are taggable) + sec 8.4 (one audit row/call)."""
    _app, key, client, db_path = _boot_app(tmp_path)
    task = _mcp_call(client, "create_node", {"kind": "task", "title": "T"}, key=key)
    assert task.status_code == 200, task.text[:1000]
    task_id = _node_id(task)
    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        conn.close()
    r = _mcp_call(client, "tag_node", {"node_id": task_id, "name": "probe"}, key=key)
    assert r.status_code == 200, f"tag on task must be 200, got {r.status_code}: {r.text[:1000]}"
    conn = sqlite3.connect(db_path)
    try:
        after = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        conn.close()
    assert after == before + 1, f"one call must add exactly one audit row ({before}->{after})"


def test_executor_receives_both_tool_and_args():
    """Sec 8.4: injected executor must receive (tool, arguments) — recorded."""
    from chronos.mcp.server import MCPServer

    calls = []

    class Recording:
        def dispatch(self, tool, arguments):
            calls.append((tool, dict(arguments)))
            return {"ok": True}

    srv = MCPServer(dispatcher=Recording())
    out = srv.handle("search_nodes", {"q": "hello"})
    assert out == {"ok": True}
    assert len(calls) == 1
    tool, args = calls[0]
    assert tool == "search_nodes"
    assert args == {"q": "hello"}, f"arguments dropped/mutated: {args!r}"


def test_argless_single_arg_executor_still_gets_arguments():
    """Sec 8.4: single-param executor must still receive the arguments (never dropped)."""
    from chronos.mcp.server import MCPServer

    received = []

    class SingleArg:
        def dispatch(self, payload):
            received.append(payload)
            return {"ok": True}

    srv = MCPServer(dispatcher=SingleArg())
    out = srv.handle("search_nodes", {"q": "keep-me"})
    assert out == {"ok": True}
    assert len(received) == 1
    payload = received[0]
    text = repr(payload)
    assert "keep-me" in text, f"arguments were dropped: {text[:1000]}"
    assert "search_nodes" in text, f"tool name lost: {text[:1000]}"
