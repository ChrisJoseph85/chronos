# proot-distro — this environment and the "No such file or directory" error

**Written:** 2026-10-03 by the previous Manager. **Not project-authoritative.**

---

## 1. What this environment is

Verified, not guessed:

| Fact | Value |
|---|---|
| OS | **Fedora Linux 44 (Container Image)** |
| Arch | **aarch64** |
| Sysroot | **proot-distro** (no systemd) |
| System Python | **`/usr/bin/python3` → 3.14.7** — has `venv` + `ensurepip` |
| Docker | **absent** (`docker: command not found`) |
| Android/Termux | **absent** |

There is a perfectly good Python at `/usr/bin/python3`, and it is exactly the
3.14 the project targets.

---

## 2. THE ERROR: "No such file or directory" for files that exist

What was seen:

```bash
.venv/bin/chronos setup
bash: .venv/bin/chronos: No such file or directory

head -c 100 /root/Chronos/.venv/bin/chronos
head: cannot open '...': No such file or directory
```

The file existed — 181 bytes, mode `-rwxr-xr-x`, and it ran. `ls -l` on it
printed **nothing at all**: not an error, just empty. `cd` into the directory
worked.

### Cause: proot path translation is per-process

Each process gets its own translated view of the filesystem. The Manager's shell
and the user's interactive shell are **not looking at the same
`/root/Chronos`**. A venv created by the Manager existed in the Manager's view
and not in the user's — so every "it works here" check was invalid for them.

### The diagnostic that settles it

Run from the user's shell. If the file appears, the namespaces differ:

```bash
ls -la /root/Chronos/.venv/bin/ | head
cat /root/Chronos/.venv/bin/chronos 2>&1 | head -2
```

Compare with what the Manager sees. If they disagree, that is the namespace
problem confirmed.

---

## 3. Fix: build the venv in the USER's view

```bash
cd /root/Chronos
rm -rf .venv .venv-local
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/chronos --version
```

- **`/usr/bin/python3` explicitly.** Bare `python3` may resolve to an agent
  runtime's private interpreter (it did — `PATH` had an agent tools directory
  ahead of `/usr/bin`). A venv built from a tool runtime is not reproducible
  outside that tool, which was the second half of the error.
- **`rm -rf .venv` is safe.** A venv holds only installed packages. Real data is
  `~/.chronos/chronos.db`, untouched.
- **`pip install -e .`** takes a couple of minutes; ignore the pip upgrade notice.

If `python3 -m venv` fails inside proot:

```bash
/usr/bin/python3 -m venv --copies .venv
```

`--copies` avoids symlinks, which behave oddly across proot bind mounts.

### If it still fails

Capture the real error — bash's message is generic and misled both sides:

```bash
.venv/bin/python --version
.venv/bin/python -c "print('ok')"
head -1 .venv/bin/chronos
ls -la .venv/bin/ | head -20
```

A "No such file or directory" from `.venv/bin/python` itself means the venv is
half-built in that view — delete and rebuild with `--copies`.

---

## 4. Rules for this environment

1. **Never trust a local check the user has not confirmed.** Build it, then ask
   them to run one command. Their view is the real one.
2. **Never build a venv from an agent runtime's Python.** Always
   `/usr/bin/python3`.
3. **The user's shell is the source of truth for paths.** If ambiguous, ask for
   `pwd` and `ls -la` from their side.
4. **No systemd.** No service management, no Docker daemon.
5. **`docker` is unavailable.** Docker acceptance criteria cannot be verified
   here — delegate to CI and label them honestly.
6. **aarch64 host, x86_64 Android tools** — see [android-app.md](android-app.md).
7. **`ps` and `pkill` may be absent.** Agents hit this; use `/proc` scanning or a
   helper script instead.

---

## 5. Quick reference

```bash
pwd && ls -la /root/Chronos | head
/usr/bin/python3 --version                    # expect 3.14.7
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/chronos serve --port 8080
./scripts/smoke.sh 8099                       # the project's own gate
```

**Last resort** if venvs keep breaking across the proot mount — install to the
system interpreter and skip the venv entirely:

```bash
/usr/bin/python3 -m pip install -e .
chronos serve --port 8080
```

Less isolated, but it removes a whole class of proot problems.