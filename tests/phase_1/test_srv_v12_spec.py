"""Server v1.2 additive endpoints — docs/android/spec.md §8.

Real sqlite + TestClient, no network. Every test cites its spec section.
"""

import secrets
import sqlite3
from datetime import datetime, timezone

OLD_TIMER_DDL = """CREATE TABLE timer_sessions (
    id         TEXT PRIMARY KEY,
    node_id    TEXT,
    label      TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,
    source     TEXT NOT NULL,
    reconciled INTEGER NOT NULL DEFAULT 0,
    mode       TEXT NOT NULL DEFAULT 'stopwatch',
    target_ms  INTEGER,
    phase      TEXT,
    cycle      INTEGER NOT NULL DEFAULT 1
)"""


def _mint_key():
    return secrets.token_urlsafe(32)


def _hash_key(raw):
    from argon2 import PasswordHasher

    return PasswordHasher().hash(raw)


def _make_app(tmp_path, name="v12-test.db"):
    from chronos.api.app import create_app

    db_path = str(tmp_path / name)
    app = create_app(db_path=db_path)
    raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    return app, raw, db_path


def _client_for(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


def _auth(raw):
    return {"X-Chronos-Key": raw}


def _ms(iso):
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


DAY_FROM = "2024-05-01T00:00:00+00:00"
DAY_TO = "2024-05-02T00:00:00+00:00"


def _insert_node(db_path, nid, kind, title, parent=None):
    conn = sqlite3.connect(db_path)
    try:
        now = _ms("2024-05-01T00:00:00+00:00")
        conn.execute(
            "INSERT INTO nodes (id, parent_id, kind, title, notes, status,"
            " created_at, updated_at, done_at) VALUES (?, ?, ?, ?, NULL, 'active', ?, ?, NULL)",
            (nid, parent, kind, title, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_session(db_path, sid, node_id, start_ms, end_ms,
                    mode="stopwatch", phase=None, voided=0, source="t"):
    conn = sqlite3.connect(db_path)
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(timer_sessions)").fetchall()]
        if "voided" in cols:
            conn.execute(
                "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
                " source, reconciled, mode, target_ms, phase, cycle, voided)"
                " VALUES (?, ?, 's', ?, ?, ?, 0, ?, NULL, ?, 1, ?)",
                (sid, node_id, start_ms, end_ms, source, mode, phase, voided),
            )
        else:
            conn.execute(
                "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
                " source, reconciled, mode, target_ms, phase, cycle)"
                " VALUES (?, ?, 's', ?, ?, ?, 0, ?, NULL, ?, 1)",
                (sid, node_id, start_ms, end_ms, source, mode, phase),
            )
        conn.commit()
    finally:
        conn.close()


def _audit_rows(db_path, action):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT * FROM audit WHERE action = ?", (action,)).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# POST /api/timer/stop void flag (spec §8: stop-void)
# ---------------------------------------------------------------------------


def test_stop_void_true_marks_voided_excluded_from_summary_plus_audit(tmp_path):
    """spec §8: void=true → voided=1, excluded from summary, audit timer_void row."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    started = client.post(
        "/api/timer/start", headers=_auth(raw),
        json={"label": "focus", "source": "shield", "mode": "stopwatch"},
    )
    assert started.status_code == 200
    tid = started.json()["id"]
    stopped = client.post(
        "/api/timer/stop", headers=_auth(raw), json={"source": "shield", "void": True}
    )
    assert stopped.status_code == 200
    body = stopped.json()
    assert body["voided"] == 1
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT voided FROM timer_sessions WHERE id = ?", (tid,)).fetchone()
    finally:
        conn.close()
    assert row[0] == 1
    summary = client.get("/api/timer/summary", headers=_auth(raw))
    assert summary.status_code == 200
    assert summary.json()["node_total_ms"] == 0
    assert summary.json()["descendant_total_ms"] == 0
    assert summary.json()["project_total_ms"] == 0
    rows = _audit_rows(db_path, "timer_void")
    assert len(rows) == 1


def test_stop_default_keeps_time_no_void_no_audit(tmp_path):
    """spec §8: stop without void keeps elapsed (backward compatible), no audit row."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    started = client.post(
        "/api/timer/start", headers=_auth(raw),
        json={"label": "keep", "source": "t", "mode": "stopwatch"},
    )
    assert started.status_code == 200
    tid = started.json()["id"]
    # Backdate the start so kept time is measurable.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE timer_sessions SET started_at = started_at - 60000 WHERE id = ?",
            (tid,),
        )
        conn.commit()
    finally:
        conn.close()
    stopped = client.post("/api/timer/stop", headers=_auth(raw), json={"source": "t"})
    assert stopped.status_code == 200
    assert stopped.json().get("voided", 0) == 0
    summary = client.get("/api/timer/summary", headers=_auth(raw))
    assert summary.status_code == 200
    assert summary.json()["node_total_ms"] >= 60000
    assert _audit_rows(db_path, "timer_void") == []


def test_stop_without_running_still_409(tmp_path):
    """spec §8: unknown id → 404/409 as today; empty stop stays 409."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    resp = client.post(
        "/api/timer/stop", headers=_auth(raw), json={"source": "t", "void": True}
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/stats/breakdown (spec §8: breakdown)
# ---------------------------------------------------------------------------


def _seed_tree(db_path):
    _insert_node(db_path, "proj", "project", "Proj")
    _insert_node(db_path, "child-a", "task", "A-task", parent="proj")
    _insert_node(db_path, "sub-a1", "task", "A-sub", parent="child-a")
    _insert_node(db_path, "child-b", "task", "B-task", parent="proj")
    base = _ms(DAY_FROM)
    _insert_session(db_path, "s-a", "child-a", base + 1000, base + 61000)          # 60_000
    _insert_session(db_path, "s-a1", "sub-a1", base + 120000, base + 242000)       # 122_000
    _insert_session(db_path, "s-b", "child-b", base + 300000, base + 425000)       # 125_000
    _insert_session(db_path, "s-b-void", "child-b", base + 500000, base + 590000,   # voided
                    voided=1)
    _insert_session(db_path, "s-b-break", "child-b", base + 600000, base + 660000,  # break
                    mode="pomodoro", phase="break")


def test_breakdown_sums_per_child_voided_and_breaks_excluded(tmp_path):
    """spec §8: breakdown per direct child; voided + pomodoro breaks excluded."""
    app, raw, db_path = _make_app(tmp_path)
    _seed_tree(db_path)
    client = _client_for(app)
    resp = client.get(
        "/api/stats/breakdown", headers=_auth(raw),
        params={"node_id": "proj", "from": DAY_FROM, "to": DAY_TO},
    )
    assert resp.status_code == 200
    by_id = {row["node_id"]: row for row in resp.json()}
    assert set(by_id) == {"child-a", "child-b"}
    assert by_id["child-a"]["total_ms"] == 60000 + 122000
    assert by_id["child-a"]["title"] == "A-task"
    assert by_id["child-a"]["kind"] == "task"
    assert by_id["child-b"]["total_ms"] == 125000
    # Outside the window → zero, not missing.
    narrow = client.get(
        "/api/stats/breakdown", headers=_auth(raw),
        params={"node_id": "proj", "from": "2024-05-03T00:00:00+00:00",
                "to": "2024-05-04T00:00:00+00:00"},
    )
    assert narrow.status_code == 200
    assert all(row["total_ms"] == 0 for row in narrow.json())


def test_breakdown_bad_range_422_unknown_node_404(tmp_path):
    """spec §8: 422 bad range, 404 unknown node."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    bad = client.get(
        "/api/stats/breakdown", headers=_auth(raw),
        params={"node_id": "proj", "from": DAY_TO, "to": DAY_FROM},
    )
    assert bad.status_code == 422
    missing = client.get("/api/stats/breakdown", headers=_auth(raw),
                         params={"node_id": "proj"})
    assert missing.status_code == 422
    unknown = client.get(
        "/api/stats/breakdown", headers=_auth(raw),
        params={"node_id": "nope", "from": DAY_FROM, "to": DAY_TO},
    )
    assert unknown.status_code == 404


