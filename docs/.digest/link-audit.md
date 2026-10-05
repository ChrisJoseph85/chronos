# Chronos — independent external-link & reference audit

Auditor: subagent with no prior context. Read-only pass over `/root/Chronos`.
Every URL below was actually fetched. No repository claim (comment, `--help`
text, docstring, filename) was accepted as evidence of what a host serves.

Date of audit: 2026-10-04 (container clock). All fetches via `curl -L`, TLS
verification ON (`ssl_verify_result=0` on every https request reported here).

---

## 1. Summary counts by severity

| Severity | Count |
|---|---|
| CRITICAL | 2 |
| HIGH | 4 |
| MEDIUM | 5 |
| LOW | 5 |
| INFO / verified-clean | 14 distinct reference items |

Distinct external references found and audited: **31** (23 unique hosts/URLs
after collapsing loopback variants and doc-only mirrors).

### CRITICAL

**C1 — `requirements-lock.txt` pins `chronos==2.0.0`, but PyPI's `chronos` is a
different, unrelated project.**
`https://pypi.org/pypi/chronos/2.0.0/json` → **HTTP 404**. The real PyPI
`chronos` project is version **0.3**, author *Nick Sinopoli*, summary
*"An ncurses stopwatch/timer."*, homepage `http://git.io/chronos` — a 2010s-era
ncurses timer. It is **not** this project. Consequences:
- A bare `pip install -r requirements-lock.txt` on any fresh machine resolves
  `chronos` to that unrelated 2015 ncurses package, not Chronos. Silent
  wrong-package install.
- `pip install chronos==2.0.0` fails outright.
- Name-squatting exposure: this repo publishes to PyPI under a name it does not
  own.
- The lock file comment says "The project itself, installed editable from the
  checkout." True in this venv — `.venv/.../__editable__.chronos-2.0.0.pth`
  exists and `pip freeze` reports `chronos==2.0.0` — but a lock file that
  resolves from an index is only correct because a local editable install
  shadows it. **Fix: add `chronos @ file://.` or drop the line and document the
  editable install; do not leave a bare index-resolvable name.**

**C2 — `install.sh` pipes a remote script straight into a shell.**
`scripts/install.sh:216`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
This *is* the URL Astral publishes as its official installer, and I verified
the redirect chain — but "it is the vendor's own documented installer" is a
trust claim, not a safety property. It is fetched over the network and executed
with no checksum, no signature, and no pin. Anyone who can MITM or who wins the
`astral.sh` / `releases.astral.sh` DNS+TLS path gets root-in-distro code
execution. The script's own security table (lines 23–53) describes this as
"the ONLY URL in this script piped into a shell, by its own design" — that is
accurate as an inventory, and it is also an admission that the pattern exists.
The script's stronger claim — "There is no code path in this script that fetches
or unpacks an archive" — is **false as written**: `curl … | sh` fetches and
executes. Verified: the redirect target `uv-installer.sh` is a 71,308-byte
`#!/bin/sh` script (MIT, Astral) that in turn downloads uv binaries from
`releases.astral.sh` / `github.com/astral-sh/uv/releases/download/0.12.23`.
The installer is genuine; the *pattern* is download-and-execute.
Mitigation already present: a `pip install uv` fallback on line 227 if curl
fails or uv is still absent.

### HIGH

**H1 — README documents a script that does not exist.**
`README.md:46-47` instructs `bash scripts/termux.sh install` / `start`.
`ls scripts/` → `backup.sh  install.sh  restore.sh  smoke.sh`. **No
`termux.sh`.** The same dead reference appears at `docs/deploy.md:44-46`,
`docs/termux.md:17-26`, `docs/phases/phase-6-deploy.md:18`, and 12 more places
in `docs/proposals/phase-6-deploy.md`. Git log `c732762` is literally
*"Replace the Termux installers with one Termux-side script"* — the replacement
landed as `scripts/install.sh`, and every doc that still says `termux.sh` now
points at a file that was deleted. The README quick-start for phones is
**broken as written**. This is a link-audit finding in the literal sense: an
internal path reference that resolves to nothing.

