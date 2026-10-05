"""Aggregate re-exports of the frozen surface. Stdlib only."""

from __future__ import annotations

from chronos.contracts import enums as _enums  # noqa: F401
from chronos.contracts import models as _models  # noqa: F401
from chronos.contracts import tools as _tools  # noqa: F401

__all__ = ["DDL_HELP", "SCHEMA_VERSION"]

SCHEMA_VERSION = "v2.0-contracts"
DDL_HELP = "DDL lives in chronos.db.bootstrap (Chronos.md §4)"
