# Chronos server — START HERE

**Read this before anything else in this folder.**

---

## 1. What you're building

A local-first AI study scheduler and time tracker. Python 3.14, FastAPI, SQLite.
One SQLite file holds everything; the clients are views.

The full product spec is **[Chronos.md](Chronos.md)** — 31 KB, and it **wins every
disagreement** with any other document here. If something below contradicts it,
`Chronos.md` is right.

---

## 2. State of the world

**There is no code.** The previous implementation was deleted before this
handoff. You are building from the spec. That is a deliberate clean slate — the
old code had a green test suite and could not boot its own server.

Nothing was pushed to GitHub before deletion: `origin/main` sat at `4833d13`,
older than the code commit. **The old code is unrecoverable.** Build it properly
this time.

---

## 3. Read in this order

| # | File | What it gives you |
|---|---|---|
| 1 | [API.md](API.md) | **Frozen backend contract. Clients build against this in parallel.** |
| 2 | [Chronos.md](Chronos.md) | **The spec. Source of truth.** |
| 2 | [REBUILD.md](REBUILD.md) | What the last attempt got wrong, and what to do differently |
| 3 | [errors-and-test-proposal.md](errors-and-test-proposal.md) | Every error, and the 5-layer test system that catches them |
| 4 | [contract-and-interfaces.md](contract-and-interfaces.md) | The frozen API surface — build to this |
| 5 | [scheduling-behaviour.md](scheduling-behaviour.md) | Buckets, proposals, and when the AI must ask |
| 6 | [phases/](phases/) | Per-phase scope and done criteria |
| 7 | [proposals/](proposals/) | Frozen interface proposals — the contracts are settled, don't relitigate |
| 8 | [manager.md](manager.md) | Manager's operating manual |
| 9 | [architecture.md](architecture.md) | Process, roles, agent ceiling |
| 10 | [decisions.md](decisions.md) | Every ruling and why |
| 11 | [proot-distro.md](proot-distro.md) | **This environment** — read before running anything |

---

## 4. Build order

1. **Read the spec end to end.** Not skimming — it defines the interfaces you
   will freeze.
2. **Contract tests first.** Before any feature: a test that runs the installed
   console script and every route. This one thing catches the entire
   "code exists but nothing calls it" class, which is what killed the last build.
3. **contracts/** — enums, models, DDL, Protocols. Everything depends on these.
4. **db/** — engine, migrations, repos, seed. Execute the DDL in tests; never
   grep it.
5. **core/** — pure scheduling logic. Must run with no database.
6. **ai/** — providers, intent, verify, packer, tools.
7. **api/** — routes, auth. One instance key, `X-Chronos-Key`.
8. **realtime/**, **notify/**, **mcp/**, **cli/** — no `web/` (removed 2026-10-05, API-only).
9. **scripts/smoke.sh** — the real gate.
10. Deployment: Dockerfile, Termux, CI.

---

## 5. The rules that matter most

- **The test author is not the implementer.** Write the failing test, hand it to
  a different agent. This is the single highest-value rule in this folder.
- **A test must be able to fail.** Mutate the behaviour, confirm red, restore.
- **Never edit a test to make it pass.** The spec decides which side is wrong.
- **A red test with a correct assertion is a deliverable.**
- **`smoke.sh` is the gate.** A green unit suite is not a running app.
- **One writer per file.** Two agents on one file = silent overwrite.
- **`ruff check chronos tests` must be 0** before anything is called done.
- **Verify every agent claim yourself.** Every number in any document must come
  from a run you performed.

---

## 6. Environment — read this

This host is a **proot-distro** container (`Chronos`) on **aarch64**, Fedora 44.
No systemd, no Docker daemon, no Android.

**Python: use `/usr/bin/python3` explicitly.** Bare `python3` may resolve to an
agent runtime's private interpreter, and a venv built from that is not
reproducible for the user. This caused hours of confusion — see
[proot-distro.md](proot-distro.md).

```bash
cd <your checkout>
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests -q
```

**Cannot be verified here, ever:** `docker build`, `docker compose up`,
volume-survives-replacement, image size, daemon HEALTHCHECK, and every
Termux/Android path. Mark them honestly; delegate to CI. Never claim what you
could not run.

---

## 7. Scope

**You are building the server.** The HTTP API you expose is the deliverable.

There are other documents under `/root/docs/` — a browser client and an Android
app. **They are not your concern.** Do not read them, do not build them, do not
let their requirements change your API. If one of them needs something the spec
does not already call for, that is a conversation for the user, not a change you
make unilaterally.