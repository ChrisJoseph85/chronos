# Phase 6 — Interface Proposal: Deployment (Termux, Docker, packaging, CI)

**Status:** FROZEN — Phase 6 proposal approved
**Manager review:** All 8 ambiguities ruled on and approved. See `docs/decisions.md`.  
**Author:** Phase-6 Proposer  
**Date:** 2026-10-03  
**Spec source:** `docs/Chronos.md` §8.1 (process and targets), §11 (operational notes), §12 (out of scope)  
**Phase doc:** `docs/phases/phase-6-deploy.md`  
**Frozen contracts:** `docs/proposals/phase-1-contracts.md`

---

## 0. Scope and principles

This document proposes the complete interface surface for Phase 6 — everything
needed to build, ship, and run the Chronos server on all three targets (§8.1):
Linux desktop/laptop, Termux on Android, and Windows (best effort).

It covers:

- **A.** Dockerfile — base image, dependencies, entrypoint, volume mounts.
- **B.** Docker Compose — services, volumes, environment, ports.
- **C.** Termux support — install/start/stop script, wake-lock, health, embedding download.
- **D.** Packaging — `pyproject.toml`, entry points, single-sourced version.
- **E.** CI — lint + test workflow, Docker build workflow.
- **F.** Deploy scripts — `scripts/` layout and responsibilities.
- **G.** File layout — every file with purpose and exports.

**Principles:**

1. The server is a plain `chronos serve` process — no systemd, no root, no OS
   timezone configuration (§8.1).
2. The database is one SQLite file. Copy the file and you have a backup (§2).
   The container must not break that story.
3. No secret is ever baked into an image layer. `.env` is mounted or passed in,
   never committed and never copied into a layer (§8.1, phase doc).
4. The image is small and reproducible; the base image version is pinned (§8.1,
   phase doc).
5. `/api/health` is the readiness probe and the client's "server is down"
   signal (§11).
6. The embedding model (~274 MB) downloads on first use. The download is
   announced with progress and never happens silently inside a request (§11).
7. CI must pass on a clean checkout — no reliance on a developer's local state
   or `.env` (§8.1, phase doc).

---

## A. Dockerfile

**Spec:** §8.1 (process and targets), §11 (operational notes), phase doc §"Behaviour the tests must pin" → Docker.

### A.1 Base image

| Decision | Value | Spec |
|---|---|---|
| Base image | `python:3.14-slim` | §8.1 — Python + FastAPI; phase doc — "pin the base image version" |
| Pinned tag | `python:3.14.7-slim-bookworm` | Phase doc — "pin the base image version" |
| Architecture | Multi-arch (linux/amd64, linux/arm64) | §8.1 — Linux desktop + Termux on Android (aarch64) |

**Rationale:** `python:3.14-slim` is the smallest official Python image that
includes the C toolchain needed to build `sqlite-vec` wheels. The full tag
`python:3.14.7-slim-bookworm` is pinned to a specific patch release so builds
are reproducible. Multi-arch is required because the build host is Fedora 44
aarch64 (§8.1) and the primary target is a phone.

### A.2 Build stages

The Dockerfile uses a multi-stage build to keep the final image small.

```
Stage 1: builder
  - FROM python:3.14.7-slim-bookworm
  - Install build-essential (gcc, g++, make) for compiling sqlite-vec
  - COPY pyproject.toml README.md ./
  - COPY chronos/ ./chronos/
  - RUN pip install --no-cache-dir .
  - The builder stage is discarded; only the installed site-packages carry forward.

Stage 2: runtime
  - FROM python:3.14.7-slim-bookworm
  - COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
  - COPY --from=builder /usr/local/bin/chronos /usr/local/bin/chronos
  - No build-essential in the final image.
```

**Rationale:** `sqlite-vec` ships as a source distribution that requires a C
compiler. The builder stage compiles it; the runtime stage carries only the
compiled `.so` and the Python packages. This keeps the final image ~200 MB
smaller than a single-stage build.

### A.3 Environment variables

| Variable | Default | Purpose | Spec |
|---|---|---|---|
| `PYTHONUNBUFFERED` | `1` | Unbuffered stdout/stderr so logs appear immediately | Operational best practice |
| `PYTHONDONTWRITEBYTECODE` | `1` | No `.pyc` files in the image | Keeps image small |
| `CHRONOS_DB` | `/data/chronos.db` | Database path | §2 — one SQLite file |
| `CHRONOS_WEB` | `1` | Serve the Web HUD; `0` = headless API only | §8.1 — `--no-web` / `CHRONOS_WEB=0` |

