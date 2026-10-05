"""Wave-2 API fixes — Chronos.md §4.3/§4.4/§4.8/§7.1/§8.2/§9.1, API.md REST/Auth.

Real sqlite + TestClient, no network. Covers the manager-ruled fixes in
chronos/api/routes.py, chronos/api/app.py, chronos/api/voice.py.
"""

import datetime
import secrets

DATETIME = datetime.datetime
TIMEZONE = datetime.timezone


def _mint_key():
    return secrets.token_urlsafe(32)


def _hash_key(raw):
    from argon2 import PasswordHasher

    return PasswordHasher().hash(raw)


def _make_app(tmp_path, name="fixes-test.db"):
    from chronos.api.app import create_app

    db_path = str(tmp_path / name)
    app = create_app(db_path=db_path)
    raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    return app, raw, db_path


def _client_for(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _auth(raw):
    return {"X-Chronos-Key": raw}


def _cmd(client, raw, tool, args):
    resp = client.post(
        "/api/commands", headers=_auth(raw), json={"tool": tool, "arguments": args}
    )
    assert resp.status_code == 200, resp.text[:500]
    return resp.json()["result"]


# ---------------------------------------------------------------------------
# reschedule_series is real (Chronos.md §4.4: bounded series, honest result)
# ---------------------------------------------------------------------------


def test_reschedule_series_moves_events(tmp_path):
    """§4.4: reschedule deletes series events + regenerates; starts move."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    node = _cmd(client, raw, "create_node", {"kind": "task", "title": "rs task"})
    anchor1 = int(DATETIME(2026, 10, 10, tzinfo=TIMEZONE.utc).timestamp() * 1000)
    series = _cmd(
        client,
        raw,
        "schedule_series",
        {"node_id": node["id"], "tier": "custom", "offsets_days": [1],
         "max_count": 1, "anchor_ms": anchor1},
    )
    sid = series.get("series_id") or series.get("id")
    assert sid, series

    def _series_events():
        resp = client.get(
            "/api/events",
            headers=_auth(raw),
            params={"from": "2026-10-01T00:00:00+00:00", "to": "2026-12-01T00:00:00+00:00"},
        )
        assert resp.status_code == 200
        return [e for e in resp.json() if e.get("series_id") == sid]

    before = _series_events()
    assert len(before) == 1
    anchor2 = int(DATETIME(2026, 11, 10, tzinfo=TIMEZONE.utc).timestamp() * 1000)
    moved = _cmd(client, raw, "reschedule_series", {"series_id": sid, "anchor_ms": anchor2})
    assert moved.get("rescheduled") is True
    after = _series_events()
    assert len(after) == 1, "one transaction: old deleted, new generated"
    assert after[0]["start_ms"] != before[0]["start_ms"]
    assert after[0]["start_ms"] == (anchor2 // 60000) * 60000 + 86400000


def test_reschedule_unknown_series_is_honest_error(tmp_path):
    """§4.4/API.md: unknown series never reports success:true (400, no lie)."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/commands",
        headers=_auth(raw),
        json={"tool": "reschedule_series", "arguments": {"series_id": "nope"}},
    )
    assert resp.status_code == 400
    assert resp.json().get("success") is not True


# ---------------------------------------------------------------------------
# voice uses the real STT adapter, 503 when unconfigured (API.md REST voice)
# ---------------------------------------------------------------------------


def _add_stt_provider(db_path):
    import sqlite3

    from chronos.ai.providers.registry import ProviderRegistry

    conn = sqlite3.connect(db_path)
    try:
        reg = ProviderRegistry(conn)
        entry = reg.create_provider(
            "stt", "fake-stt", "https://stt.example/v1", "whisper-large-v3-turbo"
        )
        reg.add_key(entry["id"], "k-fake")
        conn.commit()
    finally:
        conn.close()


def test_voice_calls_adapter_fake(tmp_path):
    """API.md voice: POST /api/voice returns the STT adapter transcript."""
    app, raw, db_path = _make_app(tmp_path)
    _add_stt_provider(db_path)

    def _fake_transport(url, headers, payload):
        return {"choices": [{"message": {"content": "hello world"}}]}

    app.state.provider_transport = _fake_transport
    client = _client_for(app)
    resp = client.post(
        "/api/voice", headers=_auth(raw), files={"file": ("a.wav", b"fake-audio")}
    )
    assert resp.status_code == 200, resp.text[:500]
    assert resp.json()["transcript"] == "hello world"


