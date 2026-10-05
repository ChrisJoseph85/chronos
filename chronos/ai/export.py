"""CSV export of events + timers (no cost columns)."""

from __future__ import annotations

import csv
import datetime
import io
import sqlite3


def _iso(ms):
    if ms is None:
        return ""
    dt = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)
    return dt.isoformat()


def _dump(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def export_events_csv(db):
    try:
        cur = db.execute(
            "SELECT id, title, start_ms, end_ms, kind FROM events ORDER BY start_ms"
        )
        data = cur.fetchall()
    except sqlite3.OperationalError:
        data = []
    except Exception:
        data = []
    rows = [(r[0], r[1], _iso(r[2]), _iso(r[3]), r[4]) for r in data]
    return _dump(["id", "title", "start", "end", "kind"], rows)


def export_timers_csv(db):
    try:
        cur = db.execute(
            "SELECT id, label, started_at, ended_at, mode FROM timer_sessions"
            " ORDER BY started_at"
        )
        data = cur.fetchall()
    except sqlite3.OperationalError:
        data = []
    except Exception:
        data = []
    rows = [(r[0], r[1], _iso(r[2]), _iso(r[3]), r[4]) for r in data]
    return _dump(["id", "label", "started_at", "ended_at", "mode"], rows)
