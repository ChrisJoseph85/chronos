"""Initial schema: Chronos.md §4 baseline (see chronos.db.bootstrap).

Applies the bootstrap DDL statements to the TARGET database file (never
:memory:), records schema_version 0001, and is idempotent: every statement
uses IF NOT EXISTS and the version row uses INSERT OR IGNORE, so a second
run is a no-op.
"""

from __future__ import annotations

import os
import sqlite3

revision = "0001"
down_revision = None

SCHEMA_VERSION = "0001"


def _resolve_db_path(db_path: str | None = None) -> str:
    """Resolve the target DB file: explicit arg > CHRONOS_DB > ./chronos.db."""
    if db_path:
        return db_path
    env_path = os.environ.get("CHRONOS_DB")
    if env_path:
        return env_path
    return os.path.abspath(os.path.join(os.getcwd(), "chronos.db"))


def _apply_ddl(conn: sqlite3.Connection) -> None:
    from chronos.db.bootstrap import DDL_STATEMENTS

    conn.execute("PRAGMA foreign_keys = ON")
    for item in DDL_STATEMENTS:
        try:
            conn.execute(item)
        except sqlite3.OperationalError as exc:
            # vec0-tolerant, mirrors chronos.db.bootstrap.init_db.
            msg = str(exc).lower()
            if "vec0" in msg or "no such module" in msg:
                continue
            raise
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version TEXT PRIMARY KEY)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def upgrade(db_path: str | None = None) -> None:
    """Apply baseline DDL to the target database file (idempotent)."""
    # 1. When running under `alembic upgrade head`, use the migration bind so
    #    the DDL lands in the TARGET database, not a throwaway connection.
    try:
        from alembic import op

        bind = op.get_bind()
    except Exception:
        bind = None
    if bind is not None:
        conn = bind.connection if hasattr(bind, "connection") else bind
        if isinstance(conn, sqlite3.Connection):
            _apply_ddl(conn)
            return
        # SQLAlchemy bind: run DDL through it statement-by-statement.
        from sqlalchemy import text as _text

        from chronos.db.bootstrap import DDL_STATEMENTS as _DDL

        with bind.begin():
            for item in _DDL:
                try:
                    bind.execute(_text(item))
                except Exception as exc:  # noqa: BLE001
                    if "vec0" in str(exc).lower() or "no such module" in str(exc).lower():
                        continue
                    raise
            bind.execute(_text("CREATE TABLE IF NOT EXISTS schema_version (version TEXT PRIMARY KEY)"))
            bind.execute(_text("INSERT OR IGNORE INTO schema_version(version) VALUES ('0001')"))
        return
    # 2. Standalone (tests / scripts): open the target file directly.
    path = _resolve_db_path(db_path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        _apply_ddl(conn)
    finally:
        conn.close()


def downgrade() -> None:
    pass
