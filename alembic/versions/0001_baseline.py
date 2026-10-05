"""Initial schema: Chronos.md §4 baseline (see chronos.db.bootstrap)."""

revision = "0001"
down_revision = None


def upgrade() -> None:
    from chronos.db.bootstrap import init_db
    import sqlite3

    conn = sqlite3.connect(":memory:")
    init_db(conn)
    conn.close()


def downgrade() -> None:
    pass
