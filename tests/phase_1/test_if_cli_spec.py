"""Phase 4 CLI contract tests — Chronos.md section 9.2, section 8.1, section 3.

Backend-only freeze 2026-10-05: CLI + MCP only, no HUD, token-cost removed.
Decisions: CLI key storage raw ~/.chronos/key 0600 hash in DB,
chronos export JSON only, say errors if server down,
CLI get only day/timer/briefing.
errors-and-test-proposal.md Layer 1: console script must run.

Every test runs the real console entry point in a subprocess
(installed script or python -m chronos.cli), asserts exit codes +
stdout shape + no traceback. No source-file reads.
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile

CLI = [sys.executable, "-m", "chronos.cli"]
TIMEOUT = 60


def run_cli(*args, input_text=None, env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [*CLI, *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        env=env,
        cwd=cwd,
    )


def combined(result):
    return (result.stdout or "") + (result.stderr or "")


def test_top_help_runs_and_lists_commands():
    """Chronos.md sec 8.1 + errors Layer 1: console script runs, lists subcommands."""
    r = run_cli("--help")
    assert r.returncode == 0, f"--help exit {r.returncode}: {combined(r)[:2000]}"
    assert "Traceback" not in combined(r)
    out = r.stdout
    assert out.strip() != ""
    for cmd in ["serve", "setup", "key-renew", "db-upgrade", "export", "say", "get"]:
        assert cmd in out, f"missing subcommand {cmd} in --help:\n{out[:2000]}"


def test_serve_help_shows_db_port_host():
    """Chronos.md sec 8.1 + phase-4: serve [--port] [--host] [--db]."""
    r = run_cli("serve", "--help")
    assert r.returncode == 0, f"serve --help exit {r.returncode}: {combined(r)[:2000]}"
    assert "Traceback" not in combined(r)
    assert "--db" in r.stdout, f"serve --help must show --db:\n{r.stdout[:2000]}"
    assert "--port" in r.stdout
    assert "--host" in r.stdout


def test_serve_resolves_create_app_factory():
    """Phase-4 Done: serve must resolve chronos.api.create_app (decisions: signature frozen)."""
    code = (
        "from chronos.api import create_app; "
        "import inspect; "
        "assert callable(create_app), 'create_app not callable'; "
        "sig = inspect.signature(create_app); "
        "assert 'db_path' in sig.parameters, f'signature {sig} missing db_path'"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert r.returncode == 0, (
        f"chronos.api.create_app(db_path=None) not importable: {combined(r)[:2000]}"
    )
    assert "Traceback" not in combined(r)


def test_setup_help_runs():
    """Chronos.md sec 8.1: chronos setup exists and its help runs."""
    r = run_cli("setup", "--help")
    assert r.returncode == 0, f"setup --help exit {r.returncode}: {combined(r)[:2000]}"
    assert "Traceback" not in combined(r)
    assert r.stdout.strip() != ""


def test_key_renew_runs_with_throwaway_db():
    """Chronos.md sec 3: chronos key-renew rotates the instance key."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "chronos.db")
        r = run_cli("key-renew", env_extra={"CHRONOS_DB": db})
        assert r.returncode == 0, f"key-renew exit {r.returncode}: {combined(r)[:2000]}"
        assert "Traceback" not in combined(r)
        assert (r.stdout.strip() + r.stderr.strip()).strip() != "", "key-renew produced no output"


