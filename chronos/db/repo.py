"""sqlite3-backed repo (stdlib only). Enforces bounded series + timer rules.

FTS maintenance (index/remove/reindex) is best-effort with narrow
`except OperationalError` only, so core writes never break.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid

__all__ = ["Repo", "open_repo", "FTS_DDL"]

try:
    from chronos.db.bootstrap import FTS_DDL
except ImportError:  # pragma: no cover - fallback keeps canonical string identical
    FTS_DDL = "CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(title, notes, node_id UNINDEXED)"


def _now() -> int:
    return int(time.time() * 1000)


def _uid() -> str:
    return uuid.uuid4().hex


def _snap_to_minute(ms: int) -> int:
    """Snap to minute grid (Chronos.md §7.2): ceil to next minute boundary."""
    ms = int(ms)
    return ((ms + 60_000 - 1) // 60_000) * 60_000


def _ensure_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(FTS_DDL)
    except sqlite3.OperationalError:
        pass


def _index_node(conn: sqlite3.Connection, node_id: str, title: str | None,
                notes: str | None) -> None:
    try:
        try:
            conn.execute(FTS_DDL)
        except sqlite3.OperationalError:
            pass
        conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node_id,))
        conn.execute(
            "INSERT INTO node_fts (title, notes, node_id) VALUES (?, ?, ?)",
            (title or "", notes or "", node_id),
        )
    except sqlite3.OperationalError:
        pass


def _remove_node_index(conn: sqlite3.Connection, node_id: str) -> None:
    try:
        conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node_id,))
    except sqlite3.OperationalError:
        pass


class Repo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.execute("PRAGMA foreign_keys = ON")

    # -- nodes --
    def create_node(self, kind: str, title: str, parent_id=None, notes=None,
                    status: str = "active") -> dict:
        if kind == "project":
            pass
        nid = _uid()
        now = _now()
        self.conn.execute(
            "INSERT INTO nodes (id, parent_id, kind, title, notes, status,"
            " created_at, updated_at, done_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (nid, parent_id, kind, title, notes, status, now, now),
        )
        self.conn.commit()
        _index_node(self.conn, nid, title, notes)
        try:
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        return {"id": nid, "kind": kind, "title": title}

    def get_node(self, node_id: str):
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return row

    def delete_node(self, node_id: str) -> None:
        _remove_node_index(self.conn, node_id)
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        try:
            self.conn.commit()
        except sqlite3.OperationalError:
            pass
        _remove_node_index(self.conn, node_id)
        try:
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    # -- events --
    def create_event(self, title: str, start_ms: int, end_ms: int, kind: str = "focus",
                     node_id=None) -> dict:
        eid = _uid()
        start_ms = _snap_to_minute(start_ms)
        end_ms = _snap_to_minute(end_ms)
        if end_ms <= start_ms:
            end_ms = start_ms + 60_000
        self.conn.execute(
            "INSERT INTO events (id, node_id, title, start_ms, end_ms, kind,"
            " bucket_id, series_id, review_index, derived_from, soft_deleted, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 0, ?)",
            (eid, node_id, title, start_ms, end_ms, kind, _now()),
        )
        self.conn.commit()
        return {"id": eid}

    def conflicts(self, start_ms: int, end_ms: int):
        return self.conn.execute(
            "SELECT id FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0",
            (end_ms, start_ms),
        ).fetchall()

    # -- review series (bounded enforced at repo level too) --
    def create_series(self, node_id: str, tier: str, offsets_days, anchor_node_id: str,
                      max_count=None, ends_on_ms=None, state: str = "active") -> dict:
        if max_count is None and ends_on_ms is None:
            raise ValueError("bounded series required: max_count and/or ends_on_ms")
        from chronos.core.scheduling import TIER_OFFSETS

        offsets = list(TIER_OFFSETS.get(tier, [])) if tier != "custom" else list(offsets_days)
        sid = _uid()
        self.conn.execute(
            "INSERT INTO review_series (id, node_id, tier, offsets_days,"
            " anchor_node_id, max_count, ends_on_ms, state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, node_id, tier, json.dumps(offsets), anchor_node_id,
             max_count, ends_on_ms, state, _now()),
        )
        from chronos.core.scheduling import DAY_MS

        anchor_ms = _now()
        for i, off in enumerate(offsets, start=1):
            eid = _uid()
            self.conn.execute(
                "INSERT INTO events (id, node_id, title, start_ms, end_ms, kind,"
                " bucket_id, series_id, review_index, derived_from, soft_deleted, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'review', NULL, ?, ?, ?, 0, ?)",
                (eid, node_id, "review", anchor_ms + off * DAY_MS,
                 anchor_ms + off * DAY_MS + 30 * 60_000, sid, i, anchor_node_id, _now()),
            )
        self.conn.commit()
        return {"id": sid, "offsets_days": offsets}

    def delete_series(self, series_id: str) -> None:
        self.conn.execute("DELETE FROM events WHERE series_id = ?", (series_id,))
        self.conn.execute("DELETE FROM review_series WHERE id = ?", (series_id,))
        self.conn.commit()

    # -- timers (one-at-a-time; stopwatch ignores target) --
    def start_timer(self, label: str, mode: str = "stopwatch", target_ms=None,
                    node_id=None, source: str = "", phase=None) -> dict:
        if mode == "stopwatch":
            target_ms = None
        tid = _uid()
        self.conn.execute(
            "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
            " source, reconciled, mode, target_ms, phase, cycle)"
            " VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?, ?, 1)",
            (tid, node_id, label, _now(), source, mode, target_ms, phase),
        )
        self.conn.commit()
        return {"id": tid, "mode": mode, "target_ms": target_ms}

    def stop_timer(self, timer_id: str, void: bool = False) -> None:
        if void:
            try:
                self.conn.execute(
                    "UPDATE timer_sessions SET ended_at = ?, voided = 1 WHERE id = ?",
                    (_now(), timer_id),
                )
            except sqlite3.OperationalError:
                # Pre-migration DB without voided column: plain stop.
                self.conn.execute(
                    "UPDATE timer_sessions SET ended_at = ? WHERE id = ?", (_now(), timer_id)
                )
        else:
            self.conn.execute(
                "UPDATE timer_sessions SET ended_at = ? WHERE id = ?", (_now(), timer_id)
            )
        self.conn.commit()

    def void_timer(self, timer_id: str) -> None:
        """Mark a session voided (v1.2, spec §8): excluded from all totals."""
        self.stop_timer(timer_id, void=True)

    def timer_summary_ms(self, node_ids: list[str] | None = None) -> int:
        """Total ms over sessions, voided + pomodoro breaks excluded (v1.2)."""
        try:
            if node_ids:
                placeholders = ",".join("?" for _ in node_ids)
                row = self.conn.execute(
                    "SELECT COALESCE(SUM(COALESCE(ended_at, ?) - started_at), 0)"
                    " FROM timer_sessions WHERE NOT (mode = 'pomodoro' AND phase = 'break')"
                    " AND COALESCE(voided, 0) = 0 AND node_id IN (%s)" % placeholders,
                    (_now(), *node_ids),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT COALESCE(SUM(COALESCE(ended_at, ?) - started_at), 0)"
                    " FROM timer_sessions WHERE NOT (mode = 'pomodoro' AND phase = 'break')"
                    " AND COALESCE(voided, 0) = 0",
                    (_now(),),
                ).fetchone()
            return int(row[0] or 0)
        except sqlite3.OperationalError:
            return 0

    def timer_breakdown_ms(self, node_ids: list[str], start_ms: int, end_ms: int,
                           now: int | None = None) -> int:
        """Total ms for a node set in [start_ms, end_ms), voided/breaks excluded (v1.2)."""
        now = _now() if now is None else now
        try:
            placeholders = ",".join("?" for _ in node_ids)
            row = self.conn.execute(
                "SELECT COALESCE(SUM(COALESCE(ended_at, ?) - started_at), 0)"
                " FROM timer_sessions WHERE NOT (mode = 'pomodoro' AND phase = 'break')"
                " AND COALESCE(voided, 0) = 0 AND node_id IN (%s)"
                " AND started_at < ? AND COALESCE(ended_at, ?) > ?" % placeholders,
                (now, *node_ids, end_ms, now, start_ms),
            ).fetchone()
            return int(row[0] or 0)
        except sqlite3.OperationalError:
            return 0

    def reindex_fts(self) -> None:
        try:
            self.conn.execute("INSERT INTO node_fts(node_fts) VALUES ('rebuild')")
        except sqlite3.OperationalError:
            pass


def open_repo(path: str = ":memory:") -> Repo:
    from chronos.db.engine import connect

    return Repo(connect(path))
