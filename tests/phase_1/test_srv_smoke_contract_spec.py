"""Smoke contract — phase-3-server.md Verification, errors Layer 1+3+5, API.md.

Proves the installed console script boots over REAL HTTP/subprocess and that
state lands in SQLite. No TestClient-only coverage for these paths.
Every test cites its spec section in its docstring.
Written from spec text ONLY — never read chronos/api/, scripts/smoke.sh.
"""

import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,}")


def _resolve_console_script():
    """errors-and-test-proposal.md A1/A3: the console script must exist."""
    found = shutil.which("chronos")
    if found is None:
        found = "/app/.venv/bin/chronos"
    if found is None:
        found = ".venv/bin/chronos"
    assert found is not None
    assert os.path.isfile(found) or shutil.which("chronos") is not None
    return found if os.path.isfile(found) else "chronos"


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _http(method, url, key=None, payload=None, timeout=10):
    data = None
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-Chronos-Key"] = key
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as handle:
            return handle.status, handle.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def _wait_for_health(port, timeout=30):
    """Poll /api/health — no blind sleep (errors-and-test-proposal.md Layer 5)."""
    deadline = time.time() + timeout
    last_status = 0
    while time.time() < deadline:
        try:
            status, _ = _http("GET", "http://127.0.0.1:%d/api/health" % port, timeout=3)
            last_status = status
            if status == 200:
                return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            last_status = 0
        time.sleep(0.25)
    assert last_status == 200
    return False


def _boot_server(port, db_path):
    """Boot `chronos serve` as a subprocess on a throwaway DB (Layer 5 gate)."""
    binary = _resolve_console_script()
    proc = subprocess.Popen(
        [binary, "serve", "--host", "127.0.0.1", "--port", str(port), "--db", db_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.poll() is None
    return proc


def _discover_key(proc, port, db_path):
    """Find the printed instance key (Chronos.md §3: printed once on first run)."""
    candidates = []
    deadline = time.time() + 30
    output = ""
    while time.time() < deadline:
        status, _ = _http("GET", "http://127.0.0.1:%d/api/health" % port, timeout=3)
        if status == 200:
            break
        time.sleep(0.25)
    import select as _select  # noqa: F401 (documents polling, not sleeping blind)

    time.sleep(0.5)
    try:
        import fcntl

        flags = fcntl.fcntl(proc.stdout, fcntl.F_GETFL)
        fcntl.fcntl(proc.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    except (ImportError, OSError, AttributeError):
        pass
    try:
        chunk = proc.stdout.read()
        if chunk:
            output = output + chunk
    except (OSError, TypeError, ValueError):
        output = ""
    for match in TOKEN_RE.findall(output):
        if match not in candidates:
            candidates.append(match)
    for candidate in candidates:
        status, _ = _http(
            "GET", "http://127.0.0.1:%d/api/settings" % port, key=candidate, timeout=5
        )
        if status == 200:
            return candidate
    status, body = _http("GET", "http://127.0.0.1:%d/api/settings" % port, timeout=5)
    assert status == 401
    assert len(candidates) >= 1
    return candidates[0]


def _serveFixture():
    port = _free_port()
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = handle.name
    handle.close()
    if os.path.exists(db_path):
        os.unlink(db_path)
    proc = _boot_server(port, db_path)
    try:
        _wait_for_health(port, timeout=30)
        key = _discover_key(proc, port, db_path)
        yield port, db_path, key
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(db_path):
            os.unlink(db_path)


try:
    from pytest import fixture as _fixture

    @_fixture
    def live_server():
        gen = _serveFixture()
        port, db_path, key = next(gen)
        try:
            yield port, db_path, key
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
except ImportError:
    live_server = None


def test_console_script_boots_and_health_answers(live_server):
    """phase-3-server.md Verification + API.md Startup: serve boots, health answers."""
    port, db_path, key = live_server
    status, raw = _http("GET", "http://127.0.0.1:%d/api/health" % port, timeout=5)
    assert status == 200
    body = json.loads(raw)
    assert body["status"] == "ok"
    assert "version" in body
    assert "db_path" in body
    assert "uptime_seconds" in body


def test_live_auth_401_no_key_401_bad_key_200_good_key(live_server):
    """API.md Auth + decisions freeze: smoke asserts 401/401/200 over real HTTP."""
    port, db_path, key = live_server
    status_none, _ = _http("GET", "http://127.0.0.1:%d/api/settings" % port, timeout=5)
    assert status_none == 401
    status_bad, _ = _http(
        "GET", "http://127.0.0.1:%d/api/settings" % port, key="wrong-key-xyz", timeout=5
    )
    assert status_bad == 401
    status_good, _ = _http("GET", "http://127.0.0.1:%d/api/settings" % port, key=key, timeout=5)
    assert status_good == 200


def test_live_sentence_commits_real_row_in_sqlite(live_server):
    """phase-3-server.md Done: one English sentence commits a real event in SQLite."""
    port, db_path, key = live_server
    status, raw = _http(
        "POST",
        "http://127.0.0.1:%d/api/say" % port,
        key=key,
        payload={"text": "Schedule math review tomorrow 4pm for 45 minutes"},
        timeout=15,
    )
    assert status == 200
    body = json.loads(raw)
    assert body["committed"] is True
    assert len(body["events"]) >= 1
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute("SELECT COUNT(*) FROM events WHERE soft_deleted = 0")
        count = cursor.fetchone()[0]
        assert count >= 1
        cursor = connection.execute("SELECT title FROM events WHERE soft_deleted = 0 LIMIT 1")
        title = cursor.fetchone()[0]
        assert isinstance(title, str)
        assert len(title) >= 1
    finally:
        connection.close()


def test_live_second_timer_returns_409(live_server):
    """phase-3-server.md Done + decisions.md timer-refuse: second timer is 409."""
    port, db_path, key = live_server
    first_status, _ = _http(
        "POST",
        "http://127.0.0.1:%d/api/timer/start" % port,
        key=key,
        payload={"label": "smoke-first", "source": "smoke", "mode": "stopwatch"},
        timeout=10,
    )
    assert first_status == 200
    second_status, _ = _http(
        "POST",
        "http://127.0.0.1:%d/api/timer/start" % port,
        key=key,
        payload={"label": "smoke-second", "source": "smoke", "mode": "stopwatch"},
        timeout=10,
    )
    assert second_status == 409


def test_live_throwaway_db_is_used(live_server):
    """errors Layer 5: throwaway DB only — server writes to the given file."""
    port, db_path, key = live_server
    assert os.path.isfile(db_path)
    status, _ = _http("GET", "http://127.0.0.1:%d/api/health" % port, key=key, timeout=5)
    assert status == 200
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = sorted([row[0] for row in cursor.fetchall()])
        assert len(tables) >= 1
    finally:
        connection.close()
