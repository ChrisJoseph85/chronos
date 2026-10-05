# Termux on Android — running Chronos on the phone

Phase 6, part 6.3. Spec: §8.1 target 2 (this is where the app is expected to
actually live, so it must work), §11 (Android doze, `/api/health`, the ~274 MB
embedding model).

No root. No systemd. No OS timezone configuration. The process is a plain
`chronos serve`.

---

## Install

One-time, in Termux:

```bash
pkg update -y
pkg install -y python clang libsqlite make pkg-install git curl
```

`clang` and `libsqlite` are not optional: `sqlite-vec` ships a C extension and
will not build without them.

Then, from your checkout (the directory containing `pyproject.toml`):

```bash
./scripts/termux.sh doctor      # what this phone supports
./scripts/termux.sh install     # venv + pip install -e .
```

`install` is a wrapper around exactly this:

```bash
python3 -m venv ~/.chronos/venv
~/.chronos/venv/bin/pip install -e /path/to/Chronos
```

## Fetch the embedding model — deliberately, in the foreground

The embedding model is roughly **274 MB**. It is not in the repository and it is
not downloaded silently inside a request: a 274 MB transfer started from
inside an HTTP request looks like a hung request and shows no progress.

```bash
CHRONOS_MODEL_URL=https://<your-host>/model.onnx ./scripts/fetch-model.sh
# or, equivalently
CHRONOS_MODEL_URL=https://<your-host>/model.onnx ./scripts/termux.sh fetch-model
```

No model URL is hardcoded anywhere in this repository — none is written down in
the spec, and guessing a host would mean downloading 274 MB of the wrong
weights. Set the variable. The download uses `curl --progress-bar -C -`, so it
shows progress and **resumes** if Android kills it mid-transfer.

`./scripts/termux.sh run` prints the size, the destination and the command to
run, and then starts the server. It never downloads for you behind your back.

## Run

```bash
./scripts/termux.sh run
```

That is:

```bash
termux-wake-unlock                     # clear a stale lock from a crashed run
termux-wake-lock                       # BEFORE the server starts
chronos serve --host 127.0.0.1 --port 8080
```

**The wake lock comes first, and this is not a style preference.** Android
doze kills backgrounded processes; a wake lock taken after the server is already
running can lose the race, and the server dies minutes later with no obvious
cause. `tests/phase_6/test_deploy_spec.py::test_termux_wake_lock_precedes_server_start`
parses `cmd_run` and fails if the two lines are swapped, so the ordering cannot
rot without a red test.

`termux-wake-lock` comes from the separate **Termux:API** app (F-Droid). Without
it the script says so plainly and continues — the server will work until the
screen turns off and Termux is backgrounded, at which point Android kills it.
Install Termux:API if you want the phone to survive a locked screen.

To run it detached:

```bash
nohup ./scripts/termux.sh run > ~/.chronos/serve.log 2>&1 &
```

## Check it is up

```bash
./scripts/termux.sh status
```

which polls `curl -fsS http://127.0.0.1:8080/api/health` up to 10 times and
then says `[health] DOWN` and exits non-zero.

`/api/health` is deliberately **unauthenticated**. A client has to be able to
answer "is the server down?" without holding the key — a health endpoint that
required auth would force the app to show a generic error instead of a clear
"server is down" state, or worse, spin forever (§11). Every other route is 401
without the instance key.

## Stop

```bash
./scripts/termux.sh stop      # kill the server, release the wake lock
```

---

## What was verified on the build host, and what was not

Build host: the `occ` prootdistro container on aarch64 (Fedora 44 userspace).
**This host is not Termux and not Android.** `TERMUX_VERSION` is unset and
`/data/data/com.termux` does not exist, so
`./scripts/termux.sh doctor` here reports `is Termux: no`.

### Genuinely verified here

- `bash -n scripts/termux.sh` — the script parses (`test_termux_script_is_valid_bash`).
- The script's **structure and ordering**, by parsing it rather than reading it:
  wake-lock-before-server-start, trap-and-release on EXIT, model announced at
  ~274 MB with `--progress-bar` and `--continue-at -` and offered *before* the
  server starts, a bounded polled health check that exits non-zero, `doctor`
  reporting honestly, no `su`/`sudo`/`systemctl` anywhere.
- `TERMUX` set or not, `cmd_run` refuses with a clear message instead of
  pretending (`need_termux`).
- The venv + `pip install -e .` step, because that step is identical on this host
  and Linux: `pip install -e .` from a clean checkout works and `chronos serve`
  boots and answers `/api/health` — proven by `scripts/smoke.sh`.

### NOT verified here — and honestly so

| Claim | Why it could not be checked |
|---|---|
| `pkg install python clang libsqlite` on a phone | no Termux, no Android, no `pkg` binary |
| `python3 -m venv` in Termux's prefix | Termux's Python is patched for bionic/ndk; the venv layout differs from a glibc host and this was **not** exercised |
| `sqlite-vec` compiling against bionic with Termux's clang | not exercised; this is the single most likely thing to need a fix on a real phone |
| `termux-wake-lock` existing and succeeding | the binary is not on this host |
| Android doze actually killing an unlocked server, and a wake lock preventing it | requires a physical device and a screen-off cycle |
| the ~274 MB model actually downloading to a phone filesystem | requires the phone and a real model URL |
| **Windows** (spec §8.1 target 3) | no Windows host; best effort, untested — see `docs/docker.md` |

Everything in the table above is exactly what
`./scripts/termux.sh doctor` exists to answer on a real phone. Run it there
first, before `install`, and expect to come back and adjust this document with
what it actually reports.

---

## Project-wide status, for context

`ruff check tests/phase_6` and `python -m pytest tests/phase_6 -q` are green on
this host. Project-wide `ruff check chronos tests` and the phases 1–5 test
suites are **owned by those phases and are not green yet** — phase 6 does not
gate them and does not claim otherwise. See `docs/docker.md`, "What CI does and
does not assert".