### A.4 Volume mounts

| Mount | Purpose | Spec |
|---|---|---|
| `/data` | Database file lives here | §2 — "copy the file and you have a backup"; phase doc — "the database lives on a volume" |

The `VOLUME ["/data"]` instruction creates an anonymous volume if none is
mounted. In Docker Compose (§B), a named volume `chronos-data` is mounted
there instead.

### A.5 Entrypoint and command

```dockerfile
ENTRYPOINT ["chronos"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
```

**Spec:** §8.1 — `chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]`.

The entrypoint is the `chronos` console script (§D). The default command starts
the server on `0.0.0.0:8080`. Override with `docker run chronos serve --port 9000`
or `docker run chronos db-upgrade`.

### A.6 Health check

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status==200 else 1)"
```

**Spec:** §11 — "`/api/health` exists so a client can show a clear 'server is
down' state instead of a spinner that never resolves."

The health check hits `/api/health` (§8.2 — the only unauthenticated route).
`start-period=10s` gives the server time to boot and run migrations before the
first check.

### A.7 Exposed port

```dockerfile
EXPOSE 8080
```

**Spec:** §8.1 — default port 8080.

### A.8 What the image does NOT contain

- No `.env` file (§8.1, phase doc — "no secret is baked into an image layer").
- No database file (§2 — the database lives on a volume).
- No build tools (build-essential is in the builder stage only).
- No `.git` directory (excluded by `.dockerignore`).
- No `tests/`, `docs/`, `scripts/` (excluded by `.dockerignore`).

### A.9 Build and run commands

```bash
# Build
docker build -t chronos .

# Run with an anonymous volume
docker run --rm -p 8080:8080 -v chronos-data:/data chronos

# Run with a bind mount (development)
docker run --rm -p 8080:8080 -v $(pwd)/data:/data chronos

# Run headless
docker run --rm -p 8080:8080 -e CHRONOS_WEB=0 -v chronos-data:/data chronos
```

---

## B. Docker Compose

**Spec:** §8.1, phase doc §"Behaviour the tests must pin" → Docker.

### B.1 Services

```yaml
services:
  chronos:
    build: .
    image: chronos:latest
    container_name: chronos
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - chronos-data:/data
    environment:
      CHRONOS_DB: /data/chronos.db
      CHRONOS_WEB: "1"
    env_file:
      - path: .env
        required: false
```

### B.2 Volumes

```yaml
volumes:
  chronos-data:
