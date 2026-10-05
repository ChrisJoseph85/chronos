# Termux on Android — running Chronos on the phone

Spec: `docs/server/Chronos.md` §8.1 target 2, §11. No root, no service
manager. The process is a plain `chronos serve` executed **inside** a
proot-distro guest. Termux's own python must NEVER run the app (version
drift is the bug).

## Naming constraint (honest)

You may want the guest to be called `chronos`. proot-distro does not allow
that: it names instances by distro (the login name IS the distro name, e.g.
`ubuntu`, `debian`, `fedora`). So:

```bash
DISTRO="${CHRONOS_DISTRO:-ubuntu}"
```

`scripts/termux.sh` uses `DISTRO="${CHRONOS_DISTRO:-ubuntu}"`, checks
`proot-distro list`, and only runs `proot-distro install "$DISTRO"` when the
instance is missing. There is no `chronos`-named instance; `chronos` is the
app that runs inside the `$DISTRO` guest.

## Install

One-time, in Termux. `pkg` is used ONLY for host bootstrap (proot-distro
itself) — never for the app python:

```bash
pkg update -y
pkg install -y proot-distro
```

Then, from your checkout:

```bash
./scripts/termux.sh install
```

which does, in order:

```bash
proot-distro list                      # check-before-install
proot-distro install "$DISTRO"         # only if the instance is missing
proot-distro login "$DISTRO" -- sh -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
proot-distro login "$DISTRO" -- sh -c "\$HOME/.local/bin/uv python install 3.14.7"
proot-distro login "$DISTRO" -- sh -c "cd <checkout> && \$HOME/.local/bin/uv venv ~/.chronos/venv && \$HOME/.local/bin/uv pip install -e ."
```

Details:

- `uv` is installed inside the distro via the official installer
  (`https://astral.sh/uv/install.sh`).
- The interpreter is pinned to exactly **3.14.7** (matches repo
  interpreters; `requires-python >=3.14`). Override with `CHRONOS_PYTHON`:

  ```bash
  CHRONOS_PYTHON=3.14.7 ./scripts/termux.sh install
  ```

- The venv and `uv pip install -e .` both run inside the distro
  (`uv venv`, `uv pip install -e .`). Termux-prefix python is never used.

Doctor reports guest state:

```bash
./scripts/termux.sh doctor
```

which checks `proot-distro` availability plus instance presence
(`proot-distro list` showing `$DISTRO` present vs missing).

## Embedding model — announced, with progress, never silent

The embedding model is roughly **274 MB**. It is not downloaded silently
inside a request. Fetch it deliberately first (the download runs INSIDE the
distro with a visible bar):

```bash
CHRONOS_MODEL_URL=https://<your-host>/model.onnx ./scripts/termux.sh fetch-model
```

Inside, that is `curl --progress-bar` (visible progress) with `-C -`
(resume) executed via `proot-distro login "$DISTRO"`.
`./scripts/termux.sh run` never downloads for you behind your back.

## Run

```bash
./scripts/termux.sh run
```

That is:

```bash
termux-wake-lock
proot-distro login "$DISTRO" -- sh -c "exec chronos serve --host 127.0.0.1 --port 8080 --db ~/.chronos/chronos.db"
```

The wake lock is taken on the Termux side **before** starting the server
inside the distro: Android doze kills a backgrounded server, and a lock
taken afterwards can lose the race. `termux-wake-lock` comes from the
Termux:API app; without it the script fails plainly instead of pretending.

Check it is up (polled from outside the distro; the guest shares the
Termux network namespace, so loopback works):

```bash
./scripts/termux.sh status
# polls http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/health
```

`/api/health` is the only unauthenticated route, so a client can show a
clear "server is down" state instead of a spinner that never resolves.

Stop:

```bash
./scripts/termux.sh stop
```

## Windows

Windows (§8.1 target 3) is best effort and untested here. The expected
path is `pip install -e .` plus `chronos serve`, but that expectation is
**not verified** on any Windows host in this environment.

## What was verified here, and what was not

Verified-here (parse only, structural):

- `bash -n scripts/termux.sh` parses.
- `scripts/termux.sh` checks `proot-distro list` before `proot-distro install`.
- `scripts/termux.sh` installs `uv` inside the distro and pins
  `uv python install 3.14.7`.
- `scripts/termux.sh` calls `termux-wake-lock` before `chronos serve`.
- The 274 MB model download path announces the size and hooks progress
  (inside the distro).
- `pytest tests/phase_6 -q` structural tests for the above are green.

Not-verified-here (no Termux/Android/daemon on this host — nothing here
executes proot-distro, pkg, or uv-for-aarch64-device):

- `pkg install` on a real phone (no Termux/Android on this host).
- `proot-distro install` / `proot-distro login` guest behaviour (no guest here).
- `uv` for an aarch64 device and `uv python install 3.14.7` on-device
  (nothing here executes uv-for-aarch64-device).
- `termux-wake-lock` behaviour and Android doze (needs a physical device).
- The 274 MB model actually downloading (needs a phone and a real URL).
- Windows (no Windows host available).
