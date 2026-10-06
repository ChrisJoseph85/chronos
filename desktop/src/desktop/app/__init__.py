"""Chronos desktop entry point: `chronos-desktop [--smoke] [--url URL]`."""
from __future__ import annotations

import argparse
import sys


def self_check():
    """No-GUI, no-network self check: transport headers/gate, redact,
    state math, notify floor, keystore round-trip. Returns (ok, lines)."""
    import io
    import logging
    import tempfile
    lines = []

    from .notify import clamp_interval
    from .state import (build_stop_body, load_key, save_key, session_elapsed_ms,
                        summarize_breakdown)
    from .transport import ChronosClient, ServerDown, safe_headers

    # -- auth header + gate (fake opener, no network) ---------------------
    seen = {}

    class FakeResp:
        status = 200

        def read(self):
            return b'{"ok": true}'

    def opener(req):
        seen["headers"] = dict(req.header_items())
        return FakeResp()

    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=opener)
    c.say("hi")
    hdrs = {k.lower(): v for k, v in seen["headers"].items()}
    assert hdrs.get("x-chronos-key") == "K", "X-Chronos-Key missing"
    lines.append("auth header ok")
    assert safe_headers({"X-Chronos-Key": "K"}) == {"X-Chronos-Key": "***"}
    lines.append("redact ok")
    c.healthy = False
    try:
        c.say("blocked")
        raise AssertionError("gate did not block")
    except ServerDown:
        lines.append("health gate ok")

    # -- key never in logs ------------------------------------------------
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    logging.getLogger("desktop.app.transport").addHandler(h)
    try:
        c2 = ChronosClient("http://127.0.0.1:8080", key="SUPERSECRET", opener=opener)
        c2.say("hello")
        c2.providers_add_key("p1", "PROVIDERSECRET")
    finally:
        logging.getLogger("desktop.app.transport").removeHandler(h)
    blob = buf.getvalue()
    assert "SUPERSECRET" not in blob and "PROVIDERSECRET" not in blob, "key leaked to logs"
    lines.append("key-absence-in-logs ok")

    # -- state math ---------------------------------------------------------
    assert build_stop_body("desktop", False) == {"source": "desktop", "void": False}
    assert build_stop_body("desktop", True) == {"source": "desktop", "void": True}
    lines.append("void flag ok")
    agg = summarize_breakdown([
        {"node_id": "a", "title": "A", "kind": "task", "total_ms": 100},
        {"node_id": "b", "title": "B", "kind": "project", "total_ms": 300}])
    assert agg["total_ms"] == 400 and agg["rows"][0]["node_id"] == "b"
    assert agg["by_kind"] == {"task": 100, "project": 300}
    lines.append("breakdown ok")
    assert session_elapsed_ms({"start_ms": 0, "end_ms": 5000}, 9999) == 5000
    assert session_elapsed_ms({"start_ms": 1000, "end_ms": None}, 6000) == 5000
    lines.append("elapsed ok")
    assert clamp_interval(5) == 30 and clamp_interval(60) == 60
    lines.append("poll floor ok")

    # -- keystore round-trip (file fallback, tmp HOME) -----------------------
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/key"
        assert save_key("abc", path=p, use_secret=False) == "file"
        assert load_key(path=p, use_secret=False) == "abc"
        import os, stat
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    lines.append("keystore ok")
    return True, lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog="chronos-desktop")
    parser.add_argument("--smoke", action="store_true",
                        help="self-check transport+state, no GUI, no network")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    args = parser.parse_args(argv)

    if args.smoke:
        try:
            ok, lines = self_check()
        except Exception as e:  # noqa: BLE001
            print(f"SMOKE FAIL: {e}")
            return 1
        for line in lines:
            print(f"smoke: {line}")
        print("SMOKE PASS")
        return 0

    # -- GUI -----------------------------------------------------------------
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio
    except Exception as e:
        print(f"chronos-desktop: GTK4/libadwaita unavailable: {e}", file=sys.stderr)
        return 2

    from .notify import Notifier, briefing_question_text, start_polling
    from .state import AppState, load_key
    from .transport import ChronosClient, WsClient

    state = AppState(base_url=args.url)
    client = ChronosClient(args.url, key=load_key())
    notifier = Notifier()

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id="io.chronos.desktop",
                             flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
            self._windows = {}

        def do_activate(self):
            from .windows.bar import BarWindow
            if "bar" not in self._windows:
                self._windows["bar"] = BarWindow(self, client, state, self.show_w2)
            self._windows["bar"].present()

        def show_w1(self):
            from .windows.planner import PlannerWindow
            w = self._windows.get("planner")
            if w is None:
                w = self._windows["planner"] = PlannerWindow(self, client, state, ws)
            w.present()

        def show_w2(self):
            from .windows.timerlog import TimerLogWindow
            w = self._windows.get("timer")
            if w is None:
                w = self._windows["timer"] = TimerLogWindow(self, client, state)
            w.present()

    app = App()

    def on_frame(frame):
        kind = state.update_from_frame(frame)
        if kind == "proposal":
            p = frame.get("proposal") or {}
            w = app._windows.get("planner")
            if w is not None:
                w.show_proposal(p)
            else:
                from .notify import proposal_text
                t, b = proposal_text(p)
                notifier.send(t, b)
        elif kind == "question":
            q = frame.get("question")
            notifier.send("Briefing question",
                          q.get("text") if isinstance(q, dict) else str(q))
        elif kind == "timer":
            from .notify import milestone_text
            sess = frame.get("timer") or {}
            if sess.get("voided"):
                t, b = milestone_text("void", sess)
            elif sess.get("end_ms"):
                t, b = milestone_text("stop", sess)
            else:
                t, b = milestone_text("start", sess)
            notifier.send(t, b)

    ws = WsClient(args.url, client._key, on_frame=on_frame)
    ws.run_in_thread()
    start_polling(client, notifier)

    try:
        client.check_health()
        state.healthy, state.server_version = client.healthy, client.version
    except Exception:
        state.healthy = False
    return app.run([])
