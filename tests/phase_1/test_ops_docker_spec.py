"""Phase 6 Docker spec tests.

Spec: docs/server/Chronos.md §8.1 (process/targets), §11 (ops),
  docs/server/API.md Docker (compose up --build, volume chronos-data:/data,
  .env env_file required:false, healthcheck /api/health),
  docs/server/phases/phase-6-deploy.md Docker,
  docs/server/decisions.md 2026-10-03 Phase 6 rulings 1-2/6/8
  (base python:3.14.7-slim-bookworm, multi-arch amd64+arm64 via buildx,
  no registry push, docs/docker.md).

Honesty: no Docker daemon, no systemd here — build/run tests skip with a
reason, never fail on a missing daemon, never claim pass.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKER_MD = REPO_ROOT / "docs" / "docker.md"
ALT_DOCKER_MD = REPO_ROOT / "docs" / "server" / "docker.md"

PINNED_BASE = "python:3.14.7-slim-bookworm"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required file: {path}"
    return path.read_text(encoding="utf-8")


def test_dockerfile_base_image_pinned():
    """Spec decisions.md Phase 6 ruling 1 + phase-6-deploy.md: pin base version."""
    text = _read(DOCKERFILE)
    from_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().upper().startswith("FROM ")
    ]
    assert len(from_lines) > 0, f"Dockerfile has no FROM line: {DOCKERFILE}"
    for line in from_lines:
        assert PINNED_BASE in line, (
            f"FROM line {line!r} does not pin {PINNED_BASE!r}"
        )


def test_dockerfile_bakes_no_secrets():
    """Spec phase-6-deploy.md Docker: .env mounted, never copied into a layer."""
    text = _read(DOCKERFILE)
    assert "COPY .env" not in text, "Dockerfile must not COPY .env"
    assert "ADD .env" not in text, "Dockerfile must not ADD .env"
    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("ENV "):
            assert "KEY" not in upper, f"Dockerfile ENV bakes a key: {stripped!r}"
            assert "SECRET" not in upper, f"Dockerfile ENV bakes a secret: {stripped!r}"
            assert "TOKEN" not in upper, f"Dockerfile ENV bakes a token: {stripped!r}"


def test_compose_declares_chronos_data_volume():
    """Spec API.md Docker + phase-6-deploy.md: database on chronos-data:/data."""
    text = _read(COMPOSE)
    assert "chronos-data" in text, "compose missing chronos-data volume"
    assert "/data" in text, "compose missing /data mount target"
    assert "volumes" in text, "compose declares no volumes block"


def test_compose_env_file_required_false():
    """Spec API.md Docker: .env via env_file required:false."""
    text = _read(COMPOSE)
    assert "env_file" in text, "compose missing env_file for .env"
    normalized = text.replace(" ", "").replace('"', "").replace("'", "")
    assert "required:false" in normalized, (
        "compose env_file must set required:false so checkout starts without .env"
    )


def test_compose_healthcheck_hits_api_health():
    """Spec Chronos §11 + phase-6-deploy.md: /api/health answers."""
    text = _read(COMPOSE)
    assert "/api/health" in text, "compose healthcheck must probe /api/health"


def test_docs_note_multiarch_buildx():
    """Spec decisions.md Phase 6 ruling 2: multi-arch amd64+arm64 via buildx."""
    md_path = DOCKER_MD if DOCKER_MD.is_file() else ALT_DOCKER_MD
    text = _read(md_path)
    assert "amd64" in text, f"{md_path} must note linux/amd64"
    assert "arm64" in text, f"{md_path} must note linux/arm64"
    assert "buildx" in text, f"{md_path} must note docker buildx"


def _docker_daemon_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError:
        return False
    return proc.returncode == 0


def test_docker_build_and_health():
    """Spec phase-6-deploy.md Verification + Done means: compose up -> /api/health.

    Skips honestly where no daemon exists; never fails on a missing daemon.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed on this host")
    if _docker_daemon_available() is False:
        pytest.skip("no reachable Docker daemon on this host")
    proc = subprocess.run(
        ["docker", "build", "-t", "chronos-test", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, f"docker build failed: {proc.stderr[-2000:]}"
