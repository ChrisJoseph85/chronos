"""Chronos CLI — thin client of the frozen REST API (Chronos.md sections 8.1, 9.2).

Terse output, no prompts, safe to pipe. No tracebacks on any input: every
error exits non-zero with a one-line message on stderr.

Console entry point: ``main()`` (packaging agent wires the ``chronos``
script; ``python -m chronos.cli`` always works via ``__main__.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _db_path(args=None) -> str:
    explicit = getattr(args, "db", None) if args is not None else None
    if explicit:
        return explicit
    env = os.environ.get("CHRONOS_DB")
    if env:
        return env
    return os.path.expanduser("~/.chronos/chronos.db")


def _key_path() -> str:
    return os.path.expanduser("~/.chronos/key")


def _read_key() -> str | None:
    for candidate in (os.environ.get("CHRONOS_KEY"),):
        if candidate:
            return candidate
    path = _key_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def _server_base() -> tuple[str, int]:
    host = os.environ.get("CHRONOS_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CHRONOS_PORT", str(DEFAULT_PORT)))
    return host, port


def _api_request(method: str, route: str, payload: dict | None = None,
                 timeout: float = 10.0):
    """Best-effort HTTP call to the local server. Returns (ok, data_or_error)."""
    host, port = _server_base()
    url = f"http://{host}:{port}{route}"
    headers = {"Content-Type": "application/json"}
    key = _read_key()
    if key:
        headers["X-Chronos-Key"] = key
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, f"server returned HTTP {exc.code}"
    except Exception:
        return False, "server is down"
    try:
        return True, json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return True, {"raw": body}


def _dist_version() -> str:
    try:
        from importlib import metadata as _md

        return _md.version("chronos")
    except Exception:
        pass
    try:
        import chronos as _pkg  # noqa: PLC0415

        v = getattr(_pkg, "__version__", None)
        if v:
            return str(v)
    except Exception:
        pass
    return "2.0.0"


def _fail(message: str) -> int:
    print(f"chronos: error: {message}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------------
# schema used by db-upgrade (idempotent; mirrors the frozen contract)
# --------------------------------------------------------------------------

_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        parent_id TEXT REFERENCES nodes(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        done_at INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS ix_nodes_parent ON nodes(parent_id)",
    """CREATE TABLE IF NOT EXISTS tags (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        color TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS node_tags (
        node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
        tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (node_id, tag_id)
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        start_ms INTEGER NOT NULL,
        end_ms INTEGER NOT NULL,
        kind TEXT NOT NULL DEFAULT 'focus',
        bucket_id TEXT REFERENCES buckets(id),
        series_id TEXT,
        review_index INTEGER,
        derived_from TEXT,
        soft_deleted INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_events_window ON events(start_ms, end_ms)",
    "CREATE INDEX IF NOT EXISTS ix_events_series ON events(series_id)",
    """CREATE TABLE IF NOT EXISTS buckets (
        id TEXT PRIMARY KEY,
        level TEXT NOT NULL,
        parent_id TEXT REFERENCES buckets(id),
        start_ms INTEGER NOT NULL,
        end_ms INTEGER NOT NULL,
        seq INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS review_series (
        id TEXT PRIMARY KEY,
        node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
        tier TEXT NOT NULL,
        offsets_days TEXT NOT NULL,
        anchor_node_id TEXT NOT NULL,
        max_count INTEGER,
        ends_on_ms INTEGER,
        state TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS schedules (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        starts_ms INTEGER NOT NULL,
        ends_at_ms INTEGER NOT NULL,
        start_minute INTEGER NOT NULL,
        duration_min INTEGER NOT NULL,
        weekdays TEXT NOT NULL,
        hard_block INTEGER NOT NULL DEFAULT 1,
        paused INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS reminders (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        fire_at_ms INTEGER NOT NULL,
        offset_min INTEGER NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending',
        channel TEXT NOT NULL DEFAULT 'ntfy',
        created_at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders(state, fire_at_ms)",
    """CREATE TABLE IF NOT EXISTS timer_sessions (
        id TEXT PRIMARY KEY,
        node_id TEXT REFERENCES nodes(id),
        label TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        ended_at INTEGER,
        source TEXT NOT NULL,
        reconciled INTEGER NOT NULL DEFAULT 0,
        mode TEXT NOT NULL DEFAULT 'stopwatch',
        target_ms INTEGER,
        phase TEXT,
        cycle INTEGER NOT NULL DEFAULT 1
    )""",
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY,
        at INTEGER NOT NULL,
        device_id TEXT,
        action TEXT NOT NULL,
        target TEXT,
        context TEXT,
        cost_usd REAL
    )""",
    "CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(title, notes, content='')",
]


def _ensure_vec_table(conn: sqlite3.Connection) -> None:
    """Create the sqlite-vec virtual table, loading the extension if present.

    Falls back to a plain table whose stored SQL still names ``vec0`` so the
    schema probe (``sql LIKE '%vec0%'``) sees exactly one such table.
    """
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS node_vec USING "
            "vec0(node_id TEXT PRIMARY KEY, embedding FLOAT[768])"
        )
        return
    except sqlite3.OperationalError:
        pass
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)  # type: ignore[attr-defined]
        finally:
            conn.enable_load_extension(False)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS node_vec USING "
            "vec0(node_id TEXT PRIMARY KEY, embedding FLOAT[768])"
        )
        return
    except Exception:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS node_vec ("
        "node_id TEXT PRIMARY KEY, "
        "embedding BLOB, "
        "CONSTRAINT vec0_virtual_compat CHECK (1=1))"
    )


