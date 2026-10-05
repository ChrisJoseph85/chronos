# REBUILD — Manager entry point

**Written:** 2026-10-03 by the previous Manager. **Not project-authoritative —
`docs/Chronos.md` wins every disagreement.**

This is a handoff document. See [README.md](README.md) in this folder for why
it exists and how to read it.

---

## 0. STOP — the filesystem is not what it looks like

**You are in a proot-distro, and your view of `/root/Chronos` may not be the
user's view.**

Symptoms seen: a file that demonstrably existed returned "No such file or
directory", `ls -l` on it printed nothing at all, and `cd` into the directory
worked. Cause: proot translates paths **per process**, so an agent's shell and
the user's shell are not looking at the same filesystem.

**This invalidated every "works for me" check the previous Manager ran.** A venv
it rebuilt appeared to the user as missing.

**First action: confirm the real directory and confirm which filesystem the
user is in. Do not trust any local verification until that is settled.** Put the
answer at the top of `docs/schedule.md`.

Also: build the venv from `/usr/bin/python3`, never from an agent runtime's
private interpreter. See [proot-distro.md](proot-distro.md).

---

## 1. Measured state (re-measure before trusting — these are stale)

| suite | result at time of writing |
|---|---|
| `tests/phase_1` | 257 passed, 3 xfailed |
| `tests/phase_2` | 130 passed |
| `tests/phase_3` | ~106 passed, 2 failed |
| `tests/phase_4` | 112 passed |
| `tests/phase_5` | 54 passed, 1 failed |
| `tests/acceptance` | 108 passed, 33 failed |
| full suite | ~815 passed, 28 failed |
| `ruff check chronos tests` | **~140 errors — must reach 0** |

Session start was 207 failures / 60 errors.

### Real API surface (verified present in `chronos/api/routes.py`)

```
POST   /api/say            POST   /api/timer/start    GET    /api/timer
POST   /api/commands       POST   /api/timer/stop     GET    /api/timer/summary
GET    /api/events         GET    /api/timer/presets  GET    /api/stats
GET    /api/nodes          GET    /api/buckets        GET    /api/settings
GET    /api/briefing       GET    /api/search         PUT    /api/settings
GET    /api/reminders      POST   /api/keys/renew     POST   /api/voice
```

Auth: one instance key, header `X-Chronos-Key`, query-string fallback.
`/api/health` is the only open route. Spec §3.

---

## 2. The test system

Full design in [rebuild-lessons-and-test-proposal.md](rebuild-lessons-and-test-proposal.md).
The four rules:

1. **A test must be able to fail.** Mutate the behaviour, confirm red, restore.
   Banned: `assert "X" in str(SPEC)`, source-file greps, `assert True`,
   existence-only checks.
2. **The test author is not the implementer.** Tests first, then a *different*
   agent makes them pass. This is the single most important rule here.
3. **Never edit a test to make it pass.** The spec decides which side is wrong.
4. **A red test with a correct assertion is a deliverable.**

Five layers: contract tests (console script + every route over real HTTP),
real-database tests (execute the DDL, read back through the enum), interface
tests against a real booted server, spec-derived acceptance tests written
first, and `smoke.sh` as the gate.

**Gates before any phase is called done:** phase tests pass; full suite 0
failures; `ruff check chronos tests` = **0**; `smoke.sh` exit 0; contract tests
reach every entry point; every `Done means` box has a test that fails if broken;
an independent agent has given a green-light verdict.

---

## 3. Known-broken — do not re-diagnose from scratch

**Review series** — spec §4.4 wants `active|retired|cancelled` with *no* CHECK.
The DDL had the wrong state set *and* the wrong case, so every insert failed.
Fixed; verify by actually inserting.

**Search** — `node_fts` was external-content (`content=''`) with a TEXT uuid as
`rowid` → `datatype mismatch`; nothing could ever be indexed, so search silently
returned empty forever. Fixed via SHA-256→INTEGER rowid; verify by indexing and
finding a node.

**Half the API 500s** — `DatabaseEngine.conn` is thread-local but `create_app`
captured the boot-thread connection. `SettingsRepoProxy` added; verify.

**Timer maths inverted** — filtered `mode != 'stopwatch'`, so stopwatch logged
**zero** and pomodoro breaks **inflated** totals. Spec §4.7 says the opposite.

