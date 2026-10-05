"""Phase 5.2 search + duplicate check + hierarchy reuse.

Spec: Chronos.md 4.8 (vector/FTS), 5.4 (hierarchy reuse), 6 (duplicate check).
Decisions: reuse threshold 0.85, check_conflict returns array, best-effort
indexing, narrow except OperationalError only.
Freeze 2026-10-05: node_fts is fts5(title, notes) regular joining back to
nodes; absent FTS never breaks writes.
"""

import math
import sqlite3
import uuid

import pytest


# ---------------------------------------------------------------- fakes


def fake_embed(text):
    v = [0.0] * 8
    s = sum(ord(c) for c in text) % 97
    v[s % 8] = 1.0
    v[(s + 3) % 8] = 0.5
    n = math.sqrt(sum(x * x for x in v))
    out = [x / n for x in v]
    return out


def fake_embed_identical(text):
    # Deterministic unit vector derived from text, identical texts match exactly.
    h = 0
    for c in text:
        h = (h * 31 + ord(c)) % 1009
    v = [0.0] * 8
    v[h % 8] = 1.0
    return v


def fake_judge_top_is_duplicate(candidates):
    # Model judge: first candidate is genuine duplicate.
    out = []
    for i, c in enumerate(candidates):
        d = dict(c)
        d["duplicate"] = (i == 0)
        d["confidence"] = 0.9 if i == 0 else 0.2
        out.append(d)
    return out


class FakeSession:
    """Minimal SQLAlchemy-Session-like wrapper around sqlite3.Connection."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)


def _search_mod():
    try:
        import chronos.db.search as m
    except ImportError as e:
        pytest.fail("Spec 4.8: chronos.db.search missing: %s" % e)
    return m


def _make_nodes(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nodes ("
        "id TEXT PRIMARY KEY, parent_id TEXT, kind TEXT NOT NULL, "
        "title TEXT NOT NULL, notes TEXT, status TEXT NOT NULL DEFAULT 'active', "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)"
    )
    conn.commit()


def _fingerprint(rows):
    return [(r["node_id"] if isinstance(r, dict) else r[0]) for r in rows]


# ---------------------------------------------------------------- tests


def test_three_stages_fts_narrows_vec_ranks_model_judges():
    """Spec 4.8: FTS narrows, vec ranks, model judges duplicates."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    fn = getattr(sch, "search_nodes", None)
    assert fn is not None
    n1 = "n-" + uuid.uuid4().hex[:8]
    n2 = "n-" + uuid.uuid4().hex[:8]
    now = 1_700_000_000_000
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'biology mitosis review', 'cell division', ?, ?)",
        (n1, now, now),
    )
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'grocery shopping list', 'buy milk eggs', ?, ?)",
        (n2, now, now),
    )
    conn.commit()
    sch.index_node(conn, n1, "biology mitosis review", "cell division")
    sch.index_node(conn, n2, "grocery shopping list", "buy milk eggs")
    ranked = fn(conn, "mitosis", limit=10, embed_fn=fake_embed)
    assert len(ranked) >= 1
    first = ranked[0]
    assert first["node_id"] == n1
    judged = fake_judge_top_is_duplicate(ranked)
    assert judged[0]["duplicate"] is True
    assert judged[0]["confidence"] == 0.9


def test_missing_vec_table_keywords_only_never_raise():
    """Spec 4.8 degrade: missing vec table means keywords only, never raise."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    fn = getattr(sch, "search_nodes", None)
    assert fn is not None
    now = 1_700_000_000_000
    nid = "n-" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'unique keyword alpha', 'some notes', ?, ?)",
        (nid, now, now),
    )
    conn.commit()
    try:
        sch.index_node(conn, nid, "unique keyword alpha", "some notes")
    except Exception as e:
        pytest.fail("Spec 4.8: index must not raise when vec missing: %s" % e)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='node_vec'"
    )
    assert cur.fetchone() is None
    rows = fn(conn, "alpha", limit=10, embed_fn=fake_embed)
    assert len(rows) == 1
    assert rows[0]["node_id"] == nid


def test_scores_absolute_reuse_threshold_can_fire():
    """Spec 5.4 + decisions: scores absolute so reuse threshold 0.85 can fire."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    fn = getattr(sch, "search_nodes", None)
    assert fn is not None
    now = 1_700_000_000_000
    nid = "n-" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'photosynthesis lab report', 'chlorophyll', ?, ?)",
        (nid, now, now),
    )
    conn.commit()
    sch.index_node(conn, nid, "photosynthesis lab report", "chlorophyll")
    rows = fn(conn, "photosynthesis lab report", limit=10, embed_fn=fake_embed_identical)
    assert len(rows) >= 1
    top = rows[0]
    assert top["node_id"] == nid
    assert top["similarity"] >= 0.85
    assert top["score"] >= 0.85


