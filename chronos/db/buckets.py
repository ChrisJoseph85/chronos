"""10-year Y→M→W→D bucket seed (Chronos.md §4.3).

- 10 contiguous years starting at min(today.year, 2026) so the documented
  example ids (Y:2026 … D:2026-08-04) always exist.
- Weeks are Monday-start groups; week id = ISO year/week of the week's own
  start date; week parent = month of its start; day parent = its week.
- Idempotent via INSERT OR IGNORE.
"""

from __future__ import annotations

import calendar
import datetime

__all__ = ["seed_buckets", "ensure_buckets", "seed", "bootstrap_buckets"]


def _day_ms(day: datetime.date) -> tuple[int, int]:
    start = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    s = int(start.timestamp() * 1000)
    return s, s + 86_400_000


def seed_buckets(conn) -> dict:
    today = datetime.date.today()
    start_year = min(today.year, 2026)
    first = datetime.date(start_year, 1, 1)
    last = datetime.date(start_year + 10, 1, 1)  # exclusive
    days: list[datetime.date] = []
    d = first
    while d < last:
        days.append(d)
        d += datetime.timedelta(days=1)

    # Weeks: Monday-start groups covering the range.
    weeks: dict[datetime.date, list[datetime.date]] = {}
    for day in days:
        monday = day - datetime.timedelta(days=day.weekday())
        weeks.setdefault(monday, []).append(day)

    cur = conn.cursor()
    # Years + months.
    for i in range(10):
        y = start_year + i
        s_ms = int(datetime.datetime(y, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        e_ms = int(datetime.datetime(y + 1, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        cur.execute(
            "INSERT OR IGNORE INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
            " VALUES (?, 'Y', NULL, ?, ?, ?)",
            ("Y:%04d" % y, s_ms, e_ms, i + 1),
        )
        for m in range(1, 13):
            ms = int(datetime.datetime(y, m, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
            me = int(
                datetime.datetime(y + (m // 12), (m % 12) + 1, 1,
                                  tzinfo=datetime.timezone.utc).timestamp() * 1000
            )
            cur.execute(
                "INSERT OR IGNORE INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
                " VALUES (?, 'M', ?, ?, ?, ?)",
                ("M:%04d-%02d" % (y, m), "Y:%04d" % y, ms, me, m),
            )
    # Weeks (parent = month of week start).
    ordered = sorted(weeks)
    for monday, members in ((m, weeks[m]) for m in ordered):
        iso_year, iso_week, _ = monday.isocalendar()
        wid = "W:%04d-W%02d" % (iso_year, iso_week)
        parent = "M:%04d-%02d" % (monday.year, monday.month)
        # Parent month row always exists when monday is inside the seeded range;
        # edge Mondays in Dec of the previous year need their rows — fall back
        # to the month of the first in-range child.
        row = cur.execute("SELECT id FROM buckets WHERE id = ?", (parent,)).fetchone()
        if row is None:
            first_in = min(members)
            parent = "M:%04d-%02d" % (first_in.year, first_in.month)
        s_ms, _ = _day_ms(min(members))
        _, e_ms = _day_ms(max(members))
        # seq = ordinal of this week among weeks whose start falls in parent month.
        month_weeks = [w for w in ordered if (w.year, w.month) == (monday.year, monday.month)]
        seq = month_weeks.index(monday) + 1 if monday in month_weeks else 1
        cur.execute(
            "INSERT OR IGNORE INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
            " VALUES (?, 'W', ?, ?, ?, ?)",
            (wid, parent, s_ms, e_ms, seq),
        )
    # Days (parent = containing week; seq = ordinal within week 1..7).
    for monday in ordered:
        iso_year, iso_week, _ = monday.isocalendar()
        wid = "W:%04d-W%02d" % (iso_year, iso_week)
        for member in sorted(weeks[monday]):
            s_ms, e_ms = _day_ms(member)
            seq = member.weekday() + 1
            cur.execute(
                "INSERT OR IGNORE INTO buckets (id, level, parent_id, start_ms, end_ms, seq)"
                " VALUES (?, 'D', ?, ?, ?, ?)",
                ("D:%s" % member.isoformat(), wid, s_ms, e_ms, seq),
            )
    conn.commit()
    counts = {}
    for level in ("Y", "M", "W", "D"):
        counts[level] = cur.execute(
            "SELECT COUNT(*) FROM buckets WHERE level = ?", (level,)
        ).fetchone()[0]
    return counts


def ensure_buckets(conn) -> dict:
    return seed_buckets(conn)


def seed(conn) -> dict:
    return seed_buckets(conn)


def bootstrap_buckets(conn) -> dict:
    return seed_buckets(conn)


def create_buckets(conn) -> dict:
    return seed_buckets(conn)


def seed_ten_years(conn) -> dict:
    return seed_buckets(conn)


def ensure_ten_years(conn) -> dict:
    return seed_buckets(conn)
