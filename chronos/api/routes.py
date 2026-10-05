"""Phase 3 REST routes + WebSocket endpoint (real implementations, no stubs)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocket

from chronos.api.auth import extract_key, verify_key
from chronos.api.voice import STTNotConfigured, transcribe_audio

router = APIRouter()

_VERSION = "2.0.0"
_DEFAULT_PRESET = {"name": "default", "focus_minutes": 25, "break_minutes": 5, "cycles": 4}
_PRESETS_KEY = "timer.pomodoro_presets"
_HIDDEN_SETTING_PARTS = ("api_key_hash", "api_key", "key_hash", "chronos_key")


# ---------------------------------------------------------------------------
# db helpers (per-call connection: thread-safe, opens the exact db file)
# ---------------------------------------------------------------------------

def _db_path(request: Request) -> str:
    return str(request.app.state.db_path)


def _connect(request: Request) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(request))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.DatabaseError:
        pass
    return conn


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uid() -> str:
    return uuid.uuid4().hex


def _parse_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    return (ms // 60000) * 60000


def _iso_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _row_to_dict(row: Any) -> dict:
    return {key: row[key] for key in row.keys()}


def _series_day_ms() -> tuple[int, dict]:
    try:
        from chronos.core.scheduling import DAY_MS, TIER_OFFSETS
    except ImportError:
        DAY_MS = 86400000
        TIER_OFFSETS = {"hard": [1, 2, 4, 8, 16], "medium": [3, 7, 15, 30],
                        "easy": [10, 30, 90]}
    return DAY_MS, TIER_OFFSETS


def _insert_series_events(conn: sqlite3.Connection, node_id: str, series_id: str,
                           offsets: list, anchor_ms: int, anchor: str,
                           day_ms: int, now: int) -> int:
    """Insert one review event per offset (minute-grid snapped); returns count."""
    for i, off in enumerate(offsets, start=1):
        eid = _uid()
        start = anchor_ms + int(off) * day_ms
        conn.execute(
            "INSERT INTO events (id, node_id, title, start_ms, end_ms, kind,"
            " bucket_id, series_id, review_index, derived_from, soft_deleted, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'review', NULL, ?, ?, ?, 0, ?)",
            (eid, node_id, "review", start, start + 30 * 60000, series_id, i, anchor, now),
        )
    return len(offsets)


def _resolve_offsets(args: dict, tier: str, tier_offsets: dict, fallback: list | None = None) -> list:
    if args.get("offsets_days") is not None or args.get("offsets") is not None:
        return list(args.get("offsets_days") or args.get("offsets") or [1])
    if tier == "custom" and fallback is not None:
        return list(fallback)
    if tier == "custom":
        return list(args.get("offsets_days") or args.get("offsets") or [1])
    return list(tier_offsets.get(tier, [1]))


# ---------------------------------------------------------------------------
# FTS helpers (canonical: fts5(title, notes, node_id UNINDEXED), best-effort)
# ---------------------------------------------------------------------------

def _fts_insert(conn: sqlite3.Connection, title: Any, notes: Any, node_id: str) -> None:
    """Best-effort FTS write; narrow OperationalError only, never raises."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS node_fts"
            " USING fts5(title, notes, node_id UNINDEXED)"
        )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "INSERT INTO node_fts (title, notes, node_id) VALUES (?, ?, ?)",
            (title or "", notes or "", node_id),
        )
    except sqlite3.OperationalError:
        try:
            conn.execute(
                "INSERT INTO node_fts (title, notes) VALUES (?, ?)",
                (title or "", notes or ""),
            )
        except sqlite3.OperationalError:
            pass


def _fts_reindex(conn: sqlite3.Connection, node_id: str, title: Any, notes: Any) -> None:
    """Best-effort FTS re-index on update; narrow OperationalError only."""
    try:
        conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node_id,))
        conn.execute(
            "INSERT INTO node_fts (title, notes, node_id) VALUES (?, ?, ?)",
            (title or "", notes or "", node_id),
        )
    except sqlite3.OperationalError:
        _fts_insert(conn, title, notes, node_id)


def _fts_delete(conn: sqlite3.Connection, node_id: str) -> None:
    """Best-effort FTS row removal on delete; narrow OperationalError only."""
    try:
        conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node_id,))
    except sqlite3.OperationalError:
        pass


# ---------------------------------------------------------------------------
# instance timezone (Chronos.md §7: one instance tz governs day boundaries)
# ---------------------------------------------------------------------------

