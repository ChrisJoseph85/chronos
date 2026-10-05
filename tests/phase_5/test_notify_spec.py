"""Phase 5.1 notify + reminder scheduler.

Spec: Chronos.md section 4.6 (reminders), section 10 (notifications).
API: GET /api/reminders returns pending ordered by fire_at_ms.
Decisions 2026-10-03: offset sign positive means before start.
Freeze 2026-10-05: backend only, no web UI.
"""

import ast
import pathlib
import sqlite3
import uuid

import pytest


# ---------------------------------------------------------------- helpers


class FakeTransport:
    """Fake HTTP transport. Records posts. No network."""

    def __init__(self):
        self.posts = []

    def post(self, url, payload):
        self.posts.append((url, payload))

        class Resp:
            status_code = 200

        return Resp()


def _notify_mod():
    try:
        import chronos.notify as m
    except ImportError as e:
        pytest.fail("Spec 4.6/10: chronos.notify missing: %s" % e)
    return m


def _scheduler_mod():
    try:
        import chronos.notify.scheduler as m
    except ImportError:
        try:
            import chronos.notify as m2
            has = (
                hasattr(m2, "publish_due")
                and hasattr(m2, "create_reminder")
                and hasattr(m2, "cancel_reminder")
            )
            assert has is True
            return m2
        except Exception as e:
            pytest.fail("Spec 4.6: reminder scheduler missing: %s" % e)
    return m


def _make_tables(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reminders ("
        "id TEXT PRIMARY KEY, event_id TEXT NOT NULL, "
        "fire_at_ms INTEGER NOT NULL, offset_min INTEGER NOT NULL, "
        "state TEXT NOT NULL DEFAULT 'pending', "
        "channel TEXT NOT NULL DEFAULT 'ntfy', "
        "created_at INTEGER NOT NULL)"
    )
    conn.commit()


def _seed_event(conn, start_ms, end_ms, title="study"):
    eid = "ev-" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO events (id, title, start_ms, end_ms) VALUES (?, ?, ?, ?)",
        (eid, title, start_ms, end_ms),
    )
    conn.commit()
    return eid


# ---------------------------------------------------------------- tests


def test_notifier_one_post_per_publish():
    """Spec 10: ntfy publish is one HTTP POST per publish call."""
    mod = _notify_mod()
    cls = getattr(mod, "NtfyNotifier", None)
    assert cls is not None
    fake = FakeTransport()
    try:
        n = cls("http://example.invalid", fake)
    except TypeError:
        try:
            n = cls(base_url="http://example.invalid", transport=fake)
        except Exception as e:
            pytest.fail("Spec 10: NtfyNotifier must accept injected transport: %s" % e)
    assert len(fake.posts) == 0
    n.publish("topic1", "t1", "b1")
    assert len(fake.posts) == 1
    n.publish("topic1", "t2", "b2")
    assert len(fake.posts) == 2


def test_notifier_interface_publish_shape():
    """Spec 10: Notifier interface exposes publish behind which Gotify can slot."""
    mod = _notify_mod()
    proto = getattr(mod, "Notifier", None)
    assert proto is not None
    names = [a for a in dir(proto) if a == "publish"]
    assert names == ["publish"]


def test_default_offsets_value():
    """Spec 4.6: default offsets are 10 minutes before and at start."""
    mod = _notify_mod()
    val = getattr(mod, "DEFAULT_REMINDER_OFFSETS_MIN", None)
    assert val is not None
    assert list(val) == [10, 0]
    assert len(list(val)) == 2


def test_default_offsets_single_definition():
    """Spec 4.6: DEFAULT_REMINDER_OFFSETS_MIN has exactly one definition."""
    root = pathlib.Path(__file__).resolve().parents[2] / "chronos"
    count = 0
    nodes_seen = []
    for p in root.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        if t.id == "DEFAULT_REMINDER_OFFSETS_MIN":
                            count += 1
                            nodes_seen.append(str(p))
            if isinstance(node, ast.AnnAssign):
                t = node.target
                if isinstance(t, ast.Name):
                    if t.id == "DEFAULT_REMINDER_OFFSETS_MIN":
                        count += 1
                        nodes_seen.append(str(p))
    assert count == 1


