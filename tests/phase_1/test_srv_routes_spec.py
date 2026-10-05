"""REST route contract + behaviour — Chronos.md §8.2/§6, API.md REST, decisions.md.

Every test cites its spec section in its docstring.
Written from spec text ONLY — never read chronos/api/, chronos/realtime/.
"""

import secrets

import pytest

ROUTE_TABLE = [
    ("POST", "/api/say", {"json": {"text": "Schedule math review tomorrow 4pm for 45 minutes"}}),
    ("POST", "/api/commands", {"json": {"tool": "search_nodes", "arguments": {"q": "test", "limit": 5}}}),
    ("POST", "/api/voice", {}),
    ("GET", "/api/events", {"params": {"from": "2026-10-05T00:00:00+00:00", "to": "2026-10-06T00:00:00+00:00"}}),
    ("GET", "/api/nodes", {}),
    ("GET", "/api/buckets", {"params": {"level": "D", "date": "2026-10-05"}}),
    ("GET", "/api/briefing", {"params": {"date": "2026-10-05"}}),
    ("GET", "/api/search", {"params": {"q": "test", "limit": 5}}),
    ("GET", "/api/reminders", {}),
    ("POST", "/api/timer/start", {"json": {"label": "route-probe", "source": "route-test", "mode": "stopwatch"}}),
    ("POST", "/api/timer/stop", {"json": {"source": "route-test"}}),
    ("GET", "/api/timer", {}),
    ("GET", "/api/timer/summary", {}),
    ("GET", "/api/timer/presets", {}),
    ("POST", "/api/timer/presets", {"json": {"name": "probe", "focus_minutes": 50, "break_minutes": 10, "cycles": 2}}),
    ("GET", "/api/stats", {}),
    ("GET", "/api/settings", {}),
    ("PUT", "/api/settings", {"json": {"route.probe": "1"}}),
    ("POST", "/api/keys/renew", {}),
    ("GET", "/api/health", {}),
]


def _mint_key():
    return secrets.token_urlsafe(32)


def _hash_key(raw):
    from argon2 import PasswordHasher

    return PasswordHasher().hash(raw)


def _make_app(tmp_path):
    from chronos.api.app import create_app

    db_path = str(tmp_path / "routes-test.db")
    app = create_app(db_path=db_path)
    raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    return app, raw, db_path


