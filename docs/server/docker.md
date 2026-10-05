# Docker — running Chronos in a container

Phase 6, part 6.1/6.2. The process is a plain `chronos serve`; there is no
systemd, no root on the host, and no OS timezone configuration involved.

---

## Quick start

```bash
cp .env.example .env        # provider keys and ntfy topics — never commit this
docker compose up -d
curl -fsS http://127.0.0.1:8080/api/health
# {"status":"ok","version":"2.0.0","db_path":"/data/chronos.db",...}
docker compose logs -f chronos
```

The port binds to `127.0.0.1` by default. The instance key is the only thing
between a client and the database, so publishing it to the LAN by accident is
not a default worth having. Override with `CHRONOS_BIND=0.0.0.0` when you mean
it.

Stop it without losing data:

```bash
docker compose down          # container gone, /data volume kept
docker compose down -v       # ALSO deletes the database
```

---

## What the image guarantees

| Property | How it is achieved | Pinned by |
|---|---|---|
| Small, reproducible | two-stage build; only the venv crosses into the runtime stage; base image pinned to `python:3.14.2-slim-bookworm` | `test_dockerfile_base_image_is_pinned`, `test_dockerfile_builds_in_a_separate_stage` |
| No baked secrets | allowlist `.dockerignore` starting with `*`, explicit `.env` denylist, no `COPY . .`, no COPY source that could be a `.env`/`.db`/`.key` | `test_dockerfile_copies_no_secret_and_no_whole_tree`, `test_dockerignore_excludes_secrets_and_local_state` |
| Data survives container replacement | named volume `chronos-data` at `/data`; the container is disposable, the volume is not | `test_compose_declares_a_volume_backed_database` |
| No root | `USER chronos` (uid 10001), `/data` chowned at build | `test_dockerfile_runs_as_non_root_and_exposes_the_port` |
| Reaches the model endpoints | default bridge networking; nothing else is needed | — |

Configuration arrives as environment variables at run time. `docker-compose.yml`
reads `.env` with `env_file` (marked `required: false`, so a checkout with no
`.env` still starts) and passes the values through. The file is read by the
Docker client on your machine; it is never copied into an image layer.

### Digest pinning: not done here

The base image is pinned to an exact version tag, not a digest. Pinning a
digest needs a reachable registry to read the real `sha256:` from, and a
fabricated digest would break the build for everyone in a way that looks like a
network problem. Whoever publishes the first release should add
`@sha256:<digest of python:3.14.2-slim-bookworm>` to both `FROM` lines;
`test_dockerfile_base_image_is_pinned` will still pass, because it only forbids
floating tags.

---

## Backup (spec §2 — the whole story)

Copying the SQLite file is the backup. The container must not break that:

```bash
# live copy out of the running container
docker cp chronos:/data/chronos.db ./chronos-$(date +%F).db

# or stop, copy the volume, start
docker compose stop
docker run --rm -v chronos-data:/src -v "$PWD":/dst alpine \
  cp /src/chronos.db /dst/chronos-$(date +%F).db
docker compose start
```

To restore, stop the server, put the file back at `/data/chronos.db`, and start
it again. `scripts/restore.sh` does this on the host install; the container path
is the `docker cp` above, because the volume is the same file.

---

## What was verified on the build host, and what was not

Build host: the `occ` prootdistro container, aarch64, Fedora 44 userspace.
This host has **no Docker daemon** (`docker: command not found`), so every
Docker behaviour below is verified *structurally* by parsing the files, not by
running Docker.

### Genuinely verified here

- `Dockerfile`, `.dockerignore` and `docker-compose.yml` parse, and every
  structural property in the table above is asserted by a test that fails when
  the property is broken (`tests/phase_6/test_deploy_spec.py`, 14 tests over
  the Dockerfile/compose files, including "COPY source must exist in the repo").
- Every `COPY` source resolves to a real path in a clean checkout, so the build
  cannot fail on a missing file.
- `ruff check tests/phase_6` is clean.
- `python -m pytest tests/phase_6 -q` is green (see the test file's own output).
- `./scripts/smoke.sh` boots the real installed `chronos serve` over real HTTP
  on this host, polls `/api/health`, proves `/api/events` is 401 without the key
  while health stays open, sends an English sentence through `/api/say`, and
  commits then reads a row back out of SQLite. **This is the closest thing to
  `docker compose up` that can be run on this host, and it is a real server.**

### NOT verified here — and honestly so

| Claim | Why it could not be checked on this host |
|---|---|
| `docker compose up` yields a server answering `/api/health` | no Docker daemon |
| the database survives `docker compose up -d --force-recreate` | no Docker daemon |
| `docker build` succeeds at all | no Docker daemon; `pip install` of the same tree into a fresh venv is the closest analogue, and it passes |
| the image's final size and layer contents | no Docker daemon |
| the `HEALTHCHECK` line actually marks the container healthy | no Docker daemon |
| digest pinning (see above) | needs a registry to read the digest from |
| **Windows** (spec §8.1 target 3) | not tested here, and there is no Windows host in this environment. Best effort only: the image is Linux/aarch64-specific (`linux/arm64`), and `chronos serve` itself is plain Python and is expected to work on Windows, but that expectation is untested. |

The two Docker-behaviour tests exist and are correct, but they **skip** on this
host with the reason printed (`docker CLI is not installed on this host` /
`no reachable Docker daemon on this host`). They are the thing to run first on a
machine that has Docker:

```bash
python -m pytest tests/phase_6 -q -m docker
```

---

## What CI does and does not assert

`.github/workflows/ci.yml` runs on every push and pull request and gates only
what phase 6 owns:

- `ruff check tests/phase_6`
- `python -m pytest tests/phase_6 -q`
- `chronos --help` / `chronos --version`, cross-checked against
  `chronos.__version__`
- `./scripts/smoke.sh 8099`
- `bash -n` on all three shell scripts

It deliberately does **not** run `ruff check chronos tests` or the full pytest
suite. Project-wide lint and the phases 1–5 test suites are **owned by those
phases and are not green yet**. Gating them from this phase would produce a
permanently red badge that says nothing about deployment, and would hide
phase 6's own result behind someone else's backlog. When the project-wide run
goes green, widen the two scoped steps in `ci.yml`; that is a one-line change
and `test_ci_gates_only_what_phase_6_owns_and_says_so` documents the intent so
the widening is a deliberate act.

`.github/workflows/docker.yml` builds the image, asserts the image is not root,
brings it up, polls `/api/health`, replaces the container and re-checks that
the database survived. That workflow **has never run** — it was written on a
host with no Docker and is unverified. Treat its first run as the real test of
the Dockerfile.
