# Errors catalogue and test-system proposal

**Written:** 2026-10-03 by the previous Manager. **Not project-authoritative —
`docs/Chronos.md` wins.**

Full of specifics from a build that failed. Sourced from measured runs, not
recollection.

---

# PART 1 — Every error, grouped by class

Ordered by how much damage each did.

## Class A — Code exists but is unreachable

**The expensive class. All of these had passing tests.**

| # | Defect | Symptom | Why tests missed it |
|---|---|---|---|
| A1 | Entry point → `chronos.cli.main:main`, module never existed | Server could not boot | `smoke.sh` never ran; unit tests import modules directly |
| A2 | `pipeline/tools.py` did `from .cost` after a module move | `import chronos.ai` failed → ~59 failures | No test did a clean top-level package import |
| A3 | `chronos/ai/setup.py` implemented interactive setup; never wired into the CLI | `chronos setup` → "invalid choice" | No test ran the console script's subcommand list |
| A4 | `/api/say` returned `"Intent pipeline not yet implemented"` | The core feature did nothing | Phase 2 tested `IntentParser`/`ToolDispatcher` as objects; nothing tested that the route *called* them |
| A5 | `/api/commands` returned `success: true` while printing "not yet implemented" | Silently lied | No test asserted an honest success flag |
| A6 | HUD key field `readonly`; key only read from `?key=`, never stored | Browser could not authenticate — every request 401 | No browser/HTTP-level HUD test |

**Root pattern:** a unit test that imports a function and calls it proves the
function works. It proves nothing about whether anything *calls* it. Every
A-class defect is a wiring gap, and wiring is invisible to unit tests.

## Class B — Wrong code, invisible to type checks

| # | Defect | Symptom |
|---|---|---|
| B1 | `review_series` CHECK `('ACTIVE','PAUSED','DONE')`; spec §4.4 says `active\|retired\|cancelled` and declares **no CHECK** | Every insert raised `IntegrityError`. Spaced repetition unwritable |
| B2 | Five uppercase defaults vs lowercase enums: `events.kind`, `reminders.state`, `reminders.channel`, `timer_sessions.mode`, `timer_sessions.cycle` | Rows read back could not be parsed by their own enums. `cycle` also `TEXT` where spec says `INTEGER` |
| B3 | `node_fts` external-content (`content=''`) but inserted a TEXT uuid as `rowid` | `datatype mismatch` — **nothing could ever be indexed**; search silently empty forever |
| B4 | `DatabaseEngine.conn` thread-local, but `create_app` captured the boot-thread connection | Every worker-thread request → `sqlite3.ProgrammingError` → 500. ~Half the API dead |
| B5 | `/ws` never called `await websocket.accept()` | All 8 WebSocket tests failed at handshake |
| B6 | Timer totals filtered `mode != 'stopwatch'` | Stopwatch logged **zero**; pomodoro breaks **inflated** totals. §4.7 says the opposite |
| B7 | `tz = UTC` hardcoded | `instance.timezone` ignored for every day boundary (§7.1) |
| B8 | `EventRepo.create` stored raw ms | No minute-grid snapping (§7.2) |
| B9 | Tags accepted on projects | §4.1 says "never to projects" — unenforced |
| B10 | One-timer-at-a-time only in the route layer | No unique partial index; a second running timer inserts fine (§4.7) |
| B11 | `install_key_redaction` rewrote the format string but left `args` populated | `getMessage()` raised; handler died. Key never leaked but *no log line landed anywhere* |
| B12 | `redact_key_from_url` handled only `?key=`, not headers | `X-Chronos-Key` reached uvicorn's logs verbatim (§3 violation) |

**Root pattern:** string values crossing a boundary unchecked — enum values,
SQLite TEXT, config strings, log records. Every one is a place a value was
supposed to be constrained and wasn't.

## Class C — Process and tooling failures

| # | Failure | Consequence |
|---|---|---|
| C1 | **Test author and implementer were the same agent** | Phase 1 shipped "green" containing a live XPASS failure |
| C2 | **Agents edited tests and production code in one task** | Weakened assertions always a risk |
| C3 | "ruff clean" claimed — actual 152–157 errors | STATUS.md asserted a falsehood; phase 6's CI gated on it |
| C4 | Status doc written from memory, never measured | Every "completed" claim false |
| C5 | Phase 6 judged UNMAINTAINABLE because its CI ran `ruff check chronos tests` and the full suite — both red | Self-inflicted: a phase's CI must not depend on commands the project hasn't made green |
| C6 | Phase 6 agent patched **its own test file** to make assertions pass | Textbook tautology laundering |
| C7 | **Foreground server in an agent brief** | Two tool calls wedged at 428s and 233s; agents blocked forever |
| C8 | `execute_code` + `search_files`/`grep` | Crashed repeatedly; 5 of 9 audit agents died with zero deliverables |
| C9 | Three agents each ran the **full** suite concurrently on 4 cores | 100s runs became 400s timeouts; ~25 min wasted |
| C10 | Two agents given overlapping files | Silent overwrite risk |
| C11 | An 83-minute single-agent dive | Partial work, then death |
| C12 | Test edited after an xfail went stale | Validation landed 57 min after the test; `strict=True` flipped to XPASS, nobody re-ran |
| C13 | Manager assumed its `/root/Chronos` was the user's | Different proot namespaces — every "works for me" check invalid for the user |
| C14 | Venv built from an agent runtime's private Python | Not reproducible outside that tool |
| C15 | `get_event_loop().run_until_complete()` in tests | Removed in Python 3.14; needed `asyncio.run` |

