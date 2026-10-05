"""Phase 5.3 briefings + clarification budget.

Spec: Chronos.md 5.7 (clarification budget), 9.1 (briefing), 5.6 (packer
checked/showing), 4.4 (series due reviews).
API: GET /api/briefing?date=YYYY-MM-DD returns date, unallocated_tasks,
rollover, due_reviews, question.
Decisions: briefing query-based, Briefing dataclass internally dict at
boundary, budget persists across restart, question stored action=question.
"""

import sqlite3

import pytest


def _mod():
    try:
        import chronos.ai.briefings as m
    except ImportError as e:
        pytest.fail("Spec 9.1: chronos.ai.briefings missing: %s" % e)
    return m


def _make_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, kind TEXT, "
        "title TEXT NOT NULL, status TEXT DEFAULT 'active', bucket_day TEXT, "
        "due_day TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, title TEXT, "
        "kind TEXT DEFAULT 'review', day TEXT, series_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at INTEGER, "
        "action TEXT NOT NULL, target TEXT, context TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS briefing_budget (day TEXT PRIMARY KEY, spent INTEGER)"
    )
    conn.commit()


def _seed(conn):
    _make_schema(conn)
    conn.execute(
        "INSERT INTO nodes VALUES ('t-today', 'task', 'today task alpha', "
        "'active', '2026-10-06', NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('t-week', 'task', 'week task beta', "
        "'active', '2026-10-08', NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('t-over', 'task', 'overdue gamma', "
        "'active', '2026-10-04', NULL)"
    )
    conn.execute(
        "INSERT INTO events VALUES ('e-rev', 'review mitosis', 'review', "
        "'2026-10-06', 's1')"
    )
    conn.commit()


def _build(conn, day):
    m = _mod()
    fn = getattr(m, "build_briefing", None)
    assert fn is not None
    return fn(conn, day)


def test_content_unallocated_today():
    """Spec 9.1: briefing holds unallocated tasks for today."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    b = _build(conn, "2026-10-06")
    assert b["date"] == "2026-10-06"
    titles = [t["title"] if isinstance(t, dict) else t[0] for t in b["unallocated_tasks"]]
    assert list(titles).count("today task alpha") == 1


def test_content_unallocated_week():
    """Spec 9.1: briefing holds unallocated tasks for this week."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    b = _build(conn, "2026-10-06")
    titles = [t["title"] if isinstance(t, dict) else t[0] for t in b["unallocated_tasks"]]
    assert list(titles).count("week task beta") == 1


def test_content_rollover():
    """Spec 9.1: briefing holds rollover."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    b = _build(conn, "2026-10-06")
    titles = [t["title"] if isinstance(t, dict) else t[0] for t in b["rollover"]]
    assert list(titles).count("overdue gamma") == 1


def test_content_due_reviews():
    """Spec 4.4/9.1: briefing holds due reviews."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    b = _build(conn, "2026-10-06")
    titles = [t["title"] if isinstance(t, dict) else t[0] for t in b["due_reviews"]]
    assert list(titles).count("review mitosis") == 1


def test_at_most_one_question():
    """Spec 5.7: at most one question per briefing."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    m = _mod()
    rq = getattr(m, "request_question", None)
    assert rq is not None
    rq(conn, "2026-10-06", "first question?")
    rq(conn, "2026-10-06", "second question?")
    b = _build(conn, "2026-10-06")
    q = b.get("question", None)
    if q is None:
        counted = 0
    elif isinstance(q, list):
        counted = len(q)
    else:
        counted = 1
    assert counted <= 1
    assert counted == 1


def test_generated_not_templated():
    """Spec 9.1 phase note: briefing generated, varies with data."""
    c1 = sqlite3.connect(":memory:")
    _make_schema(c1)
    c1.execute(
        "INSERT INTO nodes VALUES ('a1', 'task', 'alpha dataset task', "
        "'active', '2026-10-06', NULL)"
    )
    c1.commit()
    c2 = sqlite3.connect(":memory:")
    _make_schema(c2)
    c2.execute(
        "INSERT INTO nodes VALUES ('b1', 'task', 'beta dataset task', "
        "'active', '2026-10-06', NULL)"
    )
    c2.commit()
    b1 = _build(c1, "2026-10-06")
    b2 = _build(c2, "2026-10-06")
    assert b1 != b2
    t1 = [t["title"] if isinstance(t, dict) else t[0] for t in b1["unallocated_tasks"]]
    t2 = [t["title"] if isinstance(t, dict) else t[0] for t in b2["unallocated_tasks"]]
    assert list(t1) == ["alpha dataset task"]
    assert list(t2) == ["beta dataset task"]


def test_budget_one_per_day_queued_not_blocking():
    """Spec 5.7: one question per day, queued not blocking."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    m = _mod()
    rq = getattr(m, "request_question", None)
    assert rq is not None
    first = rq(conn, "2026-10-06", "q1?")
    second = rq(conn, "2026-10-06", "q2?")
    assert first is not None
    assert second is not None
    b = _build(conn, "2026-10-06")
    assert b["question"] is not None
    b2 = _build(conn, "2026-10-07")
    assert b2["question"] is not None


def test_budget_rolls_to_tomorrow():
    """Spec 5.7: spent budget rolls questions into tomorrow briefing."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    m = _mod()
    rq = getattr(m, "request_question", None)
    assert rq is not None
    rq(conn, "2026-10-06", "first?")
    rq(conn, "2026-10-06", "rolled?")
    b_next = _build(conn, "2026-10-07")
    q = b_next["question"]
    text = q["text"] if isinstance(q, dict) else q
    assert text == "rolled?"


def test_budget_persists_across_restart(tmp_path):
    """Spec 5.7 phase note: budget survives process restart via same DB."""
    m = _mod()
    rq = getattr(m, "request_question", None)
    assert rq is not None
    db = str(tmp_path / "b.db")
    c1 = sqlite3.connect(db)
    _seed(c1)
    rq(c1, "2026-10-06", "persist me?")
    c1.commit()
    c1.close()
    c2 = sqlite3.connect(db)
    b = _build(c2, "2026-10-06")
    assert b["question"] is not None
    c2.close()
    c3 = sqlite3.connect(db)
    b_again = _build(c3, "2026-10-06")
    assert b_again["question"] is not None
    c3.close()


def test_reports_checked_showing():
    """Spec 5.6: briefing reports what it considered, checked and showing."""
    conn = sqlite3.connect(":memory:")
    _seed(conn)
    b = _build(conn, "2026-10-06")
    assert b["checked"] == 3
    assert b["showing"] == 2
    assert b["showing"] <= b["checked"]