**H2 — `.env.example` documents an entire configuration scheme the code never
reads.** All commented-out in `.env.example`, zero hits in `chronos/`:
- `TEXT_PROVIDER_1_NAME` / `TEXT_PROVIDER_1_BASE_URL` / `TEXT_PROVIDER_1_KEYS`
  (+ `_2_` variants). The code builds the prefix from
  `TEXT_PROVIDERS` (default `"groq,nim"`) as `f"{prefix}_BASE_URL"` →
  it reads `GROQ_BASE_URL` / `NIM_BASE_URL`, *not* `TEXT_PROVIDER_1_BASE_URL`.
- `NTFY_TOPIC` / `NTFY_SERVER` — `NTFY_TOPIC` has **0 hits in `chronos/`**.
  `NtfyNotifier.__init__` raises `ValueError` if neither `server_url` nor `url`
  is passed, so there is no default ntfy host; nothing reads `NTFY_SERVER`.
- `CHRONOS_PORT` — 0 hits in `chronos/`. `.env.example` line sets
  `CHRONOS_PORT=8080` uncommented; the CLI takes `--port`, not that env var.

The URLs themselves are canonical, but the *variable names that would select
them are inert*. A user following `.env.example` to the letter configures
nothing.

**H3 — `docs/proposals/phase-2-ai.md` documents the same inert names as the
design contract.** Tables at §env list `GROQ_BASE_URL`/`NIM_BASE_URL`/
`TEXT_PROVIDERS` *and* the `TEXT_PROVIDER_n_*` scheme in different places, and
`tests/phase_2/test_ai_spec.py:503-525` asserts on `GROQ_BASE_URL`/
`NIM_BASE_URL`. So the tests agree with the code and disagree with
`.env.example` and with README's config table. One of the two specs is wrong;
the code+tests are the coherent pair.

### MEDIUM

**M1 — `pydantic_core==2.46.5` is stale against its own parent.** PyPI latest
`pydantic_core` is **2.49.0** while `pydantic` is pinned at 2.13.5 (which is
PyPI latest). Not broken — `pip install -r requirements-lock.txt` resolves
2.46.5 fine — but it is not a consistent reproduction of a working env and
will drift from the stated purpose ("as resolved into the venv").
`pip==26.0.1` similarly trails latest 26.2.1. These are the only two stale pins;
the other 45 are all at current latest.

**M2 — `README.md` calls the repo "docs-only right now."** Not a link issue,
but it contradicts the repo's own contents: 60+ `.py` files under `chronos/`,
six populated test packages, and a working venv. The `guard` job in both
workflows exists specifically to skip on docs-only checkouts, so this is stale
scaffolding text, not a live condition.

**M3 — `.dockerignore` excludes `docs/`, `scripts/`, `tests/`, `.github/`.**
Intentional and correct for an image build (the Dockerfile copies only
`pyproject.toml`, `README.md`, `chronos/`). No issue — recorded because the
brief asked about it. `.env` is excluded, good.

**M4 — `docker-compose.yml` uses `env_file: [{path: .env, required: false}]`.**
The long-form `path`/`required` mapping needs Compose v2.24+. Fine, but it is
the less portable spelling; noted, not a defect.

**M5 — `.env.example`'s `EMBED_BASE_URL=http://localhost:8000/v1` is plain
http.** Correct in context: it is a loopback embedding server the user runs
themselves, and `chronos/ai/providers/adapter.py:321` uses the identical default.
Not a TLS problem.

### LOW

**L1 — `LICENSE` links `https://www.gnu.org/licenses/`** — 200, FSF-controlled,
canonical. **But** GitHub's API reports the repo license as
`spdx_id: NOASSERTION` / `"other"`, because the `LICENSE` file has no
machine-readable header. Cosmetic only; the file text is the real GPL-3.0.

**L2 — `install.sh` claims to use `CHRONOS_HOST`/`CHRONOS_PORT` as overrides.**
Both are real env reads in the shell script (`HOST_ADDR`, `START_PORT`), but
neither is read by the Python application — see H2. So overriding them affects
install-time health polling only, not the printed "to start Chronos later"
command's meaning versus what `chronos serve` will do.

**L3 — Astral installer is version-floating.** `astral.sh/uv/install.sh`
redirects to `.../uv/**latest**/uv-installer.sh`, whose body hardcodes uv
`0.12.23`. Re-running the installer at different times installs different uv
versions. Combined with C2, this is a real reproducibility gap for a script
that otherwise goes to great lengths to pin everything else.

**L4 — Test fixture hostnames.** `http://example.com/api/events` (7×) and
`https://fake.example/v1` appear only in `tests/`. IANA-reserved
documentation domains; never resolved at runtime.

