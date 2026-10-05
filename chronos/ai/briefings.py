"""Daily briefing + clarification budget (spec 9.1, 5.7)."""

from __future__ import annotations

import datetime
import time


def _commit(db):
    commit = getattr(db, "commit", None)
    if callable(commit):
        try:
            commit()
        except Exception:
            pass


def _ensure_tables(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS briefing_budget"
        " (day TEXT PRIMARY KEY, spent INTEGER)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY,"
        " at INTEGER, device_id TEXT, action TEXT NOT NULL,"
        " target TEXT, context TEXT)"
    )


def _shift(day, n):
    d = datetime.date.fromisoformat(day) + datetime.timedelta(days=n)
    return d.isoformat()


def request_question(db, day, text):
    _ensure_tables(db)
    db.execute(
        "INSERT INTO audit (at, action, target, context) VALUES (?, ?, ?, ?)",
        (int(time.time() * 1000), "question", day, text),
    )
    db.execute(
        "INSERT OR IGNORE INTO briefing_budget (day, spent) VALUES (?, 1)", (day,)
    )
    db.execute("UPDATE briefing_budget SET spent=1 WHERE day=?", (day,))
    _commit(db)
    return {"day": day, "text": text}


def _all_questions(db):
    try:
        cur = db.execute(
            "SELECT target, context FROM audit WHERE action='question' ORDER BY id"
        )
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def _question_for(db, day):
    pool = [(t, c) for (t, c) in _all_questions(db) if t is not None and t <= day]
    if not pool:
        return None
    pool.sort(key=lambda p: (p[0],))
    # Stable: keep insertion order within same target (already by id).
    start = pool[0][0]
    cursor = start
    idx = 0
    assigned = {}
    while cursor <= day and idx < len(pool):
        # earliest unconsumed question with target <= cursor
        while idx < len(pool) and pool[idx][0] > cursor:
            cursor = pool[idx][0]
            if cursor > day:
                break
        if cursor > day or idx >= len(pool):
            break
        if pool[idx][0] <= cursor:
            assigned[cursor] = pool[idx][1]
            idx += 1
        cursor = _shift(cursor, 1)
    if day in assigned:
        return {"text": assigned[day]}
    return None


def build_briefing(db, day):
    week_end = _shift(day, 6)
    try:
        nodes = db.execute(
            "SELECT id, title, bucket_day FROM nodes WHERE status='active'"
            " OR status IS NULL"
        ).fetchall()
    except Exception:
        nodes = []
    try:
        total = db.execute("SELECT count(*) FROM nodes").fetchone()[0]
    except Exception:
        total = len(nodes)
    unallocated = [
        {"id": r[0], "title": r[1]}
        for r in nodes
        if r[2] is not None and day <= r[2] <= week_end
    ]
    rollover = [
        {"id": r[0], "title": r[1]}
        for r in nodes
        if r[2] is not None and r[2] < day
    ]
    try:
        rev = db.execute(
            "SELECT id, title FROM events WHERE kind='review' AND day=?", (day,)
        ).fetchall()
    except Exception:
        rev = []
    due_reviews = [{"id": r[0], "title": r[1]} for r in rev]
    question = _question_for(db, day)
    return {
        "date": day,
        "unallocated_tasks": unallocated,
        "rollover": rollover,
        "due_reviews": due_reviews,
        "question": question,
        "checked": total,
        "showing": len(unallocated),
    }
