"""DB engine helpers (sqlite3, FK on)."""

from __future__ import annotations

import sqlite3

from chronos.db.bootstrap import DDL_STATEMENTS, init_db

__all__ = ["DDL_STATEMENTS", "connect", "init_db"]


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn
