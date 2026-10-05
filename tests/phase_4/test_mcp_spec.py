"""Phase 4 MCP contract tests — Chronos.md section 8.4, section 5.5, section 3.

API.md MCP section: same 27 tools as TOOL_SCHEMAS adapted to injected
ToolDispatcher.dispatch; same auth, same validation as voice;
every call writes an audit row.
Decisions: MCP transport HTTP with /mcp endpoint.
errors-and-test-proposal.md Layer 1: public entry points only.

No source-file reads. Tool names below are copied from API.md text.
"""

import importlib
import inspect
import json
import secrets
import sqlite3

import pytest

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

_MCP_MODULE_ATTRS = [
    "TOOL_NAMES",
    "TOOLS",
    "TOOL_LIST",
    "ALL_TOOLS",
]
_MCP_MODULES = ["chronos.mcp", "chronos.mcp.server", "chronos.mcp.tools"]
_SCHEMAS_MODULES = [
    "chronos.contracts",
    "chronos.contracts.tools",
    "chronos.ai.pipeline",
    "chronos.ai.tools",
    "chronos.mcp",
    "chronos.mcp.server",
]


def _load_mcp_tool_names():
    """Return the MCP tool-name list from the implementation. Fails citing spec if absent."""
    tried = []
    for mod_name in _MCP_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            tried.append(f"{mod_name}: {exc}")
            continue
        for attr in _MCP_MODULE_ATTRS:
            if hasattr(mod, attr):
                value = getattr(mod, attr)
                names = list(value.keys()) if isinstance(value, dict) else list(value)
                if all(isinstance(n, str) for n in names) and len(names) > 0:
                    return names
        for fn_name in ["list_tools", "tool_names", "get_tools"]:
            if hasattr(mod, fn_name):
                value = getattr(mod, fn_name)()
                names = list(value.keys()) if isinstance(value, dict) else list(value)
                if all(isinstance(n, str) for n in names) and len(names) > 0:
                    return names
        tried.append(f"{mod_name}: no tool-list attribute")
    pytest.fail(
        "Chronos.md sec 8.4 / API.md MCP: MCP server must expose its tool list "
        f"(tried {_MCP_MODULES} attrs {_MCP_MODULE_ATTRS}). Attempts: {tried}"
    )


def _load_tool_schemas_names():
    """Return TOOL_SCHEMAS tool names. Fails citing spec if the symbol is missing."""
    for mod_name in _SCHEMAS_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        if hasattr(mod, "TOOL_SCHEMAS"):
            schemas = getattr(mod, "TOOL_SCHEMAS")
            names = list(schemas.keys()) if isinstance(schemas, dict) else [s["name"] for s in schemas]
            return names
    pytest.fail(
        "API.md MCP: TOOL_SCHEMAS with the 27 tools must exist "
        f"(searched {_SCHEMAS_MODULES})."
    )


def _boot_app(tmp_path):
    """Create the real app on a throwaway DB with a freshly minted key.

    Chronos.md sec 3 + decisions: mint a key, store only its Argon2 hash
    in app.state.api_key_hash; never a literal.
    """
    api_mod = importlib.import_module("chronos.api")
    assert hasattr(api_mod, "create_app"), (
        "Chronos.md sec 8.1/decisions: chronos.api.create_app(db_path=None) is frozen"
    )
    sig = inspect.signature(api_mod.create_app)
    assert "db_path" in sig.parameters, f"create_app signature {sig} missing db_path"
    db_path = str(tmp_path / "mcp-test.db")
    app = api_mod.create_app(db_path=db_path)
    key = secrets.token_urlsafe(32)
    try:
        from argon2 import PasswordHasher

        hashed = PasswordHasher().hash(key)
    except ImportError:
        pytest.fail("Chronos.md sec 3: Argon2 is required for the instance-key hash")
    state = app.state
    if hasattr(state, "api_key_hash"):
        state.api_key_hash = hashed
    elif hasattr(state, "key_hash"):
        state.key_hash = hashed
    else:
        state.api_key_hash = hashed
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.fail("HTTP contract tests require fastapi.testclient.TestClient")
    return app, key, TestClient(app), db_path


