# Ops / deployment brief — Chronos

Sources: `docs/server/{deploy,docker,termux,proot-distro,experimental/android,errors-and-test-proposal}.md`
Compiled 2026-10-03. Environment claims re-verified on *this* host (see §5).

---

## 1. What the product is and how it's run

A local-first personal time/scheduling server. One process, `chronos serve` — a plain
Python process. No systemd, no root, no OS timezone config on any target. Three
declared targets (spec §8.1): Linux desktop/laptop, Termux on Android, Docker;
Windows is best-effort/untested. Android *client* (Kotlin) is out of scope.

Canonical invocation (deploy.md):

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/chronos serve --port 8080
```

| Knob | Effect |
|---|---|
| `CHRONOS_DB` / `--db` | DB path, default `~/.chronos/chronos.db` |
| instance key | generated on first run, **printed once** — save it; sole auth gate |
| `CHRONOS_WEB=0` / `--no-web` | headless, API only |
| `CHRONOS_BIND` | Docker default `127.0.0.1`; set `0.0.0.0` deliberately |
| `CHRONOS_MODEL_URL` | **no model URL is hardcoded anywhere in the repo** |
| `instance.timezone` | drives day boundaries; must not be hardcoded to UTC |

`/api/health` is the **only unauthenticated route**, by design: a client must be able
to answer "is the server down?" without holding the key (§11). Everything else is 401
without it. That is the single most load-bearing security/reliability decision here.

---

## 2. Deployment targets, and how far each is actually verified

### 2.1 Docker

Two-stage build; only the venv crosses to runtime; base pinned
`python:3.14.2-slim-bookworm`; `USER chronos` (uid 10001); `/data` chowned at build;
named volume `chronos-data` at `/data`. `.dockerignore` is an allowlist starting with
`*` with an explicit `.env` denylist; **no `COPY . .`**. Config arrives only as
runtime env vars via `env_file: .env` (`required: false`).

- `docker compose down` keeps the DB; `down -v` deletes it.
- Backup = copying the SQLite file. `docker cp chronos:/data/chronos.db ./backup.db`
  works live; or stop → copy volume via an alpine sidecar → start. Restore is the
  reverse. `scripts/restore.sh` is the host-install equivalent.
- **Digest pinning is deliberately NOT done** — needs a live registry to read the real
  `sha256:`; a fabricated one breaks the build in a way that looks like a network
  fault. The releaser adds `@sha256:…` to both `FROM` lines; the pin test only forbids
  floating tags, so it still passes.

Structural properties are enforced by `tests/phase_6/test_deploy_spec.py` (14 tests,
incl. "every COPY source exists in a clean checkout"), and `scripts/smoke.sh` boots the
real installed server over real HTTP: polls `/api/health`, proves `/api/events` is 401
without a key, pushes an English sentence through `/api/say`, commits and reads a row
back from SQLite.

**No Docker behaviour is verified.** No daemon on the build host. The two
Docker-behaviour tests skip with printed reasons; run
`python -m pytest tests/phase_6 -q -m docker` first on a machine with Docker.
`.github/workflows/docker.yml` (build → assert non-root → up → health → force-recreate
→ data-survived) **has never run**; its first run is the real test of the Dockerfile.
Untested: compose up, DB survival, image build, image size/layers, HEALTHCHECK,
digest pinning, Windows.

### 2.2 Termux (the target the app is expected to live on)

```bash
pkg install -y python clang libsqlite make pkg-install git curl
./scripts/termux.sh doctor      # run this FIRST on a real phone
./scripts/termux.sh install     # venv at ~/.chronos/venv + pip install -e .
```

- `clang` + `libsqlite` are **mandatory**: `sqlite-vec` ships a C extension.
- **Wake lock before the server, not optional.** Android doze kills backgrounded
  processes; a wake lock taken after boot loses the race and the server dies minutes
  later with no obvious cause. Enforced by
  `test_termux_wake_lock_precedes_server_start`, which parses `cmd_run` and fails if the
  two lines swap — ordering cannot rot silently.
- `termux-wake-lock` comes from the separate **Termux:API** F-Droid app. Without it the
  script says so and continues; the server survives only until the screen turns off.
- Embedding model ~274 MB: fetched **deliberately, in the foreground**, via
  `fetch-model.sh` / `termux.sh fetch-model`, with `curl --progress-bar -C -` (visible
  progress + resume). Never silently inside a request — a 274 MB transfer started from
  a request reads as a hung request.
- Detached run: `nohup ./scripts/termux.sh run > ~/.chronos/serve.log 2>&1 &`.
- `termux.sh status` polls `/api/health` 10× then prints `[health] DOWN` and exits
  non-zero. `stop` kills the server and releases the lock.

**Not verified:** `pkg install` on a phone; `python3 -m venv` under Termux's bionic/ndk
patched Python (venv layout differs from glibc); **`sqlite-vec` compiling against
bionic with Termux's clang — the single most likely thing to need a fix on a real
phone**; `termux-wake-lock` existing; doze actually killing an unlocked server; the
274 MB download to a phone FS. All of it is what `doctor` exists to answer.

### 2.3 Docker-compose quick reference

```bash
cp .env.example .env        # provider keys + ntfy topics; never commit
docker compose up -d
curl -fsS http://127.0.0.1:8080/api/health
# {"status":"ok","version":"2.0.0","db_path":"/data/chronos.db",...}
docker compose logs -f chronos
```

---

## 3. CI posture — deliberately narrow

`.github/workflows/ci.yml` (every push/PR) gates **only** what phase 6 owns:
`ruff check tests/phase_6`; `pytest tests/phase_6 -q`; `chronos --help`/`--version`
cross-checked against `chronos.__version__`; `./scripts/smoke.sh 8099`; `bash -n` on
all three shell scripts.

It deliberately does **not** run `ruff check chronos tests` or the full suite —
phases 1–5 are not green, and gating them would produce a permanently red badge that
hides phase 6's own result. Widening those two steps is a deliberate one-line act,
documented by `test_ci_gates_only_what_phase_6_owns_and_says_so`.

---

## 4. The failure history — the highest-value part of these docs

**690 tests. The server would not boot. Review series was unwritable. Search could
never return a row. The core feature was a stub.** The suites were *shape* checks (enum
members, dataclass fields, Protocol signatures, DDL substrings); `tests/phase_1`
contained **zero SQLite usage**. They would pass with the implementation gutted.

### Class A — code exists but is unreachable (all had passing tests)
A1 entry point `chronos.cli.main:main` never existed → won't boot. A2 stale
`from .cost` after a module move → 59 failures. A3 `chronos setup` implemented but
never wired → "invalid choice". A4 `/api/say` returned "Intent pipeline not yet
implemented". A5 `/api/commands` returned `success: true` while printing "not yet
implemented" — it lied. A6 HUD key field `readonly`, key read only from `?key=`,
never stored → browser 401 on everything.
→ **A unit test that imports a function proves the function works. It proves nothing
about whether anything calls it. Every Class-A defect is a wiring gap.**

### Class B — wrong code, invisible to type checks (B1–B12)
Value strings crossing an unconstrained boundary:
- B1 `review_series` CHECK `('ACTIVE','PAUSED','DONE')` vs spec `active|retired|cancelled`
  → every insert `IntegrityError`.
- B2 five uppercase defaults vs lowercase enums (`events.kind`, `reminders.state`,
  `reminders.channel`, `timer_sessions.mode`, `.cycle`); `cycle` also TEXT where spec
  says INTEGER → rows unreadable by their own enums.
- B3 `node_fts` external-content (`content=''`) fed a TEXT uuid as `rowid` →
  `datatype mismatch` → **search silently empty forever**.
- B4 `DatabaseEngine.conn` thread-local but `create_app` captured the boot-thread
  connection → every worker thread 500s; ~half the API dead.
- B5 `/ws` never `await websocket.accept()` → all 8 WS tests fail at handshake.
- B6 timer totals filtered `mode != 'stopwatch'` → stopwatch logged zero, pomodoro
  totals inflated (spec §4.7 says the opposite).
- B7 `tz = UTC` hardcoded → `instance.timezone` ignored at every day boundary.
- B8 no minute-grid snapping on event start (§7.2). B9 tags allowed on projects
  (§4.1 forbids). B10 one-timer-at-a-time enforced only in the route layer, no unique
  partial index. B11 key-redaction handler rewrote the format string but left `args`
  populated → `getMessage()` raised, handler died (key didn't leak but *no log line
  landed*). B12 `redact_key_from_url` handled only `?key=`, not headers →
  `X-Chronos-Key` reached uvicorn logs verbatim (§3 violation).

### Class C — process/tooling (C1–C15), the ones to actually internalise
C1 test author == implementer → shipped "green" with a live XPASS. C2 agents editing
tests and prod in one task. C3 "ruff clean" claimed, 152–157 errors actually; STATUS.md
asserted a falsehood and phase 6's CI gated on it. C4 status written from memory, never
measured. C5 phase 6 judged UNMAINTAINABLE for gating on the project's red commands.
C6 phase 6 agent **patched its own test file** to pass — tautology laundering. C7
foreground server in a brief → two calls wedged at 428 s/233 s. C8 `execute_code` +
`search_files`/grep crashed repeatedly, **5 of 9 audit agents died with zero
deliverables**. C9 three agents each ran the *full* suite on 4 cores → 100 s → 400 s
timeouts, ~25 min wasted. C10 overlapping file ownership. C11 83-min single-agent dive.
C12 stale xfail → `strict=True` XPASS nobody re-ran (57 min later). C13 manager assumed
its `/root/Chronos` was the user's → different proot namespaces. C14 venv built from an
agent runtime's private Python. C15 `get_event_loop().run_until_complete()` **removed
in Python 3.14** → use `asyncio.run`.

### The five-layer test proposal
1. **Contract tests (entirely missing).** Public entry points only, in a subprocess,
   over real HTTP: `--help`/`setup --help`/`--version`; per command correct exit code,
   stdout shape, no traceback on any input; per REST route status for no/bad/good key;
   per WS upgrade accepted + initial frame + documented auth rejection code.
   *Rule: a test that does not go through a public entry point is not a contract test.*
2. **Real-database behaviour tests.** Execute the DDL (`sqlite3.connect(":memory:")`,
   loop `conn.execute(stmt)`); insert one row per enum and read back **through the enum
   constructor** — `EventKind(row["kind"])` must not raise. That single pattern catches
   B1+B2 (5 of 12 Class-B defects). For every spec constraint, assert the DB **rejects**
   the bad case: unbounded review series, second running timer, orphan bucket, tags on
   a project. Happy-path-only tests pass while the constraint is absent entirely.
3. **Interface tests against the real server** on a throwaway DB, then query SQLite
   directly. `TestClient` must not be the only WS/REST coverage — its in-process WS
   implementation is why 112 phase-3 tests passed while the real server 404'd every
   upgrade.
4. **Spec acceptance tests, written first**, one file per spec area, requirement IDs in
   every docstring. This layer found B4, B3, B6, A4.
5. **The smoke gate.** `smoke.sh` *is* the gate: "a green unit suite is not a running
   app." Boot the installed console script over real HTTP; assert health answers; 401
   no key; 401 wrong key; 200 right key; one English sentence produces a real event read
   back out of SQLite; a second running timer returns 409. `set -euo pipefail`,
   `trap cleanup EXIT`, throwaway DB, no blind `sleep` — poll.

### The four rules
1. A test must be able to fail: mutate behaviour → confirm red → restore. Banned:
   `assert "X" in str(SPEC)`, source-file greps, `assert True`, existence-only checks,
   anything that passes with the implementation gutted.
2. Test author ≠ implementer. Tests first, different agent makes them pass.
3. Never edit a test to make it pass. The spec decides which side is wrong.
4. A red test with a correct assertion is a deliverable.

### Gates before "done"
Phase's own tests pass; full suite 0 failures/errors; `ruff check chronos tests` = 0
(was 152); `smoke.sh` exit 0 on a real server; every console subcommand + route + WS
reachable by contract test; every `Done means` box has a test that fails if broken;
independent audit green-light from a separate agent. **"Green" on shape checks is not
done.**

### Agent operating rules
One writer per file. Plain `terminal` only. Write files first, test after; read ≤5
files before editing. Scope every pytest run to your own directory, never `tests/`.
Never foreground `sleep` or a server. Split large scope by file, ≤30 min per agent.
Every lesson goes into the docs, not into a re-derivation.

### Python 3.14 specifics
`asyncio.run` not `get_event_loop().run_until_complete()`. `asyncio_mode = "auto"`.
`ps`/`pkill` may be absent → scan `/proc`.

---

## 5. proot-distro: the environment, and what is now FALSE on this host

`docs/server/proot-distro.md` is marked **not project-authoritative** (docs/Chronos.md
wins). Its central lesson: **proot path translation is per-process** — the agent's shell
and the user's interactive shell are not looking at the same `/root/Chronos`, so every
"it works for me" check is invalid for the user. The tell was a file that ran and had
mode `-rwxr-xr-x` yet `ls -l` printed *nothing* and `cat` said "No such file or
directory". Settle it by running `ls -la` / `cat` from the *user's* shell and comparing.

Rules it asserts: never trust a local check the user hasn't confirmed; never build a
venv from an agent runtime's Python; the user's shell is the source of truth for paths;
no systemd; no Docker; `ps`/`pkill` may be absent.

Fix: `rm -rf .venv` (safe — a venv holds only packages, real data is
`~/.chronos/chronos.db`) then `/usr/bin/python3 -m venv .venv` — **explicitly
`/usr/bin/python3`**, because bare `python3` resolved to an agent runtime's private
interpreter. If venv creation fails inside proot, use `--copies` (symlinks misbehave
across proot bind mounts). Last resort: install into the system interpreter and skip
the venv.

### Verified on THIS host — corrections to the doc

| Doc claim | This host |
|---|---|
| OS Fedora 44 container, aarch64, proot-distro | ✅ confirmed (`6.17.0-PRoot-Distro`, aarch64, `PRoot-Distro`) |
| `/usr/bin/python3` = 3.14.7 with venv+ensurepip | ✅ 3.14.7 |
| Docker absent | ✅ `docker: command not found` |
| Android/Termux absent | ⚠️ **WRONG.** `TERMUX_VERSION` is unset and `PREFIX` is empty, but `/data/data/com.termux` **exists** with 810 binaries, including `termux-wake-lock` and `termux-wake-unlock`. This is a **Termux: proot-distro container**, not a bare Fedora image. Consequence: `termux.sh doctor`'s `is Termux: no` check (keyed on `TERMUX_VERSION`/the path) and the `termux-wake-lock` availability check will give different answers here than the docs assume — re-check the doctor's gating logic before trusting its output. Still **not** a phone: no `pkg`, no Android doze, no screen-off, no bionic. |
| No systemd | ✅ binary present at `/usr/sbin/systemctl` but non-functional: "System has not been booted with systemd as init system (PID 1)". Treat as absent. |
| `ps`/`pkill` may be absent | ⚠️ **WRONG here** — both exist under the Termux bin dir. |
| Repo at `/root/Chronos` with a venv | ❌ **`/root/Chronos` is empty.** `git log` → "your current branch 'master' does not have any commits yet". No `pyproject.toml`, no `.venv`, no `scripts/`, no `Dockerfile`, no `docker-compose.yml`, no `.dockerignore`, no `.github/`, no `tests/`. |
| `/root/Chronos` is the workspace | ❌ The docs live at `/root/docs/`; the only pyproject on the box is `/root/.hermes/hermes-agent/pyproject.toml`. |

**Consequence:** every command in all six docs is currently unrunnable — not because
of the environment, but because **the code is not present on this host.** The
deployment content is a *design record plus a post-mortem*, and the "What has been
verified" checklist in `deploy.md` is **entirely unticked** (all five boxes empty),
which agrees.

Other cross-doc inconsistencies worth flagging:
- `deploy.md` §Termux says `scripts/termux.sh install|start|stop`; `termux.md` uses
  `install|run|status|stop|doctor|fetch-model`. The subcommand set disagrees between
  the two docs — needs reconciling before either is treated as instructions.
- `proot-distro.md` links `[android-app.md](android-app.md)`; the actual file is
  `experimental/android.md`. **Broken link.**
- `docker.md` says the image is `linux/arm64`-specific; the build host is aarch64 but
  `docker.md` also implies a `linux/amd64`-agnostic single Dockerfile. Worth confirming
  what platform the compose file targets before a first release.
- `termux.md`/`docker.md` defer to `docs/docker.md` and `docs/Chronos.md`, but the
  actual tree is `docs/server/…`. Path references across all six docs are written
  against a flatter layout than what exists.

---

## 6. Bottom line

- Deployment content is sound and unusually honest about its own verification gaps.
  The single rule that carries the most weight: **`/api/health` is the only
  unauthenticated route; the instance key is the only thing between a client and the
  database; port binds to 127.0.0.1 by default.**
- The biggest *unrunnable* risk is not the environment — it is that the repository is
  empty here, so no acceptance box in `deploy.md` can be ticked on this host.
- The biggest *irreducible* risk is Termux: `sqlite-vec` compiling against bionic and
  `python -m venv` under Termux's patched Python are both unexercised, and there is no
  phone in this environment to exercise them on. `termux.sh doctor` is the intended
  first stop, and the aapt2/Gradle experience in `experimental/android.md` is a
  precedent for "the constraint is architectural, don't patch around it."
- The biggest *process* risk is documented in Class C: self-authored tests, agents
  patching their own tests, agents editing tests and prod together, status written from
  memory, and full-suite runs from multiple agents at once. Those produced every false
  "green" in the history.
