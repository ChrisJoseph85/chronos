# Chronos deployment

How to run the server where it is supposed to run. See `docs/phases/phase-6-deploy.md`
for the acceptance criteria; this file records what has actually been verified.

Targets: **proot-distro container inside Termux on Android (primary build host)**, **Linux desktop/laptop**, **Docker**. Windows best-effort only.

> 2026-10-05: we run inside proot-distro (`Chronos`, Fedora 44 aarch64), which itself is hosted by Termux on Android. We do NOT run in the Termux prefix itself. `pkg`, `$PREFIX`, `$TERMUX_VERSION`, `termux-wake-lock` live outside this container and cannot be relied on here. See `environment-corrections.md`.

---

## Direct (proot-distro, Linux)

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/chronos serve --port 8080 --host 127.0.0.1 --db ~/.chronos/chronos.db
```

Always use `/usr/bin/python3` explicitly. Bare `python3` may be an agent runtime. See `proot-distro.md`.

The database defaults to `~/.chronos/chronos.db`. Override with `CHRONOS_DB` or
`--db`. The instance key is generated on first run and printed **once** — save it. Backend is API-only; no web flag exists.

---

## Docker

```bash
docker compose up --build
curl http://127.0.0.1:8080/api/health
```

The database lives on the `chronos-data` volume, so replacing the container does
not lose data. Secrets go in a `.env` file beside `docker-compose.yml` — it is
gitignored and never copied into an image layer.

`/api/health` is the healthcheck and the only unauthenticated route, so it is safe
to probe.

---

## Termux vs proot-distro (Android)

Build host = proot-distro container. Termux prefix (`/data/data/com.termux`, `pkg`, wake-lock) is the *host* of this container, not this container.

- Inside proot: use `scripts/smoke.sh`, `scripts/backup.sh`, `scripts/restore.sh`. Never call `pkg` or `termux-wake-lock` here — they do not exist in this view.
- On the Termux side (phone, outside proot): `termux-wake-lock` before `proot-distro login Chronos -- chronos serve`. That is a phone instruction, not a file in this repo.
- `scripts/termux.sh` is removed. `scripts/install.sh` detects proot vs Termux and refuses rather than doing the wrong thing.

---

## What has been verified

*(the Manager updates this section with real output — do not claim anything here
that was not observed)*

- [ ] `pip install -e .` then `chronos serve` on Linux
- [ ] `docker compose up` and `/api/health` answers
- [ ] the database survives container replacement
- [ ] the Termux script installs and starts the server
- [ ] CI passes on a clean checkout