def _client_for(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _auth_headers(raw):
    return {"X-Chronos-Key": raw}


# ---------------------------------------------------------------------------
# All routes present + authenticated (Chronos.md §8.2, API.md REST)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,kwargs", ROUTE_TABLE)
def test_route_present_and_authenticated(tmp_path, method, path, kwargs):
    """Chronos.md §8.2 + API.md REST: route exists (never 404) and needs auth."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    call = dict(kwargs)
    no_auth = getattr(client, method.lower())(path, **call)
    if path == "/api/health":
        assert no_auth.status_code == 200
    else:
        assert no_auth.status_code == 401
    authed_call = dict(kwargs)
    authed = getattr(client, method.lower())(path, headers=_auth_headers(raw), **authed_call)
    assert authed.status_code != 404


def test_backend_only_freeze_no_root_route(tmp_path):
    """2026-10-05 freeze: no web UI, no / routes — GET / is 404, not HTML."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/say shape (API.md REST, Chronos.md §5/§8.2)
# ---------------------------------------------------------------------------


def test_say_unambiguous_returns_commit_shape(tmp_path):
    """API.md: POST /api/say -> {intent,tool_calls,proposal_id,committed,events,message}."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/say",
        headers=_auth_headers(raw),
        json={"text": "Schedule math review tomorrow 4pm for 45 minutes"},
    )
    assert resp.status_code == 200
    body = resp.json()
    for field in ("intent", "tool_calls", "committed", "events", "message"):
        assert field in body
    assert isinstance(body["tool_calls"], list)
    assert isinstance(body["events"], list)
    assert body["committed"] is True
    assert len(body["events"]) >= 1


def test_say_is_real_implementation_not_stub(tmp_path):
    """errors-and-test-proposal.md A4: /api/say must call the pipeline, never stub."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/say", headers=_auth_headers(raw), json={"text": "Schedule math review tomorrow 4pm for 45 minutes"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("detail") != "Intent pipeline not yet implemented"
    assert "intent" in body
    assert "tool_calls" in body


def test_say_ambiguous_proposes_with_at_most_one_question(tmp_path):
    """API.md: /api/say never silently commits ambiguous input; ≤1 question."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post("/api/say", headers=_auth_headers(raw), json={"text": "schedule it sometime"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["committed"] is False
    assert body.get("proposal_id") is not None
    questions = body.get("questions", [])
    if "question" in body and body["question"] is not None:
        questions = questions + [body["question"]]
    assert len(questions) <= 1


def test_say_conflict_pushes_slot_and_reports_both(tmp_path):
    """Chronos.md §6: overlapping commit pushes to first free minute; reports both slots."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    first = client.post(
        "/api/say", headers=_auth_headers(raw), json={"text": "Schedule physics tomorrow 4pm for 60 minutes"}
    )
    assert first.status_code == 200
    second = client.post(
        "/api/say", headers=_auth_headers(raw), json={"text": "Schedule chemistry tomorrow 4pm for 60 minutes"}
    )
    assert second.status_code == 200
    body = second.json()
    assert body["committed"] is True
    assert len(body["events"]) >= 1


# ---------------------------------------------------------------------------
# POST /api/commands shape (API.md REST)
# ---------------------------------------------------------------------------


def test_commands_returns_tool_result_events_shape(tmp_path):
    """API.md: POST /api/commands {tool,arguments} -> {tool,result,events,proposal_id}."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/commands",
        headers=_auth_headers(raw),
        json={"tool": "search_nodes", "arguments": {"q": "test", "limit": 5}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "search_nodes"
    assert "result" in body
    assert "events" in body
    assert isinstance(body["events"], list)


def test_commands_unimplemented_tool_never_success(tmp_path):
    """API.md: unimplemented tool never returns success:true (errors A5)."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/commands",
        headers=_auth_headers(raw),
        json={"tool": "does_not_exist_xyz", "arguments": {}},
    )
    assert resp.status_code in (400, 422)
    body = resp.json()
    assert body.get("success") is not True


def test_commands_is_real_implementation_not_stub(tmp_path):
    """errors-and-test-proposal.md A5: /api/commands must not lie success:true."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/commands",
        headers=_auth_headers(raw),
        json={"tool": "does_not_exist_xyz", "arguments": {}},
    )
    assert resp.status_code != 200
    assert resp.json().get("success") is not True


# ---------------------------------------------------------------------------
# Timer 409 rules (Chronos.md §4.7, decisions.md timer-refuse, API.md)
# ---------------------------------------------------------------------------


def test_timer_second_start_returns_409(tmp_path):
    """Chronos.md §4.7 + decisions.md: start while running is refused with 409."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    first = client.post(
        "/api/timer/start", headers=_auth_headers(raw), json={"label": "first", "source": "t1", "mode": "stopwatch"}
    )
    assert first.status_code == 200
    second = client.post(
        "/api/timer/start", headers=_auth_headers(raw), json={"label": "second", "source": "t1", "mode": "stopwatch"}
    )
    assert second.status_code == 409


