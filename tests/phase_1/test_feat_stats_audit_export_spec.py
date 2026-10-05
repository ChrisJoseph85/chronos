"""Phase 5.4/5.5/5.6 stats, audit viewer, CSV export.

Spec: Chronos.md 4.7 (timer/audit), API GET /api/stats counts+streaks.
Decisions: audit limit/offset default 100, question action=question,
CSV ISO-8601.
Freeze 2026-10-05: NO token-cost anywhere: no token_cost/provider_prices
tables, no cost_usd in stats, export events+timers only.
"""

import csv
import datetime
import io
import sqlite3

import pytest


_SENT = object()


def _stats_mod():
    try:
        import chronos.ai.stats as m
    except ImportError as e:
        pytest.fail("Spec stats: chronos.ai.stats missing: %s" % e)
    return m


def _audit_mod():
    try:
        import chronos.db.audit as m
    except ImportError as e:
        pytest.fail("Spec 4.7: chronos.db.audit missing: %s" % e)
    return m


def _export_mod():
    try:
        import chronos.ai.export as m
    except ImportError as e:
        pytest.fail("Spec export: chronos.ai.export missing: %s" % e)
    return m


def _seed_base(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, title TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, title TEXT, "
        "start_ms INTEGER, end_ms INTEGER, kind TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS timer_sessions (id TEXT PRIMARY KEY, "
        "label TEXT, started_at INTEGER, ended_at INTEGER, mode TEXT)"
    )
    conn.commit()


# ---------------------------------------------------------------- stats


def test_stats_counts():
    """API GET /api/stats: counts."""
    m = _stats_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    conn.execute("INSERT INTO nodes VALUES ('n1', 'a')")
    conn.execute("INSERT INTO nodes VALUES ('n2', 'b')")
    conn.execute(
        "INSERT INTO events VALUES ('e1', 'ev', 1000, 2000, 'focus')"
    )
    conn.commit()
    s = m.get_stats(conn)
    assert s["counts"]["nodes"] == 2
    assert s["counts"]["events"] == 1


def test_stats_streaks():
    """API GET /api/stats: streaks."""
    m = _stats_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    day = 86_400_000
    base = 1_700_000_000_000
    for i in range(3):
        conn.execute(
            "INSERT INTO timer_sessions VALUES (?, 'work', ?, ?, 'stopwatch')",
            ("t%d" % i, base + i * day, base + i * day + 1000),
        )
    conn.commit()
    s = m.get_stats(conn)
    assert s["streaks"]["days"] == 3


def test_stats_no_token_fields():
    """Freeze 2026-10-05: stats has counts+streaks, no token-cost."""
    m = _stats_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    conn.commit()
    s = m.get_stats(conn)
    assert s.get("cost_usd", _SENT) is _SENT
    assert s.get("token_cost", _SENT) is _SENT
    assert s.get("token_spend", _SENT) is _SENT
    counts = s["counts"]
    assert counts.get("cost_usd", _SENT) is _SENT


def test_no_token_cost_tables():
    """Freeze 2026-10-05: no token_cost/provider_prices tables."""
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert names.count("token_cost") == 0
    assert names.count("token_costs") == 0
    assert names.count("provider_prices") == 0


# ---------------------------------------------------------------- audit


def _seed_audit(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at INTEGER, "
        "device_id TEXT, action TEXT NOT NULL, target TEXT, context TEXT)"
    )
    now = 1_700_000_000_000
    day = 86_400_000
    conn.execute(
        "INSERT INTO audit (at, action, target) VALUES (?, 'create_event', 'e1')",
        (now,),
    )
    conn.execute(
        "INSERT INTO audit (at, action, target) VALUES (?, 'delete_event', 'e2')",
        (now,),
    )
    conn.execute(
        "INSERT INTO audit (at, action, target) VALUES (?, 'create_event', 'e3')",
        (now - 8 * day,),
    )
    conn.commit()
    return now


def test_audit_filter_by_action():
    """Spec 4.7: audit filterable by action."""
    m = _audit_mod()
    conn = sqlite3.connect(":memory:")
    _seed_audit(conn)
    rows = m.list_audit(conn, action="create_event")
    targets = sorted([r["target"] if isinstance(r, dict) else r[4] for r in rows])
    assert targets == ["e1"]


def test_audit_filter_by_target():
    """Spec 4.7: audit filterable by target."""
    m = _audit_mod()
    conn = sqlite3.connect(":memory:")
    _seed_audit(conn)
    rows = m.list_audit(conn, target="e2")
    assert len(rows) == 1
    r = rows[0]
    act = r["action"] if isinstance(r, dict) else r[3]
    assert act == "delete_event"


