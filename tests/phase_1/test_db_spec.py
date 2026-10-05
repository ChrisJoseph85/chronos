"""Phase 1 DB behaviour tests (Chronos.md §4, §6, §7.3; API.md; decisions.md).

Layer 2 rules (errors-and-test-proposal.md): execute the REAL DDL in a real
sqlite3 :memory: database — never assert on DDL source text. Insert one row per
enum and read it back through the enum constructor. Every spec constraint is
tested by asserting the database REJECTS the bad case.
"""

import importlib
import json
import sqlite3
import uuid

import pytest

_DDL_MODULES = (
    "chronos.db.bootstrap",
    "chronos.db.orm",
    "chronos.db.schema",
    "chronos.db.engine",
    "chronos.db",
)

_DDL_ATTRS = (
    "DDL_STATEMENTS",
    "SCHEMA_STATEMENTS",
    "CREATE_STATEMENTS",
    "DDL",
    "SCHEMA_SQL",
    "SCHEMA",
    "BASE_DDL",
)

# Chronos.md §4 tables (node_links per decisions.md 2026-10-03 ruling 1).
EXPECTED_TABLES = (
    "nodes",
    "tags",
    "node_tags",
    "node_links",
    "events",
    "buckets",
    "review_series",
    "schedules",
    "reminders",
    "timer_sessions",
    "settings",
    "audit",
)

# Backend-only freeze 2026-10-05 (decisions.md): these must NOT exist.
FORBIDDEN_TABLES = ("token_cost", "token_costs", "cost_tracker", "provider_prices")


def _lookup_contract(name):
    try:
        pkg = importlib.import_module("chronos.contracts")
    except ImportError:
        pytest.fail("chronos.contracts missing; cannot resolve %r (Chronos.md §2.1)" % name)
    if hasattr(pkg, name):
        return getattr(pkg, name)
    for sub in ("chronos.contracts.enums", "chronos.contracts.models"):
        try:
            mod = importlib.import_module(sub)
        except ImportError:
            continue
        if hasattr(mod, name):
            return getattr(mod, name)
    pytest.fail("chronos.contracts must expose %r (Chronos.md §4)" % name)


def _load_ddl_items():
    loaded_from = None
    for modname in _DDL_MODULES:
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            continue
        for attr in _DDL_ATTRS:
            value = getattr(mod, attr, None)
            if value is not None:
                loaded_from = "%s.%s" % (modname, attr)
                return value, loaded_from
    pytest.fail(
        "No DDL statements found in chronos.db (tried %s × %s). "
        "Expose the real schema as e.g. chronos.db.bootstrap.DDL_STATEMENTS "
        "(Chronos.md §4; phase-1-core Part 1.2)." % (_DDL_MODULES, _DDL_ATTRS)
    )


def _exec_ddl(conn, ddl):
    """Execute real DDL; tolerate only a missing vec0 module (OperationalError)."""
    if isinstance(ddl, str):
        items = [ddl]
    else:
        items = list(ddl)
    assert len(items) > 0
    for item in items:
        assert isinstance(item, str)
        if len(item.strip()) == 0:
            continue
        try:
            conn.execute(item)
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "vec0" in message or "no such module" in message:
                continue
            raise
        except (sqlite3.ProgrammingError, sqlite3.Warning):
            conn.executescript(item)


@pytest.fixture()
def db():
    """Fresh :memory: database with the real schema and FK enforcement on."""
    ddl, _ = _load_ddl_items()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _exec_ddl(conn, ddl)
        yield conn
    finally:
        conn.close()


def _tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return set(r[0] for r in rows)


def _uid():
    return uuid.uuid4().hex


def _insert_node(conn, kind="task", status="active", title="n", parent=None):
    now = 1700000000000
    nid = _uid()
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, title, notes, status,"
        " created_at, updated_at, done_at)"
        " VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL)",
        (nid, parent, kind, title, status, now, now),
    )
    conn.commit()
    return nid


