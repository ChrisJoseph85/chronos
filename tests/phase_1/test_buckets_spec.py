"""Phase 1 bucket-seed tests (Chronos.md §4.3; phase-1-core Behaviour/Buckets).

Fresh DB seeds exactly 10 years forward (~10Y/~120M/~522W/~3653D, ~4300 rows)
as a nested Y→M→W→D chain. Day parent = week, week parent = month.
Week id number = ISO week of its start. Re-seed is idempotent.
Uses real sqlite3 only.
"""

import datetime
import importlib
import inspect
import re
import sqlite3

import pytest

_SEED_MODULE = "chronos.db.buckets"
_SEED_CANDIDATES = (
    "seed_buckets",
    "ensure_buckets",
    "seed",
    "bootstrap_buckets",
    "create_buckets",
    "seed_ten_years",
    "ensure_ten_years",
)

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

ID_PATTERNS = {
    "Y": re.compile(r"^Y:\d{4}$"),
    "M": re.compile(r"^M:\d{4}-\d{2}$"),
    "W": re.compile(r"^W:\d{4}-W\d{2}$"),
    "D": re.compile(r"^D:\d{4}-\d{2}-\d{2}$"),
}


def _load_ddl():
    for modname in _DDL_MODULES:
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            continue
        for attr in _DDL_ATTRS:
            value = getattr(mod, attr, None)
            if value is not None:
                return value
    pytest.fail(
        "No DDL found in chronos.db; expose e.g. chronos.db.bootstrap.DDL_STATEMENTS"
        " (Chronos.md §4; phase-1-core Part 1.2)"
    )


def _exec_ddl(conn, ddl):
    items = [ddl] if isinstance(ddl, str) else list(ddl)
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


def _load_seed_fn():
    try:
        mod = importlib.import_module(_SEED_MODULE)
    except ImportError:
        pytest.fail(
            "chronos.db.buckets missing (Chronos.md §4.3; phase-1-core Part 1.3). "
            "Implement bucket seeding there."
        )
    for name in _SEED_CANDIDATES:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    pytest.fail(
        "chronos.db.buckets must expose one of %s "
        "(Chronos.md §4.3: seed 10 years of Y→M→W→D rows)" % (_SEED_CANDIDATES,)
    )


def _run_seed(fn, conn):
    attempts = []
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        params = []
    if len(params) == 0:
        attempts.append(())
    first = params[0].name if params else "conn"
    if first in ("conn", "connection", "cursor", "cur", "db", "session", "handle"):
        attempts.append((conn,))
    else:
        attempts.append((conn,))
        attempts.append(())
    last_error = None
    for args in attempts:
        try:
            return fn(*args)
        except TypeError as exc:
            last_error = exc
            continue
    pytest.fail(
        "Bucket seed must accept a sqlite3 connection, e.g. seed_buckets(conn) "
        "(Chronos.md §4.3). Last error: %s" % (last_error,)
    )


@pytest.fixture()
def seeded():
    """Fresh :memory: DB with real DDL executed and the 10-year seed applied."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        _exec_ddl(conn, _load_ddl())
        _run_seed(_load_seed_fn(), conn)
        yield conn
    finally:
        conn.close()


def _counts(conn):
    out = {}
    for level in ("Y", "M", "W", "D"):
        out[level] = conn.execute(
            "SELECT COUNT(*) FROM buckets WHERE level = ?", (level,)
        ).fetchone()[0]
    out["total"] = conn.execute("SELECT COUNT(*) FROM buckets").fetchone()[0]
    return out


def test_seed_counts_ten_years(seeded):
    """Fresh seed: 10 Y / ~120 M / ~522 W / ~3653 D, ~4300 total (Chronos.md §4.3)."""
    counts = _counts(seeded)
    assert counts["Y"] == 10
    assert counts["M"] == 120
    assert 515 <= counts["W"] <= 530
    assert 3650 <= counts["D"] <= 3660
    assert 4250 <= counts["total"] <= 4400


def test_years_contiguous_and_include_current(seeded):
    """Seed covers exactly 10 contiguous years incl. the current one (Chronos.md §4.3)."""
    rows = seeded.execute("SELECT id FROM buckets WHERE level = 'Y'").fetchall()
    years = sorted(int(r[0][2:]) for r in rows)
    assert len(years) == 10
    assert years == list(range(years[0], years[0] + 10))
    assert datetime.datetime.now().year in years


def test_ids_follow_format(seeded):
    """Bucket ids match Y:/M:/W:/D: formats (Chronos.md §4.3)."""
    rows = seeded.execute("SELECT id, level FROM buckets").fetchall()
    assert len(rows) > 4000
    for bid, level in rows:
        assert ID_PATTERNS[level].match(bid) is not None


def test_documented_example_ids_exist(seeded):
    """Doc example ids Y:2026/M:2026-08/W:2026-W31/D:2026-08-04 exist (Chronos.md §4.3)."""
    for bid in ("Y:2026", "M:2026-08", "W:2026-W31", "D:2026-08-04"):
        found = seeded.execute("SELECT id FROM buckets WHERE id = ?", (bid,)).fetchone()
        assert found is not None


def test_day_parent_is_week(seeded):
    """Every day's parent is a week (phase-1-core: day parent = week)."""
    bad = seeded.execute(
        "SELECT COUNT(*) FROM buckets d JOIN buckets p ON p.id = d.parent_id"
        " WHERE d.level = 'D' AND p.level != 'W'"
    ).fetchone()[0]
    assert bad == 0
    orphan = seeded.execute(
        "SELECT COUNT(*) FROM buckets d LEFT JOIN buckets p ON p.id = d.parent_id"
        " WHERE d.level = 'D' AND p.id IS NULL"
    ).fetchone()[0]
    assert orphan == 0


