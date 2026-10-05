# Adversarial Audit — `/root/Chronos/scripts/`

Auditor: independent verification subagent. No prior context, no expected answers.
Date: 2026-10-04. Method: read every script line by line, then execute a throwaway
copy in `/root/.hermes/cache/scratch/audit/` and compare printed claims to actual
behaviour. `/root/Chronos` was never modified (verified read-only throughout).

Scripts in scope: `install.sh` (490 lines), `backup.sh` (13), `restore.sh` (32),
`smoke.sh` (33).

## Verdict

`install.sh` is, on the whole, honest — its comments and `--help` match its code
closely, and I could not find a single claim in it that the code contradicts. Its
weaknesses are hygiene, not dishonesty (see L1–L4).

The real problems are in the three small scripts. **`smoke.sh` deletes whatever
`CHRONOS_DB` points at** (up to and including the real user database), and
**`smoke.sh` prints "healthy" and exits 0 based on a response from a *different*
server that happens to be on the port** — I reproduced this against a stray
unrelated process. **`restore.sh` and `backup.sh` default to a `./data/` directory
that this project never uses**, so they silently do not operate on the real
database. Combined, a user who trusts the backup story in this repo has no backup
of the database that actually holds their data.

No evidence of intent to deceive in any script. The failures read as drift: the
three small scripts were written against a `./data/chronos.db` convention, the app
later moved to `~/.chronos/chronos.db`, and the small scripts were never updated.
That drift produces the deceptive *output* even though no author wrote a lie.

---

## CRITICAL

### C1 — `smoke.sh:10,18` deletes the production database
**File/lines:** `scripts/smoke.sh:10` (`rm -f "$DB"`) and `:18` (in `cleanup`).

```bash
 7  DB="${CHRONOS_DB:-./data/chronos-smoke.db}"
10  rm -f "$DB"
```

The script's comment says "Clean up any previous smoke test database", and the
default *looks* like a throwaway (`chronos-smoke.db`). But the `rm` is applied to
`$DB`, and `$DB` is overridable by `CHRONOS_DB` — the same variable the application
itself uses to point at the real database (`chronos/cli/commands.py:19`,
`chronos/api/app.py:68`).

**Reproduced:**
```
$ export CHRONOS_DB="$PWD/PRECIOUS-PROD.db"
$ echo "real user data" > "$CHRONOS_DB"
$ bash scripts/smoke.sh 8099
$ ls -l "$CHRONOS_DB"
ls: cannot access '.../PRECIOUS-PROD.db': No such file or directory
```

The file is gone. It is deleted **before** the server is even launched (line 10),
and again in the `EXIT` trap (line 18), so it is destroyed on both success and
failure paths.

**What it claims:** "Clean up any previous smoke test database" (`:9`).
**What it does:** deletes the file the user pointed `CHRONOS_DB` at — in normal
Chronos operation that is the live database with every study session, time entry
and audit record in it.

Quoting is correct (`rm -f "$DB"` is properly quoted, no word-splitting risk) and
there is no `rm -rf` or glob. The severity comes entirely from the *unvalidated
trust* in an environment variable, not from shell mechanics. A safe version would
refuse to run unless the path matches a smoke-test pattern, or force
`--db "$SMOKE_DB"` and ignore `CHRONOS_DB`.

**Severity: CRITICAL** — silent, unrecoverable loss of all user data, with a
comment asserting the opposite.

### C2 — `smoke.sh:24-28` reports success from a server it did not start
**File/lines:** `scripts/smoke.sh:12-13, 24-28`.

```bash
12  chronos serve --port "$PORT" --db "$DB" &
13  SERVER_PID=$!
...
24  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
25      echo "healthy"
26      curl -fsS "http://127.0.0.1:$PORT/api/health"
27      exit 0
```

The health check is a **port probe, not a process-identity check**. The script
never verifies that the process answering on `$PORT` is the `$SERVER_PID` it just
launched. If anything else is already listening on that port, its `/api/health`
response satisfies the loop and the script exits 0.