def test_reminder_row_cancellable_individually():
    """Spec 4.6: reminder row is a real row, cancellable individually."""
    sch = _scheduler_mod()
    conn = sqlite3.connect(":memory:")
    _make_tables(conn)
    eid = _seed_event(conn, 1_700_000_000_000, 1_700_000_060_000)
    r1 = sch.create_reminder(conn, eid, 1_699_999_400_000, 10)
    r2 = sch.create_reminder(conn, eid, 1_700_000_000_000, 0)
    assert r1 != r2
    sch.cancel_reminder(conn, r1)
    cur = conn.execute("SELECT id, state FROM reminders ORDER BY fire_at_ms")
    rows = cur.fetchall()
    assert len(rows) == 2
    by_id = {r[0]: r[1] for r in rows}
    assert by_id[r1] == "cancelled"
    assert by_id[r2] == "pending"


def test_scheduler_publishes_due_on_tick():
    """Spec 4.6: scheduler runs on realtime tick and publishes anything due."""
    mod = _notify_mod()
    sch = _scheduler_mod()
    cls = getattr(mod, "NtfyNotifier", None)
    assert cls is not None
    conn = sqlite3.connect(":memory:")
    _make_tables(conn)
    now = 1_700_000_000_000
    eid_due = _seed_event(conn, now + 600_000, now + 3_600_000, title="due-ev")
    eid_future = _seed_event(conn, now + 100_000_000, now + 103_600_000, title="future-ev")
    sch.create_reminder(conn, eid_due, now - 1_000, 10)
    sch.create_reminder(conn, eid_future, now + 90_000_000, 10)
    fake = FakeTransport()
    try:
        n = cls("http://example.invalid", fake)
    except TypeError:
        n = cls(base_url="http://example.invalid", transport=fake)
    fired = sch.publish_due(conn, n, now)
    assert fired == 1
    assert len(fake.posts) == 1


def test_scheduler_cancelled_never_fires():
    """Spec 4.6: cancelled reminders never fire."""
    mod = _notify_mod()
    sch = _scheduler_mod()
    cls = getattr(mod, "NtfyNotifier", None)
    assert cls is not None
    conn = sqlite3.connect(":memory:")
    _make_tables(conn)
    now = 1_700_000_000_000
    eid = _seed_event(conn, now + 600_000, now + 3_600_000, title="cancel-ev")
    rid = sch.create_reminder(conn, eid, now - 5_000, 10)
    sch.cancel_reminder(conn, rid)
    fake = FakeTransport()
    try:
        n = cls("http://example.invalid", fake)
    except TypeError:
        n = cls(base_url="http://example.invalid", transport=fake)
    fired = sch.publish_due(conn, n, now)
    assert fired == 0
    assert len(fake.posts) == 0


def test_reminders_pending_ordered_by_fire_time():
    """API GET /api/reminders: pending reminders ordered by fire_at_ms."""
    sch = _scheduler_mod()
    list_fn = getattr(sch, "list_pending", None)
    assert list_fn is not None
    conn = sqlite3.connect(":memory:")
    _make_tables(conn)
    eid = _seed_event(conn, 1_700_000_000_000, 1_700_000_060_000)
    sch.create_reminder(conn, eid, 3000, 10)
    sch.create_reminder(conn, eid, 1000, 10)
    sch.create_reminder(conn, eid, 2000, 0)
    rows = list_fn(conn)
    got = [r["fire_at_ms"] if isinstance(r, dict) else r[2] for r in rows]
    assert list(got) == [1000, 2000, 3000]
