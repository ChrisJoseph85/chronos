"""Native notifications via Gio.Notification (no polling faster than 30s)."""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

MIN_POLL_S = 30
APP_ID = "io.chronos.desktop"


def clamp_interval(seconds):
    """Enforce the >=30s polling floor."""
    return max(float(seconds), MIN_POLL_S)


def reminder_text(reminder):
    r = reminder or {}
    return ("Chronos reminder", r.get("text") or r.get("title") or "reminder due")


def milestone_text(kind, session=None):
    s = session or {}
    label = s.get("label") or s.get("node_id") or "timer"
    if kind == "start":
        return ("Timer started", label)
    if kind == "void":
        return ("Session voided", f"{label} discarded (distracted)")
    return ("Timer stopped", f"{label} logged")


def briefing_question_text(briefing):
    q = (briefing or {}).get("question")
    if not q:
        return None
    if isinstance(q, dict):
        return ("Briefing question", q.get("text", str(q)))
    return ("Briefing question", str(q))


def proposal_text(proposal):
    p = proposal or {}
    return ("Proposal awaiting review",
            p.get("message") or p.get("summary") or "say returned a proposal")


class Notifier:
    """Thin Gio.Notification wrapper; falls back to logging headless."""

    def __init__(self, app=None):
        self._app = app

    def send(self, title, body=""):
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            n = Gio.Notification.new(title)
            n.set_body(body or "")
            if self._app is not None:
                self._app.send_notification(f"chronos-{time.time_ns()}", n)
                return "gio"
        except Exception as e:
            log.debug("gio notify unavailable: %s", e)
        log.info("notify: %s — %s", title, body)
        return "log"


def poll_once(client, notifier, seen_ids):
    """One reminders poll; notifies only unseen ids. Returns updated set."""
    seen = set(seen_ids)
    try:
        reminders = client.reminders() or []
    except Exception as e:
        log.debug("reminders poll failed: %s", e)
        return seen
    for r in reminders:
        rid = r.get("id", r.get("fire_at_ms"))
        if rid in seen:
            continue
        seen.add(rid)
        title, body = reminder_text(r)
        notifier.send(title, body)
    return seen


def start_polling(client, notifier, interval_s=60, stop_event=None):
    """Background reminders poll; interval clamped to >=30s."""
    interval = clamp_interval(interval_s)
    stop = stop_event or threading.Event()

    def loop():
        seen = set()
        while not stop.wait(interval):
            seen = poll_once(client, notifier, seen)

    t = threading.Thread(target=loop, name="chronos-reminders", daemon=True)
    t.start()
    return t, stop, interval