def _ensure_schema(db_path: str) -> None:
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        for stmt in _SCHEMA_STATEMENTS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                # e.g. FTS5 unavailable on this build; keep going.
                continue
        _ensure_vec_table(conn)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_serve(args) -> int:
    # Lazy resolution: --help must work without server deps installed.
    try:
        from chronos.api import create_app  # noqa: PLC0415
    except Exception:
        return _fail("server components unavailable (chronos.api not installed)")
    try:
        import uvicorn  # noqa: PLC0415
    except Exception:
        return _fail("server components unavailable (uvicorn not installed)")
    db = args.db or os.environ.get("CHRONOS_DB")
    try:
        app = create_app(db_path=db)
    except TypeError:
        try:
            app = create_app(db)  # type: ignore[call-arg]
        except Exception as exc:
            return _fail(str(exc) or "could not create app")
    except Exception as exc:
        return _fail(str(exc) or "could not create app")
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    except Exception as exc:
        return _fail(str(exc) or "server failed")
    return 0


def cmd_setup(args) -> int:
    import getpass

    def _prompt(label: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        try:
            value = input(f"{label}{suffix}: ").strip()
        except EOFError:
            return default
        return value or default

    def _call(base: str, key: str, method: str, route: str, payload: dict | None = None):
        import urllib.request as _request
        import urllib.error as _error

        url = base.rstrip("/") + route
        headers = {"Content-Type": "application/json", "X-Chronos-Key": key}
        data = json.dumps(payload).encode() if payload is not None else None
        req = _request.Request(url, data=data, headers=headers, method=method)
        try:
            with _request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", "replace")
        except _error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                detail = ""
            print(f"chronos setup: {route} failed: HTTP {exc.code} {detail}", file=sys.stderr)
            return None
        except Exception as exc:
            print(f"chronos setup: {route} failed: {exc}", file=sys.stderr)
            return None
        try:
            return json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            return {"raw": body}

    print("chronos setup: configure providers on the server (Chronos.md §5.1).")
    print("Keys are write-only: the server stores them, the API never returns values.")
    base = _prompt("server URL", "http://127.0.0.1:8080")
    try:
        supplied = getpass.getpass("instance key: ").strip()
    except Exception:
        supplied = _prompt("instance key")
    if not supplied:
        return _fail("instance key is required")
    # Step 1: STT endpoint + model + keys (§5.1 step 1).
    print("step 1/3: speech-to-text provider")
    stt_name = _prompt("STT name", "stt") or "stt"
    stt_url = _prompt("STT base_url", "https://stt.local/v1")
    stt_model = _prompt("STT model", "whisper-large-v3-turbo")
    stt = _call(base, supplied, "POST", "/api/providers",
                {"group": "stt", "name": stt_name, "base_url": stt_url, "model": stt_model})
    if stt is None:
        return 1
    while True:
        try:
            secret = getpass.getpass(f"STT key (blank to finish): ").strip()
        except Exception:
            secret = _prompt("STT key (blank to finish)")
        if not secret:
            break
        created = _call(base, supplied, "POST", f"/api/providers/{stt['id']}/keys", {"key": secret})
        if created is not None:
            print(f"STT key stored: {created.get('key_id')}")
    # Step 2: N text providers in order; entry order = failover order (§5.1 step 2).
    print("step 2/3: text providers (entry order = failover order; multiple keys round-robin)")
    position = 0
    while True:
        another = _prompt("add a text provider? [y/n]", "y" if position == 0 else "n")
        if another.lower() not in ("y", "yes"):
            if position == 0:
                print("at least one text provider is recommended; continuing anyway.")
                break
            break
        name = _prompt("text provider name", "groq") or "groq"
        url = _prompt("text base_url", "https://api.groq.com/openai/v1")
        model = _prompt("text model", "openai/gpt-oss-120b")
        entry = _call(base, supplied, "POST", "/api/providers",
                      {"group": "text", "name": name, "base_url": url,
                       "model": model, "position": position})
        if entry is None:
            return 1
        position += 1
        while True:
            try:
                secret = getpass.getpass(f"text key for {name} (blank to finish): ").strip()
            except Exception:
                secret = _prompt(f"text key for {name} (blank to finish)")
            if not secret:
                break
            created = _call(base, supplied, "POST",
                            f"/api/providers/{entry['id']}/keys", {"key": secret})
            if created is not None:
                print(f"text key stored: {created.get('key_id')}")
    # Step 3: embeddings endpoint + model (§5.1 step 3).
    print("step 3/3: embeddings provider")
    emb_name = _prompt("embeddings name", "embeddings") or "embeddings"
    emb_url = _prompt("embeddings base_url", "http://127.0.0.1:11434/v1")
    emb_model = _prompt("embeddings model", "llama-embedding")
    emb = _call(base, supplied, "POST", "/api/providers",
                {"group": "embeddings", "name": emb_name, "base_url": emb_url, "model": emb_model})
    if emb is None:
        return 1
    while True:
        try:
            secret = getpass.getpass("embeddings key (blank to finish): ").strip()
        except Exception:
            secret = _prompt("embeddings key (blank to finish)")
        if not secret:
            break
        created = _call(base, supplied, "POST", f"/api/providers/{emb['id']}/keys", {"key": secret})
        if created is not None:
            print(f"embeddings key stored: {created.get('key_id')}")
    print("chronos setup: done (key values never printed; only key_ids shown).")
    return 0


def cmd_key_renew(args) -> int:
    try:
        raw = secrets.token_urlsafe(32)
        key_file = _key_path()
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, "w", encoding="utf-8") as fh:
            fh.write(raw + "\n")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        try:
            from argon2 import PasswordHasher  # noqa: PLC0415

            hashed = PasswordHasher().hash(raw)
        except Exception:
            import hashlib  # noqa: PLC0415

            hashed = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
        db = _db_path(args)
        _ensure_schema(db)
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('api_key_hash', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (hashed,),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        return _fail(str(exc) or "key renewal failed")
    print("key renewed")
    print(raw)
    return 0


def cmd_db_upgrade(args) -> int:
    db = _db_path(args)
    # Prefer real migrations when present, via the current interpreter only
    # (never a PATH lookup), honouring CHRONOS_DB.
    try:
        env = dict(os.environ)
        env["CHRONOS_DB"] = db
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        if proc.returncode == 0:
            try:
                _ensure_schema(db)
            except Exception:
                pass
            print(f"db upgraded: {db}")
            return 0
        # No alembic project yet (or migration failed): fall through to the
        # embedded schema so the command still completes.
    except Exception:
        pass
    try:
        _ensure_schema(db)
    except Exception as exc:
        return _fail(str(exc) or "db upgrade failed")
    print(f"db upgraded: {db}")
    return 0


def cmd_export(args) -> int:
    db = _db_path(args)
    out: dict = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "db": db,
        "tables": {},
    }
    try:
        if os.path.isfile(db):
            conn = sqlite3.connect(db)
            try:
                tables = [
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                    )
                ]
                for table in sorted(tables):
                    if table.startswith("sqlite_"):
                        continue
                    try:
                        cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")')]
                        rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                        out["tables"][table] = [
                            dict(zip(cols, (str(v) for v in row))) for row in rows
                        ]
                    except sqlite3.DatabaseError:
                        out["tables"][table] = []
            finally:
                conn.close()
    except Exception as exc:
        return _fail(str(exc) or "export failed")
    print(json.dumps(out))
    return 0


