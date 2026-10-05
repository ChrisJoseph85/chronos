"""Alembic environment: applies chronos.db.bootstrap.DDL_STATEMENTS."""

from __future__ import annotations

import sqlite3
from logging.config import fileConfig

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url", "sqlite:///:memory:")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        pass


def run_migrations_online() -> None:
    from chronos.db.bootstrap import init_db

    db_path = config.get_main_option("db_path", ":memory:")
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