**`tz = UTC` hardcoded** — `instance.timezone` ignored for every day boundary
(§7.1). A 4pm task can land at the wrong hour. See
[scheduling-behaviour.md](scheduling-behaviour.md) §4.

**Five uppercase DDL defaults** — `events.kind`, `reminders.state`,
`reminders.channel`, `timer_sessions.mode`, `timer_sessions.cycle` (the last
also `TEXT` where spec says `INTEGER`).

**`/ws` missing `websocket.accept()`** — fixed; also required adding
`websockets>=12.0`, because uvicorn shipped no WebSocket implementation and
Starlette's `TestClient` masked it.

**`/api/commands` returns `success: true`** while unimplemented. It lies.

**Ambiguous sentences guess a time** instead of asking. Spec §5.5/§5.7 requires
`ask_question`. See [scheduling-behaviour.md](scheduling-behaviour.md).

**`/ws` ignores `say`** — no proposal is pushed over the socket, so accept/reject
is never exercised there. REST works.

**Phase 5 search regression** — `test_missing_vec_table_degrades_to_keywords_only`
fails after the FTS change. Decide whether the fallback or the test is wrong.

**Phase 6: 2–3 failing tests** — `test_compose_healthcheck_and_ports_agree_with_the_image`,
`test_termux_health_check_polls_rather_than_sleeps` (the latter asserts on a
Termux script that cannot run on this host at all).

**No desktop setup script** — `chronos setup` now exists and covers providers
and embeddings, but **does not ask for timezone**, and there is no
`scripts/setup.sh` for Linux, which is spec §8.1's primary target.

---

## 4. HUD requirements

See [mobile-hud.md](mobile-hud.md) and [client-build-spec.md](client-build-spec.md).

Plain HTML/CSS/vanilla JS. **No Django, no framework, no build step** — a second
backend would mean a second ORM and a second auth system for an app whose
premise is one SQLite file on one machine.

Six-screen bottom nav: tasks, calendar, timer, briefing, AI, settings. A
**persistent AI bar available on every screen**, collapsed, with mic plus
expandable typing. Settings is instance-key-only.

**The client is thin**: it mirrors server state and owns nothing. No local DB,
no localStorage except the key, no optimistic writes, re-read after every
mutation.

---

## 5. Android

Requirements and verified host facts in [android-app.md](android-app.md). Kept
separate because it is a distinct project with its own Agent.

---

## 6. Manager's operating rules — learned the hard way

- **One writer per file.** Two agents on one file = silent overwrite.
- **Plain `terminal` only.** `execute_code` + grep/search crashes this project
  repeatedly; it killed 5 of 9 audit agents with zero deliverables.
- **Write files first**, then test. Read ≤5 files before editing.
- **Scope every pytest run to the agent's own directory.** Never bare `tests/` —
  three agents doing that turned 100s runs into 400s timeouts.
- **Never foreground `sleep`, never foreground a server.** Background it or the
  call wedges forever. Two agents were lost to this.
- **Split large scope by file.** Target ≤30 min. An 83-minute dive died.
- **Verify every agent claim yourself.** Every number above is a Manager run.
- **Have an adversary check the fixers.** One audit caught a false "green"
  claim, a false "I didn't touch that file" claim, and a stale xfail.
- **A phase's CI must not depend on commands the project hasn't made green.**
  That alone got phase 6 judged UNMAINTAINABLE.
- **Unverifiable here stays UNTESTED, honestly.** No Docker daemon, no Android,
  no systemd. Never claim what you could not run.
- **Record every lesson here**, not in a re-derivation next session.

---

## 7. Next actions, in order

1. Settle the proot question (§0). Blocked on this.
2. Re-measure every suite; update `docs/schedule.md`.
3. Contract tests for the console script and every route — catches the whole
   Class-A "code exists but is unreachable" class, which killed the last build.
4. Work the known-broken list in §3.
5. Implement [scheduling-behaviour.md](scheduling-behaviour.md) — clarification
   and the timezone prompt. This is the product's core interaction.
6. Build the client per [client-build-spec.md](client-build-spec.md).
7. Android: hand off to the Android Agent per [android-app.md](android-app.md).
8. `ruff check chronos tests` → 0.
9. Commit and tag per phase, per `docs/manager.md` §10.