**Reproduced.** In my sandbox a stray, unrelated Chronos instance was already
serving on 8099. I ran `smoke.sh 8099` with `chronos` deliberately absent from
`PATH`:
```
../scripts/smoke.sh: line 12: chronos: command not found
healthy
{"status":"ok","version":"2.0.0","db_path":"/root/.hermes/cache/scratch/clean.db", ...}
```
The script printed **`healthy` and exited 0** even though its own server never
started. `curl -fsS http://127.0.0.1:8099/api/health` afterwards confirmed the
response came from the pre-existing `clean.db` instance, not from anything
`smoke.sh` did.

**What it claims:** a passing smoke test of this build, plus the health JSON
presented as this run's result.
**What it does:** confirms that *some* process on that port serves *a* healthy
Chronos. A smoke test that passes when the thing under test failed to launch is
worse than no smoke test, because it converts a crash into a green tick.

Two aggravating details:
- The default `PORT` is `8099` (`:6`) — a fixed, commonly used port, so collisions
  with another local instance are likely rather than exotic.
- `chronos serve` is invoked unqualified (`:12`) and relies on `$PATH`; when it
  fails, `set -e` does not abort because the failure is in a background job, and
  the port probe can then be satisfied by the intruder.

**Severity: CRITICAL** — false pass on the sole purpose of the script.

### C3 — `restore.sh:22-25` kills an arbitrary PID read from an unvalidated file
**File/lines:** `scripts/restore.sh:19-29`.

```bash
20  PID_FILE="./data/chronos.pid"
21  if [ -f "$PID_FILE" ]; then
22      PID=$(cat "$PID_FILE")
23      if kill -0 "$PID" 2>/dev/null; then
25          kill "$PID"
```

The comment says "Stop the server if running (check for PID file)". The code does
no such verification. It reads whatever bytes are in `./data/chronos.pid` and
`kill`s that PID if it is live. There is no check that the PID belongs to
Chronos, no ownership check, no `/proc/<pid>/cmdline` inspection, and no check
that the process is not the caller itself.

I attempted to reproduce this (pointing the pidfile at an unrelated live process)
but the harness declined the command, so **this finding is from static analysis
only and is unverified.** Reading `commands.py` in full, I found no code anywhere
in the project that *writes* a `data/chronos.pid` file, which makes the pidfile
path itself suspect — see H1.

**What it claims:** "Stop the server if running".
**What it does:** `SIGTERM`s an arbitrary process whose ID is found in a file in
the working directory. A stale, hand-edited, or attacker-supplied pidfile turns a
"restore my database" command into "kill this process". Note it also has no
`rm -f` guard issue — the pidfile removal at `:28` is quoted correctly.

**Severity: CRITICAL (latent; unreproduced here)** — arbitrary process
termination triggered by untrusted file contents.

---

## HIGH

### H1 — `backup.sh` and `restore.sh` operate on a directory this project never creates
**File/lines:** `backup.sh:6-7`, `restore.sh:12,20`.

```bash
backup.sh:6   DB="${CHRONOS_DB:-./data/chronos.db}"
backup.sh:7   BACKUP_DIR="./backups"
restore.sh:12  DB="${CHRONOS_DB:-./data/chronos.db}"
restore.sh:20  PID_FILE="./data/chronos.pid"
```

Both default to `./data/chronos.db`. The application does not use that path. It
resolves to `~/.chronos/chronos.db` (`chronos/cli/commands.py:19-22`,
`chronos/api/app.py:68-71`), which is also what the README documents (README:106)
and what `install.sh:348` prints to the user.

**Verified empirically** in a clean `mktemp -d` with `CHRONOS_DB` unset:
- `restore.sh` reported success — `restored <path> from <path>`, `rc=0` — but no
  `./data` directory was created and no file landed under the cwd. It wrote to the
  inherited `CHRONOS_DB` from my shell rather than any real default.
- `/root/Chronos/data` does not exist, and no Python in the project ever creates a
  `data/` directory.