def test_db_upgrade_runs_creates_schema_honours_chronos_db():
    """Phase-4 Done: db-upgrade completes, creates schema in the CHRONOS_DB file."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "cli.db")
        r = run_cli("db-upgrade", env_extra={"CHRONOS_DB": db})
        assert r.returncode == 0, f"db-upgrade exit {r.returncode}: {combined(r)[:2000]}"
        assert "Traceback" not in combined(r)
        assert os.path.isfile(db), "db-upgrade did not create $CHRONOS_DB file"
        assert os.path.getsize(db) > 0, "db-upgrade left $CHRONOS_DB empty"
        conn = sqlite3.connect(db)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        assert "nodes" in tables, f"schema missing nodes table: {sorted(tables)}"
        assert "events" in tables, f"schema missing events table: {sorted(tables)}"


def test_db_upgrade_honours_chronos_db_path():
    """Phase-4: db-upgrade must honour CHRONOS_DB (two paths -> two files)."""
    with tempfile.TemporaryDirectory() as tmp:
        db_a = os.path.join(tmp, "a.db")
        db_b = os.path.join(tmp, "b.db")
        ra = run_cli("db-upgrade", env_extra={"CHRONOS_DB": db_a})
        rb = run_cli("db-upgrade", env_extra={"CHRONOS_DB": db_b})
        assert ra.returncode == 0, f"db-upgrade A failed: {combined(ra)[:2000]}"
        assert rb.returncode == 0, f"db-upgrade B failed: {combined(rb)[:2000]}"
        assert os.path.isfile(db_a)
        assert os.path.isfile(db_b)
        assert os.path.getsize(db_a) > 0
        assert os.path.getsize(db_b) > 0


def test_db_upgrade_works_without_alembic_on_path():
    """Phase-4: db-upgrade must invoke alembic via current interpreter, not PATH lookup."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "nopath.db")
        env_extra = {"CHRONOS_DB": db, "PATH": "/nonexistent"}
        r = run_cli("db-upgrade", env_extra=env_extra)
        assert r.returncode == 0, (
            f"db-upgrade must not depend on PATH alembic (use sys.executable -m alembic): "
            f"{combined(r)[:2000]}"
        )
        assert "Traceback" not in combined(r)
        assert os.path.isfile(db)


def test_db_upgrade_schema_loads_vec0_extension():
    """Phase-4: migration must load sqlite-vec (schema creates a vec0 virtual table)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "vec.db")
        r = run_cli("db-upgrade", env_extra={"CHRONOS_DB": db})
        assert r.returncode == 0, f"db-upgrade exit {r.returncode}: {combined(r)[:2000]}"
        conn = sqlite3.connect(db)
        try:
            rows = list(
                conn.execute(
                    "SELECT name, sql FROM sqlite_master WHERE sql LIKE '%vec0%'"
                )
            )
        finally:
            conn.close()
        assert len(rows) == 1, f"expected exactly one vec0 virtual table, got {rows}"


def test_token_cost_removed_absent_or_clean_error():
    """Decisions 2026-10-05: token-cost removed completely; must be absent or error cleanly."""
    r = run_cli("token-cost")
    assert r.returncode != 0, "token-cost must not succeed: it was removed 2026-10-05"
    assert "Traceback" not in combined(r), f"token-cost error must be clean: {combined(r)[:2000]}"
    assert combined(r).strip() != "", "removed command must still explain itself"


def test_token_cost_not_in_help():
    """Decisions 2026-10-05: removed command must not be advertised in --help."""
    r = run_cli("--help")
    assert r.returncode == 0
    assert "token-cost" not in r.stdout, f"--help still advertises removed token-cost:\n{r.stdout[:2000]}"


def test_export_runs_and_emits_json_only():
    """Decisions Phase 4-2: chronos export format JSON only in v1 (CSV deferred)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "exp.db")
        up = run_cli("db-upgrade", env_extra={"CHRONOS_DB": db})
        assert up.returncode == 0, f"db-upgrade failed: {combined(up)[:2000]}"
        r = run_cli("export", env_extra={"CHRONOS_DB": db})
        assert r.returncode == 0, f"export exit {r.returncode}: {combined(r)[:2000]}"
        assert "Traceback" not in combined(r)
        assert r.stdout.strip() != "", "export produced no output"
        parsed = json.loads(r.stdout)
        assert isinstance(parsed, dict), f"export must emit a JSON object, got {type(parsed)}"


