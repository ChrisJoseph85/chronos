# Chronos Android client — frozen spec (2026-10-05)

Server is remote and is the source of truth. The app is a view + control.
API base: REST + WS per docs/server/API.md v1.1, plus §8 additions below.

## 0. Stack (frozen)

Native Kotlin, minSdk 29, targetSdk 36, Gradle wrapper committed, no Google
services (F-Droid compatible). Foreground service for the timer tick.
Builds on x86_64 (this host OK: JDK 21 + SDK present) and in CI
(.github/workflows/android.yml → assembleDebug + unit tests).
Device/emulator runs are the user's — never claimed here.

## 1. Transport and auth

- Server URL + instance key in EncryptedSharedPreferences. Key never logged.
- `GET /api/health` gates everything: unreachable → cached read-only +
  "server is down" banner; writes blocked. No silent queuing.
- Calendar sync = `GET /api/events?from&to` ranges + `/ws` `patch` frames.
- WS `timer` frames drive the home card; `proposal`/`question` drive cards.

## 2. Screens (bottom nav: 5 tabs + More)

BottomNavigationView hard limit is 5 items (crashed on launch with 7 —
fixed 2026-10-06). Tabs: Home, Calendar, Tasks, Briefing, **More**.
More screen holds Projects, Stats, Settings buttons (same fragments).

- **Home** — timer card: mode selector (stopwatch | countdown | pomodoro),
  target picker (project/tag/task via nodes API), strict-shield toggle
  (default ON), presets row (25/5x4 always). If a session runs ANYWHERE
  (started by any client), the card shows it live with elapsed + End button.
  Second start → server 409 → "stop current first".
- **Calendar** — month/week/day agenda, Google-Calendar-phone style. View
  only; tap a slot prefills the voice bar; commit only via proposal accept.
- **Tasks / Projects** — one shared tree component, different roots.
  Project → subproject → task → subtask, tags shown (never on projects).
- **Briefing** — `GET /api/briefing?date`, rollover/due-reviews, ≤1 question
  card (accept/skip = clarification budget).
- **Stats** — `GET /api/timer/summary` totals + `GET /api/stats/breakdown`
  drilldown bars: project → children → tasks (per-child total_ms).
- **Settings** — server URL/key, blocklist picker, providers (reuse v1.1
  `/api/providers`: add/reorder, keys never displayed).

## 3. Global voice bar (every tab)

Mic → `POST /api/voice` → transcript appended to text box → `POST /api/say`
→ proposal diff card → accept/reject/skip over WS. Never silent-commits.

## 4. Focus shield (the anti-cheat rules — frozen UX)

- Strict toggle ON (default): blocklist enforced while ANY session runs.
- Foreground-app tripwire via UsageStats permission. Rationale text shown
  in-app: "used only to detect a blocked app opening; no usage statistics
  are collected, stored, or sent anywhere." No measurement, tripwire only.
- Blocked app opens → full-screen redirect, no direct entry:
  "Session running — 23:41 left. [Back to timer] [End session — time voided]".
  The lock lasts as long as the session runs (no magic cooldown).
- Attempt counter per session (device-side). Stop rules:
  - Clean stop (zero attempts) → elapsed KEPT (server already does this).
  - Stop after ≥1 attempt → app sends `void:true` → session VOIDED,
    elapsed discarded, audit logs the void. This is the ONLY bypass, and it
    costs the session (e.g. 40 min gone). Server trusts and records the flag
    (self-discipline boundary — documented, not a multi-user guarantee).
- Strict toggle OFF → no blocking, stop always keeps time.
- Remote stop/void (another client) reflects on this client via WS.

## 5. Timer semantics (server-owned, app mirrors)

One session at a time (409). Stopwatch ignores target. Pomodoro breaks
excluded from totals; early-stop focus ≠ completed cycle. Voided sessions
excluded from summary/breakdown/streaks, shown struck-through in log.

## 6. Notifications

ntfy (F-Droid build) for reminders/proposal/question/timer milestones.
No Firebase.

## 7. Done gates

`./gradlew assembleDebug` green HERE + unit tests (fakes, no network) +
a verifier agent driving the app flows against a live server (user device).
No APK claimed without a local `assembleDebug` artifact.

## 8. Server API additions (v1.2, implemented alongside)

- `POST /api/timer/stop {source, void?:bool}` → voided sessions marked
  (`TimerSession.voided INTEGER DEFAULT 0`, new DDL column + migration),
  excluded from summary/breakdown/streaks, audit entry. Backward compatible.
- `GET /api/stats/breakdown?node_id&from&to` → per-child
  `{node_id,title,kind,total_ms}` from timer_sessions + parent walk,
  voided excluded. Powers Stats drilldown.
- API.md v1.2 amendment note. No other contract changes.

## 9. Server auto-discovery (Settings)

Manual URL entry stays. Auto-find button scans for the server (which the
user runs with `--port 693`, e.g. `CHRONOS_PORT=693 chronos serve`):
order 127.0.0.1 → device's LAN /24 subnet hosts, same port throughout
(port field editable, default 693). Per host: `GET /api/health` (short
timeout, background, cancelable, progress UI), then an authenticated
probe with the SAVED instance key only (never a pasted/typed key at
scan time). First host answering healthy + authorized wins and fills the
URL field. Sweep bounded (connect timeout ≤1s/host, max ~254 hosts,
user-cancelable). Server default port stays 8080 — discovery port is an
app setting, not a server change.
