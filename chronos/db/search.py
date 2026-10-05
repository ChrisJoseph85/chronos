"""Keyword + semantic search over nodes (spec 4.8, 5.4, 6)."""

from __future__ import annotations

import math
import sqlite3
import uuid

from chronos.db.bootstrap import FTS_DDL as _CANONICAL_FTS_DDL

REUSE_THRESHOLD = 0.85

# Canonical FTS CREATE (Chronos.md §4.8; 2026-10-05 freeze): identical string
# everywhere — regular table joining back to nodes on node_id match.
FTS_DDL = _CANONICAL_FTS_DDL


def _commit(db):
    commit = getattr(db, "commit", None)
    if callable(commit):
        try:
            commit()
        except Exception:
            pass


def _ensure_fts(db):
    db.execute(_CANONICAL_FTS_DDL)


def index_node(db, node_id, title, notes=""):
    try:
        _ensure_fts(db)
        db.execute("DELETE FROM node_fts WHERE node_id=?", (node_id,))
        db.execute(
            "INSERT INTO node_fts (title, notes, node_id) VALUES (?, ?, ?)",
            (title or "", notes or "", node_id),
        )
        _commit(db)
    except sqlite3.OperationalError:
        pass


def reindex_node(db, node_id, title, notes=""):
    try:
        _ensure_fts(db)
        db.execute("DELETE FROM node_fts WHERE node_id=?", (node_id,))
        db.execute(
            "INSERT INTO node_fts (title, notes, node_id) VALUES (?, ?, ?)",
            (title or "", notes or "", node_id),
        )
        _commit(db)
    except sqlite3.OperationalError:
        pass


def remove_from_index(db, node_id):
    try:
        db.execute("DELETE FROM node_fts WHERE node_id=?", (node_id,))
        _commit(db)
    except sqlite3.OperationalError:
        pass


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _fts_candidates(db, query):
    cur = db.execute(
        "SELECT node_fts.node_id, node_fts.title, bm25(node_fts) AS rank FROM node_fts"
        " JOIN nodes ON nodes.id = node_fts.node_id"
        " WHERE node_fts MATCH ?",
        (query,),
    )
    out = []
    for row in cur.fetchall():
        out.append({"node_id": row[0], "title": row[1], "bm25": float(row[2])})
    return out


def _like_fallback(db, query):
    terms = [t for t in query.split() if t]
    if not terms:
        return []
    like = "%" + terms[0] + "%"
    cur = db.execute(
        "SELECT id, title FROM nodes WHERE title LIKE ? OR notes LIKE ?",
        (like, like),
    )
    return [{"node_id": r[0], "title": r[1], "bm25": -1.0} for r in cur.fetchall()]


def search_nodes(db, query, limit=10, embed_fn=None):
    try:
        candidates = _fts_candidates(db, query)
    except sqlite3.OperationalError:
        try:
            candidates = _like_fallback(db, query)
        except sqlite3.OperationalError:
            return []
    # Probe vec table; missing means keywords only. Never raise.
    try:
        db.execute("SELECT count(*) FROM node_vec").fetchone()
    except sqlite3.OperationalError:
        pass
    results = []
    qvec = None
    if embed_fn is not None:
        try:
            qvec = embed_fn(query)
        except Exception:
            qvec = None
    for cand in candidates:
        sim = 0.0
        if qvec is not None and embed_fn is not None:
            try:
                dvec = embed_fn(cand.get("title") or "")
                sim = float(_cosine(qvec, dvec))
            except Exception:
                sim = 0.0
        else:
            sim = 1.0
        results.append(
            {
                "node_id": cand["node_id"],
                "title": cand.get("title"),
                "bm25": cand["bm25"],
                "similarity": sim,
                "score": sim,
            }
        )
    if qvec is not None:
        results.sort(key=lambda r: r["similarity"], reverse=True)
    else:
        results.sort(key=lambda r: r["bm25"])
    return results[:limit]


def check_conflict(db, title, at_ms, window_days=1, embed_fn=None):
    window_days = max(1, min(int(window_days), 7))
    span = window_days * 86_400_000
    lo = at_ms - span
    hi = at_ms + span
    try:
        cur = db.execute(
            "SELECT id, title, start_ms, end_ms FROM events"
            " WHERE start_ms BETWEEN ? AND ? ORDER BY start_ms",
            (lo, hi),
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {"event_id": r[0], "title": r[1], "start_ms": r[2], "end_ms": r[3]}
        for r in rows
    ]


def find_reuse_candidate(db, title, notes="", threshold=0.85, embed_fn=None):
    query = (title or "") if not notes else ("%s %s" % (title, notes))
    try:
        rows = search_nodes(db, title or "", limit=5, embed_fn=embed_fn)
    except sqlite3.OperationalError:
        return None
    for r in rows:
        if r.get("similarity", 0.0) >= threshold:
            return r
    return None


def get_or_create_tag(db, name):
    try:
        cur = db.execute("SELECT id FROM tags WHERE name=?", (name,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        return None
    if row is not None:
        return row[0]
    tid = "tag-" + uuid.uuid4().hex[:8]
    try:
        db.execute("INSERT INTO tags (id, name) VALUES (?, ?)", (tid, name))
    except sqlite3.OperationalError:
        try:
            db.execute("INSERT INTO tags (id, name) VALUES (?, ?)", (tid, name))
        except Exception:
            return tid
    _commit(db)
    # Race: return the winner's id.
    try:
        cur = db.execute("SELECT id FROM tags WHERE name=?", (name,))
        row = cur.fetchone()
        if row is not None:
            return row[0]
    except sqlite3.OperationalError:
        pass
    return tid
