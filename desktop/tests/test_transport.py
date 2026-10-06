"""Transport tests: auth headers, health gate, key-absence-in-logs. Fakes only."""
import io
import json
import logging
import urllib.error

import pytest

from desktop.app.transport import (ApiError, AuthError, ChronosClient, ServerDown,
                                   TimerConflict, safe_headers)


class FakeResp:
    def __init__(self, payload=None, status=200):
        self._payload = payload if payload is not None else {}
        self.status = status

    def read(self):
        return json.dumps(self._payload).encode()


class FakeOpener:
    """Records requests; canned responses keyed by (method, path)."""

    def __init__(self):
        self.requests = []
        self.routes = {}
        self.calls = 0

    def add(self, method, path, payload=None, status=200):
        self.routes[(method, path)] = (payload, status)

    def __call__(self, req):
        self.calls += 1
        self.requests.append(req)
        key = (req.get_method(), req.full_url.split("127.0.0.1:8080")[-1])
        if key in self.routes:
            payload, status = self.routes[key]
            if status >= 400:
                raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(b"{}"))
            return FakeResp(payload, status)
        return FakeResp({"ok": True})


def headers_of(req):
    return {k.lower(): v for k, v in req.header_items()}


def test_auth_header_sent():
    op = FakeOpener()
    c = ChronosClient("http://127.0.0.1:8080", key="K123", opener=op)
    c.say("hi")
    assert headers_of(op.requests[0])["x-chronos-key"] == "K123"


def test_health_is_open_no_key_header():
    op = FakeOpener()
    op.add("GET", "/api/health", {"status": "ok", "version": "1.2"})
    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=op)
    data = c.check_health()
    assert data["status"] == "ok" and c.healthy and c.version == "1.2"
    assert "x-chronos-key" not in headers_of(op.requests[0])


def test_health_gate_blocks_writes():
    op = FakeOpener()
    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=op)
    c.healthy = False
    with pytest.raises(ServerDown):
        c.say("blocked")
    with pytest.raises(ServerDown):
        c.timer_start("x")
    assert op.calls == 0  # no network touched


def test_health_failure_marks_down():
    def boom(req):
        raise urllib.error.URLError("refused")

    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=boom)
    with pytest.raises(ServerDown):
        c.check_health()
    assert c.healthy is False


def test_401_maps_to_auth_error():
    op = FakeOpener()
    op.add("POST", "/api/say", None, status=401)
    c = ChronosClient("http://127.0.0.1:8080", key="BAD", opener=op)
    with pytest.raises(AuthError):
        c.say("hi")


def test_409_maps_to_timer_conflict():
    op = FakeOpener()
    op.add("POST", "/api/timer/start", {"running": True}, status=409)
    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=op)
    with pytest.raises(TimerConflict):
        c.timer_start("x")


def test_other_error_maps_to_api_error():
    op = FakeOpener()
    op.add("GET", "/api/nodes?parent=", None, status=422)
    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=op)
    with pytest.raises(ApiError) as ei:
        c.nodes()
    assert ei.value.status == 422


def test_key_never_in_logs():
    op = FakeOpener()
    c = ChronosClient("http://127.0.0.1:8080", key="INSTANCE-SECRET-1", opener=op)
    records = []

    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r.getMessage())

    logger = logging.getLogger("desktop.app.transport")
    h = Cap()
    logger.addHandler(h)
    try:
        c.say("hello")
        c.providers_add_key("p1", "PROVIDER-SECRET-2")
        c.timer_start("focus")
    finally:
        logger.removeHandler(h)
    blob = "\n".join(records)
    assert "INSTANCE-SECRET-1" not in blob
    assert "PROVIDER-SECRET-2" not in blob
    # redaction helper itself
    assert safe_headers({"X-Chronos-Key": "abc"}) == {"X-Chronos-Key": "***"}
