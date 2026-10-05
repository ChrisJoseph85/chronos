# Environment corrections — this host

**Status:** FACT RECORD — do not re-derive
**Date:** 2026-10-04
**Purpose:** three statements about this build host are wrong as they appear in
the docs or in build logs. They are corrected here once so that no future
session, smoke check or doctor script wastes a pass rediscovering them.

**Rule:** when a doc or a script disagrees with this file, this file is right
about the host. Where this file contradicts a *proposal*, the proposal is
governing about the product and this file is governing about the machine.

---

## 1. "Android/Termux is absent" — WRONG

**The claim:** the build host has no Termux, so
`phase-6-deploy.md` §C.7 lists `termux-wake-lock` / `termux-wake-unlock`
among the things that "could not be tested here", and a doctor script reports
Termux absent.

**The correction:** `/data/data/com.termux` **exists**, with roughly **810
binaries** in it, including both:

- `termux-wake-lock`
- `termux-wake-unlock`

This host is a **Termux-hosted proot-distro** — the proot userland runs inside a
Termux prefix on Android. So the two commands `phase-6-deploy.md` §C.3.2 and
§C.3.3 mandate are, in fact, **present and callable here**.

**But do not trust `scripts/termux.sh doctor` on this host.** `TERMUX_VERSION`
and `PREFIX` are **both empty** in the environment, because this session runs
under the proot userland rather than under Termux's own login shell. Every
conventional Termux detection heuristic keys on `$PREFIX` or
`$TERMUX_VERSION`, so `doctor` will report `is Termux: no` — a **false
negative**. The detection is wrong; the host is not.

**What to do:**
- Treat `doctor`'s Termux answer as **meaningless on this host**, not as
  evidence of absence.
- Test the wake-lock path by invoking `termux-wake-lock` directly rather than
  gating on the doctor result.
- Do not edit `decisions.md` or `phase-6-deploy.md` §C.7 to claim Termux paths
  are verified. Whether the wake lock actually takes effect still depends on
  Android doze permissions and the Termux:API add-on, and neither can be
  confirmed from inside proot. §C.7's *substantive* claim — "Android doze
  behavior cannot be simulated in proot" — remains true regardless.

---

## 2. "ps and pkill may be absent" — WRONG

**The claim:** process tools may not exist on this host, so any script using
them needs a fallback branch.

**The correction:** **both `ps` and `pkill` are present.** No fallback needed.

**What to do:** write `scripts/smoke.sh`, `scripts/termux.sh` and
`scripts/restore.sh` against plain `ps`/`pkill` without a non-POSIX branch.
Note that `phase-6-deploy.md` §C.3.3 `stop` reads the PID from
`$HOME/.chronos/server.pid` rather than using `pkill` — that remains the better
design (a PID file cannot kill an unrelated process), but the absence of a
process-tool fallback is no longer a reason for it.

---

## 3. `systemctl` exists but is non-functional — treat it as ABSENT

**The claim:** a check that finds `systemctl` on `PATH` concludes systemd is
available and the deployment is supervised.

**The correction:** `/usr/sbin/systemctl` **exists on this host**, and it is
**non-functional**. Invoking it returns the refusal:

> `System has not been booted with systemd as init system`

There is no systemd here. There will not be one.

**Rule: treat `systemctl` as absent on this host, and never let a smoke check
or doctor pass on its mere existence.** Existence of the binary is not evidence
of a working init system — check for the actual condition (a booted systemd
`/run/systemd/system`, or a successful `systemctl is-system-running`), not for
the file.

This is consistent with, not a counterexample to, `phase-6-deploy.md` §0
principle 1 and §F.5:

> "The server is a plain `chronos serve` process — **no systemd**, no root, no
> OS timezone configuration (§8.1)."

> "**No systemd unit files** (§8.1 — "no systemd"). **No root-required
> scripts** (§8.1 — "no root")."

So the frozen design already excludes systemd. The only open question is
verification hygiene: a naive `command -v systemctl` probe gives a false
positive here, and any test asserting "no systemd" must assert the *absence of
supervision*, not the absence of a binary.

---

## 4. Still true — do not "correct" these

These four held up and are recorded so they are not re-litigated:

| Fact | Value |
|---|---|
| Distribution | **Fedora 44** |
| Architecture | **aarch64** (ARM64) |
| Isolation | **proot-distro** (see §1 above — hosted by Termux) |
| Python | **`/usr/bin/python3` = 3.14.7** |
| Docker daemon | **none** — no Docker daemon on this host |

The Fedora/aarch64/proot facts are consistent with `phase-6-deploy.md` §A.1
("the build host is Fedora 44 aarch64 (§8.1) and the primary target is a
phone") and §C.7 ("The build host is Fedora 44 aarch64 in a proot container").

The Python 3.14.7 fact matters for **conflict 9** in `contract-conflicts.md`:
it is the tiebreaker for which Docker base-image pin is correct, because 3.14.7
is the interpreter version actually validated on this host. The recommendation
there is to pin `python:3.14.7-slim-bookworm` everywhere, matching
`phase-6-deploy.md` §A.2's two `FROM` lines and `decisions.md`'s Phase 6 ruling
1, and to correct `/root/docs/server/docker.md`, which reportedly says 3.14.2.

The absent Docker daemon matters for the same file's **conflict 9** and for any
deploy verification: the Dockerfile in §A and the compose file in §B **cannot be
built or run on this host**. `docker build`, `docker compose up -d`,
`docker run` and the phase-6 §E.3 `docker.yml` CI job are all untestable here
and must be reported as untested rather than assumed green. Docker *files* can
be authored and reviewed; Docker *behaviour* cannot be demonstrated on this
machine. If a Docker smoke check appears to pass here, it is not exercising
Docker.

---

## Net effect on the docs

| Doc statement | Status |
|---|---|
| Termux absent | **Wrong** — Termux prefix present, ~810 binaries, wake-lock/unlock available; `TERMUX_VERSION`/`PREFIX` empty make `doctor` report a false negative |
| `ps`/`pkill` may be absent | **Wrong** — both present |
| systemd available (implied by `systemctl` existing) | **Wrong** — binary present, init system absent; treat as absent, never probe by existence |
| Fedora 44 / aarch64 / proot-distro / Python 3.14.7 | **True** |
| No Docker daemon | **True** — Docker behaviour untestable on this host |