def test_voice_unconfigured_is_503(tmp_path):
    """API.md voice: no STT provider configured -> graceful 503, never empty lie."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/voice", headers=_auth(raw), files={"file": ("a.wav", b"fake-audio")}
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# briefing is real (Chronos.md §9.1/§5.6: generated, varies with data)
# ---------------------------------------------------------------------------


def test_briefing_varies_with_data(tmp_path):
    """§9.1 + §5.6: GET /api/briefing calls build_briefing; checked tracks nodes."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    first = client.get("/api/briefing", headers=_auth(raw), params={"date": "2026-10-06"})
    assert first.status_code == 200
    assert first.json()["date"] == "2026-10-06"
    assert first.json()["checked"] == 0
    _cmd(client, raw, "create_node", {"kind": "task", "title": "briefing probe"})
    second = client.get("/api/briefing", headers=_auth(raw), params={"date": "2026-10-06"})
    assert second.status_code == 200
    assert second.json()["checked"] == 1
    assert second.json() != first.json()


# ---------------------------------------------------------------------------
# settings guard + rotation (Chronos.md §3: key stored hashed, renewed only)
# ---------------------------------------------------------------------------


def test_settings_hash_overwrite_refused_but_renew_works(tmp_path):
    """§3: PUT /api/settings refuses key-hash overwrite (403/422); renew rotates."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    for evil in ("api_key_hash", "api_key", "API_KEY_HASH"):
        resp = client.put("/api/settings", headers=_auth(raw), json={evil: "x"})
        assert resp.status_code in (403, 422), (evil, resp.status_code)
    ok = client.put("/api/settings", headers=_auth(raw), json={"ui.theme": "dark"})
    assert ok.status_code == 200
    renew = client.post("/api/keys/renew", headers=_auth(raw))
    assert renew.status_code == 200
    new_key = renew.json()["new_key"]
    assert client.get("/api/settings", headers=_auth(raw)).status_code == 401
    assert client.get("/api/settings", headers=_auth(new_key)).status_code == 200


# ---------------------------------------------------------------------------
# buckets seeded + FTS canonical + tz day-range + tag guard
# ---------------------------------------------------------------------------


def test_buckets_non_empty_after_create_app(tmp_path):
    """§4.3: seed_buckets runs at startup so /api/buckets is never empty."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.get("/api/buckets", headers=_auth(raw))
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_fts_row_findable_post_create(tmp_path):
    """§4.8: canonical fts5(title, notes, node_id UNINDEXED) written on create."""
    import sqlite3

    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    created = _cmd(client, raw, "create_node", {"kind": "task", "title": "zephyrquux task"})
    resp = client.get("/api/search", headers=_auth(raw), params={"q": "zephyrquux"})
    assert resp.status_code == 200
    found = [n for n in resp.json() if n.get("id") == created["id"]]
    assert found, resp.json()
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT node_id FROM node_fts WHERE node_fts MATCH 'zephyrquux'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] == created["id"]


def test_day_range_uses_instance_timezone(tmp_path):
    """§7.1: day boundaries use instance.timezone, never hardcoded UTC."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    client.put("/api/settings", headers=_auth(raw), json={"instance.timezone": "America/New_York"})
    body = _cmd(client, raw, "get_day", {"date": "2026-10-05"})
    ny_midnight_utc = int(DATETIME(2026, 10, 5, 4, tzinfo=TIMEZONE.utc).timestamp() * 1000)
    assert body["start_ms"] == ny_midnight_utc
    assert body["start_ms"] != int(DATETIME(2026, 10, 5, tzinfo=TIMEZONE.utc).timestamp() * 1000)


def test_tag_on_project_is_422_not_500(tmp_path):
    """§4.1: tag_node on a project is 422 (code guard, never trigger-500)."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    proj = _cmd(client, raw, "create_node", {"kind": "project", "title": "untaggable"})
    resp = client.post(
        "/api/commands",
        headers=_auth(raw),
        json={"tool": "tag_node", "arguments": {"node_id": proj["id"], "tag": "t"}},
    )
    assert resp.status_code == 422