def _instance_tz_name(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'instance.timezone'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return "UTC"
    if row is None:
        return "UTC"
    name = str(row[0]).strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
    except Exception:
        return "UTC"
    return name


def _briefing_day(raw: str, tz_name: str) -> str:
    """Resolve a YYYY-MM-DD briefing day; default is today in instance tz."""
    from zoneinfo import ZoneInfo

    text = (raw or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
        if len(text) >= 10:
            try:
                return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
            except ValueError:
                pass
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).date().isoformat()


# ---------------------------------------------------------------------------
# auth guard (runs before validation -> 401 without key)
# ---------------------------------------------------------------------------

async def _require_auth(request: Request) -> None:
    key_hash = getattr(request.app.state, "api_key_hash", None)
    candidate = extract_key(request.headers, request.query_params)
    if not verify_key(candidate, key_hash):
        raise HTTPException(status_code=401, detail="Missing/Invalid key")


# ---------------------------------------------------------------------------
# store adapter for the frozen ToolDispatcher
# ---------------------------------------------------------------------------

class _Store:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.DatabaseError:
            pass
        return conn

    def get_node_kind(self, node_id: str) -> str | None:
        if not node_id:
            return None
        conn = self._conn()
        try:
            row = conn.execute("SELECT kind FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return row["kind"] if row else None
        finally:
            conn.close()

    def list_schedules(self) -> list:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM schedules WHERE paused = 0").fetchall()
            return [_row_to_dict(r) for r in rows]
        except sqlite3.DatabaseError:
            return []
        finally:
            conn.close()

    def list_events(self, start: int, end: int) -> list:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0",
                (end, start),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def create_event(self, args: dict) -> dict:
        conn = self._conn()
        try:
            eid = _uid()
            title = str(args.get("title") or "untitled")[:200]
            start_ms = _parse_ms(args.get("start_ms", args.get("start")))
            end_ms = _parse_ms(args.get("end_ms", args.get("end")))
            if start_ms is None:
                start_ms = (_now_ms() // 60000) * 60000
            if end_ms is None or end_ms <= start_ms:
                end_ms = start_ms + 60 * 60000
            kind = str(args.get("kind") or "focus")
            node_id = args.get("node_id")
            now = _now_ms()
            conn.execute(
                "INSERT INTO events (id, node_id, title, start_ms, end_ms, kind,"
                " bucket_id, series_id, review_index, derived_from, soft_deleted, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 0, ?)",
                (eid, node_id, title, start_ms, end_ms, kind, now),
            )
            conn.commit()
            return {"id": eid, "title": title, "start_ms": start_ms, "end_ms": end_ms}
        finally:
            conn.close()

    def schedule_series(self, args: dict) -> dict:
        DAY_MS, TIER_OFFSETS = _series_day_ms()
        conn = self._conn()
        try:
            sid = _uid()
            now = _now_ms()
            node_id = args.get("node_id") or args.get("anchor_node_id")
            if node_id is None:
                created = self.create_node({"kind": "task", "title": str(args.get("title") or "series")})
                node_id = created["id"]
            tier = str(args.get("tier") or "custom")
            offsets = _resolve_offsets(args, tier, TIER_OFFSETS)
            max_count = args.get("max_count")
            if isinstance(max_count, int) and max_count > 0:
                offsets = offsets[:max_count]
            anchor = args.get("anchor_node_id") or node_id
            conn.execute(
                "INSERT INTO review_series (id, node_id, tier, offsets_days,"
                " anchor_node_id, max_count, ends_on_ms, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                (sid, node_id, tier, json.dumps(list(offsets)), anchor,
                 args.get("max_count"), _parse_ms(args.get("ends_on_ms")), now),
            )
            anchor_ms = _parse_ms(args.get("anchor_ms")) or (now + DAY_MS)
            anchor_ms = (anchor_ms // 60000) * 60000
            count = _insert_series_events(conn, node_id, sid, offsets, anchor_ms,
                                          anchor, DAY_MS, now)
            conn.commit()
            return {"id": sid, "series_id": sid, "offsets_days": offsets,
                    "event_count": count}
        finally:
            conn.close()

    def search_nodes(self, args: dict) -> dict:
        query = str((args or {}).get("q") or (args or {}).get("query") or "")
        limit = int((args or {}).get("limit") or 10)
        conn = self._conn()
        try:
            try:
                rows = conn.execute(
                    "SELECT node_id, title FROM node_fts WHERE node_fts MATCH ? LIMIT ?",
                    (query, limit),
                ).fetchall()
                nodes = []
                for r in rows:
                    nid = r[0]
                    try:
                        nrow = conn.execute(
                            "SELECT kind FROM nodes WHERE id = ?", (nid,)
                        ).fetchone()
                    except sqlite3.OperationalError:
                        nrow = None
                    nodes.append({"id": nid, "kind": nrow[0] if nrow else None,
                                  "title": r[1]})
                if nodes:
                    return {"nodes": nodes, "results": nodes}
            except sqlite3.OperationalError:
                pass
            like = "%" + query + "%"
            rows = conn.execute(
                "SELECT id, kind, title FROM nodes WHERE title LIKE ? LIMIT ?",
                (like, limit),
            ).fetchall()
            nodes = [{"id": r["id"], "kind": r["kind"], "title": r["title"]} for r in rows]
            return {"nodes": nodes, "results": nodes}
        finally:
            conn.close()

    # -- full tool surface (single-dict-arg, dispatcher _passthrough shape) --
    def get_node(self, node_id: str) -> dict | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def create_node(self, args: dict) -> dict:
        conn = self._conn()
        try:
            nid = _uid()
            now = _now_ms()
            kind = str(args.get("kind") or "task")
            title = str(args.get("title") or "untitled")[:200]
            conn.execute(
                "INSERT INTO nodes (id, parent_id, kind, title, notes, status,"
                " created_at, updated_at, done_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (nid, args.get("parent_id"), kind, title, args.get("notes"),
                 str(args.get("status") or "active"), now, now),
            )
            _fts_insert(conn, title, args.get("notes"), nid)
            conn.commit()
            return {"id": nid, "kind": kind, "title": title}
        finally:
            conn.close()

    def update_node(self, args: dict) -> dict:
        conn = self._conn()
        try:
            nid = args.get("node_id") or args.get("id")
            fields = {k: v for k, v in args.items()
                      if k in ("title", "notes", "status", "parent_id") and v is not None}
            if fields:
                fields["updated_at"] = _now_ms()
                conn.execute(
                    "UPDATE nodes SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields),
                    (*fields.values(), nid),
                )
                try:
                    current = conn.execute(
                        "SELECT title, notes FROM nodes WHERE id = ?", (nid,)
                    ).fetchone()
                except sqlite3.OperationalError:
                    current = None
                if current is not None:
                    _fts_reindex(conn, nid, current[0], current[1])
                conn.commit()
            return {"id": nid, "updated": True}
        finally:
            conn.close()

    def delete_node(self, args: dict) -> dict:
        conn = self._conn()
        try:
            nid = args.get("node_id") or args.get("id")
            conn.execute("DELETE FROM nodes WHERE id = ?", (nid,))
            _fts_delete(conn, nid)
            conn.commit()
            return {"id": nid, "deleted": True}
        finally:
            conn.close()

    def link_nodes(self, args: dict) -> dict:
        conn = self._conn()
        try:
            source = args.get("source_id") or args.get("node_id") or args.get("from")
            target = args.get("target_id") or args.get("target") or args.get("to")
            conn.execute("INSERT OR IGNORE INTO node_links (source_id, target_id) VALUES (?, ?)",
                         (source, target))
            conn.commit()
            return {"source_id": source, "target_id": target, "linked": True}
        finally:
            conn.close()

    def tag_node(self, args: dict) -> dict:
        conn = self._conn()
        try:
            nid = args.get("node_id")
            if self.get_node_kind(nid) == "project":
                raise ValueError("tags never apply to projects")
            name = str(args.get("name") or args.get("tag") or "tag")
            tid = _uid()
            conn.execute("INSERT OR IGNORE INTO tags (id, name) VALUES (?, ?)", (tid, name))
            row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
            try:
                conn.execute("INSERT OR IGNORE INTO node_tags (node_id, tag_id) VALUES (?, ?)",
                             (nid, row["id"]))
            except sqlite3.IntegrityError as exc:
                raise ValueError("tags never apply to projects") from exc
            conn.commit()
            return {"node_id": nid, "tag": name, "tagged": True}
        finally:
            conn.close()

    def untag_node(self, args: dict) -> dict:
        conn = self._conn()
        try:
            nid = args.get("node_id")
            name = args.get("name") or args.get("tag")
            if name:
                row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
                if row:
                    conn.execute("DELETE FROM node_tags WHERE node_id = ? AND tag_id = ?",
                                 (nid, row["id"]))
            else:
                conn.execute("DELETE FROM node_tags WHERE node_id = ?", (nid,))
            conn.commit()
            return {"node_id": nid, "untagged": True}
        finally:
            conn.close()

    def update_event(self, args: dict) -> dict:
        conn = self._conn()
        try:
            eid = args.get("event_id") or args.get("id")
            fields: dict = {}
            if args.get("title"):
                fields["title"] = str(args["title"])[:200]
            for key, col in (("start", "start_ms"), ("end", "end_ms"),
                             ("start_ms", "start_ms"), ("end_ms", "end_ms")):
                if args.get(key) is not None:
                    ms = _parse_ms(args[key])
                    if ms is not None:
                        fields[col] = ms
            if args.get("kind"):
                fields["kind"] = str(args["kind"])
            if fields:
                conn.execute("UPDATE events SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields),
                             (*fields.values(), eid))
                conn.commit()
            return {"id": eid, "updated": True}
        finally:
            conn.close()

    def delete_event(self, args: dict) -> dict:
        conn = self._conn()
        try:
            eid = args.get("event_id") or args.get("id")
            conn.execute("UPDATE events SET soft_deleted = 1 WHERE id = ?", (eid,))
            conn.commit()
            return {"id": eid, "deleted": True}
        finally:
            conn.close()

    def delete_series(self, args: dict) -> dict:
        conn = self._conn()
        try:
            sid = args.get("series_id") or args.get("id")
            conn.execute("DELETE FROM events WHERE series_id = ?", (sid,))
            conn.execute("DELETE FROM review_series WHERE id = ?", (sid,))
            conn.commit()
            return {"series_id": sid, "deleted": True}
        finally:
            conn.close()

    def reschedule_series(self, args: dict) -> dict:
        """Delete series events + regenerate in one transaction (honest result)."""
        DAY_MS, TIER_OFFSETS = _series_day_ms()
        sid = args.get("series_id") or args.get("id")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM review_series WHERE id = ?", (sid,)
            ).fetchone()
            if row is None:
                raise ValueError("unknown series: %r" % (sid,))
            prev = _row_to_dict(row)
            try:
                prev_offsets = json.loads(prev.get("offsets_days") or "[]")
            except (ValueError, TypeError):
                prev_offsets = [1]
            tier = str(args.get("tier") or prev.get("tier") or "custom")
            offsets = _resolve_offsets(args, tier, TIER_OFFSETS, fallback=prev_offsets)
            max_count = args.get("max_count", prev.get("max_count"))
            if isinstance(max_count, int) and max_count > 0:
                offsets = offsets[:max_count]
            node_id = args.get("node_id") or prev.get("node_id")
            anchor = args.get("anchor_node_id") or prev.get("anchor_node_id") or node_id
            if args.get("ends_on_ms") is not None:
                ends_on = _parse_ms(args.get("ends_on_ms"))
            else:
                ends_on = prev.get("ends_on_ms")
            anchor_ms = _parse_ms(args.get("anchor_ms")) or (_now_ms() + DAY_MS)
            anchor_ms = (anchor_ms // 60000) * 60000
            now = _now_ms()
            with conn:
                conn.execute("DELETE FROM events WHERE series_id = ?", (sid,))
                conn.execute(
                    "UPDATE review_series SET node_id = ?, tier = ?, offsets_days = ?,"
                    " anchor_node_id = ?, max_count = ?, ends_on_ms = ? WHERE id = ?",
                    (node_id, tier, json.dumps(list(offsets)), anchor,
                     max_count if isinstance(max_count, int) else None, ends_on, sid),
                )
                count = _insert_series_events(conn, node_id, sid, offsets, anchor_ms,
                                              anchor, DAY_MS, now)
            return {"id": sid, "series_id": sid, "rescheduled": True,
                    "offsets_days": list(offsets), "event_count": count,
                    "anchor_ms": anchor_ms}
        finally:
            conn.close()

    def check_conflict(self, args: dict) -> dict:
        start_ms = _parse_ms(args.get("start_ms", args.get("start", args.get("from"))))
        end_ms = _parse_ms(args.get("end_ms", args.get("end", args.get("to"))))
        conn = self._conn()
        try:
            if start_ms is None:
                start_ms = _now_ms()
            if end_ms is None or end_ms <= start_ms:
                end_ms = start_ms + 60 * 60000
            rows = conn.execute(
                "SELECT * FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0",
                (end_ms, start_ms),
            ).fetchall()
            conflicts = [_row_to_dict(r) for r in rows]
            return {"conflicts": conflicts, "free": not conflicts,
                    "start_ms": start_ms, "end_ms": end_ms}
        finally:
            conn.close()

    def find_free_slots(self, args: dict) -> list | dict:
        return self.get_free_time(args)

    def get_free_time(self, args: dict) -> dict:
        start_ms = _parse_ms(args.get("from_ms", args.get("from", args.get("start"))))
        end_ms = _parse_ms(args.get("to_ms", args.get("to", args.get("end"))))
        if start_ms is None:
            start_ms = (_now_ms() // 60000) * 60000
        if end_ms is None or end_ms <= start_ms:
            end_ms = start_ms + 4 * 3600 * 1000
        try:
            duration = int(args.get("duration_min") or args.get("duration_ms") or 30)
        except (TypeError, ValueError):
            duration = 30
        if duration > 10000:
            duration = duration // 60000 or 30
        conn = self._conn()
        try:
            busy = conn.execute(
                "SELECT start_ms, end_ms FROM events WHERE start_ms < ? AND end_ms > ?"
                " AND soft_deleted = 0 ORDER BY start_ms",
                (end_ms, start_ms),
            ).fetchall()
        finally:
            conn.close()
        slots = []
        cursor = start_ms
        step = duration * 60000
        for row in list(busy) + [{"start_ms": end_ms, "end_ms": end_ms}]:
            gap_end = int(row["start_ms"] if isinstance(row, dict) else row[0])
            while cursor + step <= min(gap_end, end_ms):
                slots.append({"start": _iso_ms(cursor), "start_ms": cursor,
                              "end": _iso_ms(cursor + step), "end_ms": cursor + step})
                cursor += step
            busy_end = int(row["end_ms"] if isinstance(row, dict) else row[1])
            cursor = max(cursor, busy_end)
        return {"free": slots, "slots": slots, "from": _iso_ms(start_ms), "to": _iso_ms(end_ms)}

    def create_schedule(self, args: dict) -> dict:
        conn = self._conn()
        try:
            sid = _uid()
            now = _now_ms()
            starts_ms = _parse_ms(args.get("starts_ms", args.get("starts_at", args.get("start")))) or now
            ends_ms = _parse_ms(args.get("ends_at_ms", args.get("ends_at", args.get("end")))) or (starts_ms + 90 * 86400 * 1000)
            weekdays = args.get("weekdays") or [1, 2, 3, 4, 5]
            conn.execute(
                "INSERT INTO schedules (id, title, starts_ms, ends_at_ms, start_minute,"
                " duration_min, weekdays, hard_block, paused, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (sid, str(args.get("title") or "schedule"), starts_ms, ends_ms,
                 int(args.get("start_minute", 510)), int(args.get("duration_min", 60)),
                 json.dumps(list(weekdays)), int(args.get("hard_block", 1)), now),
            )
            conn.commit()
            return {"id": sid, "title": args.get("title")}
        finally:
            conn.close()

    def update_schedule(self, args: dict) -> dict:
        conn = self._conn()
        try:
            sid = args.get("schedule_id") or args.get("id")
            fields = {k: v for k, v in args.items()
                      if k in ("title", "start_minute", "duration_min", "weekdays",
                               "hard_block", "paused") and v is not None}
            if isinstance(fields.get("weekdays"), list):
                fields["weekdays"] = json.dumps(fields["weekdays"])
            if fields:
                conn.execute("UPDATE schedules SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields),
                             (*fields.values(), sid))
                conn.commit()
            return {"id": sid, "updated": True}
        finally:
            conn.close()

    def pause_schedule(self, args: dict) -> dict:
        conn = self._conn()
        try:
            sid = args.get("schedule_id") or args.get("id")
            conn.execute("UPDATE schedules SET paused = 1 WHERE id = ?", (sid,))
            conn.commit()
            return {"id": sid, "paused": True}
        finally:
            conn.close()

    def start_timer(self, args: dict) -> dict:
        conn = self._conn()
        try:
            if conn.execute("SELECT id FROM timer_sessions WHERE ended_at IS NULL LIMIT 1").fetchone():
                return {"success": False, "error": "a timer is already running"}
            mode = str(args.get("mode") or "stopwatch")
            target = args.get("target_ms")
            if mode == "stopwatch":
                target = None
            tid = _uid()
            conn.execute(
                "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
                " source, reconciled, mode, target_ms, phase, cycle)"
                " VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?, ?, 1)",
                (tid, args.get("node_id"), str(args.get("label") or "timer"),
                 _now_ms(), str(args.get("source") or "mcp"), mode, target,
                 args.get("phase") if mode == "pomodoro" else None),
            )
            conn.commit()
            return {"success": True, "id": tid, "mode": mode, "target_ms": target}
        finally:
            conn.close()

    def stop_timer(self, args: dict) -> dict:
        conn = self._conn()
        try:
            row = conn.execute("SELECT id FROM timer_sessions WHERE ended_at IS NULL LIMIT 1").fetchone()
            if row is None:
                return {"success": False, "error": "no timer is running"}
            conn.execute("UPDATE timer_sessions SET ended_at = ? WHERE id = ?", (_now_ms(), row["id"]))
            conn.commit()
            return {"success": True, "id": row["id"], "stopped": True}
        finally:
            conn.close()

    def log_time(self, args: dict) -> dict:
        try:
            duration = int(args.get("duration_ms") or args.get("duration_min", 25) * 60000)
        except (TypeError, ValueError):
            duration = 25 * 60000
        conn = self._conn()
        try:
            tid = _uid()
            now = _now_ms()
            conn.execute(
                "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
                " source, reconciled, mode, target_ms, phase, cycle)"
                " VALUES (?, ?, ?, ?, ?, ?, 0, 'stopwatch', NULL, NULL, 1)",
                (tid, args.get("node_id"), str(args.get("label") or "logged"),
                 now - duration, now, str(args.get("source") or "mcp")),
            )
            conn.commit()
            return {"id": tid, "logged_ms": duration}
        finally:
            conn.close()

    def _day_range(self, args: dict) -> tuple[int, int, str]:
        from zoneinfo import ZoneInfo

        raw = str(args.get("date") or "")
        label: str | None = None
        if raw.strip():
            try:
                label = datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                label = None
        conn = self._conn()
        try:
            tz_name = _instance_tz_name(conn)
        finally:
            conn.close()
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        if label is not None:
            year, month, day = (int(p) for p in label.split("-"))
            start_ms = int(datetime(year, month, day, tzinfo=tz).timestamp() * 1000)
        else:
            now_local = datetime.now(tz)
            label = now_local.date().isoformat()
            start_ms = int(datetime(now_local.year, now_local.month, now_local.day,
                                    tzinfo=tz).timestamp() * 1000)
        return start_ms, start_ms + 86400000, label

    def get_day(self, args: dict) -> dict:
        start, end, label = self._day_range(args)
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0 ORDER BY start_ms",
                (end, start),
            ).fetchall()
            return {"date": label, "events": [_row_to_dict(r) for r in rows],
                    "start_ms": start, "end_ms": end}
        finally:
            conn.close()

    def get_week(self, args: dict) -> dict:
        start, _, label = self._day_range(args)
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE start_ms < ? AND end_ms >= ? AND soft_deleted = 0 ORDER BY start_ms",
                (start + 7 * 86400000, start),
            ).fetchall()
            return {"week_of": label, "events": [_row_to_dict(r) for r in rows]}
        finally:
            conn.close()

    def get_month(self, args: dict) -> dict:
        start, _, label = self._day_range(args)
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE start_ms < ? AND end_ms >= ? AND soft_deleted = 0 ORDER BY start_ms",
                (start + 31 * 86400000, start),
            ).fetchall()
            return {"month_of": label, "events": [_row_to_dict(r) for r in rows]}
        finally:
            conn.close()

    def get_briefing(self, args: dict) -> dict:
        from chronos.ai.briefings import build_briefing

        conn = self._conn()
        try:
            day = _briefing_day(str((args or {}).get("date") or ""), _instance_tz_name(conn))
            return dict(build_briefing(conn, day))
        finally:
            conn.close()

    def ask_question(self, args: dict) -> dict:
        return {"question": str(args.get("question") or "Could you clarify?"), "asked": True}