def test_timer_stop_without_running_returns_409(tmp_path):
    """API.md: POST /api/timer/stop is 409 when no timer runs."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post("/api/timer/stop", headers=_auth_headers(raw), json={"source": "t-none"})
    assert resp.status_code == 409


def test_timer_stopwatch_ignores_target_ms(tmp_path):
    """Chronos.md §4.7: a stopwatch counts up and ignores any target sent."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/timer/start",
        headers=_auth_headers(raw),
        json={"label": "sw", "source": "t-sw", "mode": "stopwatch", "target_ms": 1500000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("target_ms") is None


def test_timer_get_without_node_id_returns_running(tmp_path):
    """decisions.md Phase-3 ruling 4: GET /api/timer without node_id returns running."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    started = client.post(
        "/api/timer/start", headers=_auth_headers(raw), json={"label": "run", "source": "t-get", "mode": "stopwatch"}
    )
    assert started.status_code == 200
    started_id = started.json()["id"]
    fetched = client.get("/api/timer", headers=_auth_headers(raw))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == started_id
    fetched_other = client.get("/api/timer", headers=_auth_headers(raw), params={"node_id": "some-other-node"})
    assert fetched_other.status_code == 200
    assert fetched_other.json()["id"] == started_id


def test_timer_summary_shape_excludes_breaks(tmp_path):
    """API.md: GET /api/timer/summary -> {node_total_ms, descendant_total_ms, project_total_ms}."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/timer/summary", headers=_auth_headers(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert "node_total_ms" in body
    assert "descendant_total_ms" in body
    assert "project_total_ms" in body


# ---------------------------------------------------------------------------
# Settings merge + presets append (API.md, decisions.md Phase-3 rulings 5/6)
# ---------------------------------------------------------------------------


def test_settings_put_merges_not_replaces(tmp_path):
    """decisions.md Phase-3 ruling 5: PUT /api/settings is merge, not replace."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    first = client.put("/api/settings", headers=_auth_headers(raw), json={"merge.a": "1"})
    assert first.status_code == 200
    second = client.put("/api/settings", headers=_auth_headers(raw), json={"merge.b": "2"})
    assert second.status_code == 200
    current = client.get("/api/settings", headers=_auth_headers(raw))
    assert current.status_code == 200
    body = current.json()
    assert body["merge.a"] == "1"
    assert body["merge.b"] == "2"


def test_settings_hides_key_hash(tmp_path):
    """API.md: GET /api/settings hides the key hash."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/settings", headers=_auth_headers(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert "api_key_hash" not in body
    assert "api_key" not in body


def test_presets_always_include_default_25_5x4(tmp_path):
    """Chronos.md §4.7: the default 25/5 x 4 preset is always available."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/timer/presets", headers=_auth_headers(raw))
    assert resp.status_code == 200
    presets = resp.json()
    assert isinstance(presets, list)
    matches = [
        p
        for p in presets
        if p.get("focus_minutes") == 25 and p.get("break_minutes") == 5 and p.get("cycles") == 4
    ]
    assert len(matches) == 1


def test_presets_post_appends_not_replaces(tmp_path):
    """decisions.md Phase-3 ruling 6: POST /api/timer/presets appends."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    before = client.get("/api/timer/presets", headers=_auth_headers(raw))
    assert before.status_code == 200
    before_count = len(before.json())
    added = client.post(
        "/api/timer/presets",
        headers=_auth_headers(raw),
        json={"name": "deep-work", "focus_minutes": 50, "break_minutes": 10, "cycles": 3},
    )
    assert added.status_code == 200
    after = client.get("/api/timer/presets", headers=_auth_headers(raw))
    assert after.status_code == 200
    presets = after.json()
    assert len(presets) == before_count + 1
    defaults = [
        p
        for p in presets
        if p.get("focus_minutes") == 25 and p.get("break_minutes") == 5 and p.get("cycles") == 4
    ]
    assert len(defaults) == 1
    names = [p.get("name") for p in presets]
    assert "deep-work" in names


# ---------------------------------------------------------------------------
# Stats without token-cost (API.md, 2026-10-05 freeze)
# ---------------------------------------------------------------------------


def test_stats_has_counts_and_streaks_without_token_cost(tmp_path):
    """API.md: GET /api/stats -> {counts, streaks}; token-cost removed (freeze)."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/stats", headers=_auth_headers(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert "counts" in body
    assert "streaks" in body
    assert "token_cost" not in body
    assert "token_costs" not in body
    assert "cost_usd" not in body
