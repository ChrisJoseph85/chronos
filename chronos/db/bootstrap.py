"""Real SQLite DDL for Chronos.md §4 (+ decisions.md rulings).

FTS freeze 2026-10-05 (canonical): node_fts = fts5(title, notes, node_id UNINDEXED)
regular table joining back to nodes on node_id match.
No token-cost tables. No web.
"""

from __future__ import annotations

FTS_DDL = "CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(title, notes, node_id UNINDEXED)"

DDL_STATEMENTS: list[str] = [
    """CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    parent_id  TEXT REFERENCES nodes(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    notes      TEXT,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    done_at    INTEGER
)""",
    "CREATE INDEX IF NOT EXISTS ix_nodes_parent ON nodes(parent_id)",
    """CREATE TABLE IF NOT EXISTS tags (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    color TEXT
)""",
    """CREATE TABLE IF NOT EXISTS node_tags (
    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tag_id  TEXT NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (node_id, tag_id)
)""",
    """CREATE TABLE IF NOT EXISTS node_links (
    source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, target_id)
)""",
    """CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    node_id      TEXT REFERENCES nodes(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    start_ms     INTEGER NOT NULL,
    end_ms       INTEGER NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'focus',
    bucket_id    TEXT REFERENCES buckets(id),
    series_id    TEXT,
    review_index INTEGER,
    derived_from TEXT,
    soft_deleted INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_events_window ON events(start_ms, end_ms)",
    "CREATE INDEX IF NOT EXISTS ix_events_series ON events(series_id)",
    """CREATE TABLE IF NOT EXISTS buckets (
    id        TEXT PRIMARY KEY,
    level     TEXT NOT NULL,
    parent_id TEXT REFERENCES buckets(id),
    start_ms  INTEGER NOT NULL,
    end_ms    INTEGER NOT NULL,
    seq       INTEGER NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS review_series (
    id             TEXT PRIMARY KEY,
    node_id        TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    tier           TEXT NOT NULL,
    offsets_days   TEXT NOT NULL,
    anchor_node_id TEXT NOT NULL,
    max_count      INTEGER,
    ends_on_ms     INTEGER,
    state          TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    CHECK (max_count IS NOT NULL OR ends_on_ms IS NOT NULL)
)""",
    """CREATE TABLE IF NOT EXISTS schedules (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    starts_ms      INTEGER NOT NULL,
    ends_at_ms     INTEGER NOT NULL,
    start_minute   INTEGER NOT NULL,
    duration_min   INTEGER NOT NULL,
    weekdays       TEXT NOT NULL,
    hard_block     INTEGER NOT NULL DEFAULT 1,
    paused         INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS reminders (
    id           TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    fire_at_ms   INTEGER NOT NULL,
    offset_min   INTEGER NOT NULL,
    state        TEXT NOT NULL DEFAULT 'pending',
    channel      TEXT NOT NULL DEFAULT 'ntfy',
    created_at   INTEGER NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders(state, fire_at_ms)",
    """CREATE TABLE IF NOT EXISTS timer_sessions (
    id         TEXT PRIMARY KEY,
    node_id    TEXT REFERENCES nodes(id),
    label      TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,
    source     TEXT NOT NULL,
    reconciled INTEGER NOT NULL DEFAULT 0,
    mode       TEXT NOT NULL DEFAULT 'stopwatch',
    target_ms  INTEGER,
    phase      TEXT,
    cycle      INTEGER NOT NULL DEFAULT 1,
    voided     INTEGER NOT NULL DEFAULT 0
)""",
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY,
    at        INTEGER NOT NULL,
    device_id TEXT,
    action    TEXT NOT NULL,
    target    TEXT,
    context   TEXT,
    cost_usd  REAL
)""",
    # Tags never on projects (Chronos.md §4.1).
    """CREATE TRIGGER IF NOT EXISTS trg_node_tags_no_project_ins
BEFORE INSERT ON node_tags
BEGIN
    SELECT CASE
        WHEN (SELECT kind FROM nodes WHERE id = NEW.node_id) = 'project'
        THEN RAISE(ABORT, 'tags never on projects')
    END;
END""",
    """CREATE TRIGGER IF NOT EXISTS trg_node_tags_no_project_upd
BEFORE UPDATE ON node_tags
BEGIN
    SELECT CASE
        WHEN (SELECT kind FROM nodes WHERE id = NEW.node_id) = 'project'
        THEN RAISE(ABORT, 'tags never on projects')
    END;
END""",
    # One timer at a time (Chronos.md §4.7).
    """CREATE TRIGGER IF NOT EXISTS trg_timer_one_running_ins
BEFORE INSERT ON timer_sessions WHEN NEW.ended_at IS NULL
BEGIN
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM timer_sessions WHERE ended_at IS NULL)
        THEN RAISE(ABORT, 'one timer at a time')
    END;
END""",
    """CREATE TRIGGER IF NOT EXISTS trg_timer_one_running_upd
BEFORE UPDATE OF ended_at ON timer_sessions WHEN NEW.ended_at IS NULL
BEGIN
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM timer_sessions WHERE ended_at IS NULL AND id != NEW.id)
        THEN RAISE(ABORT, 'one timer at a time')
    END;
END""",
    # FTS5 regular table (2026-10-05 freeze, canonical): narrow OperationalError only at query time.
    FTS_DDL,
    # Provider management (v1.1 amendment 2026-10-05): server-side store, no .env.
    # Key VALUES live in SQLite; the API never returns them (write-only).
    """CREATE TABLE IF NOT EXISTS providers (
    id         TEXT PRIMARY KEY,
    grp        TEXT NOT NULL,
    name       TEXT NOT NULL,
    base_url   TEXT NOT NULL,
    model      TEXT NOT NULL,
    position   INTEGER NOT NULL,
    active     INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_providers_grp_pos ON providers(grp, position)",
    """CREATE TABLE IF NOT EXISTS provider_keys (
    id          TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    key_value   TEXT NOT NULL,
    created_at  INTEGER NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_provider_keys_provider ON provider_keys(provider_id)",
]

SCHEMA_STATEMENTS = DDL_STATEMENTS
CREATE_STATEMENTS = DDL_STATEMENTS
DDL = DDL_STATEMENTS
SCHEMA_SQL = DDL_STATEMENTS
SCHEMA = DDL_STATEMENTS
BASE_DDL = DDL_STATEMENTS


def _ensure_timer_voided_column(conn) -> None:
    """v1.2 migration: add timer_sessions.voided when missing (idempotent)."""
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(timer_sessions)").fetchall()]
    except Exception:
        return
    if cols and "voided" not in cols:
        try:
            conn.execute("ALTER TABLE timer_sessions ADD COLUMN voided INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass


def init_db(conn) -> None:
    """Execute the real DDL on a sqlite3 connection (vec0-tolerant)."""
    try:
        import sqlite3 as _sqlite3
    except ImportError:  # pragma: no cover
        _sqlite3 = None
    conn.execute("PRAGMA foreign_keys = ON")
    for item in DDL_STATEMENTS:
        try:
            conn.execute(item)
        except Exception as exc:  # noqa: BLE001
            if _sqlite3 is not None and isinstance(exc, _sqlite3.OperationalError):
                if "vec0" in str(exc).lower() or "no such module" in str(exc).lower():
                    continue
            raise
    _ensure_timer_voided_column(conn)
    conn.commit()
