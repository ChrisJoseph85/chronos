"""Phase 6 Termux + CI spec tests.

Spec: docs/server/Chronos.md §8.1 (targets), §11 (doze/wake-lock, /api/health,
  ~274 MB embedding model announced with progress, never silent),
  docs/server/API.md Startup (proot-distro /usr/bin/python3) + Docker CI note,
  docs/server/phases/phase-6-deploy.md Termux/CI/scripts,
  docs/server/decisions.md 2026-10-03 Phase 6 rulings 3-5/7/8
  (embedding progress, termux pkgs, windows untested, backup scripts/backup.sh,
  docs/docker.md + docs/termux.md),
  docs/server/decisions.md 2026-10-05 freeze §5 (smoke.sh gate).

Honesty: no Android/Termux pkg, no systemd, no Docker daemon here — on-device
behaviours skip with a reason, never claim pass.
"""

import os
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TERMUX_SH = REPO_ROOT / "scripts" / "termux.sh"
BACKUP_SH = REPO_ROOT / "scripts" / "backup.sh"
SMOKE_SH = REPO_ROOT / "scripts" / "smoke.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GITIGNORE = REPO_ROOT / ".gitignore"
TERMUX_MD = REPO_ROOT / "docs" / "termux.md"
ALT_TERMUX_MD = REPO_ROOT / "docs" / "server" / "termux.md"
DOCKER_MD = REPO_ROOT / "docs" / "docker.md"
ALT_DOCKER_MD = REPO_ROOT / "docs" / "server" / "docker.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required file: {path}"
    return path.read_text(encoding="utf-8")


def _resolve_md(primary: Path, alt: Path) -> Path:
    if primary.is_file():
        return primary
    return alt


def test_termux_script_exists_and_executable():
    """Spec Chronos §8.1 target 2 + phase-6-deploy.md Termux: install script."""
    assert TERMUX_SH.is_file(), f"missing required file: {TERMUX_SH}"
    mode = TERMUX_SH.stat().st_mode
    assert mode & stat.S_IXUSR != 0, f"{TERMUX_SH} is not executable"
    assert os.access(str(TERMUX_SH), os.X_OK), f"{TERMUX_SH} not executable"


def test_termux_wake_lock_before_serve():
    """Spec Chronos §11: termux-wake-lock BEFORE starting the server."""
    text = _read(TERMUX_SH)
    wake_idx = text.find("termux-wake-lock")
    assert wake_idx >= 0, "scripts/termux.sh must call termux-wake-lock"
    serve_idx = text.find("chronos serve")
    if serve_idx < 0:
        serve_idx = text.find("chronos")
    assert serve_idx >= 0, "scripts/termux.sh must start chronos serve"
    assert wake_idx < serve_idx, (
        "termux-wake-lock must precede chronos serve (doze kills otherwise)"
    )


def test_termux_script_has_no_systemd_or_sudo():
    """Spec Chronos §8.1: no systemd, no root required."""
    text = _read(TERMUX_SH)
    assert "systemctl" not in text, "termux script must not require systemd"
    assert "systemd" not in text, "termux script must not require systemd"


def test_termux_documents_exact_user_commands():
    """Spec phase-6-deploy.md Termux: document the exact commands a user types."""
    md_path = _resolve_md(TERMUX_MD, ALT_TERMUX_MD)
    text = _read(md_path)
    assert "termux-wake-lock" in text, f"{md_path} must document termux-wake-lock"
    assert "chronos serve" in text, f"{md_path} must document chronos serve"


def test_embedding_download_announced_with_progress():
    """Spec Chronos §11 + decisions.md ruling 3: ~274 MB announced, never silent."""
    md_path = _resolve_md(TERMUX_MD, ALT_TERMUX_MD)
    md_text = _read(md_path)
    assert "274" in md_text, f"{md_path} must announce the ~274 MB model"
    assert "progress" in md_text.lower(), f"{md_path} must mention progress"
    script_text = _read(TERMUX_SH)
    assert "274" in script_text, "termux script must announce the 274 MB download"
    assert "progress" in script_text.lower(), (
        "termux script code path must hook download progress, never silent"
    )


def test_docs_state_what_was_and_was_not_verified():
    """Spec phase-6-deploy.md Done means: docs state verified vs not verified."""
    termux_path = _resolve_md(TERMUX_MD, ALT_TERMUX_MD)
    docker_path = _resolve_md(DOCKER_MD, ALT_DOCKER_MD)
    termux_lower = _read(termux_path).lower()
    docker_lower = _read(docker_path).lower()
    assert "verified" in termux_lower, f"{termux_path} must state what was verified"
    assert "not verified" in termux_lower, (
        f"{termux_path} must honestly state what was NOT verified here"
    )
    assert "verified" in docker_lower, f"{docker_path} must state what was verified"
    assert "not verified" in docker_lower, (
        f"{docker_path} must honestly state what was NOT verified here"
    )


def _all_workflow_text() -> str:
    assert WORKFLOWS.is_dir(), f"missing required dir: {WORKFLOWS}"
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert len(files) > 0, f"no workflow files in {WORKFLOWS}"
    chunks = []
    for path in files:
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_ci_runs_ruff_pytest_docker_on_clean_checkout():
    """Spec phase-6-deploy.md CI: ruff + pytest + docker build, no local state."""
    combined = _all_workflow_text()
    assert "ruff" in combined, "CI workflows must run ruff check"
    assert "pytest" in combined, "CI workflows must run the pytest suite"
    assert "docker" in combined, "CI workflows must build the Docker image"
    gitignore_text = _read(GITIGNORE)
    assert ".env" in gitignore_text, ".env must be gitignored (clean checkout has none)"


def test_backup_script_timestamped_copies():
    """Spec decisions.md ruling 7 + Chronos §2: backup is timestamped file copies."""
    assert BACKUP_SH.is_file(), f"missing required file: {BACKUP_SH}"
    mode = BACKUP_SH.stat().st_mode
    assert mode & stat.S_IXUSR != 0, f"{BACKUP_SH} is not executable"
    text = _read(BACKUP_SH)
    assert "cp" in text, "scripts/backup.sh must copy the SQLite file"
    assert "date" in text, "scripts/backup.sh copies must be timestamped via date"


def test_smoke_uses_venv_throwaway_db_and_asserts_auth_flow():
    """Spec decisions.md 2026-10-05 freeze §5: smoke.sh gate behaviour."""
    text = _read(SMOKE_SH)
    assert ".venv/bin/chronos" in text, "smoke.sh must use .venv/bin/chronos"
    assert "/api/health" in text, "smoke.sh must poll /api/health"
    assert "401" in text, "smoke.sh must assert 401 no-key / 401 bad-key"
    assert "409" in text, "smoke.sh must assert second timer -> 409"
    assert "timer" in text, "smoke.sh must exercise the timer for the 409 case"
    assert "$CHRONOS_DB" not in text, (
        "smoke.sh must use a throwaway DB, never $CHRONOS_DB"
    )


def test_termux_on_device_install_requires_android():
    """Spec Chronos §8.1 target 2: Termux install runs on Android, not here."""
    is_termux = Path("/data/data/com.termux").exists()
    has_pkg = False
    try:
        import shutil

        has_pkg = shutil.which("pkg") is not None
    except OSError:
        has_pkg = False
    if is_termux is False and has_pkg is False:
        pytest.skip("no Termux/Android on this host (no /data/data/com.termux, no pkg)")
    text = _read(TERMUX_SH)
    assert "termux-wake-lock" in text
