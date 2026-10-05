# Termux on Android — running Chronos on the phone

Spec: `docs/server/Chronos.md` §8.1 target 2, §11. No root, no systemd.
The process is a plain `chronos serve`.

## Install

One-time, in Termux:

```bash
pkg update -y
pkg install -y python git rust binutils libsqlite
```

Then, from your checkout:

```bash
./scripts/termux.sh install
```

which runs `python3 -m venv ~/.chronos/venv` and
`pip install -e .` in it.

## Embedding model — announced, with progress, never silent

The embedding model is roughly **274 MB**. It is not downloaded silently
inside a request. Fetch it deliberately first:

```bash
CHRONOS_MODEL_URL=https://<your-host>/model.onnx ./scripts/termux.sh fetch-model
```

The download shows progress (`curl --progress-bar`) and resumes (`-C -`).
`./scripts/termux.sh run` never downloads for you behind your back.

## Run

```bash
./scripts/termux.sh run
```

That is:

```bash
termux-wake-lock
chronos serve --host 127.0.0.1 --port 8080 --db ~/.chronos/chronos.db
```

The wake lock comes **before** the server starts: Android doze kills a
backgrounded server, and a lock taken afterwards can lose the race.
`termux-wake-lock` comes from the Termux:API app; without it the script
fails plainly instead of pretending.

Check it is up:

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

`/api/health` is the only unauthenticated route, so a client can show a
clear "server is down" state instead of a spinner that never resolves.

## Windows

Windows (§8.1 target 3) is best effort and untested here. The expected
path is `pip install -e .` plus `chronos serve`, but that expectation is
**not verified** on any Windows host in this environment.

## What was verified here, and what was not

Build host: proot-distro container (Fedora 44 aarch64). This host is not
Termux and not Android — no `/data/data/com.termux`, no `pkg` binary.

Verified here:

- `bash -n scripts/termux.sh` parses.
- `scripts/termux.sh` calls `termux-wake-lock` before `chronos serve`.
- The 274 MB model download path announces the size and hooks progress.
- `pytest tests/phase_6 -q` structural tests for the above are green.

Not verified here:

- `pkg install` on a real phone (no Termux/Android on this host).
- `termux-wake-lock` behaviour and Android doze (needs a physical device).
- The 274 MB model actually downloading (needs a phone and a real URL).
- Windows (no Windows host available).