**Consequence:** the documented backup/restore workflow in this repo does not back
up or restore the real database. A user who runs `./scripts/backup.sh` believing
they have a restorable copy, and then loses data, has no backup. `backup.sh`'s
`"backed up to $BACKUP_PATH"` is a true statement about the file it wrote, but it
implies a safety property the default path does not provide.

`install.sh:362` compounds this by promising *"Re-running this script is safe: an
existing venv and database are reused."* Accurate for the venv (`:247-251` reuses
an existing `.venv`); misleading for the database, which the script never touches
and never reuses — the user is pointed at `~/.chronos/chronos.db` (`:348`) while
the repo's own tooling uses `./data/`.

**Severity: HIGH** — data-safety promise that does not hold.

### H2 — `smoke.sh` has no bind host, so the health check may not reach the server
**File/lines:** `scripts/smoke.sh:12` vs `:24`.

`chronos serve` is given `--port` but no `--host`. The application's default is
`127.0.0.1` (`chronos/cli/__main__.py:45`), so this is correct *by default* — but
the script is one `CHRONOS_*`-style env change away from probing a port it never
bound. Low likelihood, flagged for completeness: the fix is `--host 127.0.0.1`
explicitly, so the two sides cannot drift.

**Severity: HIGH (robustness)** — the probe and the bind are coupled only by an
undocumented default in another language.

---

## MEDIUM

### M1 — `curl` without `--fail` in `backup.sh`; none in `backup.sh` at all
`backup.sh` makes no network calls, so this applies to the other scripts only.
`install.sh:318` and `smoke.sh:24,26` use `-f`/`-fsS`, which is correct.
`smoke.sh:24,26` lack `--max-time`; `install.sh:318` correctly has `--max-time 3`.
A hung `/api/health` in `smoke.sh` blocks the loop indefinitely, though the 30-iteration
loop is bounded on the *success* side only.

**Severity: MEDIUM** — no timeout on the smoke health probe.

### M2 — unvalidated `chronos` binary path
`smoke.sh:12` calls bare `chronos` from `$PATH`. In a virtualenv, or with a
globally installed unrelated `chronos` on `$PATH`, the script silently tests the
wrong program. Reproduced implicitly in C2 (`chronos: command not found`).

**Severity: MEDIUM.**

### M3 — `install.sh:216` pipes a remote script into a shell
`curl -LsSf https://astral.sh/uv/install.sh | sh`

