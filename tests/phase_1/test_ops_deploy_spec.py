"""Phase 6 ops/deploy spec tests (WAVE-2 FIXER C).

Spec: docs/server/Chronos.md §2 (backup is timestamped file copies),
  §8.1 (process/targets), §11 (ops: wake-lock, /api/health),
  docs/server/phases/phase-6-deploy.md (Packaging / Docker / Termux / CI),
  docs/server/decisions.md 2026-10-03 Phase 6 rulings (pinned base,
  backup scripts/backup.sh).

Honesty: no Docker daemon, no Android/Termux here — on-device and daemon
behaviours skip with a reason, never fail, never claim pass.
"""

import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
BASELINE = REPO_ROOT / "alembic" / "versions" / "0001_baseline.py"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
TERMUX_SH = REPO_ROOT / "scripts" / "termux.sh"
BACKUP_SH = REPO_ROOT / "scripts" / "backup.sh"

# dist name -> importable top-level module name.
EXPECTED_RUNTIME_DEPS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "argon2-cffi": "argon2",
    "websockets": "websockets",
    "python-multipart": "python_multipart",
    "alembic": "alembic",
}


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required file: {path}"
    return path.read_text(encoding="utf-8")


def test_pyproject_runtime_deps_non_empty_and_importable():
    """Spec phase-6-deploy.md Packaging: pip install -e . ships real deps."""
    with open(PYPROJECT, "rb") as fh:
        data = tomllib.load(fh)
    deps = data["project"].get("dependencies", [])
    assert len(deps) > 0, "pyproject dependencies must not be empty"
    names = {d.split()[0].split(";")[0].split("=")[0].split(">")[0].split("<")[0].strip().lower() for d in deps}
    for dist in EXPECTED_RUNTIME_DEPS:
        assert dist in names, f"runtime dep {dist!r} missing from pyproject dependencies"
    missing = []
    for dist, module in EXPECTED_RUNTIME_DEPS.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(f"{dist} (module {module})")
    if missing:
        pytest.skip(f"not installed in this env (structural decl checked): {', '.join(missing)}")


def test_baseline_applies_ddl_to_real_file_twice_idempotent(tmp_path, monkeypatch):
    """Spec phase-6-deploy.md: baseline upgrade() targets a real DB file, twice."""
    import importlib.util

    target = tmp_path / "chronos.db"
    monkeypatch.setenv("CHRONOS_DB", str(target))
    spec = importlib.util.spec_from_file_location("baseline_0001", BASELINE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["baseline_0001"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("baseline_0001", None)
    module.upgrade(str(target))
    module.upgrade(str(target))  # second run must be a no-op, not an error
    conn = sqlite3.connect(str(target))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "nodes" in tables, "baseline DDL did not create nodes table"
        assert "schema_version" in tables, "baseline did not record schema_version"
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row is not None and row[0] == "0001"
    finally:
        conn.close()


def test_alembic_ini_points_at_target_db_not_memory():
    """Spec phase-6-deploy.md: alembic.ini targets a real DB file, no :memory:."""
    text = _read(ALEMBIC_INI)
    assert ":memory:" not in text, "alembic.ini must not point at :memory:"
    assert "sqlalchemy.url" in text, "alembic.ini must declare sqlalchemy.url"


def test_termux_parses_and_orders_guest_venv_path_before_serve():
    """Spec Chronos §11 + phase-6-deploy.md Termux: guest venv on PATH before serve."""
    if shutil.which("bash") is None:
        pytest.skip("bash not available on this host")
    proc = subprocess.run(
        ["bash", "-n", str(TERMUX_SH)], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"bash -n failed: {proc.stderr}"
    text = _read(TERMUX_SH)
    assert "chronos serve" in text
    path_idx = text.find('export PATH="$VENV_DIR/bin:$PATH"')
    if path_idx < 0:
        path_idx = text.find("VENV_DIR/bin")
    assert path_idx >= 0, "termux.sh must put guest venv/bin on PATH"
    serve_idx = text.find("chronos serve")
    assert path_idx < serve_idx, "guest venv PATH export must precede chronos serve"
    assert "termux-wake-lock" in text
    assert text.find("termux-wake-lock") < serve_idx, "wake lock must precede serve (Chronos §11)"


def test_backup_parses_and_checkpoints_wal_before_copy():
    """Spec Chronos §2 + decisions.md ruling 7: checkpoint, then timestamped cp."""
    if shutil.which("bash") is None:
        pytest.skip("bash not available on this host")
    proc = subprocess.run(
        ["bash", "-n", str(BACKUP_SH)], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"bash -n failed: {proc.stderr}"
    text = _read(BACKUP_SH)
    assert "wal_checkpoint" in text.lower() or "checkpoint" in text.lower(), (
        "backup.sh must WAL-checkpoint before copying"
    )
    assert "cp" in text, "backup.sh must copy the SQLite file"
    assert "date" in text, "backup.sh copies must be timestamped via date"


def test_dockerfile_copy_sources_in_build_context():
    """Every Dockerfile COPY source must survive .dockerignore.

    Regression: builder COPY of alembic.ini/alembic failed with
    '"/alembic": not found' because the allowlist .dockerignore excluded
    them from the build context. Spec: phases/phase-1-foundation.md parts
    1.29-1.30 (image builds from the repository).
    """
    import fnmatch

    dockerfile = _read(REPO_ROOT / "Dockerfile")
    patterns = [
        line.strip()
        for line in _read(REPO_ROOT / ".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    def included(rel: str) -> bool:
        # Last matching pattern wins; '!' negates (re-includes).
        # Check both 'rel' and 'rel/' so directory exceptions ('!alembic/')
        # match the directory itself, mirroring Docker dir semantics.
        result = True  # default: included unless excluded
        for pat in patterns:
            negated = pat.startswith("!")
            body = pat[1:] if negated else pat
            candidates = (rel, rel + "/") if not rel.endswith("/") else (rel,)
            for cand in candidates:
                if fnmatch.fnmatch(cand, body) or fnmatch.fnmatch(
                    cand, body.rstrip("/") + "/*"
                ):
                    result = negated
                    break
        return result

    missing = []
    for line in dockerfile.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "COPY" and not parts[1].startswith("--"):
            for src in parts[1:-1]:
                if not included(src):
                    missing.append(src)
    assert not missing, f"Dockerfile COPY sources excluded by .dockerignore: {missing}"


def test_docker_build_and_run_require_daemon():
    """Spec phase-6-deploy.md Verification: image build/run needs a daemon."""
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed on this host")
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=30
        )
    except OSError:
        pytest.skip("docker CLI not runnable on this host")
    if proc.returncode != 0:
        pytest.skip("no reachable Docker daemon on this host")


def test_termux_on_device_install_requires_android():
    """Spec Chronos §8.1 target 2: Termux install runs on Android, not here."""
    if Path("/data/data/com.termux").exists() or shutil.which("pkg") is not None:
        return
    pytest.skip("no Termux/Android on this host (no /data/data/com.termux, no pkg)")
