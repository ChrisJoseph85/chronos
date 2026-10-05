"""Alembic environment: applies chronos.db.bootstrap DDL to the TARGET db."""

from __future__ import annotations

import os
import sqlite3
from logging.config import fileConfig
from urllib.parse import unquote, urlparse

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _resolve_db_path() -> str:
    """Target DB file: CHRONOS_DB > alembic.ini db_path > sqlalchemy.url file.

    Never :memory: — migrations must land in a real file (deploy spec).
    """
    env_path = os.environ.get("CHRONOS_DB")
    if env_path:
        return os.path.expanduser(env_path)
    ini_path = config.get_main_option("db_path", "")
    if ini_path and ini_path != ":memory:":
        return os.path.expanduser(ini_path)
    url = config.get_main_option("sqlalchemy.url", "")
    if url.startswith("sqlite:///"):
        file_part = unquote(urlparse(url).path)
        if file_part and file_part != ":memory:":
            return os.path.expanduser(file_part)
    return os.path.expanduser("~/.chronos/chronos.db")


def _stamp_alembic_version(conn: sqlite3.Connection, revision: str = "0001") -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alembic_version "
        "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
    )
    conn.execute("DELETE FROM alembic_version")
    conn.execute(
        "INSERT INTO alembic_version(version_num) VALUES (?)", (revision,)
    )
    conn.commit()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url", "")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        pass


def run_migrations_online() -> None:
    db_path = _resolve_db_path()
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        from chronos.db.bootstrap import init_db

        init_db(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version TEXT PRIMARY KEY)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version) VALUES ('0001')"
        )
        _stamp_alembic_version(conn)
    finally:
        conn.close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