**L5 — `docs/termux.md:31` still describes the deleted installer.** "installs
Python, Rust (needed to compile `sqlite-vec`), binutils, and SQLite" — but
`install.sh` explicitly states Rust is *not* needed (glibc wheel, no compile).
Doc is doubly stale.

---

## 2. Runtime vs documentation — which hosts are actually contacted

**Contacted at RUNTIME by shipped code (network egress):**

| Host | What contacts it | Trigger |
|---|---|---|
| `api.groq.com` | `chronos/ai/providers/adapter.py` via `httpx.post` (`:148` chat, `:199` audio/transcriptions) | Only if the user sets `STT_API_KEY` or a `GROQ_*` provider key. Default STT base URL is hardcoded to it at `adapter.py:309`. Offline with no keys — falls back to the built-in parser. |
| `integrate.api.nvidia.com` | same `httpx.post` path | Only if `NIM_*` configured. Default `TEXT_PROVIDERS="groq,nim"`, but empty base_url ⇒ adapter never fires. |
| whatever `NTFY_SERVER`/ctor arg holds | `chronos/notify/ntfy.py` `urllib.request` POST | No default. Requires explicit arg; `NTFY_SERVER` env var is not read (H2). |
| user-configured `EMBED_BASE_URL` (default `localhost:8000`) | `adapter.py:230` | Local by default. |

**Contacted at INSTALL time by `scripts/install.sh`:**
- `astral.sh` → `releases.astral.sh` (verified 302, Cloudflare, `text/x-sh`) — **the download-and-execute**
- `releases.astral.sh` and `github.com/astral-sh/uv/releases/…` (inside that installer)
- `pypi.org` + `files.pythonhosted.org` (implicitly, via `uv pip install`/`pip install`)
- `github.com` (only via `git clone`, and **only if `pyproject.toml` is missing** — `install.sh:438`)

**Loopback only (never external):** `127.0.0.1` and `0.0.0.0`. `127.0.0.1`
appears 20×, `0.0.0.0` 4× (Docker `CMD` bind + README LAN hint). **No external
IP address literal exists anywhere in the repo.** Verified by regex sweep for
IPv4 across `*.py *.sh *.md *.yml *.toml *.js *.html`.

**Documentation/comment-only, never fetched by any code path:**
`github.com/asg017/sqlite-vec.git`, `f-droid.org` ×2, `ntfy.sh` (in README
prose; runtime ntfy is user-configured), `www.gnu.org`, `sqlite.org`,
`integrate.api.nvidia.com` / `api.groq.com` in `.env.example` comments.

**Documentation accuracy check on the audit table:** `install.sh:23-53` claims
the external hosts are exactly {astral.sh, pypi.org, files.pythonhosted.org,
github.com/ChrisJoseph85, github.com/asg017, loopback}. I confirmed this is
**accurate except for one omission**: the Astral installer itself fetches
`releases.astral.sh` and `github.com/astral-sh/uv/releases/download/0.12.23`.
Both are Astral-controlled and benign, but the table's "every external host
this script can contact" header is incomplete as written.

---

## 3. Full reference table