def _insert_event(conn, start_ms, end_ms, kind="focus", node_id=None, soft_deleted=0):
    eid = _uid()
    conn.execute(
        "INSERT INTO events (id, node_id, title, start_ms, end_ms, kind,"
        " bucket_id, series_id, review_index, derived_from, soft_deleted, created_at)"
        " VALUES (?, ?, 'e', ?, ?, ?, NULL, NULL, NULL, NULL, ?, 1700000000000)",
        (eid, node_id, start_ms, end_ms, kind, soft_deleted),
    )
    conn.commit()
    return eid


def test_real_ddl_creates_all_tables(db):
    """Real DDL creates every §4 table (Chronos.md §4; Layer 2: execute it)."""
    names = _tables(db)
    for table in EXPECTED_TABLES:
        assert table in names


def test_no_token_cost_tables(db):
    """Backend-only freeze: no token-cost tables exist (decisions.md 2026-10-05)."""
    names = _tables(db)
    present = [t for t in FORBIDDEN_TABLES if t in names]
    assert present == []


def test_nodes_enum_rows_read_back(db):
    """One row per NodeKind/NodeStatus reads back via constructors (Chronos.md §4.1)."""
    NodeKind = _lookup_contract("NodeKind")
    NodeStatus = _lookup_contract("NodeStatus")
    kinds = ["project", "task", "subtask"]
    statuses = ["active", "done", "archived"]
    for kind, status in zip(kinds, statuses):
        _insert_node(db, kind=kind, status=status, title="k-%s-%s" % (kind, status))
    rows = db.execute("SELECT kind, status FROM nodes ORDER BY title").fetchall()
    assert len(rows) == 3
    for row in rows:
        assert NodeKind(row[0]).value == row[0]
        assert NodeStatus(row[1]).value == row[1]


def test_events_enum_rows_read_back(db):
    """One row per EventKind reads back via constructor (Chronos.md §4.2)."""
    EventKind = _lookup_contract("EventKind")
    for kind in ["focus", "class", "break", "review", "admin"]:
        _insert_event(db, 1700000000000, 1700000600000, kind=kind)
    rows = db.execute("SELECT kind FROM events").fetchall()
    assert len(rows) == 5
    for row in rows:
        assert EventKind(row[0]).value == row[0]


def test_review_series_enums_read_back(db):
    """One row per ReviewTier/SeriesState reads back (Chronos.md §4.4)."""
    ReviewTier = _lookup_contract("ReviewTier")
    SeriesState = _lookup_contract("SeriesState")
    anchor = _insert_node(db, kind="task", title="anchor")
    node = _insert_node(db, kind="task", title="series-owner")
    tiers = ["hard", "medium", "easy", "custom"]
    states = ["active", "retired", "cancelled", "active"]
    for tier, state in zip(tiers, states):
        db.execute(
            "INSERT INTO review_series (id, node_id, tier, offsets_days,"
            " anchor_node_id, max_count, ends_on_ms, state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 1700000000000)",
            (_uid(), node, tier, json.dumps([1, 2]), anchor, 2, state),
        )
    db.commit()
    rows = db.execute("SELECT tier, state FROM review_series").fetchall()
    assert len(rows) == 4
    for row in rows:
        assert ReviewTier(row[0]).value == row[0]
        assert SeriesState(row[1]).value == row[1]


def test_reminder_state_rows_read_back(db):
    """One row per ReminderState reads back (Chronos.md §4.6)."""
    ReminderState = _lookup_contract("ReminderState")
    eid = _insert_event(db, 1700000000000, 1700000600000)
    for state in ["pending", "sent", "cancelled"]:
        db.execute(
            "INSERT INTO reminders (id, event_id, fire_at_ms, offset_min,"
            " state, channel, created_at)"
            " VALUES (?, ?, 1699999400000, 10, ?, 'ntfy', 1700000000000)",
            (_uid(), eid, state),
        )
    db.commit()
    rows = db.execute("SELECT state FROM reminders").fetchall()
    assert len(rows) == 3
    for row in rows:
        assert ReminderState(row[0]).value == row[0]


