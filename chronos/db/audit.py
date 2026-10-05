"""Read-only audit viewer (spec 4.7)."""

from __future__ import annotations

import sqlite3
import time

RETENTION_MS = 7 * 86_400_000


WANT_COLS = ("id", "at", "device_id", "action", "target", "context")


def _cols(db):
    try:
        rows = db.execute("PRAGMA table_info(audit)").fetchall()
        names = [r[1] for r in rows]
        if names:
            return [c for c in WANT_COLS if c in names]
    except Exception:
        pass
    return list(WANT_COLS)


def _commit(db):
    commit = getattr(db, "commit", None)
    if callable(commit):
        try:
            commit()
        except Exception:
            pass


def _ensure_audit(db):
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY,"
            " at INTEGER, device_id TEXT, action TEXT NOT NULL,"
            " target TEXT, context TEXT)"
        )
    except sqlite3.OperationalError:
        pass


def log_action(db, action, target=None, context=None, at=None, device_id=None):
    _ensure_audit(db)
    if at is None:
        at = int(time.time() * 1000)
    cols = [c for c in ("at", "device_id", "action", "target", "context")
            if c in _cols(db)]
    vals = {"at": at, "device_id": device_id, "action": action,
            "target": target, "context": context}
    db.execute(
        "INSERT INTO audit (%s) VALUES (%s)" % (", ".join(cols),
                                               ", ".join("?" for _ in cols)),
        tuple(vals[c] for c in cols),
    )
    _commit(db)
    return action


def log_question(db, action_or_text, target=None, context=None):
    if target is None:
        return log_action(db, "question", target=action_or_text, context=context)
    return log_action(db, action_or_text, target=target, context=context)


def _rows_to_dicts(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def list_audit(
    db,
    action=None,
    target=None,
    since_ms=None,
    until_ms=None,
    limit=100,
    offset=0,
):
    try:
        max_row = db.execute("SELECT max(at) FROM audit").fetchone()
    except sqlite3.OperationalError:
        return []
    cutoff = None
    if max_row is not None and max_row[0] is not None:
        cutoff = max_row[0] - RETENTION_MS
    clauses = []
    params = []
    if cutoff is not None:
        clauses.append("at >= ?")
        params.append(cutoff)
    if action is not None:
        clauses.append("action = ?")
        params.append(action)
    if target is not None:
        clauses.append("target = ?")
        params.append(target)
    if since_ms is not None:
        clauses.append("at >= ?")
        params.append(since_ms)
    if until_ms is not None:
        clauses.append("at <= ?")
        params.append(until_ms)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cols = [c for c in WANT_COLS if c in _cols(db)]
    try:
        cur = db.execute(
            "SELECT %s FROM audit" % ", ".join(cols)
            + where
            + " ORDER BY id LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        )
        rows = _rows_to_dicts(cur)
        for r in rows:
            for c in WANT_COLS:
                r.setdefault(c, None)
        return rows
    except sqlite3.OperationalError:
        return []