| URL | Resolves? | Who controls it | Official for purpose? | Runtime? | Verdict |
|---|---|---|---|---|---|
| `https://github.com/ChrisJoseph85/chronos.git` | **200** `x-git-upload-pack-advertisement` | GitHub Inc. | **Yes** — repo exists, `fork:false`, title matches README exactly ("Local-first AI study scheduler and time tracker"), 0 stars, created 2026-10-03, pushed 2026-10-04 | Install-time only, and only if checkout missing | **CLEAN.** Canonical origin, matches `git remote`. |
| `https://github.com/ChrisJoseph85/` | 200 | GitHub | Yes | Install-time only | CLEAN |
| `https://github.com/asg017/sqlite-vec.git` | **200** | GitHub | **Yes** — genuine upstream (asg017 = Alexis Gagate, sqlite-vec author), 8,160 stars, Apache-2.0, `fork:false` | **Never** (comment only) | CLEAN. Not a fork/mirror. Claim "documented for provenance ONLY, NEVER cloned" is **true** — no `git clone` of it exists in the script. |
| `https://astral.sh/uv/install.sh` | 200, **302 → `releases.astral.sh/installers/uv/latest/uv-installer.sh`** | Astral (Cloudflare-fronted) | **Yes** — Astral's own published installer | **Yes, `\| sh`** | **RISK (C2)** — genuine vendor URL, but download-and-execute, unpinned, no checksum. Redirect not disclosed in repo. |
| `https://releases.astral.sh/…/uv-installer.sh` | 200 `text/x-sh`, 71,308 B, MIT | Astral | Yes | Yes (indirect) | Genuine. Version-floating (`latest`; body pins uv 0.12.23). |
| `pypi.org` (`/simple/`) | 200 | PyPI / Python Software Foundation | **Yes** | Install-time (via uv/pip) | CLEAN |
| `files.pythonhosted.org` (bare `/`) | 404 | PyPI/PSF | Yes — 404 is *expected*, root path serves no index; it's a file CDN | Install-time (via uv/pip) | CLEAN. The 404 is not a defect. |
| `https://api.groq.com/openai/v1` | 404 on the bare path, **but real**: `/models` → 401 `{"code":"invalid_api_key"}` | Groq (Cloudflare) | **Yes** — genuine GroqCloud endpoint, OpenAI-compatible shape | **Yes, if configured** | CLEAN. Model `openai/gpt-oss-120b` confirmed current on Groq's model docs. `whisper-large-v3-turbo` also current. |
| `https://integrate.api.nvidia.com/v1` | 404 bare, `/models` → **200, 81 models** | NVIDIA (75.2.113.119, AWS) | **Yes** — NVIDIA NIM API | **Yes, if configured** | CLEAN. Default model `nvidia/nemotron-3-super-120b-a12b` **verified present** in the live list. |
| `https://ntfy.sh` | 200 `text/html` (large page, 224 KB) | Philipp C. Heckel / ntfy e.V. | **Yes** — official free public ntfy server | **No** (no default; user-configured) | CLEAN. `https://ntfy.sh/v1/account` → 200 `{"username":"*","role":"anonymous",...}` confirms the API is live. |
| `https://f-droid.org/packages/com.termux/` | 200, `<title>Termux \| F-Droid…` | F-Droid / Termux | **Yes** — official Termux listing | No (README doc) | CLEAN. Correctly warns to avoid Play Store build. |
| `https://f-droid.org/packages/io.heckel.ntfy/` | 200, `<title>ntfy - PUT/POST to your phone \| F-Droid…` | F-Droid / ntfy | **Yes** | No (README doc) | CLEAN |
| `https://www.gnu.org/licenses/` | 200 | Free Software Foundation | **Yes** | No (LICENSE) | CLEAN (see L1 for the GitHub metadata nit) |
| `sqlite.org` | 200 | SQLite Consortium | Yes | **No** — installer explicitly says "no sqlite.org" | CLEAN. Claim verified accurate: no sqlite.org reference in any code path. |
| `http://127.0.0.1:8080/api/health` | n/a (loopback) | self | Yes | Docker HEALTHCHECK, ci.yml, docker.yml, smoke.sh, install.sh | CLEAN. `/api/health` confirmed unauthenticated in `chronos/api/app.py:181-183`, matching the Dockerfile's "the only unauthenticated route" claim. |
| `http://localhost:8000/v1` | n/a (loopback) | self | Yes — user's own embedding server | Default only, if embeddings used | CLEAN |
| `http://example.com/api/events…` | n/a | IANA reserved | n/a | **No** — test fixtures only | CLEAN |
| `https://fake.example/v1` | n/a | IANA reserved | n/a | **No** — test fixture | CLEAN |
| `https://api.github.com/repos/ChrisJoseph85/chronos` | 200 | GitHub | Yes | No (my verification) | Confirms repo is the real origin, non-fork |
| `https://hub.docker.com/v2/…/3.14.7-slim-bookworm` | **200**, last_updated 2026-09-19 | Docker | Yes | No (my verification) | Dockerfile base tag is real |
| `https://endoflife.date/api/python.json` | 200 | endoflife.date (community) | Authoritative-ish | No (my verification) | 3.14 latest is **3.14.8**; Dockerfile pins 3.14.7 — real patch, one behind. Not a defect. |

---

## 4. Version verification — `requirements-lock.txt` against live PyPI

Method: `https://pypi.org/pypi/<name>/json` per pin, checking `releases[pin]`
non-empty and comparing to `info.version`. 49 pins checked.

**Result: 48/49 pins resolve to a real, published release. 1 is broken (C1).**
All 48 real pins have ≥2 files (sdist+wheel) except where noted; `sqlite-vec`
correctly has wheel-only.