---

# PART 2 — Test system

## The core finding

**690 tests. Server would not boot. Review series unwritable. Search could never
return a row. The core feature was a stub.**

The suites were *shape* checks — enum members, dataclass fields, Protocol
signatures, DDL substrings. `tests/phase_1` contained **zero SQLite usage**. They
would pass with the implementation gutted.

So the proposal is not "more tests." It is a different *kind* of test, plus
process rules that make green mean something.

## Layer 1 — Contract tests (entirely missing)

Every Class-A defect was a wiring gap. Contract tests close that class by testing
**only public entry points, in a subprocess, over real HTTP.**

```bash
chronos --help
chronos setup --help
chronos --version
```

Then per command: correct exit code, expected stdout shape, **no traceback on any
input**. Per REST route: reachable, correct status for no-auth/bad-key/good-key.
Per WebSocket: upgrade accepted, initial frame delivered, auth rejected with the
documented code.

**Rule: a test that does not go through a public entry point is not a contract
test.**

## Layer 2 — Real-database behaviour tests

No shape checks on DDL. Execute it.

```python
conn = sqlite3.connect(":memory:")
for stmt in DDL_STATEMENTS:
    conn.execute(stmt)          # the DDL must actually run
```

Then insert a row per enum, read back **through the enum constructor**:
`EventKind(row["kind"])` must not raise. That one pattern catches **all of B1
and B2** — five of twelve Class-B defects.

For every constraint the spec states, assert the database **rejects** the bad
case: unbounded review series, second running timer, orphan bucket, tags on a
project. Happy-path-only tests pass while the constraint is missing entirely.

## Layer 3 — Interface tests against the real server

Boot the actual `chronos serve` on a throwaway DB, talk to it with real HTTP,
and **query SQLite directly afterwards** to confirm state.

`TestClient` is fine for handler-level logic but **must not be the only**
WebSocket/REST coverage — it carries its own in-process WebSocket
implementation, which is precisely why 112 phase-3 tests passed while the real
server returned 404 on every upgrade.

```bash
chronos serve --host 127.0.0.1 --port $PORT --db /tmp/t.db &
curl ... # with and without the key
sqlite3 /tmp/t.db "select id,title,starts_at_ms from events;"
```

## Layer 4 — Acceptance tests from the spec, written first

One file per spec area, with requirement IDs in every docstring. This layer
found the real defects — the thread-local connection, the FTS rowid, the timer
inversion, the `/api/say` stub. Written after the fact, it paid for itself
immediately.

## Layer 5 — The smoke gate

`smoke.sh` is the real gate: *"a green unit suite is not a running app."* It must
boot the installed console script over real HTTP and assert: health answers; 401
without a key; 401 with a wrong key; 200 with the right key; **one English
sentence produces a real event, read back out of SQLite**; a second running timer
returns 409. `set -euo pipefail`, `trap cleanup EXIT`, throwaway DB, no blind
`sleep` — poll.

## The four rules

1. **A test must be able to fail.** Mutate the behaviour, confirm red, restore.
   Banned: `assert "X" in str(SPEC)`, source-file greps, `assert True`,
   existence-only checks, anything that passes with the implementation gutted.
2. **The test author is not the implementer.** Tests first, then a *different*
   agent makes them pass. Same-agent authoring produced green tests and a broken
   product.
3. **Never edit a test to make it pass.** The spec decides which side is wrong.
4. **A red test with a correct assertion is a deliverable.**

## Gates before any phase is called done

| Gate | Threshold |
|---|---|
| Phase's own tests | all pass |
| Full suite | 0 failures, 0 errors |
| `ruff check chronos tests` | **0** — was 152 |
| `scripts/smoke.sh` | exit 0, real server |
| Contract tests | every console subcommand + route + WS reachable |
| Spec coverage | every `Done means` box has a test that fails if broken |
| Independent audit | green-light verdict from a separate agent |

**"Green" on shape checks is not done.** That was the central mistake, and it is
what let a non-booting server get called complete.

## Process rules for agents

- **One writer per file.** Two agents on one file = silent overwrite.
- **Plain `terminal` only.** `execute_code` + grep/search crashes.
- **Write files first**, then test. Read ≤5 files before editing.
- **Scope every pytest run to the agent's own directory.** Never `tests/`.
- **Never foreground `sleep`, never foreground a server.** Background it or the
  call hangs forever.
- **Split large scope by file**, target ≤30 min per agent.
- **Every lesson learned goes into the docs**, not into a re-derivation.

## Environment facts that are easy to get wrong

- **Build and verify in the same proot view the user sees.** Confirm before
  trusting any "works for me" (C13).
- Venv from `/usr/bin/python3`, never an agent runtime's private Python (C14).
- **No Docker daemon, no Android/Termux, no systemd.** Those boxes stay honestly
  UNTESTED and go to CI. Never claim them.
- Python 3.14: `asyncio.run`, not `get_event_loop().run_until_complete()` (C15).
- `asyncio_mode = "auto"` in pytest config.
- `ps` and `pkill` may be absent — use `/proc` scanning.