def test_export_help_has_no_csv():
    """Decisions Phase 4-2: export is JSON only; no CSV option."""
    r = run_cli("export", "--help")
    assert r.returncode == 0, f"export --help exit {r.returncode}: {combined(r)[:2000]}"
    assert "Traceback" not in combined(r)
    lowered = r.stdout.lower()
    assert "json" in lowered, f"export --help must mention JSON:\n{r.stdout[:2000]}"
    assert "csv" not in lowered, f"export must not offer CSV:\n{r.stdout[:2000]}"


def test_say_help_runs():
    """Chronos.md sec 9.2: chronos say exists; usage: echo ... | chronos say -"""
    r = run_cli("say", "--help")
    assert r.returncode == 0, f"say --help exit {r.returncode}: {combined(r)[:2000]}"
    assert "Traceback" not in combined(r)
    assert r.stdout.strip() != ""


def test_say_stdin_sentence_errors_cleanly_when_server_down():
    """Decisions Phase 4-3 + Chronos.md sec 9.2: say reads stdin sentence; errors + exit if server down."""
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "say.db")
        sentence = "schedule DB review tomorrow 4pm for 45 mins"
        r = run_cli(
            "say",
            "-",
            input_text=sentence + "\n",
            env_extra={
                "CHRONOS_DB": db,
                "CHRONOS_PORT": "9",
                "CHRONOS_HOST": "127.0.0.1",
            },
        )
        assert r.returncode != 0, (
            f"say with no server must exit non-zero, got 0: {r.stdout[:2000]}"
        )
        assert "Traceback" not in combined(r), f"say server-down error must be clean: {combined(r)[:2000]}"
        assert combined(r).strip() != "", "say must explain that the server is down"


def test_get_day_timer_briefing_help_each_runs():
    """Chronos.md sec 9.2 + decisions Phase 4-8: chronos get day|timer|briefing."""
    for sub in ["day", "timer", "briefing"]:
        r = run_cli("get", sub, "--help")
        assert r.returncode == 0, f"get {sub} --help exit {r.returncode}: {combined(r)[:2000]}"
        assert "Traceback" not in combined(r)
        assert r.stdout.strip() != "", f"get {sub} --help produced no output"


def test_get_lists_only_day_timer_briefing():
    """Decisions Phase 4-8: CLI get subcommands only day/timer/briefing per sec 9.2."""
    r = run_cli("get", "--help")
    assert r.returncode == 0, f"get --help exit {r.returncode}: {combined(r)[:2000]}"
    assert "Traceback" not in combined(r)
    out = r.stdout
    assert "day" in out
    assert "timer" in out
    assert "briefing" in out
    assert "week" not in out, f"get must not offer week:\n{out[:2000]}"
    assert "month" not in out, f"get must not offer month:\n{out[:2000]}"


def test_get_rejects_other_subcommands_cleanly():
    """Decisions Phase 4-8: no other get subcommands; unknown ones error without traceback."""
    r = run_cli("get", "week")
    assert r.returncode != 0, "get week must fail: only day|timer|briefing exist"
    assert "Traceback" not in combined(r), f"bad get subcommand must be clean: {combined(r)[:2000]}"


def test_output_is_terse_pipe_safe_no_traceback():
    """Chronos.md sec 9.2: terse output, no prompts, safe to pipe; Layer 1: no traceback."""
    r = run_cli("get", "--help")
    assert r.returncode == 0
    text = combined(r)
    assert "Traceback" not in text
    assert 'File "' not in text, "pipe-safe output must not contain interpreter frames"
    assert r.stdout.strip() != ""
    assert len(r.stdout.splitlines()) >= 3


def test_bad_input_never_tracebacks():
    """errors-and-test-proposal.md Layer 1: no traceback on any input."""
    r = run_cli("get", "bogus-subcommand-xyz")
    assert r.returncode != 0
    assert "Traceback" not in combined(r)
    assert combined(r).strip() != ""