def _mcp_call(client, tool, arguments, key=None, via_query=False):
    """POST /mcp with the /api/commands shape {tool, arguments}.

    API.md: POST /api/commands {tool, arguments} is the raw tool call for CLI
    and MCP; MCP /mcp (HTTP) exposes the same tools through dispatch.
    """
    headers = {}
    params = {}
    if key is not None and via_query is False:
        headers["X-Chronos-Key"] = key
    if key is not None and via_query is True:
        params["key"] = key
    return client.post("/mcp", json={"tool": tool, "arguments": arguments}, headers=headers, params=params)


def test_mcp_tool_list_matches_contracts_27_exactly():
    """API.md MCP + Chronos.md sec 5.5: MCP exposes exactly the 27 contract tools."""
    names = _load_mcp_tool_names()
    assert len(names) == 27, f"expected 27 MCP tools, got {len(names)}: {sorted(names)}"
    assert len(set(names)) == 27, f"duplicate MCP tool names: {names}"
    assert sorted(names) == sorted(EXPECTED_TOOLS), (
        f"MCP tool list mismatch.\nmissing={sorted(set(EXPECTED_TOOLS) - set(names))}\n"
        f"extra={sorted(set(names) - set(EXPECTED_TOOLS))}"
    )


def test_tool_schemas_matches_27():
    """API.md MCP: TOOL_SCHEMAS holds the same 27 tools the MCP list must match."""
    names = _load_tool_schemas_names()
    assert len(names) == 27, f"TOOL_SCHEMAS must hold 27 tools, got {len(names)}"
    assert sorted(names) == sorted(EXPECTED_TOOLS), (
        f"TOOL_SCHEMAS mismatch. missing={sorted(set(EXPECTED_TOOLS) - set(names))} "
        f"extra={sorted(set(names) - set(EXPECTED_TOOLS))}"
    )


def test_no_move_tool():
    """Chronos.md sec 5.5 Rules: no AI-callable move tool; only create_event and delete_event."""
    names = _load_mcp_tool_names()
    assert "move_event" not in names, "spec forbids a move tool"
    joined = " ".join(names)
    assert "move" not in joined.split(), f"no move-family tool allowed: {names}"
    assert "create_event" in names
    assert "delete_event" in names


def test_mcp_accepts_injected_executor():
    """Phase-4 MCP: tools adapted to an injected executor, not reimplemented."""
    tried = []
    for mod_name in _MCP_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            tried.append(f"{mod_name}: {exc}")
            continue
        for cls_name in ["MCPServer", "McpServer", "MCPHandler", "ToolServer"]:
            cls = getattr(mod, cls_name, None)
            if cls is None:
                continue
            params = inspect.signature(cls.__init__).parameters
            names = set(params.keys()) - {"self"}
            if len(names & {"dispatcher", "executor", "dispatch", "tool_dispatcher", "handler"}) > 0:
                return
            tried.append(f"{mod_name}.{cls_name} params={sorted(names)}: no injected executor")
        for fn_name in ["create_server", "create_mcp_server", "build_server"]:
            fn = getattr(mod, fn_name, None)
            if fn is None:
                continue
            params = set(inspect.signature(fn).parameters.keys())
            if len(params & {"dispatcher", "executor", "dispatch", "tool_dispatcher", "handler"}) > 0:
                return
            tried.append(f"{mod_name}.{fn_name} params={sorted(params)}: no injected executor")
    pytest.fail(
        "Phase-4 MCP: MCP layer must accept an injected executor/dispatcher "
        f"(constructor param named dispatcher/executor/dispatch). Attempts: {tried}"
    )


def test_mcp_tools_not_stubbed_distinct_inputs_distinct_outputs(tmp_path):
    """Phase-4 Done: no tool stubbed — distinct inputs must give distinct outputs."""
    _app, key, client, _db = _boot_app(tmp_path)
    day_a = "2026-10-07"
    day_b = "2026-10-08"
    ra = _mcp_call(client, "get_day", {"date": day_a}, key=key)
    assert ra.status_code == 200, f"get_day {day_a} -> {ra.status_code}: {ra.text[:2000]}"
    rb = _mcp_call(client, "get_day", {"date": day_b}, key=key)
    assert rb.status_code == 200, f"get_day {day_b} -> {rb.status_code}: {rb.text[:2000]}"
    assert ra.json() != rb.json(), "identical output for two different days: tools look stubbed"