def test_audit_filter_by_time_range():
    """Spec 4.7: audit filterable by time range."""
    m = _audit_mod()
    conn = sqlite3.connect(":memory:")
    now = _seed_audit(conn)
    rows = m.list_audit(conn, since_ms=now - 1000, until_ms=now + 1000)
    assert len(rows) == 2


def test_audit_read_only():
    """Spec 4.7: audit viewer is read-only."""
    m = _audit_mod()
    assert getattr(m, "delete_audit", None) is None
    assert getattr(m, "update_audit", None) is None
    assert getattr(m, "clear_audit", None) is None
    conn = sqlite3.connect(":memory:")
    _seed_audit(conn)
    before = conn.execute("SELECT count(*) FROM audit").fetchone()[0]
    m.list_audit(conn, action="create_event")
    after = conn.execute("SELECT count(*) FROM audit").fetchone()[0]
    assert after == before


def test_audit_excludes_older_than_7_days():
    """Spec 4.7: retention 7 days, older rows excluded."""
    m = _audit_mod()
    conn = sqlite3.connect(":memory:")
    _seed_audit(conn)
    rows = m.list_audit(conn)
    targets = [r["target"] if isinstance(r, dict) else r[4] for r in rows]
    assert list(targets).count("e3") == 0
    assert len(rows) == 2


def test_audit_limit_offset_default_100():
    """Decisions phase5-7: audit pagination limit/offset default 100."""
    import inspect

    m = _audit_mod()
    sig = inspect.signature(m.list_audit)
    assert sig.parameters["limit"].default == 100
    assert sig.parameters["offset"].default == 0
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at INTEGER, "
        "action TEXT NOT NULL, target TEXT, context TEXT)"
    )
    now = 1_700_000_000_000
    for i in range(3):
        conn.execute(
            "INSERT INTO audit (at, action, target) VALUES (?, 'a', ?)",
            (now, "t%d" % i),
        )
    conn.commit()
    page = m.list_audit(conn, limit=2, offset=1)
    assert len(page) == 2


def test_question_stored_action_question():
    """Decisions phase5-3: question stored in audit with action=question."""
    m = _audit_mod()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at INTEGER, "
        "action TEXT NOT NULL, target TEXT, context TEXT)"
    )
    conn.commit()
    fn = getattr(m, "log_question", getattr(m, "log_action", None))
    assert fn is not None
    try:
        fn(conn, "question", "q1")
    except TypeError:
        fn(conn, action="question", target="q1")
    row = conn.execute(
        "SELECT action FROM audit WHERE target='q1'"
    ).fetchone()
    assert row[0] == "question"


# ---------------------------------------------------------------- export


def _parse(csv_text):
    return list(csv.reader(io.StringIO(csv_text)))


def test_csv_events_header_plus_one_row():
    """Spec export: events header row plus one row per record."""
    m = _export_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    conn.execute(
        "INSERT INTO events VALUES ('e1', 'review DB', 1700000000000, 1700003600000, 'review')"
    )
    conn.commit()
    text = m.export_events_csv(conn)
    rows = _parse(text)
    assert len(rows) == 2
    header = rows[0]
    assert header.count("title") == 1
    assert header.count("cost_usd") == 0
    assert header.count("cost") == 0


def test_csv_timers_header_plus_one_row():
    """Spec export: timers header row plus one row per record."""
    m = _export_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    conn.execute(
        "INSERT INTO timer_sessions VALUES ('s1', 'focus work', 1700000000000, 1700003600000, 'stopwatch')"
    )
    conn.commit()
    text = m.export_timers_csv(conn)
    rows = _parse(text)
    assert len(rows) == 2
    header = rows[0]
    assert header.count("label") == 1
    assert header.count("cost_usd") == 0


def test_csv_quoting_opens_cleanly():
    """Spec export: commas/quotes/newlines quoted so file opens cleanly."""
    m = _export_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    tricky = 'a, b "quoted"\nnewline'
    conn.execute(
        "INSERT INTO events VALUES ('e9', ?, 1700000000000, 1700003600000, 'focus')",
        (tricky,),
    )
    conn.commit()
    text = m.export_events_csv(conn)
    rows = _parse(text)
    assert len(rows) == 2
    header = rows[0]
    idx = header.index("title")
    assert rows[1][idx] == tricky


def test_csv_iso8601_timestamps():
    """Decisions phase5-8: CSV timestamps ISO-8601 with offset."""
    m = _export_mod()
    conn = sqlite3.connect(":memory:")
    _seed_base(conn)
    conn.execute(
        "INSERT INTO events VALUES ('e2', 't', 1700000000000, 1700003600000, 'focus')"
    )
    conn.commit()
    text = m.export_events_csv(conn)
    rows = _parse(text)
    header = rows[0]
    idx = header.index("start")
    val = rows[1][idx]
    parsed = datetime.datetime.fromisoformat(val)
    assert parsed.year == 2023
    assert parsed.tzinfo is not None
