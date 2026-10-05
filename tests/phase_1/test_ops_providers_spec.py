"""Provider-management API spec tests — Chronos.md §5.1 + proposals B.3.

Covers the REST API that FULLY REPLACES `chronos setup`: step 1 STT
endpoint+model+keys, step 2 N text providers in order+keys, step 3
embeddings endpoint+model. Entry order = failover order; multi-key
round-robin. Keys are WRITE-ONLY: no response body may contain a value.

Real sqlite file via create_app(db_path=...). Fake transports only —
NO network (socket + urlopen blocked).
"""

import json
import secrets
import socket
import sqlite3
import urllib.request

import pytest

SPEC = "Chronos.md §5.1 + proposals B.3"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network blocked: use fake transports (%s)" % SPEC)

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


def _mint_key():
    return secrets.token_urlsafe(32)


def _hash_key(raw):
    try:
        from argon2 import PasswordHasher

        return PasswordHasher().hash(raw)
    except Exception:
        import hashlib

        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _make_app(tmp_path):
    from chronos.api.app import create_app

    db_path = str(tmp_path / ("providers-%s.db" % secrets.token_hex(4)))
    app = create_app(db_path=db_path)
    raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    return app, raw, db_path


def _client_for(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _auth(raw):
    return {"X-Chronos-Key": raw}


def _make_provider(client, raw, group="text", name="groq", base_url="https://api.groq.com/openai/v1",
                   model="openai/gpt-oss-120b", position=None):
    payload = {"group": group, "name": name, "base_url": base_url, "model": model}
    if position is not None:
        payload["position"] = position
    resp = client.post("/api/providers", headers=_auth(raw), json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _add_key(client, raw, provider_id, value):
    resp = client.post(f"/api/providers/{provider_id}/keys", headers=_auth(raw), json={"key": value})
    assert resp.status_code == 200, resp.text
    return resp.json()


class FakeModelsTransport:
    """Fake GET {base}/models transport. mapping: prefix -> list-of-ids | Exception."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, url, headers=None, payload=None):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        for prefix, outcome in self.mapping.items():
            if url.startswith(prefix.rstrip("/") + "/models") or url.startswith(prefix):
                if isinstance(outcome, BaseException):
                    raise outcome
                return {"data": [{"id": m} for m in outcome]}
        return {"data": []}


def test_auth_401_on_all_new_routes(tmp_path):
    """§5.1 API: every provider route 401s without key; /api/health stays open."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    prov = _make_provider(client, raw)
    kid = _add_key(client, raw, prov["id"], "sk-auth-probe-1")["key_id"]
    probes = [
        ("GET", "/api/providers", {}),
        ("POST", "/api/providers", {"json": {"group": "text", "name": "x", "base_url": "https://x.local/v1"}}),
        ("PUT", f"/api/providers/{prov['id']}", {"json": {"name": "y"}}),
        ("DELETE", f"/api/providers/{prov['id']}", {}),
        ("POST", f"/api/providers/{prov['id']}/keys", {"json": {"key": "sk-nope"}}),
        ("DELETE", f"/api/providers/{prov['id']}/keys/{kid}", {}),
        ("POST", "/api/providers/active", {"json": {"group": "text", "id": prov["id"]}}),
        ("POST", f"/api/providers/{prov['id']}/check", {}),
        ("POST", "/api/providers/check-all", {}),
    ]
    for method, path, kw in probes:
        resp = getattr(client, method.lower())(path, **kw)
        assert resp.status_code == 401, "%s %s: expected 401, got %d (%s)" % (method, path, resp.status_code, SPEC)
    assert client.get("/api/health").status_code == 200


def test_full_crud_grouped_and_ordered(tmp_path):
    """§5.1 steps 1-3: CRUD providers; GET groups stt/text/embeddings with text in entry order."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    stt = _make_provider(client, raw, group="stt", name="stt",
                         base_url="https://stt.local/v1", model="whisper-large-v3-turbo")
    t1 = _make_provider(client, raw, group="text", name="groq",
                        base_url="https://api.groq.com/openai/v1", model="openai/gpt-oss-120b")
    t2 = _make_provider(client, raw, group="text", name="nim",
                        base_url="https://integrate.api.nvidia.com/v1",
                        model="nvidia/nemotron-3-super-120b-a12b")
    emb = _make_provider(client, raw, group="embeddings", name="local",
                         base_url="http://127.0.0.1:11434/v1", model="llama-embedding")
    resp = client.get("/api/providers", headers=_auth(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"stt", "text", "embeddings"}
    assert [p["id"] for p in body["text"]] == [t1["id"], t2["id"]]
    assert body["stt"][0]["id"] == stt["id"]
    assert body["embeddings"][0]["id"] == emb["id"]
    for entry in body["stt"] + body["text"] + body["embeddings"]:
        assert "key_ids" in entry and "key_count" in entry
    upd = client.put(f"/api/providers/{t1['id']}", headers=_auth(raw), json={"model": "openai/gpt-oss-20b"})
    assert upd.status_code == 200
    assert upd.json()["model"] == "openai/gpt-oss-20b"
    dele = client.delete(f"/api/providers/{emb['id']}", headers=_auth(raw))
    assert dele.status_code == 200
    gone = client.get("/api/providers", headers=_auth(raw)).json()
    assert all(p["id"] != emb["id"] for p in gone["embeddings"])


def test_post_rejects_bad_group_and_url(tmp_path):
    """§5.1: POST 422 on bad group/URL (proposals B.3 validation)."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    bad_group = client.post("/api/providers", headers=_auth(raw),
                            json={"group": "video", "name": "x", "base_url": "https://x.local/v1"})
    assert bad_group.status_code == 422
    bad_url = client.post("/api/providers", headers=_auth(raw),
                          json={"group": "text", "name": "x", "base_url": "not-a-url"})
    assert bad_url.status_code == 422


def test_put_with_key_field_is_422_and_keys_untouched(tmp_path):
    """Proposals B.3 write-only rule: PUT accepting any key field must 422; keys untouched."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    prov = _make_provider(client, raw)
    kid = _add_key(client, raw, prov["id"], "sk-put-untouched-1")["key_id"]
    resp = client.put(f"/api/providers/{prov['id']}", headers=_auth(raw),
                      json={"name": "renamed", "key": "sk-evil"})
    assert resp.status_code == 422
    body = client.get("/api/providers", headers=_auth(raw)).json()
    entry = [p for p in body["text"] if p["id"] == prov["id"]][0]
    assert entry["key_ids"] == [kid]
    assert entry["key_count"] == 1


def test_keys_write_only_never_in_any_response(tmp_path):
    """Proposals B.3 core security rule: key VALUES must not appear in ANY response body."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    secrets_made = ["sk-writeonly-%s" % secrets.token_hex(8) for _ in range(3)]
    prov = _make_provider(client, raw)
    bodies = []
    for s in secrets_made:
        r = client.post(f"/api/providers/{prov['id']}/keys", headers=_auth(raw), json={"key": s})
        assert r.status_code == 200
        bodies.append(r.text)
        assert s not in r.text
        assert r.json().get("key_id")
        assert "key" not in {k.lower() for k in r.json().keys()} or True
        assert set(r.json().keys()) == {"key_id"}
    for method, path, kw in [
        ("GET", "/api/providers", {"headers": _auth(raw)}),
        ("PUT", f"/api/providers/{prov['id']}", {"headers": _auth(raw), "json": {"name": "n2"}}),
    ]:
        r = getattr(client, method.lower())(path, **kw)
        bodies.append(r.text)
    check = client.post(f"/api/providers/{prov['id']}/check", headers=_auth(raw))
    bodies.append(check.text)
    check_all = client.post("/api/providers/check-all", headers=_auth(raw))
    bodies.append(check_all.text)
    blob = json.dumps(bodies)
    for s in secrets_made:
        assert s not in blob, "%s: key value leaked in response" % SPEC
    assert client.get(f"/api/providers/{prov['id']}/keys", headers=_auth(raw)).status_code in (404, 405)


def test_delete_cascades_keys(tmp_path):
    """Proposals B.3: DELETE provider removes entry + keys (CASCADE)."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    prov = _make_provider(client, raw)
    _add_key(client, raw, prov["id"], "sk-cascade-1")
    _add_key(client, raw, prov["id"], "sk-cascade-2")
    assert client.delete(f"/api/providers/{prov['id']}", headers=_auth(raw)).status_code == 200
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT * FROM provider_keys WHERE provider_id = ?", (prov["id"],)).fetchall()
        assert rows == []
        assert conn.execute("SELECT * FROM providers WHERE id = ?", (prov["id"],)).fetchone() is None
    finally:
        conn.close()


def test_active_switch_per_group(tmp_path):
    """§5.1 Settings switching: POST /api/providers/active switches active provider per group."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    t1 = _make_provider(client, raw, name="first")
    t2 = _make_provider(client, raw, name="second", base_url="https://second.local/v1")
    resp = client.post("/api/providers/active", headers=_auth(raw),
                       json={"group": "text", "id": t2["id"]})
    assert resp.status_code == 200
    body = client.get("/api/providers", headers=_auth(raw)).json()
    flags = {p["id"]: p["active"] for p in body["text"]}
    assert flags[t2["id"]] == 1
    assert flags[t1["id"]] == 0


def test_reorder_changes_chain_order(tmp_path):
    """§5.1 failover: entry order IS failover order; reorder changes build_chain order."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    t1 = _make_provider(client, raw, name="groq", position=0)
    t2 = _make_provider(client, raw, name="nim", base_url="https://nim.local/v1", position=1)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        assert reg.build_chain("text").names() == ["groq", "nim"]
    finally:
        conn.close()
    resp = client.put(f"/api/providers/{t2['id']}", headers=_auth(raw), json={"position": 0})
    assert resp.status_code == 200
    conn2 = sqlite3.connect(db)
    conn2.row_factory = sqlite3.Row
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg2 = ProviderRegistry(conn2)
        assert reg2.build_chain("text").names() == ["nim", "groq"]
    finally:
        conn2.close()
    body = client.get("/api/providers", headers=_auth(raw)).json()
    assert [p["name"] for p in body["text"]] == ["nim", "groq"]


def test_round_robin_across_keys(tmp_path):
    """§5.1: multiple keys per endpoint tried round-robin before falling through."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    prov = _make_provider(client, raw)
    _add_key(client, raw, prov["id"], "sk-rr-1")
    _add_key(client, raw, prov["id"], "sk-rr-2")

    class ChatFake:
        def __init__(self):
            self.calls = []

        def __call__(self, url, headers, payload):
            self.calls.append(dict(headers))
            return {"choices": [{"message": {"content": "ok"}}]}

    transport = ChatFake()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        chain = reg.build_chain("text", transport=transport)
        assert len(chain.providers) == 1
        adapter = chain.providers[0]
        for _ in range(4):
            adapter.complete([{"role": "user", "content": "hi"}])
        bearers = [c.get("Authorization") for c in transport.calls]
        assert bearers == ["Bearer sk-rr-1", "Bearer sk-rr-2", "Bearer sk-rr-1", "Bearer sk-rr-2"]
    finally:
        conn.close()


def test_check_returns_discovered_ids(tmp_path):
    """Proposals B.3 step check: POST /{id}/check uses server-side key, returns discovered ids."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    prov = _make_provider(client, raw, base_url="https://live.local/v1")
    _add_key(client, raw, prov["id"], "sk-check-live")
    app.state.provider_transport = FakeModelsTransport({"https://live.local/v1": ["m1", "m2"]})
    resp = client.post(f"/api/providers/{prov['id']}/check", headers=_auth(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == prov["id"]
    assert body["reachable"] is True
    assert body["models"] == ["m1", "m2"]


def test_check_all_isolates_dead_provider(tmp_path):
    """Proposals B.3: POST /check-all per-provider results; one failure never fails others."""
    app, raw, db = _make_app(tmp_path)
    client = _client_for(app)
    live = _make_provider(client, raw, name="live", base_url="https://live.local/v1")
    dead = _make_provider(client, raw, name="dead", base_url="https://dead.local/v1")
    _add_key(client, raw, live["id"], "sk-live")
    _add_key(client, raw, dead["id"], "sk-dead")
    import urllib.error

    app.state.provider_transport = FakeModelsTransport({
        "https://live.local/v1": ["mx"],
        "https://dead.local/v1": urllib.error.URLError("down"),
    })
    resp = client.post("/api/providers/check-all", headers=_auth(raw))
    assert resp.status_code == 200
    results = {r["id"]: r for r in resp.json()["results"]}
    assert results[live["id"]]["reachable"] is True
    assert results[live["id"]]["models"] == ["mx"]
    assert results[dead["id"]] == {"id": dead["id"], "reachable": False, "models": []}


def test_discover_models_graceful_on_bad_shape(tmp_path):
    """Proposals B.3: discover_models graceful on error/timeout/non-OpenAI shape."""
    from chronos.ai.providers.registry import discover_models

    assert discover_models("https://x.local/v1", "k", transport=lambda *a, **k: (_ for _ in ()).throw(TimeoutError())) == {
        "reachable": False, "models": []}
    assert discover_models("https://x.local/v1", "k", transport=lambda *a, **k: {"weird": 1}) == {
        "reachable": False, "models": []}
    ok = discover_models("https://x.local/v1", "k",
                         transport=lambda *a, **k: {"data": [{"id": "a"}, {"id": "b"}]})
    assert ok == {"reachable": True, "models": ["a", "b"]}
