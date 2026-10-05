# Phase 6 — Deployment (Termux, Docker, packaging, CI)

**Runs in parallel with phases 1–5.** It is mostly independent of the code: it
packages and ships whatever the other phases produce. Start it early so that
"does it run where it is supposed to run" is answered before the end, not after.

Spec: `docs/Chronos.md` §8.1 (process and targets), §11 (operational notes),
§12 (out of scope).

---

## Parts

| Part | Files | Owner |
|---|---|---|
| 6.1 Dockerfile | `Dockerfile`, `.dockerignore` | one code agent |
| 6.2 Compose | `docker-compose.yml` | one code agent |
| 6.3 Termux support | `scripts/termux.sh`, `docs/termux.md` | one code agent |
| 6.4 Packaging | `pyproject.toml` entry points, versioning | one code agent |
| 6.5 CI | `.github/workflows/` | one code agent |
| 6.6 Deploy scripts | `scripts/` | one code agent |

---

## Targets (§8.1)

The server must run on all three of these. They are the acceptance criteria.

1. **Linux desktop and laptop** — the development and primary target.
2. **Termux on Android** — the phone. This is where the app is expected to
   actually live, so it must work, not merely be theoretically possible.
3. **Windows** — best effort; document what is untested rather than claiming it.

There is **no systemd, no root, and no OS timezone configuration** required. The
process is a plain `chronos serve`.

---

## Behaviour the tests must pin

**Docker**
- The image builds from the repository with no network access at run time except
  the model endpoints and ntfy.
- The database lives on a **volume**, so the container can be replaced without
  losing data. Copy the file and you have a backup — that is the whole backup
  story (§2), and the container must not break it.
- `docker compose up` starts a working server and `/api/health` answers.
- The image does not bake in secrets. `.env` is mounted or passed in, never
  committed and never copied into a layer.
- The image is small and reproducible; pin the base image version.

**Termux (§11)**
- A script installs and runs the server in Termux, including
  `termux-wake-lock` **before** starting — Android doze will kill a backgrounded
  server otherwise.
- `/api/health` exists so a client can show a clear "server is down" state
  instead of a spinner that never resolves.
- The embedding model is roughly 274 MB and downloads on first use. The download
  is **announced with progress and never happens silently inside a request.**
- Document the exact commands a user types. Test them on this host where the
  equivalent paths exist; be explicit about what could not be tested here.

**Packaging**
- `pip install -e .` works from a clean checkout.
- `chronos` is on the console path and `chronos serve` starts the server.
- Version is single-sourced; the package and the CLI report the same number.

**CI**
- A workflow runs `ruff check` and the full pytest suite on every push.
- A workflow builds the Docker image.
- Both must pass on a clean checkout — no reliance on a developer's local state
  or `.env`.

---

## Done means

- [ ] `docker compose up` yields a server that answers `/api/health`
- [ ] the database survives container replacement (volume)
- [ ] no secret is baked into an image layer
- [ ] the Termux script installs, wake-locks and starts the server
- [ ] the embedding download is announced, never silent inside a request
- [ ] `pip install -e .` then `chronos serve` works from a clean checkout
- [ ] CI runs lint + tests + docker build on a clean checkout
- [ ] `docs/termux.md` and `docs/docker.md` state exactly what was and was not
      verified on this host
- [ ] full suite green
- [ ] per-part scratch tests and probe scripts deleted; the phase's spec tests kept
      (`manager.md` §10)

---

## Verification

```bash
# package
.venv/bin/pip install -e .
.venv/bin/chronos --help

# docker (if a daemon is available on this host)
docker build -t chronos .
docker run --rm -p 8080:8080 chronos &
curl -fsS http://127.0.0.1:8080/api/health

# the server itself, directly
./scripts/smoke.sh 8099
```

Report honestly which of these you could and could not run on this host. A clear
"this could not be tested here, because X" is worth more than a claim.