def test_week_parent_is_month(seeded):
    """Every week's parent is a month (Chronos.md §4.3 chain Y→M→W→D)."""
    bad = seeded.execute(
        "SELECT COUNT(*) FROM buckets w JOIN buckets p ON p.id = w.parent_id"
        " WHERE w.level = 'W' AND p.level != 'M'"
    ).fetchone()[0]
    assert bad == 0
    orphan = seeded.execute(
        "SELECT COUNT(*) FROM buckets w LEFT JOIN buckets p ON p.id = w.parent_id"
        " WHERE w.level = 'W' AND p.id IS NULL"
    ).fetchone()[0]
    assert orphan == 0


def test_month_parent_is_year(seeded):
    """Every month's parent is a year (Chronos.md §4.3 chain Y→M→W→D)."""
    bad = seeded.execute(
        "SELECT COUNT(*) FROM buckets m JOIN buckets p ON p.id = m.parent_id"
        " WHERE m.level = 'M' AND p.level != 'Y'"
    ).fetchone()[0]
    assert bad == 0


def test_chain_walks_to_year(seeded):
    """Each day walks D→W→M→Y without gaps (phase-1-core Done: chain walks cleanly)."""
    sample = seeded.execute("SELECT id, parent_id FROM buckets WHERE level = 'D'").fetchall()
    assert len(sample) > 3600
    by_id = {r[0]: r[1] for r in seeded.execute("SELECT id, parent_id FROM buckets").fetchall()}
    levels = {r[0]: r[1] for r in seeded.execute("SELECT id, level FROM buckets").fetchall()}
    for day_id, _ in sample:
        hop = by_id[day_id]
        assert levels[hop] == "W"
        hop = by_id[hop]
        assert levels[hop] == "M"
        hop = by_id[hop]
        assert levels[hop] == "Y"
        assert hop.startswith("Y:")


def test_week_number_is_iso_of_start(seeded):
    """Week id number = ISO week of its start (phase-1-core Behaviour/Buckets)."""
    rows = seeded.execute("SELECT id FROM buckets WHERE level = 'W'").fetchall()
    assert len(rows) >= 515
    for (wid,) in rows:
        children = seeded.execute(
            "SELECT id FROM buckets WHERE level = 'D' AND parent_id = ? ORDER BY id",
            (wid,),
        ).fetchall()
        assert 1 <= len(children) <= 7
        first_day = datetime.date.fromisoformat(children[0][0][2:])
        iso_week = first_day.isocalendar()[1]
        assert wid == "W:%04d-W%02d" % (first_day.isocalendar()[0], iso_week)


def test_documented_day_chain(seeded):
    """D:2026-08-04 parents to the ISO week of 2026-08-04 (Chronos.md §4.3)."""
    row = seeded.execute(
        "SELECT parent_id FROM buckets WHERE id = 'D:2026-08-04'"
    ).fetchone()
    assert row is not None
    expected_week = datetime.date(2026, 8, 4).isocalendar()[1]
    assert row[0] == "W:2026-W%02d" % expected_week


def test_week_children_contiguous(seeded):
    """A week's day children are contiguous dates, at most 7 (Chronos.md §4.3)."""
    row = seeded.execute(
        "SELECT id FROM buckets WHERE id = 'W:2026-W31'"
    ).fetchone()
    assert row is not None
    children = seeded.execute(
        "SELECT id FROM buckets WHERE level = 'D' AND parent_id = 'W:2026-W31'"
        " ORDER BY id"
    ).fetchall()
    days = [datetime.date.fromisoformat(r[0][2:]) for r in children]
    assert len(days) == 7
    for prev, today in zip(days, days[1:]):
        assert (today - prev) == datetime.timedelta(days=1)
    assert days[0] == datetime.date(2026, 7, 27)


def test_seq_uncapped(seeded):
    """Bucket.seq is the ordinal within parent, not capped at 4 (decisions.md ruling 8)."""
    max_day = seeded.execute(
        "SELECT MAX(seq) FROM buckets WHERE level = 'D'"
    ).fetchone()[0]
    assert max_day > 4
    max_month = seeded.execute(
        "SELECT MAX(seq) FROM buckets WHERE level = 'M'"
    ).fetchone()[0]
    assert max_month == 12


def test_first_year_has_every_date(seeded):
    """Every calendar date of the first seeded year has a day row (Chronos.md §4.3)."""
    first_year = seeded.execute("SELECT MIN(id) FROM buckets WHERE level = 'Y'").fetchone()[0]
    year = int(first_year[2:])
    start = datetime.date(year, 1, 1)
    days_in_year = (datetime.date(year + 1, 1, 1) - start).days
    expected = {"D:%s" % (start + datetime.timedelta(days=i)).isoformat() for i in range(days_in_year)}
    rows = seeded.execute(
        "SELECT id FROM buckets WHERE level = 'D' AND id LIKE ?", ("D:%d-%%" % year,)
    ).fetchall()
    assert set(r[0] for r in rows) == expected


def test_reseed_is_idempotent(seeded):
    """Re-running the seed changes nothing (phase-1-core Behaviour/Buckets)."""
    before = _counts(seeded)
    _run_seed(_load_seed_fn(), seeded)
    assert _counts(seeded) == before


def test_bucket_windows_positive(seeded):
    """Every bucket window has start_ms < end_ms (Chronos.md §4.3)."""
    bad = seeded.execute(
        "SELECT COUNT(*) FROM buckets WHERE start_ms >= end_ms"
    ).fetchone()[0]
    assert bad == 0
