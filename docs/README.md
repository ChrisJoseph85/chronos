# Chronos documentation

Three projects, three documentation sets. Start at the index for each.

---

## `/server/` — the Chronos server

**[→ server/START-HERE.md](server/START-HERE.md)**

Python 3.14 + FastAPI + SQLite. One SQLite file holds everything; clients are
views. **This is the project you build if you are doing Chronos.**

Read order: `START-HERE.md` → `Chronos.md` (the spec, which wins every
disagreement) → `REBUILD.md` → `errors-and-test-proposal.md` →
`contract-and-interfaces.md` → `scheduling-behaviour.md`.

**There is no code.** The previous implementation was deleted before this
handoff and was never pushed to GitHub — it is unrecoverable. This is a
deliberate clean slate; the old code had a green test suite and could not boot
its own server.

---

## 7. Scope

**You are building the Chronos server.** Everything in this folder is for the
agent doing that. Start at **[START-HERE.md](server/START-HERE.md)**, then read
**[server/Chronos.md](server/Chronos.md)** — the product spec, which wins every
disagreement with any other document here.

**The browser client and the Android app are not in scope for you.** They are
documented separately. Do not read their material, do not build them, and do not
shape the server's API around their convenience. The spec defines the
interface; the clients consume it.

---

## The shared rule

**The server owns the API contract.** Anything that consumes it — a browser UI,
an Android app — is a separate project and is not documented in this folder. None
of them edits the server's files.

---

## Environment

This host is a **proot-distro** container on **aarch64**, Fedora 44. No systemd,
no Docker daemon, no Android.

**Use `/usr/bin/python3` explicitly** — bare `python3` may resolve to an agent
runtime's private interpreter, producing a venv the user cannot run. That cost
hours once; see `server/proot-distro.md`.

**Docker and Android paths cannot be verified here.** Mark them honestly and
delegate to CI. Never claim what you could not run.