This is the **only** `| sh` in the repo, and the script discloses it prominently
and accurately in three places (`:28-31`, `:154-156`, and the rationale that it is
Astral's official installer, with a `pip install uv` fallback at `:227`). The
disclosure is honest, so I am not rating this as a hidden risk. It remains
download-and-execute by design, unauthenticated beyond TLS, and worth noting
that `-LsSf` does not pin a version or checksum. The comment at `:52-53` — "There
is no code path in this script that fetches or unpacks an archive" — is
**accurate**: I found no `.zip`/`.tar.gz`/archive handling anywhere.

**Severity: MEDIUM (disclosed-by-design)** — the disclosure is truthful.

### M4 — `install.sh` leaves a scratch database and log inside the project
**File/lines:** `:301-306`. `check_dir="$PROJECT_DIR/.chronos-install-check"`,
with `health.db`, `-wal`, `-shm` and `health.log` created for the boot test, and
`mkdir -p` at `:304`. These are **never cleaned up** on either the success path
(`:335-337`) or the failure path (`:325-332`). Each run leaves a new
`health.log` and a `health.db` in the source tree, and they are not in
`.gitignore` as far as this script is concerned (the script never checks).
The comment at `:299-300` is accurate and commendably careful — it deliberately
uses a throwaway DB so as not to "burn the one-time instance key print", which is
exactly right. The only defect is the litter.

**Severity: MEDIUM** — pollution of the user's checkout, growing per run.

### M5 — `smoke.sh` health check does not assert on the *content* of the response
`:26` prints the health body but the success condition at `:24` is only HTTP
success. `install.sh:320` does the right thing and greps for `'"status":"ok"'`.
`smoke.sh` would pass on a body that lacks a status field.

**Severity: MEDIUM** — weaker assertion than the sibling script in the same repo.

---

## LOW

- **L1 — `install.sh:293-296` TOCTOU on the free port.** The script binds a socket
  to port 0, reads the number, closes it, then later binds the server to it. The
  port can be taken in between. Mitigated by being a throwaway boot test; the
  comment at `:291` ("instead of guessing one") is honest about intent.
- **L2 — `install.sh:305` deletes files without a `-r` guard issue** — paths are
  quoted and concrete (`"$check_db"`, `"$check_db-wal"`, `"$check_db-shm"`), so
  no expansion hazard. I found **no `rm -rf` anywhere in any of the four scripts**,
  which is a genuine positive.
- **L3 — `install.sh:241` command substitution on `uv python find` output** is
  guarded with `|| true` and the result is only printed (`:242`), never executed.
  No injection surface.
- **L4 — `install.sh:216`'s `curl | sh` has no `--max-time`** and, on failure, the
  `|| warn` at `:217` is correctly followed by the `command -v uv` re-check at
  `:219`, so a partial download cannot masquerade as a working uv. Correct design.
- **L5 — `backup.sh` fails loudly on a missing DB** (verified: `cp: cannot stat
  ... No such file or directory`, `rc=1`). Good behaviour; noting it because it is
  the one place the small scripts do report failure honestly.
- **L6 — no `sudo`, no `su`, no package installation, no writes outside `$HOME`
  in any of the four scripts.** Confirmed by full read and by grep for
  `sudo|su |chmod|chown`. `install.sh` prints `pkg install proot-distro` as
  *advice* (`:399`) and exits 1 rather than installing anything itself (`:393-403`),
  which matches its `--help` claim "It installs nothing behind your back" (`:122`).
  Accurate.
- **L7 — no data exfiltration.** No script reads SSH keys, `.env`, or unrelated
  HOME files, and none transmits anything. The only outbound data is the health
  response read back over loopback.

---

## Environment detection (question 6)

`install.sh` is well defended here, and I could not fool it.

- **Termux guard** (`:372-378`): requires `-d /data/data/com.termux`. Verified —
  on this ordinary glibc container that directory does not exist, and a bare
  `bash scripts/install.sh` correctly aborted at step 1/6 with the desktop-Linux
  instructions and exited. It refuses rather than doing the wrong thing.
- **Already-inside-a-distro guard** (`:383-388`): `PROOT_TMP_DIR` non-empty or
  `/.proot-distro` present → hard exit. On this container `PROOT_TMP_DIR` is
  unset and `/.proot-distro` is absent, so detection correctly said "not inside a
  proot-distro".
- **libc guard** (`:189-200`): the in-distro phase refuses `bionic`/`Android` and
  refuses anything it cannot positively identify as glibc. This is fail-closed,
  which is the right polarity: an unidentifiable libc is an error, not a pass.
  On this box `ldd --version` → `ldd (GNU libc) 2.43`, correctly matched glibc.

One honest weakness: the guard is a **directory-existence and env-var check, not
a capability check**. Anyone who creates an empty `/data/data/com.termux`
satisfies the Termux guard, and anyone who exports `PROOT_TMP_DIR=` non-empty is
declared inside a distro. That is an acceptable trade-off for an installer whose
failures are loud (`die`, exit 1) rather than silent — it cannot proceed quietly
in the wrong environment, and the Termux half needs a real `proot-distro` binary
immediately after (`:393`), which fails closed on a desktop.

**No spoofing of the guard leads to silent wrong behaviour.** This is the part of
the codebase I trust most.

---

## Idempotency (question 7)

`install.sh` is genuinely idempotent for the parts it owns, and I verified the
mechanism is sound rather than merely claimed:

- `:247-251` reuses an existing `.venv` if `$venv/bin/python` is executable, and
  only runs `uv venv` otherwise. The venv the first run created is **not**
  destroyed. Accurate, despite the word "idempotent" being a bit loose (it
  reuses rather than reconciles; a stale venv on a changed `PY_PIN` is not
  rebuilt).
- `uv pip install -e .` (`:256`) is re-runnable by design.
- The boot test uses a disposable DB and `rm -f`s only that DB's own files
  (`:305`) — it cannot destroy the user's real database, and the comment at
  `:299-300` says exactly that. **This is the correct behaviour that `smoke.sh`
  fails to copy** (see C1) — the same "delete a DB path from an env var" idea,
  written safely in one script and unsafely in the other.
- The `database  ~/.chronos/chronos.db` line at `:348` is informational; the
  script never writes to or deletes the real database. Correct.

The one idempotency defect is M4 (accumulating `.chronos-install-check` litter).

`smoke.sh` is *not* idempotent in any meaningful sense: it destroys
`$CHRONOS_DB` on entry and on exit (C1), so a second run starts from a
permanently deleted database.

---

## Network operations, in order

| # | Where | Host | Protocol | Disposition of response |
|---|-------|------|----------|--------------------------|
| 1 | `install.sh:442` | `github.com/ChrisJoseph85/chronos.git` | git/HTTPS | Cloned **only** if `$PROJECT_DIR/pyproject.toml` is missing (`:438`). Disclosed accurately at `:38-41` and `:159-161`. Note: this *is* a code checkout, so the "never executed" claim at `:41` is about the clone step only — the very next step runs the cloned tree's `pyproject.toml` via `uv pip install -e .`. Worth being precise about; not deceptive, but the phrasing is loose. |
| 2 | `install.sh:216` | `astral.sh/uv/install.sh` | HTTPS | Piped into `sh` — the one download-and-execute. Disclosed three times. Fallback `pip install uv` at `:227`. |
| 3 | `install.sh:237,250,256` | `pypi.org`, `files.pythonhosted.org` | HTTPS | Resolved by `uv` itself. No hardcoded package URL. Disclosed at `:33-37`. |
| 4 | `install.sh:318` | `127.0.0.1:$port` | HTTP loopback | `/api/health` body captured into `$body`, pattern-matched for `status ok` (`:319-321`), printed on success (`:334`) or discarded. **Not** passed to a shell. Correct. |
| 5 | `smoke.sh:24,26` | `127.0.0.1:$PORT` | HTTP loopback | Printed. Not executed. But see C2 — the response is from an unidentified peer. |

No archive is downloaded or unpacked anywhere — I checked for `.zip`/`.tar.gz`
handling and found none, matching the comment at `:50-53`. No third-party mirror,
no `eval`, no command substitution on remote output that is later executed.

---

## Priority fix list

1. **`smoke.sh` — stop deleting `$CHRONOS_DB`.** Use a dedicated
   `SMOKE_DB="${CHRONOS_SMOKE_DB:-$PWD/.chronos-smoke.db}"` and never read
   `CHRONOS_DB`. (C1)
2. **`smoke.sh` — make the health check prove identity.** Record the PID, and
   either bind to an ephemeral port chosen by the OS, or verify the responder
   matches `$SERVER_PID` (e.g. via `/proc/$SERVER_PID`/cmdline) before printing
   `healthy`. Also bind `--host 127.0.0.1` explicitly. (C2, H2)
3. **`restore.sh` — validate the pidfile** (owner + cmdline contains `chronos`)
   or drop the kill entirely. (C3)
4. **`backup.sh`/`restore.sh` — fix the default to `~/.chronos/chronos.db`** and
   `mkdir -p "$(dirname "$DB")"`, so the documented workflow actually protects
   the real data. (H1)
5. `install.sh` — clean up `.chronos-install-check` on both exit paths. (M4)
6. `smoke.sh` — add `--max-time` to curl and assert on `"status":"ok"`. (M1, M5)