```

**Spec:** §2 — "copy the file and you have a backup"; phase doc — "the database
lives on a volume, so the container can be replaced without losing data."

The named volume `chronos-data` is created by Docker Compose on first `up` and
survives `docker compose down`. To back up the database:

```bash
docker compose exec chronos cp /data/chronos.db /data/chronos-backup.db
# or from the host:
docker cp chronos:/data/chronos.db ./chronos-backup.db
```

### B.3 Environment and secrets

| Source | Spec |
|---|---|
| `environment:` block | Non-secret config: `CHRONOS_DB`, `CHRONOS_WEB` |
| `env_file: .env` | Secrets: API keys, ntfy topic. Never committed. |

**Spec:** §8.1 — "`.env` holds every secret and is never sent to a client";
phase doc — "no secret is baked into an image layer."

The `.env` file is listed in `.gitignore` and excluded by `.dockerignore`. The
`env_file` block with `required: false` means the compose file works even if
`.env` does not exist — the server falls back to the built-in offline parser
(§5.1, `.env.example`).

### B.4 Ports

| Host | Container | Spec |
|---|---|---|
| 8080 | 8080 | §8.1 — default port 8080 |

### B.5 What `docker compose up` does

1. Builds the image from `Dockerfile` if not already built.
2. Creates the `chronos-data` named volume if it does not exist.
3. Starts the container, mounting the volume at `/data`.
4. The entrypoint runs `chronos serve --host 0.0.0.0 --port 8080`.
5. On first run, the server creates the database, runs migrations, and seeds
   the 10-year bucket range (§4.3).
6. `/api/health` answers `200 OK` once the server is ready.

### B.6 Verification

```bash
docker compose up -d
curl -fsS http://127.0.0.1:8080/api/health
# → {"status":"ok","version":"2.0.0","db":"ok"}
```

### B.7 What the compose file does NOT do

- Does not bake secrets into the image (`.env` is mounted at runtime).
- Does not require systemd or root (§8.1).
- Does not configure OS timezone (§8.1 — "no OS timezone configuration").

---

## C. Termux support

**Spec:** §11 (operational notes), phase doc §"Behaviour the tests must pin" → Termux.

### C.1 Overview

Termux is a Linux environment on Android. The server runs as a plain process
inside Termux. The script `scripts/termux.sh` installs dependencies, starts the
server with a wake lock, and stops it.

### C.2 File layout

| File | Purpose |
|---|---|
| `scripts/termux.sh` | Install, start, stop the server in Termux |
| `docs/termux.md` | User-facing documentation: exact commands, what was and was not tested |

### C.3 `scripts/termux.sh` — interface

```
bash scripts/termux.sh install   # one-time setup
bash scripts/termux.sh start     # start the server (holds a wake lock)
bash scripts/termux.sh stop      # stop the server and release the wake lock
```

#### C.3.1 `install`

1. `pkg update -y` — refresh Termux package index.
2. `pkg install -y python git rust binutils libsqlite` — Python, Rust (for
   `sqlite-vec` compilation), binutils, SQLite.
3. `python -m venv $HOME/.chronos/venv` — create a venv so Termux's system
   Python is not disturbed.
4. `$HOME/.chronos/venv/bin/pip install --upgrade pip`
5. `$HOME/.chronos/venv/bin/pip install -e .` — install Chronos from the repo.

**Spec:** §8.1 — "`pip install -e .` works from a clean checkout."

#### C.3.2 `start`

1. `termux-wake-lock` — acquire a wake lock. **This must happen before the
   server starts.** Android doze will kill a backgrounded server otherwise
   (§11).
2. `export CHRONOS_DB=$HOME/.chronos/chronos.db`
3. `nohup $HOME/.chronos/venv/bin/chronos serve --host 127.0.0.1 --port 8080 >>$LOG 2>&1 &`
4. Write the PID to `$HOME/.chronos/server.pid`.
5. Wait 2 seconds, then `curl -fsS http://127.0.0.1:8080/api/health`.
6. If health check fails, print the log path and exit 1.

**Spec:** §11 — "`termux-wake-lock` before starting"; §11 — "`/api/health`
exists so a client can show a clear 'server is down' state."

#### C.3.3 `stop`

1. Read PID from `$HOME/.chronos/server.pid`.
2. `kill $PID`.
3. Remove the PID file.
4. `termux-wake-unlock` — release the wake lock.

### C.4 Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CHRONOS_DB` | `$HOME/.chronos/chronos.db` | Database path |
| `CHRONOS_PORT` | `8080` | Server port |
| `CHRONOS_WEB` | `1` | Serve the Web HUD |

### C.5 Embedding model download

**Spec:** §11 — "The embedding model is roughly 274 MB and downloads on first
use. The download is announced with progress and never happens silently inside
a request."

The embedding model (`llama-embedding`, ~274 MB) is downloaded by the
`llama-embedding` library on first use. The download:

- Is announced with a progress bar (the library prints progress to stderr).
- Happens on first `embed()` call, not inside a request handler.
- The server logs "downloading embedding model (274 MB)…" before the first
  embedding request.
- If the download fails, the server returns a clear error — it does not hang
  or silently fall back.

**Implementation note:** The `Embedder` protocol (§D.4 of the frozen contracts)
has `embed()` and `embed_batch()`. The local implementation wraps
`llama-embedding` and emits a log line before the first download. The progress
bar is provided by the library itself (it uses `tqdm` or similar).

### C.6 Exact user commands

```bash
# One-time: install Termux from F-Droid, then:
pkg install -y git
git clone <repo-url> chronos
cd chronos

# Install
bash scripts/termux.sh install

# Start (holds wake lock, server runs in background)
bash scripts/termux.sh start

# Check health
curl -fsS http://127.0.0.1:8080/api/health

# Stop
bash scripts/termux.sh stop
```

### C.7 What could not be tested on this host

The build host is Fedora 44 aarch64 in a proot container (§8.1). Termux
specifics that could not be tested here:

- `termux-wake-lock` / `termux-wake-unlock` — these are Termux-specific
  commands that require the Termux API add-on and Android. They cannot be
  tested in a proot container.
- Android doze behavior — cannot be simulated in proot.
- The exact `pkg install` package list — Termux package names may differ from
  Fedora's. The script uses `pkg install -y python git rust binutils libsqlite`
  which is the Termux convention.

