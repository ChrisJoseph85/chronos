"""ntfy notifications + reminder scheduler (spec 4.6, 10)."""

from __future__ import annotations

import time
import urllib.request
import uuid
from typing import Protocol

DEFAULT_REMINDER_OFFSETS_MIN = [10, 0]


class Notifier(Protocol):
    def publish(self, topic: str, title: str, body: str) -> None: ...


class _UrllibTransport:
    def post(self, url, payload):
        data = str(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = getattr(resp, "status", 200)

            class Resp:
                status_code = status

            return Resp()


class NtfyNotifier:
    def __init__(self, base_url=None, transport=None, **kwargs):
        if base_url is None:
            base_url = kwargs.get("url", "http://localhost:8080")
        self.base_url = base_url.rstrip("/")
        self._transport = transport if transport is not None else _UrllibTransport()

    def publish(self, topic: str, title: str, body: str) -> None:
        url = "%s/%s" % (self.base_url, topic)
        payload = {"title": title, "message": body}
        self._transport.post(url, payload)


def _commit(db):
    commit = getattr(db, "commit", None)
    if callable(commit):
        try:
            commit()
        except Exception:
            pass


def create_reminder(db, event_id, fire_at_ms, offset_min, channel="ntfy"):
    rid = "rem-" + uuid.uuid4().hex[:8]
    db.execute(
        "INSERT INTO reminders (id, event_id, fire_at_ms, offset_min, state,"
        " channel, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
        (rid, event_id, fire_at_ms, offset_min, channel, int(time.time() * 1000)),
    )
    _commit(db)
    return rid


def cancel_reminder(db, reminder_id):
    db.execute("UPDATE reminders SET state='cancelled' WHERE id=?", (reminder_id,))
    _commit(db)


def _rows_as_dicts(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def list_pending(db):
    cur = db.execute(
        "SELECT id, event_id, fire_at_ms, offset_min, state, channel, created_at"
        " FROM reminders WHERE state='pending' ORDER BY fire_at_ms"
    )
    try:
        return _rows_as_dicts(cur)
    except Exception:
        rows = cur.fetchall()
        keys = ("id", "event_id", "fire_at_ms", "offset_min", "state", "channel", "created_at")
        return [dict(zip(keys, r)) for r in rows]


def publish_due(db, notifier, now_ms):
    cur = db.execute(
        "SELECT r.id, r.event_id, r.fire_at_ms, e.title FROM reminders r"
        " LEFT JOIN events e ON e.id = r.event_id"
        " WHERE r.state='pending' AND r.fire_at_ms <= ? ORDER BY r.fire_at_ms",
        (now_ms,),
    )
    rows = cur.fetchall()
    fired = 0
    for rid, event_id, fire_at_ms, title in rows:
        notifier.publish("reminders", title or event_id, "reminder due")
        db.execute("UPDATE reminders SET state='sent' WHERE id=?", (rid,))
        fired += 1
    if fired:
        _commit(db)
    return fired
