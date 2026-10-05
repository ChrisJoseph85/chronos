"""Realtime contract — Chronos.md §8.3, API.md WebSocket, phase-3-server.md WS.

Every test cites its spec section in its docstring.
Written from spec text ONLY — never read chronos/api/, chronos/realtime/.
"""

import secrets


def _mint_key():
    return secrets.token_urlsafe(32)


def _hash_key(raw):
    from argon2 import PasswordHasher

    return PasswordHasher().hash(raw)


def _make_app(tmp_path):
    from chronos.api.app import create_app

    db_path = str(tmp_path / "realtime-test.db")
    app = create_app(db_path=db_path)
    raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    return app, raw, db_path


def _client_for(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


ALLOWED_SERVER_TYPES = {"state", "patch", "proposal", "question", "timer", "queued", "retrying"}


def test_websockets_dependency_importable():
    """phase-3-server.md + errors C15: server needs a real WS stack (websockets)."""
    import importlib

    module = importlib.import_module("websockets")
    assert module.__name__ == "websockets"


def test_ws_rejects_missing_key_with_4001(tmp_path):
    """Chronos.md §8.3 + API.md: auth on upgrade, then accept(); reject = 4001."""
    from starlette.websockets import WebSocketDisconnect

    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws") as ws:
        try:
            ws.receive_json()
            assert False, "expected WebSocketDisconnect 4001"
        except WebSocketDisconnect as exc:
            assert exc.code == 4001


def test_ws_rejects_bad_key_with_4001(tmp_path):
    """Chronos.md §3: every WebSocket upgrade requires the instance key."""
    from starlette.websockets import WebSocketDisconnect

    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=bad-key-value") as ws:
        try:
            ws.receive_json()
            assert False, "expected WebSocketDisconnect 4001"
        except WebSocketDisconnect as exc:
            assert exc.code == 4001


def test_ws_accepts_good_key_and_sends_full_state(tmp_path):
    """Chronos.md §8.3: server→state is the full snapshot on connect."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=" + raw) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        assert isinstance(first, dict)
        assert len(first) >= 2


def test_ws_server_messages_use_documented_types(tmp_path):
    """API.md WS: server→ is only {state,patch,proposal,question,timer,queued,retrying}."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=" + raw) as ws:
        first = ws.receive_json()
        assert first["type"] in ALLOWED_SERVER_TYPES
        ws.send_json({"type": "say", "text": "Schedule math review tomorrow 4pm for 45 minutes"})
        second = ws.receive_json()
        assert second["type"] in ALLOWED_SERVER_TYPES


def test_ws_client_hello_say_accept_flow(tmp_path):
    """Chronos.md §8.3: client→{hello,say,accept|reject|skip}; server answers proposal."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=" + raw) as ws:
        state = ws.receive_json()
        assert state["type"] == "state"
        ws.send_json({"type": "hello", "key": raw, "device": "ws-test"})
        ws.send_json({"type": "say", "text": "Schedule math review tomorrow 4pm for 45 minutes"})
        reply = ws.receive_json()
        assert reply["type"] in ALLOWED_SERVER_TYPES
        assert reply["type"] in ("proposal", "question", "patch", "state", "queued")
        proposal_id = reply.get("proposal_id")
        assert proposal_id is not None
        ws.send_json({"type": "accept", "proposal_id": proposal_id})
        done = ws.receive_json()
        assert done["type"] in ALLOWED_SERVER_TYPES


def test_ws_client_reject_and_skip_shapes(tmp_path):
    """Chronos.md §8.3: client→reject|skip with proposal_id is accepted by the hub."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=" + raw) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_json({"type": "say", "text": "schedule it sometime"})
        reply = ws.receive_json()
        assert reply["type"] in ALLOWED_SERVER_TYPES
        proposal_id = reply.get("proposal_id")
        assert proposal_id is not None
        ws.send_json({"type": "reject", "proposal_id": proposal_id})
        after_reject = ws.receive_json()
        assert after_reject["type"] in ALLOWED_SERVER_TYPES


def test_ws_every_mutation_broadcasts_to_all_clients(tmp_path):
    """Chronos.md §8.3: every mutation broadcasts to all connected clients."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=" + raw) as ws_a:
        with client.websocket_connect("/ws?key=" + raw) as ws_b:
            state_a = ws_a.receive_json()
            state_b = ws_b.receive_json()
            assert state_a["type"] == "state"
            assert state_b["type"] == "state"
            rest = client.put(
                "/api/settings",
                headers={"X-Chronos-Key": raw},
                json={"realtime.broadcast.probe": "1"},
            )
            assert rest.status_code == 200
            msg_a = ws_a.receive_json()
            msg_b = ws_b.receive_json()
            assert msg_a["type"] in ALLOWED_SERVER_TYPES
            assert msg_b["type"] in ALLOWED_SERVER_TYPES
            assert msg_a["type"] in ("patch", "state")
            assert msg_b["type"] in ("patch", "state")


def test_ws_timer_mutation_broadcasts_timer_frame(tmp_path):
    """Chronos.md §8.3: server→timer on tick/start/stop reaches every client."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    with client.websocket_connect("/ws?key=" + raw) as ws_a:
        with client.websocket_connect("/ws?key=" + raw) as ws_b:
            assert ws_a.receive_json()["type"] == "state"
            assert ws_b.receive_json()["type"] == "state"
            started = client.post(
                "/api/timer/start",
                headers={"X-Chronos-Key": raw},
                json={"label": "ws-timer", "source": "ws-test", "mode": "stopwatch"},
            )
            assert started.status_code == 200
            timer_a = ws_a.receive_json()
            timer_b = ws_b.receive_json()
            assert timer_a["type"] == "timer"
            assert timer_b["type"] == "timer"