**Spec:** phase doc — "Test them on this host where the equivalent paths
exist; be explicit about what could not be tested here."

### C.8 `docs/termux.md` — required content

The document must state:

1. Prerequisites: Termux from F-Droid, Termux:API add-on.
2. Exact commands (§C.6).
3. What the script does and why (wake lock, venv, nohup).
4. How to verify the server is up (`curl /api/health`).
5. What was tested on the build host and what was not (§C.7).
6. Troubleshooting: "server did not come up" → check `$HOME/.chronos/server.log`.

---

## D. Packaging

**Spec:** §8.1, phase doc §"Behaviour the tests must pin" → Packaging.

### D.1 `pyproject.toml` — build system

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

### D.2 `pyproject.toml` — project metadata

```toml
[project]
name = "chronos"
version = "2.0.0"
description = "Local-first AI study scheduler and time tracker"
readme = "README.md"
requires-python = ">=3.14"
license = { text = "GPL-3.0-or-later" }
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "argon2-cffi>=23.1",
    "sqlite-vec>=0.1.6",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
]
```

### D.3 `pyproject.toml` — optional dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]
```

### D.4 `pyproject.toml` — entry points

```toml
[project.scripts]
chronos = "chronos.cli.main:main"
```

**Spec:** §8.1 — "`chronos` is on the console path and `chronos serve` starts
the server."

The `chronos` command dispatches to `chronos.cli.main:main`, which parses
subcommands:

| Subcommand | Spec |
|---|---|
| `chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]` | §8.1 |
| `chronos key-renew` | §8.1, §3 |
| `chronos db-upgrade` | §8.1 |
| `chronos token-cost [--days 7]` | §8.1 |
| `chronos export` | §9.2 |

### D.5 Single-sourced version

**Spec:** phase doc — "Version is single-sourced; the package and the CLI report
the same number."

The version is defined in `pyproject.toml`:

```toml
version = "2.0.0"
```

The CLI reports it via `chronos --version`:

```python
# chronos/cli/main.py
from importlib.metadata import version
__version__ = version("chronos")
```

The `chronos --version` flag prints `chronos 2.0.0`. The package and the CLI
report the same number because both read from the same `pyproject.toml` via
`importlib.metadata`.

### D.6 Package discovery

```toml
[tool.setuptools.packages.find]
include = ["chronos*"]
```

This includes `chronos/` and all subpackages (`chronos/contracts/`,
`chronos/db/`, `chronos/core/`, `chronos/ai/`, `chronos/api/`,
`chronos/realtime/`, `chronos/notify/`, `chronos/mcp/`, `chronos/cli/`,
`chronos/web/`).

### D.7 `pip install -e .` from a clean checkout

**Spec:** phase doc — "`pip install -e .` works from a clean checkout."

The editable install:

1. Creates a `.pth` file in site-packages pointing to the repo root.
2. Installs the `chronos` console script.
3. Makes `chronos` importable from anywhere.

Verification:

```bash
.venv/bin/pip install -e .
.venv/bin/chronos --help
.venv/bin/chronos --version
```

### D.8 What the package does NOT include

- No `.env` file (§8.1 — secrets are never in the package).
- No database file (§2 — the database is created on first run).
- No `tests/`, `docs/`, `scripts/` (not part of the Python package).

---

## E. CI

**Spec:** §8.1, phase doc §"Behaviour the tests must pin" → CI.

### E.1 Workflow files

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Lint + test on every push |
| `.github/workflows/docker.yml` | Build the Docker image on every push |

### E.2 `ci.yml` — lint and test

```yaml
name: ci

on:
  workflow_dispatch:
  push:
  pull_request:

jobs:
  guard:
    runs-on: ubuntu-latest
    outputs:
      has_code: ${{ steps.check.outputs.has_code }}
    steps:
      - uses: actions/checkout@v4
      - id: check
        run: |
          if [ -d chronos ] && [ -n "$(find chronos -name '*.py' -print -quit)" ]; then
            echo "has_code=true" >> "$GITHUB_OUTPUT"
          else
            echo "has_code=false" >> "$GITHUB_OUTPUT"
          fi

  tests:
    needs: guard
    if: needs.guard.outputs.has_code == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - name: Install
        run: |
          python -m venv .venv
          .venv/bin/pip install --upgrade pip
          .venv/bin/pip install -e ".[dev]"
      - name: Lint
        run: .venv/bin/ruff check chronos tests
      - name: Tests
        run: .venv/bin/python -m pytest tests -q