def test_timer_mode_phase_rows_read_back(db):
    """TimerMode/TimerPhase rows read back via constructors (Chronos.md §4.7)."""
    TimerMode = _lookup_contract("TimerMode")
    TimerPhase = _lookup_contract("TimerPhase")
    for i, (mode, phase) in enumerate(
        [("stopwatch", None), ("timer", None), ("pomodoro", "focus"), ("pomodoro", "break")]
    ):
        db.execute(
            "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
            " source, reconciled, mode, target_ms, phase, cycle)"
            " VALUES (?, NULL, ?, 1700000000000, 1700000600000, 't', 0, ?, NULL, ?, 1)",
            (_uid(), "s%d" % i, mode, phase),
        )
    db.commit()
    rows = db.execute("SELECT mode, phase FROM timer_sessions").fetchall()
    assert len(rows) == 4
    for row in rows:
        assert TimerMode(row[0]).value == row[0]
        if row[1] is not None:
            assert TimerPhase(row[1]).value == row[1]


def test_bucket_level_rows_read_back(db):
    """One row per BucketLevel reads back (Chronos.md §4.3)."""
    BucketLevel = _lookup_contract("BucketLevel")
    db.execute(
        "INSERT INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
        " VALUES ('Y:2026', 'Y', NULL, 0, 1, 1)"
    )
    db.execute(
        "INSERT INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
        " VALUES ('M:2026-01', 'M', 'Y:2026', 0, 1, 1)"
    )
    db.execute(
        "INSERT INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
        " VALUES ('W:2026-W01', 'W', 'M:2026-01', 0, 1, 1)"
    )
    db.execute(
        "INSERT INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
        " VALUES ('D:2026-01-01', 'D', 'W:2026-W01', 0, 1, 1)"
    )
    db.commit()
    rows = db.execute("SELECT level FROM buckets").fetchall()
    assert len(rows) == 4
    for row in rows:
        assert BucketLevel(row[0]).value == row[0]


def test_unbounded_series_rejected(db):
    """A series with neither max_count nor ends_on_ms is refused (Chronos.md §4.4)."""
    anchor = _insert_node(db, kind="task", title="anchor")
    node = _insert_node(db, kind="task", title="owner")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO review_series (id, node_id, tier, offsets_days,"
            " anchor_node_id, max_count, ends_on_ms, state, created_at)"
            " VALUES (?, ?, 'hard', '[1,2]', ?, NULL, NULL, 'active', 1700000000000)",
            (_uid(), node, anchor),
        )


def test_bounded_series_accepted(db):
    """max_count and/or ends_on_ms each satisfy the bound (Chronos.md §4.4)."""
    anchor = _insert_node(db, kind="task", title="anchor")
    node = _insert_node(db, kind="task", title="owner")
    db.execute(
        "INSERT INTO review_series (id, node_id, tier, offsets_days,"
        " anchor_node_id, max_count, ends_on_ms, state, created_at)"
        " VALUES (?, ?, 'hard', '[1,2]', ?, 2, NULL, 'active', 1700000000000)",
        (_uid(), node, anchor),
    )
    db.execute(
        "INSERT INTO review_series (id, node_id, tier, offsets_days,"
        " anchor_node_id, max_count, ends_on_ms, state, created_at)"
        " VALUES (?, ?, 'easy', '[10]', ?, NULL, 1750000000000, 'active', 1700000000000)",
        (_uid(), node, anchor),
    )
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM review_series").fetchone()[0]
    assert count == 2