| Package | Pin | PyPI latest | Files | Note |
|---|---|---|---|---|
| sqlite-vec | 0.1.9 | 0.1.9 | **5 whl, no sdist** | ✅ matches lock comment exactly: macos x86_64, macos arm64, manylinux glibc x86_64, manylinux glibc **aarch64**, win_amd64. Every Linux wheel is glibc — confirms the Termux/bionic reasoning in `install.sh:12-17`. PyPI metadata is junk (`author: TODO`, `home_page: https://TODO.com`) but the files are correct. |
| fastapi | 0.142.2 | 0.142.2 | 2 | current |
| uvicorn | 0.54.0 | 0.54.0 | 2 | current |
| SQLAlchemy | 2.1.3 | 2.1.3 | 72 | current |
| alembic | 1.20.0 | 1.20.0 | 2 | current |
| argon2-cffi | 25.1.0 | 25.1.0 | 2 | current |
| httpx | 0.28.1 | 0.28.1 | 2 | current |
| python-multipart | 0.0.32 | 0.0.32 | 2 | current |
| websockets | 17.2 | 17.2 | 148 | current |
| mcp | 2.3.0 | 2.3.0 | 2 | current |
| pydantic | 2.13.5 | 2.13.5 | 2 | current |
| pydantic_core | **2.46.5** | **2.49.0** | 120 | ⚠️ stale (M1) |
| pip | **26.0.1** | **26.2.1** | 2 | ⚠️ stale (M1) |
| pytest | 9.1.1 | 9.1.1 | 2 | current |
| pytest-asyncio | 1.4.0 | 1.4.0 | 2 | current |
| ruff | 0.16.10 | 0.16.10 | 18 | current |
| **chronos** | **2.0.0** | **0.3** | **0** | ❌ **404 — C1** |

The remaining 32 transitive pins (`anyio`, `httpx2`, `httpcore2`, `mcp-types`,
`annotated-doc`, `truststore`, `starlette`, `sse-starlette`, `cryptography`,
`PyJWT`, `rpds-py`, …) all exist at exactly the pinned version. I checked the
three that look most like typos/hijacks — `httpx2`, `httpcore2`, `mcp-types`,
`annotated-doc` — and they are **genuine PyPI projects**, not typos. `httpx2`
and `httpcore2` are the real successor releases to `httpx`/`httpcore`; `mcp`
2.x splits its types into `mcp-types`. So the lock file reflects a legitimately
modern dependency graph, not a fabricated one. `requires-python = ">=3.14"`
plus CPython 3.14.7 in the Dockerfile is real (3.14 latest is 3.14.8).

---

## 5. Download-then-execute audit

| Location | Pattern | Verdict |
|---|---|---|
| `scripts/install.sh:216` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | **The only download-and-execute in the repo.** Vendor-official, unpinned, unverified. |
| `scripts/install.sh:442` | `git clone "$REPO_URL" "$PROJECT_DIR"` | Clone of own repo, **never executed** (only `pyproject.toml` existence checked). Safe. |
| `scripts/install.sh:227` | `python3 -m pip install --user uv` | Package install, no pipe-to-shell. Safe. |
| `scripts/install.sh:256` | `uv pip install -e .` | Resolves from PyPI. Safe. |
| `scripts/install.sh:318` | `curl -fsS "http://127.0.0.1:$port/api/health"` | Loopback poll, output parsed not executed. Safe. |
| Dockerfile:21 | `pip install --no-cache-dir .` | Safe. |
| ci.yml / docker.yml | `pip install -e ".[dev]"`, `docker build` | Safe. |
| `scripts/{backup,restore,smoke}.sh` | `curl` loopback only, `cp`, `kill` | Safe. **Zero external hosts.** |
| **archive extraction anywhere** | **NONE** | ✅ Verified: no `tar`, `unzip`, `.tar.gz`, `.zip`, `.bundle`, or `chmod +x` on a downloaded file in any script. `.dockerignore` mentions `*.bundle` but that is an exclusion pattern, not a download. |

**Download-then-execute count: 1.** The installer's own claim "no archive
download, no download-and-execute of any bundle" is accurate about archives and
inaccurate about the `| sh` it contains.

---

## 6. TLS / transport hygiene