```

**Spec:** phase doc — "A workflow runs `ruff check` and the full pytest suite
on every push."

The `guard` job detects whether `chronos/` exists. The repository is docs-only
until the build produces `chronos/` (phase doc — "The repository is docs-only
until the build produces chronos/"). The guard job skips cleanly so the badge
stays honest instead of red.

### E.3 `docker.yml` — Docker build

```yaml
name: docker

on:
  workflow_dispatch:
  push:
  pull_request:

jobs:
  guard:
    runs-on: ubuntu-latest
    outputs:
      has_code: ${{ steps.check.outputs.has_code }}
    steps:
      - uses: actions/checkout@v4
      - id: check
        run: |
          if [ -d chronos ] && [ -n "$(find chronos -name '*.py' -print -quit)" ]; then
            echo "has_code=true" >> "$GITHUB_OUTPUT"
          else
            echo "has_code=false" >> "$GITHUB_OUTPUT"
          fi

  docker:
    needs: guard
    if: needs.guard.outputs.has_code == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t chronos:ci .
      - name: Health check
        run: |
          docker run -d --name chronos -p 8080:8080 chronos:ci
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
              echo "healthy"; exit 0
            fi
            sleep 1
          done
          echo "did not become healthy"; docker logs chronos; exit 1
```

**Spec:** phase doc — "A workflow builds the Docker image"; "Both must pass on
a clean checkout — no reliance on a developer's local state or `.env`."

The health check runs the container, waits up to 30 seconds for `/api/health`
to answer, and fails with logs if it does not.

### E.4 What CI does NOT do

- Does not require `.env` (the server runs with no keys — §5.1, `.env.example`).
- Does not run on Windows (§8.1 — Windows is best effort, not a CI target).
- Does not publish the image (no registry push in this phase).

---

## F. Deploy scripts

**Spec:** §8.1, phase doc §"Parts" → 6.6.

### F.1 `scripts/` layout

| File | Purpose |
|---|---|
| `scripts/termux.sh` | Install, start, stop the server in Termux (§C) |
| `scripts/smoke.sh` | Start the server on a port and hit `/api/health` |
| `scripts/backup.sh` | Copy the database file to a timestamped backup |
| `scripts/restore.sh` | Restore the database from a backup |

### F.2 `scripts/smoke.sh`

**Spec:** phase doc §"Verification" — "`./scripts/smoke.sh 8099`".

```bash
./scripts/smoke.sh 8099
```

1. Starts `chronos serve --port 8099` in the background.
2. Waits for `/api/health` to answer.
3. Prints the health response.
4. Stops the server.

Used in development to verify the server starts and answers.

### F.3 `scripts/backup.sh`

**Spec:** §2 — "Copy the file and you have a backup — that is the whole backup
story."

```bash
./scripts/backup.sh
```

1. Reads `CHRONOS_DB` (default: `./data/chronos.db`).
2. Copies the file to `backups/chronos-$(date +%Y%m%d-%H%M%S).db`.
3. Prints the backup path.

### F.4 `scripts/restore.sh`

```bash
./scripts/restore.sh backups/chronos-20261003-120000.db
```

1. Stops the server if running.
2. Copies the backup file to `CHRONOS_DB`.
3. Starts the server.

### F.5 What `scripts/` does NOT include

- No systemd unit files (§8.1 — "no systemd").
- No root-required scripts (§8.1 — "no root").
- No OS timezone configuration (§8.1 — "no OS timezone configuration").

---

## G. File layout

Every file in the deployment surface with its purpose and exports.

### G.1 `Dockerfile`

**Purpose:** Build the Chronos server image.  
**Exports:** A container image that runs `chronos serve` on port 8080 with the
database on a volume at `/data`.

### G.2 `.dockerignore`

**Purpose:** Exclude secrets, local state, and development files from the Docker
build context.  
**Exports:** A clean build context that contains only `pyproject.toml`,
`README.md`, and `chronos/`.

**Contents:**

```
.venv/
.env
*.db
*.sqlite
*.sqlite3
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.pytest_cache/
.ruff_cache/
.git/
.github/
tests/
android/
docs/
scripts/
*.bundle
```

### G.3 `docker-compose.yml`

**Purpose:** Define the Chronos service, its volume, and its environment.  
**Exports:** A `docker compose up` command that starts a working server with
`/api/health` answering.

### G.4 `scripts/termux.sh`

**Purpose:** Install, start, and stop the server in Termux.  
**Exports:** Three subcommands: `install`, `start`, `stop`.

### G.5 `scripts/smoke.sh`

**Purpose:** Start the server on a given port and verify `/api/health`.  
**Exports:** A health check that exits 0 on success, non-zero on failure.

### G.6 `scripts/backup.sh`

**Purpose:** Copy the database file to a timestamped backup.  
**Exports:** A backup file at `backups/chronos-<timestamp>.db`.

### G.7 `scripts/restore.sh`

**Purpose:** Restore the database from a backup.  
**Exports:** The database file replaced with the backup.

### G.8 `.github/workflows/ci.yml`

**Purpose:** Run `ruff check` and the full pytest suite on every push.  
**Exports:** A CI job that passes or fails.

### G.9 `.github/workflows/docker.yml`

**Purpose:** Build the Docker image and verify `/api/health` answers.  
**Exports:** A CI job that passes or fails.

### G.10 `pyproject.toml`

**Purpose:** Define the Python package, its dependencies, entry points, and
version.  
**Exports:** The `chronos` console script and the `chronos` Python package.

### G.11 `docs/termux.md`

**Purpose:** Document the exact commands a user types to run Chronos in Termux.  
**Exports:** User-facing documentation.

### G.12 `docs/docker.md`

**Purpose:** Document the exact commands a user types to run Chronos in Docker.  
**Exports:** User-facing documentation.

---

## H. Spec ambiguities and open questions

1. **Base image patch version (§8.1):** The spec says "pin the base image
   version" but does not specify a patch level. **Proposal:** Pin to
   `python:3.14.7-slim-bookworm` (the current stable patch). Confirm with
   Manager.

2. **Multi-arch build (§8.1):** The spec mentions Linux desktop and Termux on
   Android (aarch64) but does not explicitly require multi-arch images.
   **Proposal:** Build for both `linux/amd64` and `linux/arm64` using
   `docker buildx`. Confirm with Manager.

3. **Embedding model download progress (§11):** The spec says "announced with
   progress" but does not specify the mechanism. **Proposal:** The
   `llama-embedding` library provides its own progress bar (via `tqdm`). The
   server logs "downloading embedding model (274 MB)…" before the first
   download. Confirm with Manager.

4. **Termux package names (§11):** The spec does not specify which Termux
   packages are needed. **Proposal:** `python git rust binutils libsqlite`.
   The `rust` package is needed to compile `sqlite-vec`. Confirm with Manager.

5. **Windows support (§8.1):** The spec says "best effort; document what is
   untested rather than claiming it." **Proposal:** Document that Windows is
   untested and the server should work via `pip install -e .` and
   `chronos serve` but no Windows-specific testing has been done. Confirm
   with Manager.

6. **Docker image registry (§8.1):** The spec does not mention publishing the
   image to a registry. **Proposal:** Do not publish in this phase. The image
   is built locally with `docker build -t chronos .`. Confirm with Manager.

7. **Backup script location (§2):** The spec says "copy the file and you have a
   backup" but does not specify a backup script. **Proposal:** Provide
   `scripts/backup.sh` that copies the database to a timestamped file. Confirm
   with Manager.

8. **`docs/docker.md` (phase doc):** The phase doc's "Done means" checklist
   includes `docs/docker.md` but the phase doc's "Parts" table does not list
   it. **Proposal:** Create `docs/docker.md` alongside `docs/termux.md`.
   Confirm with Manager.

---

## I. Summary

This proposal covers the complete deployment interface for Phase 6:

- **Dockerfile** — multi-stage build, pinned base image, volume at `/data`,
  health check on `/api/health`, no secrets in layers.
- **Docker Compose** — named volume, `.env` mounted at runtime, `docker compose
  up` yields a working server.
- **Termux** — `scripts/termux.sh` with install/start/stop, wake-lock before
  start, embedding download announced with progress, `docs/termux.md` with
  exact commands.
- **Packaging** — `pip install -e .` from a clean checkout, `chronos` on the
  console path, single-sourced version via `importlib.metadata`.
- **CI** — `ci.yml` runs `ruff check` + pytest, `docker.yml` builds the image
  and health-checks it, both pass on a clean checkout.
- **Deploy scripts** — `scripts/termux.sh`, `scripts/smoke.sh`,
  `scripts/backup.sh`, `scripts/restore.sh`.
- **File layout** — every file with purpose and exports.

The proposal is detailed enough that a code agent can implement it without
re-reading the spec. All decisions are cited to the spec section.