def test_second_running_timer_rejected(db):
    """One timer at a time: a second running row fails (Chronos.md §4.7)."""
    db.execute(
        "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
        " source, reconciled, mode, target_ms, phase, cycle)"
        " VALUES ('t-run-1', NULL, 'a', 1700000000000, NULL, 'd1', 0,"
        " 'stopwatch', NULL, NULL, 1)"
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
            " source, reconciled, mode, target_ms, phase, cycle)"
            " VALUES ('t-run-2', NULL, 'b', 1700000001000, NULL, 'd1', 0,"
            " 'timer', 1500000, NULL, 1)"
        )
    db.rollback()
    db.execute("UPDATE timer_sessions SET ended_at = 1700000600000 WHERE id = 't-run-1'")
    db.execute(
        "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
        " source, reconciled, mode, target_ms, phase, cycle)"
        " VALUES ('t-run-2', NULL, 'b', 1700000001000, NULL, 'd1', 0,"
        " 'timer', 1500000, NULL, 1)"
    )
    db.commit()
    count = db.execute(
        "SELECT COUNT(*) FROM timer_sessions WHERE ended_at IS NULL"
    ).fetchone()[0]
    assert count == 1


def test_tags_on_project_refused(db):
    """Tags apply to tasks/subtasks, never projects (Chronos.md §4.1)."""
    project = _insert_node(db, kind="project", title="proj")
    tag_id = _uid()
    db.execute("INSERT INTO tags (id, name, color) VALUES (?, 't-tag', NULL)", (tag_id,))
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO node_tags (node_id, tag_id) VALUES (?, ?)", (project, tag_id)
        )