def test_new_routes_require_auth(tmp_path):
    """spec §8 + API.md auth: 401s on the new/changed surface without key."""
    app, raw, db_path = _make_app(tmp_path)
    client = _client_for(app)
    assert client.post("/api/timer/stop", json={"source": "t"}).status_code == 401
    assert client.get(
        "/api/stats/breakdown",
        params={"node_id": "x", "from": DAY_FROM, "to": DAY_TO},
    ).status_code == 401


# ---------------------------------------------------------------------------
# Migration: old DB without voided column upgrades cleanly (spec §8: DDL)
# ---------------------------------------------------------------------------


def test_migration_old_db_without_voided_column_upgrades_cleanly(tmp_path):
    """spec §8: pre-v1.2 DB file gains voided via ALTER; init idempotent; data kept."""
    old_db = str(tmp_path / "old.db")
    conn = sqlite3.connect(old_db)
    try:
        conn.execute(OLD_TIMER_DDL)
        base = _ms(DAY_FROM)
        conn.execute(
            "INSERT INTO timer_sessions (id, node_id, label, started_at, ended_at,"
            " source, reconciled, mode, target_ms, phase, cycle)"
            " VALUES ('old-1', NULL, 'old', ?, ?, 't', 0, 'stopwatch', NULL, NULL, 1)",
            (base, base + 30000),
        )
        conn.commit()
    finally:
        conn.close()
    from chronos.api.app import create_app

    app = create_app(db_path=old_db)
    raw = _mint_key()
    app.state.api_key_hash = _hash_key(raw)
    # Second boot: idempotent, no duplicate-column error.
    create_app(db_path=old_db)
    conn = sqlite3.connect(old_db)
    try:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(timer_sessions)").fetchall()]
        old = conn.execute(
            "SELECT voided, started_at, ended_at FROM timer_sessions WHERE id = 'old-1'"
        ).fetchone()
    finally:
        conn.close()
    assert "voided" in cols
    assert old[0] == 0
    assert old[2] - old[1] == 30000
    client = _client_for(app)
    summary = client.get("/api/timer/summary", headers=_auth(raw))
    assert summary.status_code == 200
    assert summary.json()["node_total_ms"] == 30000
