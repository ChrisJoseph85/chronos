"""Auth contract tests — Chronos.md §3, API.md Auth, phase-3-server.md Behaviour/Auth.

Every test cites its spec section in its docstring.
Written from spec text ONLY — never read chronos/api/, chronos/realtime/.
"""

import inspect
import logging
import secrets

import pytest

# ---------------------------------------------------------------------------
# Helpers (spec-derived public surface only)
# ---------------------------------------------------------------------------

HEALTH_PATH = "/api/health"

# (method, path, kwargs) for every authenticated route per API.md REST list.
# Query/body values are minimal-but-valid so a correct server answers
# without 422; auth runs before validation so 401 is expected without a key.
AUTHENTICATED_ROUTES = [
    ("POST", "/api/say", {"json": {"text": "Schedule math review tomorrow 4pm for 45 minutes"}}),
    ("POST", "/api/commands", {"json": {"tool": "search_nodes", "arguments": {"q": "test", "limit": 5}}}),
    ("POST", "/api/voice", {}),
    ("GET", "/api/events", {"params": {"from": "2026-10-05T00:00:00+00:00", "to": "2026-10-06T00:00:00+00:00"}}),
    ("GET", "/api/nodes", {}),
    ("GET", "/api/buckets", {"params": {"level": "D", "date": "2026-10-05"}}),
    ("GET", "/api/briefing", {"params": {"date": "2026-10-05"}}),
    ("GET", "/api/search", {"params": {"q": "test", "limit": 5}}),
    ("GET", "/api/reminders", {}),
    ("POST", "/api/timer/start", {"json": {"label": "auth-probe", "source": "auth-test", "mode": "stopwatch"}}),
    ("POST", "/api/timer/stop", {"json": {"source": "auth-test"}}),
    ("GET", "/api/timer", {}),
    ("GET", "/api/timer/summary", {}),
    ("GET", "/api/timer/presets", {}),
    ("POST", "/api/timer/presets", {"json": {"name": "probe", "focus_minutes": 50, "break_minutes": 10, "cycles": 2}}),
    ("GET", "/api/stats", {}),
    ("GET", "/api/settings", {}),
    ("PUT", "/api/settings", {"json": {"auth.probe": "1"}}),
    ("POST", "/api/keys/renew", {}),
]

# GET routes where a valid key must yield exactly 200 (no preconditions).
SAFE_GET_ROUTES = [
    ("/api/nodes", {}),
    ("/api/reminders", {}),
    ("/api/timer", {}),
    ("/api/timer/summary", {}),
    ("/api/timer/presets", {}),
    ("/api/stats", {}),
    ("/api/settings", {}),
    ("/api/search", {"params": {"q": "test", "limit": 5}}),
    ("/api/briefing", {"params": {"date": "2026-10-05"}}),
    ("/api/buckets", {"params": {"level": "D", "date": "2026-10-05"}}),
    ("/api/events", {"params": {"from": "2026-10-05T00:00:00+00:00", "to": "2026-10-06T00:00:00+00:00"}}),
]


def _mint_key():
    """Chronos.md §3: one instance key. Tests mint their own, never hardcode."""
    return secrets.token_urlsafe(32)


def _hash_key(raw):
    """Chronos.md §3: stored Argon2-hashed."""
    from argon2 import PasswordHasher

    return PasswordHasher().hash(raw)


def _make_app(tmp_path, raw=None):
    """Build app via frozen create_app(db_path=None), mint key, install hash."""
    from chronos.api.app import create_app

    db_path = str(tmp_path / "auth-test.db")
    app = create_app(db_path=db_path)
    if raw is None:
        raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    return app, raw, db_path


def _client_for(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _request(client, method, path, kwargs, key=None, use_query=False):
    headers = {}
    params = dict(kwargs.get("params", {}))
    if key is not None:
        if use_query:
            params["key"] = key
        else:
            headers["X-Chronos-Key"] = key
    call = {"headers": headers, "params": params}
    if "json" in kwargs:
        call["json"] = kwargs["json"]
    method_fn = getattr(client, method.lower())
    return method_fn(path, **call)


# ---------------------------------------------------------------------------
# /api/health — the ONLY open route (API.md Auth, Chronos.md §8.2)
# ---------------------------------------------------------------------------


def test_health_open_without_key(tmp_path):
    """API.md Auth + Chronos.md §8.2: GET /api/health is the ONLY open route."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get(HEALTH_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db_path"] == db_path
    assert isinstance(body["uptime_seconds"], (int, float))
    assert "version" in body


def test_health_open_with_bad_key(tmp_path):
    """API.md Auth: /api/health stays open even with a wrong key."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get(HEALTH_PATH, headers={"X-Chronos-Key": "wrong-key-value-xyz"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# 401 without key / 401 bad key on every other route (Chronos.md §3, API.md)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,kwargs", AUTHENTICATED_ROUTES)
def test_every_route_401_without_key(tmp_path, method, path, kwargs):
    """Chronos.md §3: every REST request requires the instance key."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = _request(client, method, path, kwargs, key=None)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,path,kwargs", AUTHENTICATED_ROUTES)
def test_every_route_401_with_bad_key(tmp_path, method, path, kwargs):
    """API.md Auth: 401 on bad key for everything except /api/health."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = _request(client, method, path, kwargs, key="bad-key-" + secrets.token_hex(8))
    assert resp.status_code == 401