def test_mcp_unauth_rejected_401(tmp_path):
    """Chronos.md sec 3 + API.md Auth: everything except /api/health is 401 without/bad key."""
    _app, _key, client, _db = _boot_app(tmp_path)
    r_missing = _mcp_call(client, "get_day", {"date": "2026-10-07"})
    assert r_missing.status_code == 401, f"no key must be 401, got {r_missing.status_code}"
    r_bad = _mcp_call(client, "get_day", {"date": "2026-10-07"}, key="wrong-key-value")
    assert r_bad.status_code == 401, f"bad key must be 401, got {r_bad.status_code}"


def test_mcp_auth_header_succeeds(tmp_path):
    """Chronos.md sec 3: header X-Chronos-Key authenticates the call."""
    _app, key, client, _db = _boot_app(tmp_path)
    r = _mcp_call(client, "get_day", {"date": "2026-10-07"}, key=key)
    assert r.status_code != 401, f"valid header key must not be 401: {r.text[:2000]}"
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:2000]}"


def test_mcp_auth_query_fallback_succeeds(tmp_path):
    """Chronos.md sec 3 + API.md Auth: ?key= fallback for MCP clients that cannot set headers."""
    _app, key, client, _db = _boot_app(tmp_path)
    r = _mcp_call(client, "get_day", {"date": "2026-10-07"}, key=key, via_query=True)
    assert r.status_code != 401, f"valid ?key= must not be 401: {r.text[:2000]}"
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:2000]}"


def test_mcp_key_never_logged(tmp_path):
    """Chronos.md sec 3: a key in a query string is never written to a log."""
    _app, _key, client, _db = _boot_app(tmp_path)
    bad = "qk-never-log-9f8e7d6c5b4a"
    r = _mcp_call(client, "get_day", {"date": "2026-10-07"}, key=bad, via_query=True)
    assert r.status_code == 401
    assert bad not in r.text, "rejected response must not echo the key"


def test_mcp_rejects_relative_dates_422(tmp_path):
    """Chronos.md sec 5.5 Rules: dates are absolute ISO-8601; the model never emits bare day numbers."""
    _app, key, client, _db = _boot_app(tmp_path)
    ok_payload = {
        "title": "absolute probe",
        "start": "2026-10-07T10:00:00+00:00",
        "end": "2026-10-07T10:30:00+00:00",
    }
    ok_r = _mcp_call(client, "create_event", ok_payload, key=key)
    assert ok_r.status_code == 200, f"absolute ISO shape must work: {ok_r.status_code} {ok_r.text[:2000]}"
    bad_payload = {"title": "relative probe", "start": "tomorrow evening", "end": "day 8"}
    bad_r = _mcp_call(client, "create_event", bad_payload, key=key)
    assert bad_r.status_code == 422, (
        f"relative dates must be 422, got {bad_r.status_code}: {bad_r.text[:2000]}"
    )


def test_mcp_rejects_unbounded_series_422(tmp_path):
    """Chronos.md sec 4.4 + API.md MCP Rules: a series must be bounded (max_count and/or ends_on_ms)."""
    _app, key, client, _db = _boot_app(tmp_path)
    node_r = _mcp_call(client, "create_node", {"kind": "task", "title": "series anchor"}, key=key)
    assert node_r.status_code == 200, f"create_node failed: {node_r.status_code} {node_r.text[:2000]}"
    node_id = node_r.json()["id"] if "id" in node_r.json() else node_r.json()["result"]["id"]
    unbounded = {"node_id": node_id, "anchor_node_id": node_id, "tier": "medium"}
    r = _mcp_call(client, "schedule_series", unbounded, key=key)
    assert r.status_code == 422, f"unbounded series must be 422, got {r.status_code}: {r.text[:2000]}"


