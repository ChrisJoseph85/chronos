"""Counts + streaks stats (no token-cost fields)."""

from __future__ import annotations

import datetime
import sqlite3


def _count(db, table):
    try:
        return db.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    except Exception:
        return 0


def _streak_days(db):
    try:
        rows = db.execute(
            "SELECT started_at FROM timer_sessions WHERE started_at IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    except Exception:
        return 0
    days = sorted(
        {
            datetime.datetime.fromtimestamp(
                r[0] / 1000, tz=datetime.timezone.utc
            ).date()
            for r in rows
            if r[0] is not None
        }
    )
    if not days:
        return 0
    streak = 1
    for i in range(len(days) - 1, 0, -1):
        if (days[i] - days[i - 1]).days == 1:
            streak += 1
        else:
            break
    return streak


def get_stats(db):
    return {
        "counts": {
            "nodes": _count(db, "nodes"),
            "events": _count(db, "events"),
            "timers": _count(db, "timer_sessions"),
        },
        "streaks": {"days": _streak_days(db)},
    }