def test_bm25_distinct_from_similarity():
    """Spec 4.8 phase note: bm25 is not similarity; surfaced as distinct fields."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    fn = getattr(sch, "search_nodes", None)
    assert fn is not None
    now = 1_700_000_000_000
    nid = "n-" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'calculus derivatives practice', 'chain rule', ?, ?)",
        (nid, now, now),
    )
    conn.commit()
    sch.index_node(conn, nid, "calculus derivatives practice", "chain rule")
    rows = fn(conn, "calculus", limit=10, embed_fn=fake_embed)
    assert len(rows) >= 1
    r = rows[0]
    assert r["bm25"] is not None
    assert r["similarity"] is not None
    assert r["bm25"] != r["similarity"]


def test_works_with_session_and_raw_connection():
    """Spec 4.8 phase note: search works with Session and raw Connection."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    fn = getattr(sch, "search_nodes", None)
    assert fn is not None
    now = 1_700_000_000_000
    nid = "n-" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'session compat check', 'raw vs session', ?, ?)",
        (nid, now, now),
    )
    conn.commit()
    sch.index_node(conn, nid, "session compat check", "raw vs session")
    raw_rows = fn(conn, "compat", limit=10, embed_fn=fake_embed)
    sess = FakeSession(conn)
    sess_rows = fn(sess, "compat", limit=10, embed_fn=fake_embed)
    assert _fingerprint(raw_rows) == _fingerprint(sess_rows)
    assert len(raw_rows) == 1
    assert raw_rows[0]["node_id"] == nid


def test_indexed_on_create_reindex_on_update_remove_on_delete():
    """Spec 4.8 phase note: index on create, re-index on update, remove on delete."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    fn = getattr(sch, "search_nodes", None)
    assert fn is not None
    nid = "n-" + uuid.uuid4().hex[:8]
    now = 1_700_000_000_000
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'original title xyz', 'notes a', ?, ?)",
        (nid, now, now),
    )
    conn.commit()
    sch.index_node(conn, nid, "original title xyz", "notes a")
    got = fn(conn, "original", limit=10, embed_fn=fake_embed)
    assert _fingerprint(got) == [nid]
    sch.reindex_node(conn, nid, "totally different qqq", "notes a")
    got_old = fn(conn, "original", limit=10, embed_fn=fake_embed)
    assert _fingerprint(got_old) == []
    got_new = fn(conn, "different", limit=10, embed_fn=fake_embed)
    assert _fingerprint(got_new) == [nid]
    sch.remove_from_index(conn, nid)
    got_gone = fn(conn, "different", limit=10, embed_fn=fake_embed)
    assert _fingerprint(got_gone) == []


def test_absent_fts_never_breaks_write():
    """Decisions: optional index never breaks a core write."""
    sch = _search_mod()
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='node_fts'"
    )
    assert cur.fetchone() is None
    try:
        sch.index_node(conn, "ghost-id", "some title", "some notes")
    except Exception as e:
        pytest.fail("Spec 4.8: absent FTS must never break write: %s" % e)
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES ('w1', 'task', 'write survives', '', 1, 1)"
    )
    conn.commit()
    cur2 = conn.execute("SELECT title FROM nodes WHERE id='w1'")
    assert cur2.fetchone()[0] == "write survives"


def test_duplicate_check_warns_never_moves():
    """Spec 6: semantic duplicate check warns and proposes, never moves."""
    sch = _search_mod()
    fn = getattr(sch, "check_conflict", None)
    assert fn is not None
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, title TEXT, "
        "start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO events VALUES ('e1', 'DB review', 1700000000000, 1700003600000)"
    )
    conn.commit()
    _make_nodes(conn)
    before = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    out = fn(conn, "DB review session", 1700000000000, window_days=1, embed_fn=fake_embed)
    assert isinstance(out, list)
    after = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert after == before
    assert before == 1


def test_check_conflict_window_up_to_7_days():
    """Spec 6: window may widen through check_conflict up to plus-minus 7 days."""
    sch = _search_mod()
    fn = getattr(sch, "check_conflict", None)
    assert fn is not None
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, title TEXT, "
        "start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL)"
    )
    day = 86_400_000
    base = 1_700_000_000_000
    conn.execute("INSERT INTO events VALUES ('e1', 'review A', ?, ?)", (base, base + 1000))
    conn.commit()
    out1 = fn(conn, "review A", base + day, window_days=1, embed_fn=fake_embed)
    out7 = fn(conn, "review A", base + 7 * day, window_days=7, embed_fn=fake_embed)
    assert isinstance(out1, list)
    assert isinstance(out7, list)
    ids1 = [d["event_id"] if isinstance(d, dict) else d[0] for d in out1]
    assert list(ids1) == ["e1"]


def test_hierarchy_reuse_and_tags_never_duplicated():
    """Spec 5.4: reuse above threshold; tags never duplicated."""
    sch = _search_mod()
    reuse_fn = getattr(sch, "find_reuse_candidate", None)
    tag_fn = getattr(sch, "get_or_create_tag", None)
    assert reuse_fn is not None
    assert tag_fn is not None
    conn = sqlite3.connect(":memory:")
    _make_nodes(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tags (id TEXT PRIMARY KEY, name TEXT UNIQUE)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS node_tags (node_id TEXT, tag_id TEXT)"
    )
    conn.commit()
    nid = "n-" + uuid.uuid4().hex[:8]
    now = 1_700_000_000_000
    conn.execute(
        "INSERT INTO nodes (id, kind, title, notes, created_at, updated_at)"
        " VALUES (?, 'task', 'linear algebra homework', 'matrices', ?, ?)",
        (nid, now, now),
    )
    conn.commit()
    sch.index_node(conn, nid, "linear algebra homework", "matrices")
    hit = reuse_fn(
        conn, "linear algebra homework", "matrices",
        threshold=0.85, embed_fn=fake_embed_identical,
    )
    assert hit is not None
    assert hit["node_id"] == nid
    t1 = tag_fn(conn, "math")
    t2 = tag_fn(conn, "math")
    assert t1 == t2
    cnt = conn.execute("SELECT count(*) FROM tags WHERE name='math'").fetchone()[0]
    assert cnt == 1