def test_hardcoded_key_never_accepted(tmp_path):
    """decisions.md: a hardcoded literal key is never acceptable — must 401."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    for literal in ("test-key", "test-key-123"):
        resp = client.get("/api/settings", headers={"X-Chronos-Key": literal})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Good key passes (header + ?key= MCP fallback)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,kwargs", SAFE_GET_ROUTES)
def test_good_key_header_returns_200(tmp_path, path, kwargs):
    """Chronos.md §3: header X-Chronos-Key authenticates; good key is 200."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = _request(client, "GET", path, kwargs, key=raw, use_query=False)
    assert resp.status_code == 200


@pytest.mark.parametrize("method,path,kwargs", AUTHENTICATED_ROUTES)
def test_good_key_never_401(tmp_path, method, path, kwargs):
    """Chronos.md §3: a valid key never yields 401 (200/409/422 all pass)."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = _request(client, method, path, kwargs, key=raw, use_query=False)
    assert resp.status_code != 401


def test_query_key_fallback_accepts_good_key(tmp_path):
    """Chronos.md §3 + API.md Auth: ?key= fallback for MCP clients."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/settings", params={"key": raw})
    assert resp.status_code == 200


def test_query_key_fallback_rejects_bad_key(tmp_path):
    """Chronos.md §3: ?key= with wrong value is still 401."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/settings", params={"key": "bad-key-value"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Key never in logs — header + query (Chronos.md §3, errors B11/B12)
# ---------------------------------------------------------------------------


def test_key_in_header_never_logged(tmp_path, caplog):
    """Chronos.md §3: X-Chronos-Key must never reach a log line (errors B12)."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with caplog.at_level(logging.DEBUG):
        resp = client.get("/api/settings", headers={"X-Chronos-Key": raw})
    assert resp.status_code == 200
    for record in caplog.records:
        message = record.getMessage()
        assert raw not in message
        assert raw not in str(record.args)


def test_key_in_query_never_logged(tmp_path, caplog):
    """Chronos.md §3: a key in a query string is never written to a log."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with caplog.at_level(logging.DEBUG):
        resp = client.get("/api/settings", params={"key": raw})
    assert resp.status_code == 200
    for record in caplog.records:
        message = record.getMessage()
        assert raw not in message
        assert raw not in str(record.args)


def test_key_not_stored_plaintext_in_db_file(tmp_path):
    """Chronos.md §3: key stored Argon2-hashed — raw bytes absent from file."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/settings", headers={"X-Chronos-Key": raw})
    assert resp.status_code == 200
    with open(db_path, "rb") as fh:
        content = fh.read()
    assert raw.encode("utf-8") not in content


# ---------------------------------------------------------------------------
# POST /api/keys/renew rotates + WS drop 4001 (API.md, Chronos.md §3)
# ---------------------------------------------------------------------------


def test_keys_renew_rotates_key(tmp_path):
    """Chronos.md §3 + API.md: POST /api/keys/renew rotates; old key dies."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post("/api/keys/renew", headers={"X-Chronos-Key": raw})
    assert resp.status_code == 200
    body = resp.json()
    assert "new_key" in body
    new_key = body["new_key"]
    assert new_key != raw
    old_resp = client.get("/api/settings", headers={"X-Chronos-Key": raw})
    assert old_resp.status_code == 401
    new_resp = client.get("/api/settings", headers={"X-Chronos-Key": new_key})
    assert new_resp.status_code == 200


def test_keys_renew_requires_auth(tmp_path):
    """Chronos.md §3: key-renew itself requires the current key."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post("/api/keys/renew")
    assert resp.status_code == 401


def test_keys_renew_drops_websocket_with_4001(tmp_path):
    """API.md Auth: renew drops WS with 4001; stale key WS is rejected 4001."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    from starlette.websockets import WebSocketDisconnect

    seen_codes = []
    with client.websocket_connect("/ws?key=" + raw) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        renew = client.post("/api/keys/renew", headers={"X-Chronos-Key": raw})
        assert renew.status_code == 200
        try:
            ws.send_json({"type": "say", "text": "ping after renew"})
            after = ws.receive_json()
            assert after.get("close_code") == 4001
        except WebSocketDisconnect as exc:
            seen_codes.append(exc.code)
            assert exc.code == 4001
    assert seen_codes == [4001]


# ---------------------------------------------------------------------------
# create_app(db_path=None) signature frozen + opens exact file (decisions.md)
# ---------------------------------------------------------------------------


def test_create_app_signature_frozen():
    """decisions.md: create_app(db_path=None) signature is frozen."""
    from chronos.api.app import create_app

    sig = inspect.signature(create_app)
    assert "db_path" in sig.parameters
    assert sig.parameters["db_path"].default is None


def test_create_app_opens_exact_db_file(tmp_path):
    """phase-3-server.md Done: create_app(db_path=...) opens that exact file."""
    from chronos.api.app import create_app

    first = str(tmp_path / "first.db")
    second = str(tmp_path / "second.db")
    raw_first = _mint_key()
    app_first = create_app(db_path=first)
    app_first.state.api_key_hash = _hash_key(raw_first)
    client_first = _client_for(app_first)
    health = client_first.get(HEALTH_PATH)
    assert health.status_code == 200
    assert health.json()["db_path"] == first
    import os

    assert os.path.isfile(first)
    assert os.path.isfile(first) is True
    assert second != first