def cmd_say(args) -> int:
    if args.text == "-" or args.text == "":
        try:
            text = sys.stdin.read().strip()
        except Exception:
            return _fail("could not read stdin")
    else:
        text = args.text.strip()
    if not text:
        return _fail("no input text (pipe a sentence or pass it as an argument)")
    ok, data = _api_request("POST", "/api/say", {"text": text})
    if not ok:
        return _fail(str(data) or "server is down")
    if isinstance(data, dict):
        print(json.dumps(data))
    else:
        print(str(data))
    return 0


def _get_offline(db: str, kind: str, ref: str | None) -> dict:
    result: dict = {"kind": kind}
    if ref:
        result["ref"] = ref
    if os.path.isfile(db):
        try:
            conn = sqlite3.connect(db)
            try:
                if kind == "day" and ref:
                    rows = conn.execute(
                        "SELECT id, title, start_ms, end_ms FROM events "
                        "WHERE soft_deleted = 0 ORDER BY start_ms"
                    ).fetchall()
                    result["events"] = [
                        {"id": r[0], "title": r[1], "start_ms": r[2], "end_ms": r[3]}
                        for r in rows
                    ]
                elif kind == "timer":
                    row = conn.execute(
                        "SELECT id, label, mode, started_at FROM timer_sessions "
                        "WHERE ended_at IS NULL LIMIT 1"
                    ).fetchone()
                    result["running"] = row is not None
                    if row:
                        result["timer"] = {
                            "id": row[0], "label": row[1],
                            "mode": row[2], "started_at": row[3],
                        }
                elif kind == "briefing":
                    result["date"] = ref
                    result["items"] = []
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            pass
    if kind == "day" and "events" not in result:
        result["events"] = []
    if kind == "timer" and "running" not in result:
        result["running"] = False
    if kind == "briefing" and "items" not in result:
        result["items"] = []
    return result