_ISO_TO_MS = {
    "start": "start_ms", "end": "end_ms",
    "from": "from_ms", "to": "to_ms",
    "fire_at": "fire_at_ms", "starts_at": "starts_ms",
    "ends_at": "ends_ms", "ends_on": "ends_on_ms",
}


def _normalize_tool_args(tool: str, arguments: dict) -> dict:
    """Translate absolute ISO date strings to *_ms ints before dispatch.

    The frozen ToolDispatcher works in epoch ms; API/MCP callers speak ISO.
    """
    args = dict(arguments or {})
    for iso_key, ms_key in _ISO_TO_MS.items():
        if args.get(iso_key) is not None and args.get(ms_key) is None:
            ms = _parse_ms(args[iso_key])
            if ms is not None:
                args[ms_key] = ms
    for key in list(args.keys()):
        if key.endswith("_ms") and isinstance(args[key], str):
            ms = _parse_ms(args[key])
            if ms is not None:
                args[key] = ms
    if tool == "create_event":
        if args.get("start_ms") is None and args.get("from_ms") is not None:
            args["start_ms"] = args["from_ms"]
        if args.get("end_ms") is None and args.get("to_ms") is not None:
            args["end_ms"] = args["to_ms"]
    return args


class NormalizingDispatcher:
    """Thin wrapper: normalize ISO args, then delegate to ToolDispatcher.

    Dispatcher-level rejections (unknown tool, unbounded series,
    tag-on-project) raise ValueError so HTTP layers answer 4xx —
    an unimplemented tool never reports success.
    """

    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner = inner
        self.store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__.get("_inner"), name)

    def get_node(self, node_id: str) -> dict | None:
        return self.store.get_node(node_id)

    def dispatch(self, tool: str, arguments: dict | None = None) -> Any:
        args = _normalize_tool_args(tool, dict(arguments or {}))
        result = self._inner.dispatch(tool, args)
        if isinstance(result, dict) and result.get("success") is False:
            raise ValueError(result.get("error") or ("unimplemented tool: %s" % tool))
        return result