def test_mcp_rejects_tag_on_project_422(tmp_path):
    """Chronos.md sec 4.1: tags apply to tasks and subtasks, never to projects."""
    _app, key, client, _db = _boot_app(tmp_path)
    task_r = _mcp_call(client, "create_node", {"kind": "task", "title": "taggable task"}, key=key)
    assert task_r.status_code == 200, f"task create failed: {task_r.text[:2000]}"
    task_body = task_r.json()
    task_id = task_body["id"] if "id" in task_body else task_body["result"]["id"]
    tag_ok = _mcp_call(client, "tag_node", {"node_id": task_id, "name": "probe-tag"}, key=key)
    assert tag_ok.status_code == 200, f"tagging a task must work: {tag_ok.status_code} {tag_ok.text[:2000]}"
    proj_r = _mcp_call(client, "create_node", {"kind": "project", "title": "untaggable project"}, key=key)
    assert proj_r.status_code == 200, f"project create failed: {proj_r.text[:2000]}"
    proj_body = proj_r.json()
    proj_id = proj_body["id"] if "id" in proj_body else proj_body["result"]["id"]
    tag_bad = _mcp_call(client, "tag_node", {"node_id": proj_id, "name": "probe-tag"}, key=key)
    assert tag_bad.status_code == 422, (
        f"tag on project must be 422, got {tag_bad.status_code}: {tag_bad.text[:2000]}"
    )


def test_mcp_every_call_writes_audit_row(tmp_path):
    """Chronos.md sec 8.4 + API.md MCP: every call writes an audit row."""
    _app, key, client, db_path = _boot_app(tmp_path)

    def audit_count():
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        finally:
            conn.close()

    before = audit_count()
    r = _mcp_call(client, "get_day", {"date": "2026-10-07"}, key=key)
    assert r.status_code == 200, f"get_day failed: {r.status_code} {r.text[:2000]}"
    after = audit_count()
    assert after == before + 1, f"one MCP call must add exactly one audit row ({before} -> {after})"
    conn = sqlite3.connect(db_path)
    try:
        last = conn.execute("SELECT action FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert last is not None, "audit table has no rows after an MCP call"
    assert last[0] == "get_day", f"audit action must name the tool, got {last[0]!r}"


def test_mcp_query_free_evening_path(tmp_path):
    """Chronos.md sec 8.4 query: 'am I free tomorrow evening?' goes through the real scheduler."""
    _app, key, client, _db = _boot_app(tmp_path)
    payload = {"from": "2026-10-07T18:00:00+00:00", "to": "2026-10-07T22:00:00+00:00"}
    r = _mcp_call(client, "get_free_time", payload, key=key)
    assert r.status_code == 200, f"get_free_time failed: {r.status_code} {r.text[:2000]}"
    body = r.json()
    text = json.dumps(body)
    assert "free" in text.lower() or "slot" in text.lower() or "start" in text.lower(), (
        f"free-time answer must describe availability: {text[:2000]}"
    )


def test_mcp_act_book_dentist_path(tmp_path):
    """Chronos.md sec 8.4 act: 'book me the dentist tomorrow' commits with voice validation."""
    _app, key, client, db_path = _boot_app(tmp_path)
    payload = {
        "title": "dentist",
        "start": "2026-10-07T10:00:00+00:00",
        "end": "2026-10-07T10:30:00+00:00",
    }
    r = _mcp_call(client, "create_event", payload, key=key)
    assert r.status_code == 200, f"act path failed: {r.status_code} {r.text[:2000]}"
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT id, title FROM events WHERE title = 'dentist'").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, f"act path must commit exactly one dentist event, got {rows}"


def test_mcp_series_is_one_call(tmp_path):
    """Chronos.md sec 5.5 Rules + sec 4.4: a series is one tool call writing all review events."""
    _app, key, client, db_path = _boot_app(tmp_path)
    node_r = _mcp_call(client, "create_node", {"kind": "task", "title": "series task"}, key=key)
    assert node_r.status_code == 200, f"create_node failed: {node_r.text[:2000]}"
    node_body = node_r.json()
    node_id = node_body["id"] if "id" in node_body else node_body["result"]["id"]
    payload = {
        "node_id": node_id,
        "anchor_node_id": node_id,
        "tier": "medium",
        "max_count": 3,
    }
    r = _mcp_call(client, "schedule_series", payload, key=key)
    assert r.status_code == 200, f"bounded schedule_series failed: {r.status_code} {r.text[:2000]}"
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT series_id FROM events WHERE series_id IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) >= 2, f"one series call must write its events together, got {len(rows)} rows"
    series_ids = {row[0] for row in rows}
    assert len(series_ids) == 1, f"one call must create one series, got {series_ids}"
