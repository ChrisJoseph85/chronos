# Chronos desktop client (Omarchy/Hyprland) — frozen spec (2026-10-05)

Separate client project in `desktop/`. API-only consumer of REST+WS
(docs/server/API.md v1.2). Never touches server files. Python + GTK4 +
libadwaita (present on Omarchy). No Google services. Key in libsecret
(or 0600 file fallback); never logged.

## 0. Windows (exactly three)

- **W1 Planner** — calendar (month grid + day agenda, Google-style) AND
  projects/tasks/subtasks tree AND tags, side by side in one window.
  Tap a slot/day → propose via `say` → accept/reject card. Reads:
  `GET /api/events?from&to`, `GET /api/nodes?parent`, WS `patch`.
- **W2 Timer+Log** — timer card (mode seg stopwatch|timer|pomodoro, target
  picker, strict toggle, presets incl 25/5x4, live elapsed incl.
  remote-started sessions, 409 handling) AND time log (per-node totals +
  `breakdown` drill project→children→tasks, voided struck-through).
- **W3 Bar** — compact always-on-top action bar: timer state + elapsed +
  start/stop + **enlarge button** (opens/focuses W2). Suggested Hyprland
  float rule shipped as docs snippet (user applies; installer never edits
  `~/.config/hypr/` unilaterally).

## 1. Transport

REST via stdlib (`urllib`), WS via `websockets` PyPI dep (pinned).
`X-Chronos-Key` header. `GET /api/health` gates all: down → banner +
writes blocked. WS `timer/proposal/question` frames update live.

## 2. Autostart + notifications

- Autostart: installer writes XDG
  `~/.config/autostart/chronos-desktop.desktop` (user-level, no sudo).
  Optional `o.launch_on_start` line for `~/.config/hypr/autostart.lua`
  documented, never auto-edited.
- Notifications via Gio.Notification (native): event reminders due
  (poll `GET /api/reminders`), timer start/stop/void milestones,
  briefing-question pings, proposal-awaiting. No polling faster than 30s.

## 3. Focus shield (desktop side)

Same rules as Android spec: blocklist is device-local (a denylist has no
meaning on desktop — instead: fullscreen "session running" reminder is
NOT wanted on desktop). Desktop shield = strict toggle arms
void-on-violation only for sessions started here; no app blocking on
Linux v1 (documented gap). Stop clean → keeps; stop after user-marked
"distracted" → `void:true`. (Desktop cannot see other apps' usage
without intrusive hooks — out of scope v1.)

## 4. Out of scope v1

Mic/voice capture (text box everywhere instead), offline writes,
multi-window tiling rules (docs snippet only), ntfy (desktop uses native
notifications directly).

## 5. Install, verify, done gates

`desktop/install.sh` (venv via `uv` or system python3, `pip install -e
./desktop`, writes .desktop entry, never sudo). Gate HERE (x86 +
Hyprland running): unit tests green (fakes, no network/display) +
`python -m compileall` + app boots to W3 bar (headless-tolerant smoke:
 Broadway backend or `--smoke` no-GUI transport check). `ruff` if present.