def _dispatcher(db_path: str):  # type: ignore[no-untyped-def]
    from chronos.ai.pipeline.tools import ToolDispatcher

    store = _Store(db_path)
    return ToolDispatcher(store)


def _mcp_dispatcher(db_path: str) -> NormalizingDispatcher:  # type: ignore[no-untyped-def]
    from chronos.ai.pipeline.tools import ToolDispatcher

    store = _Store(db_path)
    return NormalizingDispatcher(ToolDispatcher(store), store)


# ---------------------------------------------------------------------------
# /api/say core (shared by REST and WS)
# ---------------------------------------------------------------------------

def _proposal_store(request_or_app: Any) -> dict:
    app = getattr(request_or_app, "app", request_or_app)
    store = getattr(app.state, "proposals", None)
    if store is None:
        store = {}
        app.state.proposals = store
    return store


def execute_say(text: str, db_path: str, app: Any) -> dict:
    from chronos.ai.pipeline.intent import run_turn

    turn = run_turn(text, now_ms=_now_ms(), timezone="UTC")
    intent = turn.get("intent", "create")
    tool_calls = list(turn.get("tool_calls", []))
    proposal_id = turn.get("proposal_id") or ("proposal-" + _uid()[:8])
    questions = list(turn.get("questions", []) or [])
    if turn.get("question") and turn.get("question") not in questions:
        questions.append(turn["question"])
    questions = questions[:1]

    if not turn.get("committed"):
        _proposal_store(app)[proposal_id] = {
            "text": text, "intent": intent, "tool_calls": tool_calls,
            "created_at": _now_ms(),
        }
        body: dict = {
            "intent": intent, "tool_calls": tool_calls, "proposal_id": proposal_id,
            "committed": False, "events": [], "message": turn.get("message", "Need one detail."),
        }
        if questions:
            body["question"] = questions[0]
        return body

    dispatcher = _dispatcher(db_path)
    events: list[dict] = []
    committed = True
    for call in tool_calls:
        tool = call.get("tool", "")
        arguments = dict(call.get("arguments", {}))
        if tool == "create_event":
            start_ms = _parse_ms(arguments.get("start_ms", arguments.get("start")))
            end_ms = _parse_ms(arguments.get("end_ms", arguments.get("end")))
            if start_ms is None:
                start_ms = (_now_ms() // 60000) * 60000
            if end_ms is None or end_ms <= start_ms:
                end_ms = start_ms + 60 * 60000
            dispatched = dispatcher.dispatch("create_event", {
                "title": arguments.get("title") or (text.strip()[:80] or "untitled"),
                "start_ms": start_ms, "end_ms": end_ms,
                "kind": arguments.get("kind", "focus"),
                **({"node_id": arguments["node_id"]} if arguments.get("node_id") else {}),
            })
            if not dispatched.get("success"):
                committed = False
                continue
            events.append({
                "id": dispatched.get("id") or _uid(),
                "title": dispatched.get("title") or (text.strip()[:80] or "untitled"),
                "start_ms": dispatched.get("start_ms", start_ms),
                "end_ms": dispatched.get("end_ms", end_ms),
                "requested_start_ms": dispatched.get("requested_start_ms", start_ms),
            })
        elif tool == "ask_question":
            committed = False
            question = arguments.get("question") or "When exactly should I schedule it?"
            questions = [{"question": str(question)}]
        else:
            result = dispatcher.dispatch(tool, arguments)
            if isinstance(result, dict) and not result.get("success", True):
                committed = False
    _proposal_store(app)[proposal_id] = {
        "text": text, "intent": intent, "tool_calls": tool_calls,
        "events": events, "created_at": _now_ms(),
    }
    body = {
        "intent": intent, "tool_calls": tool_calls, "proposal_id": proposal_id,
        "committed": committed, "events": events,
        "message": turn.get("message", "Done."),
        "questions": questions if not committed and questions else [],
    }
    if body["questions"]:
        body["question"] = body["questions"][0]
    return body


# ---------------------------------------------------------------------------
# say / commands / voice
# ---------------------------------------------------------------------------

@router.post("/api/say")
async def post_say(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    text = (payload or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    body = execute_say(text, _db_path(request), request.app)
    try:
        await request.app.state.hub.broadcast({"type": "patch", "ops": [], "proposal_id": body.get("proposal_id")})
    except Exception:
        pass
    return JSONResponse(body)


@router.post("/api/commands")
async def post_commands(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    tool = (payload or {}).get("tool", "")
    arguments = (payload or {}).get("arguments", {}) or {}
    if not tool:
        raise HTTPException(status_code=422, detail="tool is required")
    dispatcher = _mcp_dispatcher(_db_path(request))
    try:
        result = dispatcher.dispatch(tool, dict(arguments))
    except ValueError as exc:
        message = str(exc) or ("unimplemented tool: %s" % tool)
        if tool == "tag_node" and "project" in message:
            raise HTTPException(status_code=422, detail=message)
        raise HTTPException(status_code=400, detail=message)
    events: list[dict] = []
    if isinstance(result, dict):
        for key in ("events", "created_events"):
            if isinstance(result.get(key), list):
                events = result[key]
                break
        if not events and result.get("id") and result.get("start_ms") is not None:
            events = [result]
    return JSONResponse({"tool": tool, "result": result, "events": events, "proposal_id": None})


@router.post("/api/voice")
async def post_voice(request: Request, file: UploadFile | None = None) -> JSONResponse:
    await _require_auth(request)
    try:
        result = await transcribe_audio(
            file, None,
            db_path=_db_path(request),
            transport=_provider_transport(request),
        )
    except STTNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc) or "STT provider not configured")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc) or "STT unavailable")
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@router.get("/api/events")
async def get_events(request: Request) -> JSONResponse:
    await _require_auth(request)
    start_ms = _parse_ms(request.query_params.get("from"))
    end_ms = _parse_ms(request.query_params.get("to"))
    conn = _connect(request)
    try:
        if start_ms is not None and end_ms is not None:
            rows = conn.execute(
                "SELECT * FROM events WHERE start_ms < ? AND end_ms > ? AND soft_deleted = 0 ORDER BY start_ms",
                (end_ms, start_ms),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM events WHERE soft_deleted = 0 ORDER BY start_ms").fetchall()
        return JSONResponse([_row_to_dict(r) for r in rows])
    finally:
        conn.close()


@router.get("/api/nodes")
async def get_nodes(request: Request) -> JSONResponse:
    await _require_auth(request)
    parent = request.query_params.get("parent")
    tag = request.query_params.get("tag")
    conn = _connect(request)
    try:
        if tag:
            rows = conn.execute(
                "SELECT n.* FROM nodes n JOIN node_tags nt ON nt.node_id = n.id"
                " JOIN tags t ON t.id = nt.tag_id WHERE t.name = ?",
                (tag,),
            ).fetchall()
        elif parent:
            rows = conn.execute("SELECT * FROM nodes WHERE parent_id = ?", (parent,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return JSONResponse([_row_to_dict(r) for r in rows])
    finally:
        conn.close()


@router.get("/api/buckets")
async def get_buckets(request: Request) -> JSONResponse:
    await _require_auth(request)
    level = request.query_params.get("level")
    conn = _connect(request)
    try:
        if level:
            rows = conn.execute("SELECT * FROM buckets WHERE level = ? ORDER BY start_ms LIMIT 200", (level,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM buckets ORDER BY start_ms LIMIT 200").fetchall()
        return JSONResponse([_row_to_dict(r) for r in rows])
    finally:
        conn.close()


@router.get("/api/briefing")
async def get_briefing(request: Request) -> JSONResponse:
    await _require_auth(request)
    from chronos.ai.briefings import build_briefing

    date = request.query_params.get("date") or ""
    conn = _connect(request)
    try:
        day = _briefing_day(date, _instance_tz_name(conn))
        body = build_briefing(conn, day)
    finally:
        conn.close()
    return JSONResponse(dict(body))


@router.get("/api/search")
async def get_search(request: Request) -> JSONResponse:
    await _require_auth(request)
    query = request.query_params.get("q", "")
    try:
        limit = int(request.query_params.get("limit", "10"))
    except ValueError:
        limit = 10
    store = _Store(_db_path(request))
    result = store.search_nodes({"q": query, "limit": limit})
    return JSONResponse(result.get("nodes", []))


@router.get("/api/reminders")
async def get_reminders(request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _connect(request)
    try:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE state = 'pending' ORDER BY fire_at_ms"
        ).fetchall()
        return JSONResponse([_row_to_dict(r) for r in rows])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# timer
# ---------------------------------------------------------------------------

def _running_timer(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM timer_sessions WHERE ended_at IS NULL LIMIT 1").fetchone()


@router.post("/api/timer/start")
async def post_timer_start(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payload = payload or {}
    mode = str(payload.get("mode") or "stopwatch")
    target_ms = payload.get("target_ms")
    if mode == "stopwatch":
        target_ms = None
    conn = _connect(request)
    try:
        if _running_timer(conn) is not None:
            raise HTTPException(status_code=409, detail="a timer is already running")
        tid = _uid()
        label = str(payload.get("label") or "timer")
        source = str(payload.get("source") or "")
        node_id = payload.get("node_id")
        phase = payload.get("phase") if mode == "pomodoro" else None
        now = _now_ms()
        conn.execute(
            "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
            " source, reconciled, mode, target_ms, phase, cycle)"
            " VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?, ?, 1)",
            (tid, node_id, label, now, source, mode, target_ms, phase),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM timer_sessions WHERE id = ?", (tid,)).fetchone()
        body = _row_to_dict(row)
    finally:
        conn.close()
    try:
        await request.app.state.hub.broadcast({"type": "timer", "action": "start", "timer": body})
    except Exception:
        pass
    return JSONResponse(body)


@router.post("/api/timer/stop")
async def post_timer_stop(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    conn = _connect(request)
    try:
        running = _running_timer(conn)
        if running is None:
            raise HTTPException(status_code=409, detail="no timer is running")
        now = _now_ms()
        conn.execute("UPDATE timer_sessions SET ended_at = ? WHERE id = ?", (now, running["id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM timer_sessions WHERE id = ?", (running["id"],)).fetchone()
        body = _row_to_dict(row)
    finally:
        conn.close()
    try:
        await request.app.state.hub.broadcast({"type": "timer", "action": "stop", "timer": body})
    except Exception:
        pass
    return JSONResponse(body)


@router.get("/api/timer")
async def get_timer(request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _connect(request)
    try:
        running = _running_timer(conn)
        if running is None:
            return JSONResponse(None)
        return JSONResponse(_row_to_dict(running))
    finally:
        conn.close()


@router.get("/api/timer/summary")
async def get_timer_summary(request: Request) -> JSONResponse:
    await _require_auth(request)
    node_id = request.query_params.get("node_id")
    conn = _connect(request)
    try:
        now = _now_ms()

        def _total(where: str, params: tuple) -> int:
            row = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(ended_at, ?) - started_at), 0) FROM timer_sessions"
                " WHERE NOT (mode = 'pomodoro' AND phase = 'break') AND " + where, (now, *params),
            ).fetchone()
            return int(row[0] or 0)

        if node_id:
            descendants = {node_id}
            frontier = [node_id]
            while frontier:
                current = frontier.pop()
                for r in conn.execute("SELECT id FROM nodes WHERE parent_id = ?", (current,)).fetchall():
                    if r["id"] not in descendants:
                        descendants.add(r["id"])
                        frontier.append(r["id"])
            placeholders = ",".join("?" for _ in descendants)
            node_total = _total("node_id = ?", (node_id,))
            desc_total = _total("node_id IN (%s)" % placeholders, tuple(descendants))
            project_id = node_id
            seen = set()
            while project_id and project_id not in seen:
                seen.add(project_id)
                row = conn.execute("SELECT parent_id, kind FROM nodes WHERE id = ?", (project_id,)).fetchone()
                if row is None:
                    break
                if row["kind"] == "project":
                    break
                project_id = row["parent_id"]
            if project_id:
                proj_desc = {project_id}
                frontier = [project_id]
                while frontier:
                    current = frontier.pop()
                    for r in conn.execute("SELECT id FROM nodes WHERE parent_id = ?", (current,)).fetchall():
                        if r["id"] not in proj_desc:
                            proj_desc.add(r["id"])
                            frontier.append(r["id"])
                placeholders = ",".join("?" for _ in proj_desc)
                project_total = _total("node_id IN (%s)" % placeholders, tuple(proj_desc))
            else:
                project_total = desc_total
        else:
            node_total = _total("1 = 1", ())
            desc_total = node_total
            project_total = node_total
        return JSONResponse({
            "node_total_ms": node_total,
            "descendant_total_ms": desc_total,
            "project_total_ms": project_total,
        })
    finally:
        conn.close()


def _read_presets(conn: sqlite3.Connection) -> list[dict]:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (_PRESETS_KEY,)).fetchone()
    except sqlite3.DatabaseError:
        return [dict(_DEFAULT_PRESET)]
    if row is None:
        return [dict(_DEFAULT_PRESET)]
    try:
        stored = json.loads(row["value"])
    except (ValueError, TypeError):
        return [dict(_DEFAULT_PRESET)]
    if not isinstance(stored, list):
        return [dict(_DEFAULT_PRESET)]
    presets = [p for p in stored if isinstance(p, dict)]
    if not any(p.get("focus_minutes") == 25 and p.get("break_minutes") == 5 and p.get("cycles") == 4 for p in presets):
        presets = [dict(_DEFAULT_PRESET)] + presets
    return presets


@router.get("/api/timer/presets")
async def get_presets(request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _connect(request)
    try:
        return JSONResponse(_read_presets(conn))
    finally:
        conn.close()


@router.post("/api/timer/presets")
async def post_presets(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    payload = payload or {}
    for field in ("name", "focus_minutes", "break_minutes", "cycles"):
        if field not in payload:
            raise HTTPException(status_code=422, detail="missing field: %s" % field)
    entry = {
        "name": str(payload["name"]),
        "focus_minutes": int(payload["focus_minutes"]),
        "break_minutes": int(payload["break_minutes"]),
        "cycles": int(payload["cycles"]),
    }
    conn = _connect(request)
    try:
        presets = _read_presets(conn)
        presets.append(entry)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_PRESETS_KEY, json.dumps(presets)),
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse(entry)


# ---------------------------------------------------------------------------
# stats / settings / keys / health
# ---------------------------------------------------------------------------

@router.get("/api/stats")
async def get_stats(request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _connect(request)
    try:
        def _count(table: str, where: str = "") -> int:
            try:
                row = conn.execute("SELECT COUNT(*) FROM %s %s" % (table, where)).fetchone()
                return int(row[0])
            except sqlite3.DatabaseError:
                return 0

        counts = {
            "nodes": _count("nodes"),
            "events": _count("events", "WHERE soft_deleted = 0"),
            "reminders": _count("reminders", "WHERE state = 'pending'"),
            "timer_sessions": _count("timer_sessions"),
        }
        return JSONResponse({"counts": counts, "streaks": {"current": 0, "best": 0}})
    finally:
        conn.close()


def _public_settings(conn: sqlite3.Connection) -> dict:
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    except sqlite3.DatabaseError:
        return {}
    out = {}
    for row in rows:
        key = row["key"]
        lowered = key.lower()
        if any(part in lowered for part in _HIDDEN_SETTING_PARTS):
            continue
        out[key] = row["value"]
    return out


@router.get("/api/settings")
async def get_settings(request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _connect(request)
    try:
        return JSONResponse(_public_settings(conn))
    finally:
        conn.close()


@router.put("/api/settings")
async def put_settings(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="settings body must be an object")
    for key in payload:
        lowered = str(key).lower()
        if any(part in lowered for part in _HIDDEN_SETTING_PARTS):
            raise HTTPException(
                status_code=403,
                detail="key rotation only via POST /api/keys/renew",
            )
    conn = _connect(request)
    try:
        for key, value in payload.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(key), str(value)),
            )
        conn.commit()
        body = _public_settings(conn)
    finally:
        conn.close()
    try:
        await request.app.state.hub.broadcast({"type": "patch", "ops": [{"op": "settings", "keys": list(payload.keys())}]})
    except Exception:
        pass
    return JSONResponse(body)


@router.post("/api/keys/renew")
async def post_keys_renew(request: Request) -> JSONResponse:
    await _require_auth(request)
    import secrets as _secrets

    from chronos.api.auth import hash_key

    new_key = _secrets.token_urlsafe(32)
    request.app.state.api_key_hash = hash_key(new_key)
    conn = _connect(request)
    try:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('api_key_hash', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (request.app.state.api_key_hash,),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        await request.app.state.hub.disconnect_all(code=4001)
    except Exception:
        pass
    return JSONResponse({"new_key": new_key})


@router.get("/api/health")
async def get_health(request: Request) -> JSONResponse:
    uptime = time.time() - float(getattr(request.app.state, "started_at", time.time()))
    return JSONResponse({
        "status": "ok", "version": _VERSION,
        "db_path": str(getattr(request.app.state, "db_path", "")),
        "uptime_seconds": uptime,
    })


# ---------------------------------------------------------------------------
# Providers (v1.1 amendment 2026-10-05): full replacement for `chronos setup`.
# Keys are WRITE-ONLY: values live in SQLite, never appear in any response.
# Entry order (position) = failover order; multi-key round-robin per adapter.
# ---------------------------------------------------------------------------

_PROVIDER_GROUPS = ("stt", "text", "embeddings")
_PROVIDER_KEY_FIELDS = ("key", "keys", "key_value", "api_key", "api_keys")


def _provider_registry(request: Request):  # type: ignore[no-untyped-def]
    from chronos.ai.providers.registry import ProviderRegistry

    return ProviderRegistry(_connect(request))


def _provider_transport(request: Request):
    return getattr(request.app.state, "provider_transport", None)


def _provider_conn(request: Request) -> sqlite3.Connection:
    return _connect(request)


@router.get("/api/providers")
async def get_providers(request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        return JSONResponse(reg.list_grouped())
    finally:
        conn.close()


@router.post("/api/providers")
async def post_provider(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    payload = payload or {}
    group = payload.get("group", payload.get("grp"))
    name = payload.get("name")
    base_url = payload.get("base_url")
    model = payload.get("model")
    position = payload.get("position")
    if group not in _PROVIDER_GROUPS:
        raise HTTPException(status_code=422, detail="bad group")
    if not isinstance(base_url, str) or not (
        base_url.strip().startswith("http://") or base_url.strip().startswith("https://")
    ):
        raise HTTPException(status_code=422, detail="bad base_url")
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        try:
            entry = reg.create_provider(group, name, base_url, model, position)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "invalid provider")
        conn.commit()
        return JSONResponse(entry)
    finally:
        conn.close()


@router.put("/api/providers/{provider_id}")
async def put_provider(provider_id: str, request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    payload = payload or {}
    for field in _PROVIDER_KEY_FIELDS:
        if field in payload:
            raise HTTPException(status_code=422, detail="keys are write-only: use /keys routes")
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        if reg.get_provider(provider_id) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        if "base_url" in payload:
            bu = payload["base_url"]
            if not isinstance(bu, str) or not (
                bu.strip().startswith("http://") or bu.strip().startswith("https://")
            ):
                raise HTTPException(status_code=422, detail="bad base_url")
        try:
            entry = reg.update_provider(
                provider_id,
                name=payload.get("name"),
                base_url=payload.get("base_url"),
                model=payload.get("model"),
                position=payload.get("position"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "invalid provider")
        conn.commit()
        return JSONResponse(entry)
    finally:
        conn.close()


@router.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: str, request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        if reg.get_provider(provider_id) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        reg.delete_provider(provider_id)
        conn.commit()
        return JSONResponse({"deleted": True, "id": provider_id})
    finally:
        conn.close()


@router.post("/api/providers/{provider_id}/keys")
async def post_provider_key(provider_id: str, request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    payload = payload or {}
    key = payload.get("key")
    if not isinstance(key, str) or not key.strip():
        raise HTTPException(status_code=422, detail="key is required")
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        if reg.get_provider(provider_id) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        try:
            result = reg.add_key(provider_id, key)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "invalid key")
        conn.commit()
        return JSONResponse(result)
    finally:
        conn.close()


@router.delete("/api/providers/{provider_id}/keys/{key_id}")
async def delete_provider_key(provider_id: str, key_id: str, request: Request) -> JSONResponse:
    await _require_auth(request)
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        if reg.get_provider(provider_id) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        ok = reg.delete_key(provider_id, key_id)
        if not ok:
            raise HTTPException(status_code=404, detail="key not found")
        conn.commit()
        return JSONResponse({"deleted": True, "key_id": key_id})
    finally:
        conn.close()


@router.post("/api/providers/active")
async def post_provider_active(request: Request) -> JSONResponse:
    await _require_auth(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    payload = payload or {}
    group = payload.get("group", payload.get("grp"))
    pid = payload.get("id")
    if group not in _PROVIDER_GROUPS:
        raise HTTPException(status_code=422, detail="bad group")
    if not pid:
        raise HTTPException(status_code=422, detail="id is required")
    conn = _provider_conn(request)
    try:
        from chronos.ai.providers.registry import ProviderRegistry

        reg = ProviderRegistry(conn)
        if reg.get_provider(str(pid)) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        try:
            entry = reg.set_active(group, str(pid))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc) or "invalid active switch")
        conn.commit()
        return JSONResponse(entry)
    finally:
        conn.close()


@router.post("/api/providers/check-all")
async def post_providers_check_all(request: Request) -> JSONResponse:
    await _require_auth(request)
    from chronos.ai.providers.registry import ProviderRegistry, discover_models

    transport = _provider_transport(request)
    conn = _provider_conn(request)
    try:
        reg = ProviderRegistry(conn)
        results = []
        for entry in reg.list_providers():
            try:
                values = reg.key_values(entry["id"])
                key = values[0] if values else None
                outcome = discover_models(entry["base_url"], key, transport)
                results.append(
                    {"id": entry["id"], "reachable": bool(outcome.get("reachable")),
                     "models": list(outcome.get("models") or [])}
                )
            except Exception:
                results.append({"id": entry["id"], "reachable": False, "models": []})
        return JSONResponse({"results": results})
    finally:
        conn.close()


@router.post("/api/providers/{provider_id}/check")
async def post_provider_check(provider_id: str, request: Request) -> JSONResponse:
    await _require_auth(request)
    from chronos.ai.providers.registry import ProviderRegistry, discover_models

    transport = _provider_transport(request)
    conn = _provider_conn(request)
    try:
        reg = ProviderRegistry(conn)
        entry = reg.get_provider(provider_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="provider not found")
        values = reg.key_values(provider_id)
        key = values[0] if values else None
        outcome = discover_models(entry["base_url"], key, transport)
        return JSONResponse(
            {"id": provider_id, "reachable": bool(outcome.get("reachable")),
             "models": list(outcome.get("models") or [])}
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# WebSocket /ws (auth before accept; reject = 4001)
# ---------------------------------------------------------------------------

async def _ws_snapshot(request: Request) -> dict:
    conn = _connect(request)
    try:
        try:
            event_count = int(conn.execute("SELECT COUNT(*) FROM events WHERE soft_deleted = 0").fetchone()[0])
        except sqlite3.DatabaseError:
            event_count = 0
        try:
            running = _running_timer(conn)
            timer = _row_to_dict(running) if running else None
        except sqlite3.DatabaseError:
            timer = None
        return {"type": "state", "events": event_count, "timer": timer,
                "at": _now_ms(), "db_path": str(getattr(request.app.state, "db_path", ""))}
    finally:
        conn.close()


async def websocket_endpoint(websocket: WebSocket) -> None:
    from starlette.websockets import WebSocketDisconnect

    app = websocket.app
    query_key = websocket.query_params.get("key")
    header_key = None
    try:
        header_key = websocket.headers.get("X-Chronos-Key") or websocket.headers.get("x-chronos-key")
    except Exception:
        header_key = None
    candidate = header_key or query_key
    key_hash = getattr(app.state, "api_key_hash", None)
    hub = app.state.hub
    if not verify_key(candidate, key_hash):
        # Reject with 4001. Accept first so the client observes the close
        # code on receive rather than a failed handshake.
        await websocket.accept()
        try:
            await websocket.close(code=4001)
        except Exception:
            pass
        return
    await websocket.accept()
    await hub.register(websocket)
    try:
        await websocket.send_json(await _ws_snapshot(websocket))
        while True:
            try:
                message = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                break
            if not isinstance(message, dict):
                continue
            mtype = str(message.get("type") or "")
            # Key rotation disconnect: any post-renew traffic closes 4001.
            current_hash = getattr(app.state, "api_key_hash", None)
            if current_hash is not key_hash:
                try:
                    await websocket.close(code=4001)
                except Exception:
                    pass
                break
            if mtype == "hello":
                # Presence announcement only; no reply, so the next
                # received frame answers the next request (say/accept).
                continue
            elif mtype == "say":
                text = str(message.get("text") or "")
                try:
                    body = execute_say(text, str(app.state.db_path), app)
                except Exception:
                    body = {"type": "question", "proposal_id": "proposal-" + _uid()[:8],
                            "question": "When exactly should I schedule it?"}
                proposal_id = body.get("proposal_id")
                if body.get("committed") and body.get("events"):
                    reply = {"type": "patch", "ops": [], "proposal_id": proposal_id, "events": body["events"]}
                elif body.get("question") or body.get("questions"):
                    question = body.get("question") or (body.get("questions") or [None])[0]
                    if isinstance(question, dict):
                        question = question.get("question")
                    reply = {"type": "question", "proposal_id": proposal_id, "question": question}
                else:
                    reply = {"type": "proposal", "proposal_id": proposal_id,
                             "intent": body.get("intent"), "tool_calls": body.get("tool_calls", [])}
                await websocket.send_json(reply)
                if body.get("committed"):
                    try:
                        await hub.broadcast({"type": "patch", "ops": [], "proposal_id": proposal_id})
                    except Exception:
                        pass
            elif mtype in ("accept", "reject", "skip"):
                await websocket.send_json(
                    {"type": "patch", "ops": [], "proposal_id": message.get("proposal_id"),
                     "decision": mtype})
            else:
                await websocket.send_json(await _ws_snapshot(websocket))
    finally:
        try:
            await hub.unregister(websocket)
        except Exception:
            pass
