"""Phase 6 packaging spec tests.

Spec: docs/server/Chronos.md §8.1 (process/targets), §12 (out of scope),
  docs/server/API.md Startup (venv /usr/bin/python3, pip install -e .[dev],
  chronos serve --host/--port/--db, curl /api/health),
  docs/server/phases/phase-6-deploy.md Packaging,
  docs/server/decisions.md 2026-10-05 backend-only freeze (token-cost removed).

Rule: execute via subprocess, never grep-only — every CLI assertion below
runs --help/--version in a subprocess.
"""

import importlib.metadata
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"

EXPECTED_COMMANDS = ["serve", "setup", "key-renew", "db-upgrade", "export", "say", "get"]


def _chronos_bin() -> str:
    found = shutil.which("chronos")
    if found is not None:
        return found
    for candidate in (
        REPO_ROOT / ".venv" / "bin" / "chronos",
        Path(".venv") / "bin" / "chronos",
    ):
        if candidate.is_file():
            return str(candidate)
    return "chronos"


def _run_chronos(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_chronos_bin(), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


def test_pyproject_has_project_table_and_chronos_script():
    """Spec Chronos §8.1 + phase-6-deploy.md Packaging: pip install -e . works."""
    assert PYPROJECT.is_file(), f"missing {PYPROJECT} — pip install -e . cannot work"
    with open(PYPROJECT, "rb") as fh:
        data = tomllib.load(fh)
    assert "project" in data, "[project] table missing in pyproject.toml"
    project = data["project"]
    assert "name" in project, "[project] name missing in pyproject.toml"
    assert "version" in project, "[project] version missing in pyproject.toml"
    scripts = project.get("scripts", {})
    assert "chronos" in scripts, "[project.scripts] chronos entry missing"


def test_version_single_sourced_package_vs_cli():
    """Spec phase-6-deploy.md Packaging: version single-sourced, package == CLI."""
    dist_version = importlib.metadata.version("chronos")
    assert dist_version != "", "installed distribution version is empty"
    proc = _run_chronos("--version")
    assert proc.returncode == 0, f"chronos --version failed: {proc.stderr}"
    combined = proc.stdout + proc.stderr
    assert dist_version in combined, (
        f"CLI --version output {combined!r} does not report "
        f"installed version {dist_version!r}"
    )


def test_chronos_help_lists_required_commands():
    """Spec Chronos §8.1 + §9.2 CLI: serve|setup|key-renew|db-upgrade|export|say|get."""
    proc = _run_chronos("--help")
    assert proc.returncode == 0, f"chronos --help failed: {proc.stderr}"
    combined = proc.stdout + proc.stderr
    for cmd in EXPECTED_COMMANDS:
        assert cmd in combined, f"chronos --help missing command {cmd!r}: {combined!r}"


def test_chronos_serve_help_shows_db_host_port():
    """Spec API.md Startup: chronos serve --host/--port/--db; Chronos §8.1 process."""
    proc = _run_chronos("serve", "--help")
    assert proc.returncode == 0, f"chronos serve --help failed: {proc.stderr}"
    combined = proc.stdout + proc.stderr
    assert "--db" in combined, f"serve --help missing --db: {combined!r}"
    assert "--host" in combined, f"serve --help missing --host: {combined!r}"
    assert "--port" in combined, f"serve --help missing --port: {combined!r}"


def test_no_token_cost_in_help():
    """Spec decisions.md 2026-10-05 freeze §2 + Chronos §12: token-cost removed."""
    proc = _run_chronos("--help")
    assert proc.returncode == 0, f"chronos --help failed: {proc.stderr}"
    combined = proc.stdout + proc.stderr
    assert "token-cost" not in combined, (
        f"chronos --help must not list token-cost (removed): {combined!r}"
    )
    assert "token_cost" not in combined, (
        f"chronos --help must not list token_cost (removed): {combined!r}"
    )


def test_version_consistency_metadata_matches_module():
    """Spec phase-6-deploy.md Packaging: package and CLI report the same number."""
    dist_version = importlib.metadata.version("chronos")
    proc = _run_chronos("--version")
    assert proc.returncode == 0, f"chronos --version failed: {proc.stderr}"
    cli_output = (proc.stdout + proc.stderr).strip()
    assert dist_version in cli_output, (
        f"version mismatch: dist {dist_version!r} not in CLI output {cli_output!r}"
    )
    assert sys.version_info.major == 3, "packaging tests require Python 3"
