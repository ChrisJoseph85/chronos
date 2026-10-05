"""ORM surface: re-exports the real DDL (Phase 1, sqlite3-based)."""

from __future__ import annotations

from chronos.db.bootstrap import DDL_STATEMENTS

SCHEMA_STATEMENTS = DDL_STATEMENTS
CREATE_STATEMENTS = DDL_STATEMENTS
DDL = DDL_STATEMENTS

__all__ = ["DDL_STATEMENTS", "SCHEMA_STATEMENTS", "CREATE_STATEMENTS", "DDL"]
