# Docker — running Chronos in a container

Spec: `docs/server/Chronos.md` §8.1, §11; `docs/server/API.md` Docker note.
No registry push in this phase.

## Quick start

```bash
cp .env.example .env   # never commit this; never copied into an image layer
docker compose up --build
curl -fsS http://127.0.0.1:8080/api/health
```

The database lives on the `chronos-data` volume at `/data`, so replacing
the container does not lose data. `.env` arrives via `env_file` with
`required: false`, so a checkout with no `.env` still starts.
`/api/health` is the healthcheck probe and the only unauthenticated route.

## Multi-arch build

The image builds for both `linux/amd64` and `linux/arm64` via
`docker buildx`:

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t chronos .
```

The base image is pinned to `python:3.14.7-slim-bookworm` in every
`FROM` line. No secrets are baked in: no `COPY .env`, and no `ENV`
carrying a key, secret, or token.

## Backup

Copying the SQLite file is the backup (spec §2):

```bash
docker cp chronos:/data/chronos.db ./chronos-$(date +%F).db
```

## What was verified here, and what was not

Build host: proot-distro container (Fedora 44 aarch64) with no Docker
daemon, no systemd, and no Android.

Verified here:

- `Dockerfile` pins `python:3.14.7-slim-bookworm` and bakes no secrets.
- `docker-compose.yml` declares `chronos-data:/data`, `env_file` with
  `required: false`, and a healthcheck probing `/api/health`.
- `pytest tests/phase_6 -q` structural tests for the above are green.

Not verified here:

- `docker build` and `docker compose up` answering `/api/health` (no
  Docker daemon on this host; delegated to CI).
- Database survival across container replacement (needs a daemon).
- Windows (no Windows host available; best effort, untested).