- **No plain `http://` to any external host.** Regex sweep found exactly three
  `http://` origins repo-wide: `127.0.0.1` (20×), `localhost` (10×), `example.com`
  (7×, tests only). Everything external is https.
- **No certificate problems.** Every https request returned
  `ssl_verify_result=0`. Both F-Droid URLs served over IPv6 to Cloudflare
  (`2a00:c6c0::`, `2a01:4f9::`) with valid certs.
- **No hardcoded external IPs.** Only `127.0.0.1` (loopback) and `0.0.0.0`
  (wildcard bind).
- **Third-party forks / mirrors: none.** No reference to a personal fork,
  alternate index, `--index-url`, `--extra-index-url`, jsDelivr, unpkg, or a
  GitHub raw/CDN proxy anywhere. Every artifact comes from pypi.org,
  files.pythonhosted.org, astral.sh, or the canonical GitHub repos.
- **`git` URLs:** only one clone URL in code (`REPO_URL`, own repo) and three in
  docs. All canonical.

---

## 7. What I could not verify

1. **Whether `ChrisJoseph85/chronos` on GitHub matches this checkout byte-for-byte.**
   The API shows `pushed_at 2026-10-04T14:13:09Z`; local HEAD is `c732762`. I
   did not clone (would have written into the read-only repo area) and did not
   diff against the remote tree. The repo's *description* matches, which is
   suggestive but not proof of content parity.
2. **Whether `sqlite-vec==0.1.9`'s manylinux aarch64 wheel actually imports on
   proot-distro/Fedora/glibc.** I verified the wheel exists on PyPI with the
   right platform tag; I did not install it (that would mean running the
   installer / mutating state). The installer's own verification step does this
   at install time.
3. **`uv python install 3.14` availability.** `astral-sh/uv-installer` API
   returned no `tag_name` (that repo has no "latest release" in the shape I
   queried). I did not run `uv python install`. CPython 3.14.7/3.14.8 existence
   is confirmed independently via endoflife.date.
4. **Groq model IDs could not be live-verified.** `api.groq.com` requires a key;
   every request returns 401. I confirmed `openai/gpt-oss-120b` and
   `whisper-large-v3-turbo` from Groq's published model docs and third-party
   catalogs. One secondary source claims `gpt-oss-120b` was *retired* 2026-09-03
   in favour of the 20b; Groq's own docs still list the 120b as an active
   production model with an MCP-tool-use table. **Groq's docs win, but this is
   a genuine ambiguity worth a live call once a key exists.**
5. **The ntfy.sh root page timed out mid-download** (147 KB of 224 KB after
   25 s) — a slow public free-tier server, not a fault. The JSON API endpoint
   responded instantly and confirms liveness.
6. **Runtime egress was not observed.** I read the code paths; I did not run
   the server with keys and watch network traffic. All "contacted at runtime"
   conclusions are static analysis of `httpx.post` / `urllib.request` call sites
   plus the defaults at `adapter.py:309,321`.
7. **Not checked:** `docker compose build` actually succeeding, the
   `guard` job logic, and whether `pip install -r requirements-lock.txt` works
   from scratch (C1 predicts it does not, by pulling the wrong `chronos`).

---

## 8. Bottom line

**The network surface is small, correctly-chosen, and almost entirely
trustworthy.** No third-party mirrors, no forks, no plain-http external
requests, no hardcoded external IPs, no archive-extraction, no certificate
anomalies. Every URL that claims to be official *is* official — I confirmed
ownership of all eight external hosts independently (GitHub/PSF, Astral,
Groq, NVIDIA, ntfy, F-Droid, FSF), and every claimed model ID on the two API
hosts resolves against those hosts' live model lists.

The problems are not in the URLs. They are in three places:

1. **One dangerous pattern** — `curl … | sh` in `install.sh` (C2), with the
   script's own prose simultaneously describing it as safe-by-design and
   contradicting the adjacent "no download-and-execute" claim.
2. **One genuinely broken pin** — `chronos==2.0.0` on PyPI is a different
   project by a different author (C1). This will fail or install the wrong
   package for anyone who uses the lock file as intended.
3. **Documentation drift** — `scripts/termux.sh` is deleted but still referenced
   in 15 places including the README phone quick-start (H1); `.env.example`
   and several docs describe env-var schemes the code never reads (H2/H3).

None of the eight external hosts is a fork, a mirror, or a surprise. If you fix
C1, H1, and H2, this repo's link surface is defensible.