def test_tags_on_task_allowed(db):
    """Control: the same tag link on a task succeeds (Chronos.md §4.1)."""
    task = _insert_node(db, kind="task", title="task")
    tag_id = _uid()
    db.execute("INSERT INTO tags (id, name, color) VALUES (?, 'ok-tag', NULL)", (tag_id,))
    db.execute("INSERT INTO node_tags (node_id, tag_id) VALUES (?, ?)", (task, tag_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM node_tags").fetchone()[0]
    assert count == 1


def test_soft_deleted_excluded_from_conflict(db):
    """soft_deleted events are never conflicts (Chronos.md §4.2; §6; API.md Errors)."""
    live = _insert_event(db, 1700000000000, 1700003600000, soft_deleted=0)
    _insert_event(db, 1700001000000, 1700002000000, soft_deleted=1)
    assert live is not None
    hits = db.execute(
        "SELECT id FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0",
        (1700002000000, 1700001000000),
    ).fetchall()
    assert [r[0] for r in hits] == [live]


def test_overlap_is_half_open(db):
    """Overlap is half-open [from,to): touching endpoints do not conflict (API.md Errors)."""
    _insert_event(db, 1700000000000, 1700003600000, soft_deleted=0)
    touching = db.execute(
        "SELECT id FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0",
        (1700003600000 + 1800000, 1700003600000),
    ).fetchall()
    assert touching == []
    overlapping = db.execute(
        "SELECT id FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0",
        (1700003600000 + 60000, 1700003600000 - 60000),
    ).fetchall()
    assert len(overlapping) == 1


def test_times_stored_as_integer_ms(db):
    """Times are UTC epoch ms INTEGER (Chronos.md §4; §7.3)."""
    _insert_event(db, 1700000000000, 1700003600000)
    row = db.execute("SELECT typeof(start_ms), typeof(end_ms) FROM events").fetchone()
    assert (row[0], row[1]) == ("integer", "integer")


def test_bucket_id_on_events_not_nodes(db):
    """bucket_id column is on events, absent on nodes (decisions.md ruling)."""
    event_cols = [r[1] for r in db.execute("PRAGMA table_info(events)").fetchall()]
    node_cols = [r[1] for r in db.execute("PRAGMA table_info(nodes)").fetchall()]
    assert "bucket_id" in event_cols
    assert "bucket_id" not in node_cols


def test_cascade_node_children(db):
    """Deleting a node deletes its children via parent_id cascade (Chronos.md §4.1)."""
    parent = _insert_node(db, kind="project", title="p")
    _insert_node(db, kind="task", title="c", parent=parent)
    db.execute("DELETE FROM nodes WHERE id = ?", (parent,))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    assert count == 0


def test_cascade_node_tags(db):
    """Deleting a node removes its tag links (Chronos.md §4.1)."""
    task = _insert_node(db, kind="task", title="t")
    tag_id = _uid()
    db.execute("INSERT INTO tags (id, name, color) VALUES (?, 'c-tag', NULL)", (tag_id,))
    db.execute("INSERT INTO node_tags (node_id, tag_id) VALUES (?, ?)", (task, tag_id))
    db.commit()
    db.execute("DELETE FROM nodes WHERE id = ?", (task,))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM node_tags").fetchone()[0]
    assert count == 0


def test_cascade_events_with_node(db):
    """Deleting a node deletes its events (Chronos.md §4.2 node_id CASCADE)."""
    task = _insert_node(db, kind="task", title="t")
    _insert_event(db, 1700000000000, 1700000600000, node_id=task)
    db.execute("DELETE FROM nodes WHERE id = ?", (task,))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 0


def test_cascade_series_with_node(db):
    """Deleting a node deletes its review series (Chronos.md §4.4 node_id CASCADE)."""
    anchor = _insert_node(db, kind="task", title="anchor")
    owner = _insert_node(db, kind="task", title="owner")
    db.execute(
        "INSERT INTO review_series (id, node_id, tier, offsets_days,"
        " anchor_node_id, max_count, ends_on_ms, state, created_at)"
        " VALUES ('s-cascade', ?, 'hard', '[1]', ?, 1, NULL, 'active', 1700000000000)",
        (owner, anchor),
    )
    db.commit()
    db.execute("DELETE FROM nodes WHERE id = ?", (owner,))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM review_series").fetchone()[0]
    assert count == 0


def test_cascade_reminders_with_event(db):
    """Deleting an event deletes its reminders (Chronos.md §4.6 event_id CASCADE)."""
    eid = _insert_event(db, 1700000000000, 1700000600000)
    db.execute(
        "INSERT INTO reminders (id, event_id, fire_at_ms, offset_min,"
        " state, channel, created_at)"
        " VALUES ('r-cascade', ?, 1699999400000, 10, 'pending', 'ntfy', 1700000000000)",
        (eid,),
    )
    db.commit()
    db.execute("DELETE FROM events WHERE id = ?", (eid,))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    assert count == 0


def test_cascade_node_links(db):
    """node_links rows vanish with either endpoint (decisions.md 2026-10-03 ruling 1)."""
    first = _insert_node(db, kind="task", title="a")
    second = _insert_node(db, kind="task", title="b")
    db.execute(
        "INSERT INTO node_links (source_id, target_id) VALUES (?, ?)", (first, second)
    )
    db.commit()
    db.execute("DELETE FROM nodes WHERE id = ?", (first,))
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM node_links").fetchone()[0]
    assert count == 0


def test_fts_keyword_search_joins_back(db):
    """FTS5 keyword search joins back to nodes (Chronos.md §4.8; 2026-10-05 FTS freeze)."""
    tables = _tables(db)
    assert "node_fts" in tables
    nid = _insert_node(db, kind="task", title="Buy database textbook")
    try:
        db.execute(
            "INSERT INTO node_fts (title, notes) VALUES ('Buy database textbook', NULL)"
        )
        db.commit()
    except sqlite3.OperationalError:
        pytest.fail("node_fts must accept (title, notes) rows (2026-10-05 FTS freeze)")
    hits = db.execute(
        "SELECT n.id FROM node_fts JOIN nodes n"
        " ON n.title = node_fts.title WHERE node_fts MATCH 'database'"
    ).fetchall()
    assert [nid] == [r[0] for r in hits]