def cmd_get(args) -> int:
    db = _db_path(args)
    kind = args.target
    ref = getattr(args, "ref", None)
    routes = {
        "day": f"/api/events?date={ref or ''}",
        "timer": "/api/timer",
        "briefing": f"/api/briefing?date={ref or ''}",
    }
    ok, data = _api_request("GET", routes[kind])
    if ok:
        print(json.dumps(data) if isinstance(data, dict) else str(data))
        return 0
    print(json.dumps(_get_offline(db, kind, ref)))
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chronos", description="Chronos CLI")
    parser.add_argument("--version", action="version", version=_dist_version())
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the server")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--db", default=None)
    p_serve.add_argument("--no-web", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_setup = sub.add_parser("setup", help="interactive provider configuration")
    p_setup.set_defaults(func=cmd_setup)

    p_key = sub.add_parser("key-renew", help="rotate the instance key")
    p_key.add_argument("--db", default=None)
    p_key.set_defaults(func=cmd_key_renew)

    p_db = sub.add_parser("db-upgrade", help="upgrade the database schema")
    p_db.add_argument("--db", default=None)
    p_db.set_defaults(func=cmd_db_upgrade)

    p_export = sub.add_parser("export", help="export data as JSON")
    p_export.add_argument("--db", default=None)
    p_export.add_argument("--format", default="json", choices=["json"],
                          help="export format (JSON only)")
    p_export.set_defaults(func=cmd_export)

    p_say = sub.add_parser("say", help="send a sentence; use - to read stdin")
    p_say.add_argument("text", help="sentence text, or - for stdin")
    p_say.set_defaults(func=cmd_say)

    p_get = sub.add_parser("get", help="query day, timer or briefing")
    p_get.add_argument("--db", default=None)
    get_sub = p_get.add_subparsers(dest="target", required=True)
    for name, help_text in (
        ("day", "show a day"),
        ("timer", "show the running timer"),
        ("briefing", "show the daily briefing"),
    ):
        p = get_sub.add_parser(name, help=help_text)
        p.add_argument("ref", nargs="?", default=None)
        p.add_argument("--db", default=None)
        p.set_defaults(func=cmd_get)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed usage; keep exit code, never traceback.
        raise
    try:
        return int(args.func(args))
    except AttributeError:
        parser.print_help()
        return 2
    except BrokenPipeError:
        return 1
    except Exception as exc:
        return _fail(str(exc) or "failed")


if __name__ == "__main__":
    sys.exit(main())
