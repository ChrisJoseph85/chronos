"""Timer tests: breakdown math, void flag logic, 409 handling. Fakes only."""
import io
import json
import urllib.error

import pytest

from desktop.app.state import (build_stop_body, session_elapsed_ms,
                               summarize_breakdown)
from desktop.app.transport import ChronosClient, TimerConflict


class FakeResp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status = status

    def read(self):
        return json.dumps(self._p).encode()


def make_client(handler):
    return ChronosClient("http://127.0.0.1:8080", key="K", opener=handler)


def test_breakdown_math_totals_and_order():
    rows = [
        {"node_id": "a", "title": "A", "kind": "task", "total_ms": 100},
        {"node_id": "b", "title": "B", "kind": "project", "total_ms": 300},
        {"node_id": "c", "title": "C", "kind": "task", "total_ms": 0},
    ]
    agg = summarize_breakdown(rows)
    assert agg["total_ms"] == 400
    assert [r["node_id"] for r in agg["rows"]] == ["b", "a", "c"]
    assert agg["by_kind"] == {"task": 100, "project": 300}
    assert summarize_breakdown([])["total_ms"] == 0


def test_void_flag_clean_keeps_distracted_voids():
    assert build_stop_body("desktop", distracted=False) == {"source": "desktop", "void": False}
    assert build_stop_body("desktop", distracted=True) == {"source": "desktop", "void": True}


def test_stop_sends_void_through_wire():
    bodies = []

    def opener(req):
        bodies.append(json.loads(req.data.decode()))
        return FakeResp({"label": "s", "voided": bodies[-1]["void"]})

    c = make_client(opener)
    assert c.timer_stop(source="desktop", void=False)["voided"] is False
    assert c.timer_stop(source="desktop", void=True)["voided"] is True
    assert bodies == [{"source": "desktop", "void": False},
                      {"source": "desktop", "void": True}]


def test_start_409_conflict_surfaced_with_payload():
    def opener(req):
        raise urllib.error.HTTPError(req.full_url, 409, "conflict", {},
                                     io.BytesIO(b'{"label": "remote"}'))

    c = make_client(opener)
    with pytest.raises(TimerConflict) as ei:
        c.timer_start("new")
    assert ei.value.payload == {"label": "remote"}


def test_elapsed_running_and_stopped():
    assert session_elapsed_ms({"start_ms": 1000, "end_ms": None}, 6000) == 5000
    assert session_elapsed_ms({"start_ms": 0, "end_ms": 5000}, 99999) == 5000
    assert session_elapsed_ms({"start_ms": 0, "end_ms": None, "base_ms": 2000}, 3000) == 5000


def test_pomodoro_target_sent_stopwatch_ignores_target():
    bodies = []

    def opener(req):
        bodies.append(json.loads(req.data.decode()))
        return FakeResp({"ok": True})

    c = make_client(opener)
    c.timer_start("pom", mode="pomodoro", target_ms=25 * 60 * 1000)
    c.timer_start("sw", mode="stopwatch", target_ms=12345)
    assert bodies[0]["target_ms"] == 25 * 60 * 1000
    assert "target_ms" not in bodies[1]
