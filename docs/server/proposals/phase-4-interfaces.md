# Phase 4 — Interface Proposal: Web HUD, CLI, MCP

**Status:** FROZEN — Phase 4 proposal approved
**Manager review:** All 8 ambiguities ruled on and approved. See `docs/decisions.md`.  
**Author:** Phase-4 Proposer  
**Date:** 2026-10-03  
**Spec source:** `docs/Chronos.md` §9.1 (web HUD), §9.2 (CLI), §8.4 (MCP), §3 (auth), §8.1 (process), §8.2 (REST), §8.3 (WebSocket), §7.2 (grid), §1 (zero-form input)  
**Phase doc:** `docs/phases/phase-4-interfaces.md`  
**Frozen contracts:** `docs/proposals/phase-1-contracts.md`

---

## 0. Scope and principles

This document proposes the complete interface surface for Phase 4. It covers:

- **A.** Web HUD — static files served by the host, no build step (§9.1)
- **B.** CLI — argparse entry points, terse output (§9.2)
- **C.** MCP — tool adapters, auth, audit (§8.4)
- **D.** Web mount helper — `chronos/web/__init__.py`
- **E.** File layout — every file with purpose and exports

**Principles:**

1. No build step, no bundler, no framework for the HUD (§9.1, phase doc §4.1)
2. Flat screens, dark styling, no glassmorphism, no orbital ring (§9.1, §0.14)
3. Zero-form input — no save button, change commits on blur (§1)
4. Terse CLI output, no prompts, safe to pipe (§9.2)
5. Every CLI command must actually run and produce output (phase doc)
6. MCP exposes the same 27-tool set as the pipeline — no reimplementation (§8.4)
7. Every MCP call is audited (§8.4)
8. Never expose the instance key except via the query-string path proven not to log (§3, phase doc)
9. All times are UTC epoch milliseconds in the database; ISO-8601 with offset at every API boundary (§4, §7.3)
10. The calendar grid is 1 minute (§7.2)

---

## A. Web HUD (§9.1)

### A.1 Constraints

| Constraint | Spec | Decision |
|---|---|---|
| No glassmorphism | §0.14, §9.1 | No `backdrop-filter`, no blur, no translucent layers |
| No orbital ring | §0.14 | No circular/ring visual elements |
| No build step | §9.1, phase doc | Plain HTML/CSS/JS files served as-is |
| No bundler | §9.1, phase doc | No webpack, rollup, esbuild, etc. |
| No framework | §9.1, phase doc | No React, Vue, Svelte, etc. Vanilla JS only |
| Dark styling | §9.1 | Dark background, light text, flat colors |
| Flat screens | §9.1 | No gradients, no shadows with blur, minimal border-radius |

### A.2 Screens

Eight screens, specified in §9.1. Each is a `<section>` in `index.html`, shown/hidden by `app.js`.

#### A.2.1 Today

**Spec:** §9.1 — "minute timeline, running timer, current block, say box."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Timeline container | `#today-timeline` | Vertical minute timeline for the current day |
| Running timer display | `#today-timer` | Shows running timer elapsed/target, or "no timer running" |
| Current block | `#today-current-block` | The event block that contains the current time |
| Say box | `#say-box` | The input box (text field + mic button), shared across screens |

**API calls:**
- `GET /api/events?from&to` — today's events for the timeline
- `GET /api/timer` — running timer state
- `GET /api/briefing?date` — today's briefing summary

#### A.2.2 Timer controls

**Spec:** §9.1 — "three mode buttons (stopwatch, timer, pomodoro), a task/project tag picker, and duration fields for whichever mode needs them. The countdown field is hidden for a stopwatch rather than shown disabled. A running pomodoro shows its phase and `cycle / cycles_total`. Logged time for the tagged node and the project it counts toward are shown next to the clock."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Mode button: stopwatch | `#timer-mode-stopwatch` | Selects stopwatch mode |
| Mode button: timer | `#timer-mode-timer` | Selects timer (countdown) mode |
| Mode button: pomodoro | `#timer-mode-pomodoro` | Selects pomodoro mode |
| Task/project picker | `#timer-node-picker` | Selects the node to tag time against |
| Duration field: countdown | `#timer-target-ms` | Target duration in ms (visible for timer + pomodoro, **hidden** for stopwatch) |
| Duration field: pomodoro focus | `#timer-pomodoro-focus-min` | Focus phase minutes (visible only for pomodoro) |
| Duration field: pomodoro break | `#timer-pomodoro-break-min` | Break phase minutes (visible only for pomodoro) |
| Duration field: pomodoro cycles | `#timer-pomodoro-cycles` | Number of cycles (visible only for pomodoro) |
| Start button | `#timer-start` | Starts the timer |
| Stop button | `#timer-stop` | Stops the running timer |
| Phase display | `#timer-phase` | Shows "focus" or "break" (pomodoro only) |
| Cycle display | `#timer-cycle` | Shows "cycle / cycles_total" (pomodoro only) |
| Logged time: node | `#timer-node-total` | Logged time for the tagged node |
| Logged time: project | `#timer-project-total` | Logged time for the project the node counts toward |

**Mode visibility rules (§9.1, phase doc):**

| Mode | `#timer-target-ms` | `#timer-pomodoro-*` | `#timer-phase` | `#timer-cycle` |
|---|---|---|---|---|
| stopwatch | **hidden** | hidden | hidden | hidden |
| timer | visible | hidden | hidden | hidden |
| pomodoro | visible | visible | visible (if running) | visible (if running) |

**API calls:**
- `GET /api/nodes?parent` — populate the task/project picker
- `POST /api/timer/start` — start timer
- `POST /api/timer/stop` — stop timer
- `GET /api/timer` — running timer state
- `GET /api/timer/summary?node_id` — logged time rollup
- `GET /api/timer/presets` — pomodoro presets

#### A.2.3 Calendar

**Spec:** §9.1 — "day, week and month views. Own renderer. Drag to move, resize to change duration, click an empty minute to say 'here at 4'."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| View toggle: day | `#calendar-view-day` | Switch to day view |
| View toggle: week | `#calendar-view-week` | Switch to week view |
| View toggle: month | `#calendar-view-month` | Switch to month view |
| Date navigator | `#calendar-date-nav` | Previous/next/today buttons + current date label |
| Grid container | `#calendar-grid` | The calendar grid renderer |
| Hour rule | `.calendar-hour-rule` | Horizontal line every 60 minutes |
| Minute cell | `.calendar-minute-cell` | Individual minute cell (1-minute grid, §7.2) |
| Event block | `.calendar-event` | Rendered event block |
| Expander | `.calendar-expander` | Expand/collapse minute detail for an hour |

**Calendar grid (§7.2, phase doc):**
- The grid is **1 minute** — each row or cell represents one minute.
- Hour rules every 60 minutes — a visual separator at each hour boundary.
- The HUD renders hours with **expandable minute detail** rather than a 1440-row grid. Hours are shown collapsed by default; clicking an expander reveals the 60 minute cells within that hour.
- Start and end snap to the minute (§7.2).

**Interactions:**
- Drag an event block to move it (updates `start_ms` / `end_ms`).
- Resize an event block (drag edge) to change duration.
- Click an empty minute cell to populate the say box with "here at 4" (or equivalent).

**API calls:**
- `GET /api/events?from&to` — events for the visible range
- `POST /api/commands` — raw tool call for `update_event` (drag/resize)

#### A.2.4 Briefing

**Spec:** §9.1 — "the daily planning session: unallocated tasks for today and this week, rollover, due reviews, at most one question."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Date label | `#briefing-date` | The briefing date |
| Unallocated tasks | `#briefing-unallocated` | Tasks not yet scheduled |
| Rollover | `#briefing-rollover` | Tasks that rolled over from previous days |
| Due reviews | `#briefing-due-reviews` | Review events due today |
| Question | `#briefing-question` | At most one clarification question (§5.7) |

**API calls:**
- `GET /api/briefing?date` — full briefing data

#### A.2.5 Projects

**Spec:** §9.1 — "the node tree, tags, filters."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Tree container | `#projects-tree` | The node hierarchy tree |
| Tag filter | `#projects-tag-filter` | Filter by tag |
| Node item | `.project-node` | Individual node in the tree |
| Add node | `#projects-add` | Add a new node (zero-form: type in a text field, commit on blur) |

**API calls:**
- `GET /api/nodes?parent&tag` — tree query
- `GET /api/search?q&limit` — search nodes
- `POST /api/commands` — raw tool call for `create_node`, `update_node`, `delete_node`, `tag_node`, `untag_node`

#### A.2.6 Schedules

**Spec:** §9.1 — "recurring commitments with bounds and weekday exclusions."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Schedule list | `#schedules-list` | List of all schedules |
| Schedule item | `.schedule-item` | Individual schedule |
| Add schedule | `#schedules-add` | Add a new schedule (zero-form) |
| Pause toggle | `.schedule-pause` | Pause/unpause a schedule |

**API calls:**
- `GET /api/events?from&to` — schedules rendered as events
- `POST /api/commands` — raw tool call for `create_schedule`, `update_schedule`, `pause_schedule`

#### A.2.7 Time Log

**Spec:** §9.1 — "timer sessions filtered by project, tag, range or duration."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Filter: project | `#timelog-filter-project` | Filter by project |
| Filter: tag | `#timelog-filter-tag` | Filter by tag |
| Filter: range | `#timelog-filter-range` | Filter by date range |
| Filter: duration | `#timelog-filter-duration` | Filter by minimum duration |
| Session list | `#timelog-sessions` | List of timer sessions |
| Session item | `.timelog-session` | Individual timer session |

**API calls:**
- `GET /api/timer/summary?node_id` — logged time per node
- `GET /api/stats` — counts, streaks, token spend by day

#### A.2.8 Settings

**Spec:** §9.1 — "server URL, key, timezone, provider switching, token budgets."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Server URL | `#settings-server-url` | The server base URL |
| Instance key | `#settings-key` | The instance key (display only, never editable) |
| Timezone | `#settings-timezone` | Instance timezone (§7.1) |
| Provider: text | `#settings-provider-text` | Active text provider |
| Provider: speech | `#settings-provider-speech` | Active speech provider |
| Provider: embeddings | `#settings-provider-embeddings` | Active embeddings provider |
| Token budget | `#settings-token-budget` | Token budget setting |
| Save | — | No save button — zero-form, commits on blur (§1) |

**API calls:**
- `GET /api/settings` — read settings
- `PUT /api/settings` — update settings (on blur)

### A.3 Zero-form input (§1, phase doc)

**Spec:** §1 — "No date pickers, no time dropdowns. One text box and a mic button." Phase doc — "no save button. A change commits on blur."

**Rules:**
1. No save/submit buttons anywhere in the HUD.
2. Every input change commits when the field loses focus (`blur` event).
3. No date pickers or time dropdowns — all input is free text.
4. The say box is the exception: it is a text field + mic button, and it does **not** auto-submit (§9.1).

### A.4 Input box (§9.1)

**Spec:** §9.1 — "The input box is one text field plus a mic button. The button records, streams to `/api/voice`, and **appends** the transcript after existing content, so typing and talking continue into the same box. It does **not** auto-submit."

**Elements:**

| Element | ID | Purpose |
|---|---|---|
| Text field | `#say-input` | The single text input field |
| Mic button | `#say-mic` | Starts/stops voice recording |

**Behavior:**
1. User types text into `#say-input`.
2. User clicks `#say-mic` — recording starts.
3. Audio streams to `POST /api/voice`.
4. On transcript response, the transcript is **appended** to the existing content of `#say-input` (with a space separator if the field is non-empty).
5. The say box **never auto-submits**. Submission happens only when the user presses Enter.
6. On Enter, the text is sent to `POST /api/say` and the field is cleared.

### A.5 Instance key handling (§3, phase doc)

**Spec:** §3 — "A key in a query string is never written to a log." Phase doc — "Never expose the instance key except via the query-string path that is proven not to log. No `console.log` of the key."

**Rules:**
1. The instance key is passed to the HUD via the URL query string: `/?key=<instance_key>`.
2. The key is stored in a JavaScript variable and sent as the `X-Chronos-Key` header on every API request.
3. The key is **never** logged to the console.
4. The key is **never** written to `localStorage`, `sessionStorage`, or any persistent storage.
5. The key is **never** embedded in the HTML source.
6. The key is **never** sent in the request body — only in the header.
7. The query-string path is proven not to log because the server's access log configuration excludes query strings (§3).

### A.6 WebSocket (§8.3)

**Spec:** §8.3 — "One connection per client."

**Behavior:**
1. On load, the HUD opens a WebSocket connection to `/ws`.
2. The client sends `{type: "hello", key, device}` on connect.
3. The server responds with `{type: "state", ...}` — full snapshot.
4. Subsequent messages are patches, proposals, questions, timer ticks, and queued/retrying notifications.
5. The HUD re-renders the affected screen on each message.
6. On disconnect, the HUD attempts to reconnect with exponential backoff.

### A.7 File layout

```
chronos/web/
  __init__.py          — web mount helper (§D)
  static/
    index.html         — HUD markup (all 8 screens)
    styles.css         — dark flat styling
    app.js             — HUD behaviour
```

---

## B. CLI (§9.2)

### B.1 Commands

**Spec:** §9.2 — `serve | setup | key-renew | db-upgrade | token-cost | export`, `say -`, `get day | timer | briefing`.

Ten commands total. Each must actually run and produce output (phase doc).

### B.2 Output format

**Spec:** §9.2 — "Terse output, no prompts, safe to pipe."

**Rules:**
1. All output goes to stdout. Errors go to stderr.
2. No interactive prompts — all input comes from arguments, stdin, or environment.
3. Output is plain text or JSON, safe to pipe to other commands.
4. Exit code 0 on success, non-zero on failure.
5. No color codes when stdout is not a TTY.

### B.3 `chronos setup`

**Spec:** §5.1 — interactive provider/API-key configuration.

**Behavior:**
1. Ask for STT endpoint (must be OpenAI-compatible), model name, and number of API keys. Then ask for each key.
2. Ask how many text providers to configure. For each one, in order: ask for a name, base URL, model name, and number of API keys. Then ask for each key.
3. Ask for embeddings endpoint and model name.
4. Write all configuration to `.env`.
5. The order in which text providers are entered is the failover order.
6. Multiple keys per endpoint are tried round-robin before falling through.

**Arguments:** None (interactive).

### B.4 `chronos serve`

**Spec:** §8.1 — `chronos serve [--port 8080] [--host 0.0.0.0] [--db PATH] [--no-web]`

**Phase doc:** "`serve` must resolve the app factory `chronos.api.create_app` and pass `--db` through to it, or the app opens a different file than `--db` names."

**Behavior:**
1. Resolve `chronos.api.create_app` by importing `chronos.api`.
2. Call `create_app(db_path=args.db)` — pass `--db` through to the factory.
3. If `--no-web` is not set and `CHRONOS_WEB` is not `"0"`, mount the HUD via `chronos.web.mount_hud(app)`.
4. Start uvicorn with the configured host and port.
5. On first run, generate the instance key, print it once, and store the Argon2 hash (§3).

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `--port` | `8080` | Port to bind |
| `--host` | `0.0.0.0` | Host to bind |
| `--db` | `CHRONOS_DB` env var or `~/.chronos/chronos.db` | Database file path |
| `--no-web` | `False` | Run headless, API only (§8.1) |

### B.5 `chronos key-renew`

**Spec:** §3 — "`chronos key-renew` rotates it and disconnects every client."

**Behavior:**
1. Read the current instance key from the key file (see ambiguity §G.1).
2. Generate a new instance key.
3. Store the Argon2 hash of the new key in the database.
4. Disconnect all WebSocket clients.
5. Print the new key once.
6. The old key is invalidated immediately.

**Arguments:** None.

### B.6 `chronos db-upgrade`

**Spec:** §8.1 — `chronos db-upgrade`

**Phase doc:** "`db-upgrade` must invoke alembic through the current interpreter, not a PATH lookup, and the migration must load the sqlite-vec extension (the schema creates a `vec0` virtual table) and honour `CHRONOS_DB`."

**Behavior:**
1. Determine the database path from `CHRONOS_DB` env var or `--db` argument or default.
2. Load the sqlite-vec extension into the current Python process's SQLite connection.
3. Invoke alembic using `sys.executable -m alembic upgrade head` — **not** a PATH lookup of the `alembic` binary.
4. Set `CHRONOS_DB` in the subprocess environment so alembic uses the correct database file.
5. The migration creates the full schema including the `vec0` virtual table (§4.8).
6. On success, print the target alembic revision.
7. On failure, print the error and exit non-zero.

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `--db` | `CHRONOS_DB` env var or default | Database file path |

### B.7 `chronos token-cost`

**Spec:** §8.1 — `chronos token-cost [--days 7]`

**Behavior:**
1. Query the daily token-cost table for the specified number of days.
2. Print a terse summary: date, tokens, cost per day.
3. Print a total line.

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `--days` | `7` | Number of days to summarize |

### B.8 `chronos export`

**Spec:** §9.2 — listed as a command. §14 mentions "CSV export" as Milestone 4.

**Behavior:**
1. Export all data from the database to a file.
2. Default format: JSON. CSV is a Milestone 4 extension (§14).
3. The export includes: nodes, events, buckets, review_series, schedules, reminders, timer_sessions, settings, audit.
4. Output to stdout or a file specified by `--output`.

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `--format` | `json` | Export format (`json` only in v1) |
| `--output` | stdout | Output file path |

### B.9 `chronos say`

**Spec:** §9.2 — `echo "schedule DB review tomorrow 4pm for 45 mins" | chronos say -`

**Behavior:**
1. Read text from stdin (the `-` argument means stdin).
2. Send the text to `POST /api/say` on the local server.
3. Print the response (proposal, confirmation, or error) to stdout.
4. If the server is not running, print an error and exit non-zero.

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| (positional) | `-` | Read text from stdin (`-`) or from the argument itself |

### B.10 `chronos get`

**Spec:** §9.2 — `chronos get day | timer | briefing`

**Behavior:**
1. Query the local server's API.
2. Print the response as terse JSON or plain text.

**Subcommands:**

| Subcommand | API call | Output |
|---|---|---|
| `get day` | `GET /api/events?from&to` + `GET /api/briefing?date` | Day view: events, buckets, timer |
| `get timer` | `GET /api/timer` | Running timer state or "no timer" |
| `get briefing` | `GET /api/briefing?date` | Daily briefing |

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| (positional) | — | `day`, `timer`, or `briefing` |
| `--date` | today | Date in ISO-8601 for `day` and `briefing` |

### B.10 CLI authentication (§3)

**Spec:** §3 — "Every REST request, WebSocket upgrade, MCP call and CLI command requires it."

**Behavior:**
1. The CLI reads the instance key from `~/.chronos/key` (see ambiguity §G.1).
2. The key is sent as the `X-Chronos-Key` header on every API request.
3. If the key file does not exist, the CLI prints an error and exits non-zero.
4. The key is never printed to stdout (except by `key-renew`, which prints the new key once).

### B.11 File layout

```
chronos/cli/
  __init__.py          — package init, re-exports main
  __main__.py          — entry point, argparse, command dispatch
  commands.py          — command implementations
```

---

## C. MCP (§8.4)

### C.1 Tool set

**Spec:** §8.4 — "Exposes the same tool set to external agents." §5.5 — 27 tools.

The MCP server exposes exactly these 27 tools (§5.5, Phase 1 contracts §C.1–§C.27):

| # | Tool | Phase 1 contract |
|---|---|---|
| 1 | `create_node` | §C.1 |
| 2 | `update_node` | §C.2 |
| 3 | `delete_node` | §C.3 |
| 4 | `link_nodes` | §C.4 |
| 5 | `tag_node` | §C.5 |
| 6 | `untag_node` | §C.6 |
| 7 | `create_event` | §C.7 |
| 8 | `update_event` | §C.8 |
| 9 | `delete_event` | §C.9 |
| 10 | `schedule_series` | §C.10 |
| 11 | `delete_series` | §C.11 |
| 12 | `reschedule_series` | §C.12 |
| 13 | `search_nodes` | §C.13 |
| 14 | `check_conflict` | §C.14 |
| 15 | `find_free_slots` | §C.15 |
| 16 | `get_free_time` | §C.16 |
| 17 | `create_schedule` | §C.17 |
| 18 | `update_schedule` | §C.18 |
| 19 | `pause_schedule` | §C.19 |
| 20 | `start_timer` | §C.20 |
| 21 | `stop_timer` | §C.21 |
| 22 | `log_time` | §C.22 |
| 23 | `get_day` | §C.23 |
| 24 | `get_week` | §C.24 |
| 25 | `get_month` | §C.25 |
| 26 | `get_briefing` | §C.26 |
| 27 | `ask_question` | §C.27 |

**No tool is stubbed.** Every tool is fully functional and delegates to the injected executor.

### C.2 Executor adaptation

**Spec:** §8.4 — "Exposes the same tool set as the pipeline. Do not reimplement the tools — adapt to an injected executor."

**Behavior:**
1. The MCP server receives an `executor` at creation time.
2. The executor implements the same tool-call interface as the AI pipeline (§5.5).
3. Each MCP tool adapter:
   - Validates the incoming arguments against the tool schema (Phase 1 contracts §C).
   - Converts MCP tool calls to the executor's expected format.
   - Calls the executor.
   - Converts the executor's response back to MCP format.
4. The executor is the same code path that processes voice input — agents get "the same validation the user's voice input receives" (§8.4).

### C.3 Authentication

**Spec:** §3 — "Header `X-Chronos-Key`, with a query-string fallback for MCP clients that cannot set headers." §8.4 — "Authenticated with the instance key, header with a query-string fallback."

**Behavior:**
1. Every MCP call must include the instance key.
2. Primary: `X-Chronos-Key` header.
3. Fallback: `?key=<instance_key>` query string (for MCP clients that cannot set headers).
4. The key is verified against the Argon2 hash stored in the database (§3).
5. Unauthenticated calls are rejected with an error (phase doc: "unauthenticated MCP calls are rejected").
6. A key in a query string is never written to a log (§3).

### C.4 Audit

**Spec:** §8.4 — "Every call is audited." §4.7 — audit table schema.

**Behavior:**
1. Every MCP tool call writes an `AuditEntry` to the `audit` table (§4.7).
2. The audit entry includes:
   - `at`: current timestamp (epoch ms)
   - `device_id`: the MCP client's device identifier
   - `action`: the tool name (e.g., `create_event`)
   - `target`: the target entity id (if applicable)
   - `context`: the tool arguments as JSON
   - `cost_usd`: the cost of the call (if applicable)
3. Audit retention is 7 days (§4.7).

### C.5 File layout

```
chronos/mcp/
  __init__.py          — package init, re-exports create_mcp_server
  server.py            — MCP server creation and lifecycle
  tools.py             — tool adapters (27 tools)
  auth.py              — authentication middleware
```

---

## D. Web mount helper

### D.1 `chronos/web/__init__.py`

**Purpose:** Serves static files and mounts the HUD on a FastAPI app. Used by `chronos serve` (§8.1) unless `--no-web` or `CHRONOS_WEB=0`.

**Exports:**

```python
def mount_hud(app: FastAPI, db_path: str) -> None:
    """Mount the HUD static files and index route on the FastAPI app.
    
    Args:
        app: The FastAPI application to mount on.
        db_path: Path to the SQLite database file.
    
    Serves:
        /           → index.html
        /styles.css → styles.css
        /app.js     → app.js
    """
```

**Behavior:**
1. Mount the `chronos/web/static/` directory as a `StaticFiles` handler.
2. Add a route for `/` that serves `index.html`.
3. The HUD is served at the root path — the same origin as the API.
4. If `CHRONOS_WEB=0` or `--no-web`, `mount_hud` is not called (§8.1).

---

## E. File layout

### E.1 `chronos/web/`

| File | Purpose | Exports |
|---|---|---|
| `__init__.py` | Web mount helper — serves static files, mounts HUD | `mount_hud` |
| `static/index.html` | HUD markup — all 8 screens (§9.1) | — |
| `static/styles.css` | Dark flat styling — no glassmorphism (§9.1, §0.14) | — |
| `static/app.js` | HUD behaviour — navigation, API, WebSocket, calendar, input, timer | — |

### E.2 `chronos/cli/`

| File | Purpose | Exports |
|---|---|---|
| `__init__.py` | Package init | `main` (re-exported from `__main__`) |
| `__main__.py` | Entry point — argparse, command dispatch | `main` |
| `commands.py` | Command implementations — one function per command | `serve`, `key_renew`, `db_upgrade`, `token_cost`, `export`, `say`, `get` |

### E.3 `chronos/mcp/`

| File | Purpose | Exports |
|---|---|---|
| `__init__.py` | Package init | `create_mcp_server` (re-exported from `server`) |
| `server.py` | MCP server creation and lifecycle | `create_mcp_server` |
| `tools.py` | Tool adapters — 27 tools from §5.5 | `adapt_tools` |
| `auth.py` | Authentication middleware — instance key verification | `verify_key`, `extract_key` |

### E.4 Import graph (DAG)

```
chronos/web/__init__.py     (imports fastapi, chronos.contracts)
chronos/cli/__init__.py     (imports chronos.cli.__main__)
chronos/cli/__main__.py     (imports chronos.cli.commands, chronos.api, chronos.web)
chronos/cli/commands.py     (imports chronos.contracts, chronos.db, chronos.api)
chronos/mcp/__init__.py     (imports chronos.mcp.server)
chronos/mcp/server.py       (imports chronos.mcp.tools, chronos.mcp.auth, chronos.contracts)
chronos/mcp/tools.py        (imports chronos.contracts)
chronos/mcp/auth.py         (imports chronos.contracts, chronos.db)
```

No cycles. `chronos/contracts/` is the frozen shared surface (§2.1).

---

## F. Public API signatures

### F.1 `chronos/web/__init__.py`

```python
def mount_hud(app: FastAPI, db_path: str) -> None:
    """Mount the HUD static files and index route on the FastAPI app.
    
    Spec: §8.1 (--no-web), §9.1 (HUD served by host)
    
    Args:
        app: The FastAPI application to mount on.
        db_path: Path to the SQLite database file.
    """
```

### F.2 `chronos/cli/__main__.py`

```python
def main() -> int:
    """CLI entry point. Parse arguments, dispatch to command.
    
    Spec: §9.2
    
    Returns:
        Exit code (0 = success, non-zero = failure).
    """
```

### F.3 `chronos/cli/commands.py`

```python
def serve(args: argparse.Namespace) -> int:
    """Start the server. Resolves chronos.api.create_app, passes --db through.
    
    Spec: §8.1, phase doc (serve must resolve factory and forward --db)
    """

def key_renew(args: argparse.Namespace) -> int:
    """Rotate the instance key and disconnect all clients.
    
    Spec: §3
    """

def db_upgrade(args: argparse.Namespace) -> int:
    """Run alembic migrations through the current interpreter.
    
    Spec: §8.1, phase doc (alembic via sys.executable, sqlite-vec, CHRONOS_DB)
    """

def token_cost(args: argparse.Namespace) -> int:
    """Show token costs for the last N days.
    
    Spec: §8.1
    """

def export(args: argparse.Namespace) -> int:
    """Export all data from the database.
    
    Spec: §9.2, §14 (CSV export is Milestone 4)
    """

def say(args: argparse.Namespace) -> int:
    """Send text to the AI pipeline via stdin.
    
    Spec: §9.2
    """

def get(args: argparse.Namespace) -> int:
    """Query the local server's API.
    
    Spec: §9.2
    """
```

### F.4 `chronos/mcp/server.py`

```python
def create_mcp_server(
    executor: Any,
    db_path: str,
    device_id: str = "mcp",
) -> Any:
    """Create the MCP server with the injected executor.
    
    Spec: §8.4
    
    Args:
        executor: The tool-call executor (same interface as the AI pipeline).
        db_path: Path to the SQLite database file.
        device_id: Device identifier for audit entries.
    
    Returns:
        The MCP server instance.
    """
```

### F.5 `chronos/mcp/tools.py`

```python
def adapt_tools(executor: Any) -> list[dict]:
    """Adapt the 27 tools from §5.5 to MCP format.
    
    Spec: §8.4, §5.5
    
    Args:
        executor: The tool-call executor.
    
    Returns:
        List of MCP tool definitions, each with name, description,
        input_schema, and a handler that delegates to the executor.
    """
```

### F.6 `chronos/mcp/auth.py`

```python
def verify_key(key: str, db_path: str) -> bool:
    """Verify the instance key against the Argon2 hash in the database.
    
    Spec: §3
    
    Args:
        key: The instance key to verify.
        db_path: Path to the SQLite database file.
    
    Returns:
        True if the key is valid, False otherwise.
    """

def extract_key(headers: dict, query_string: str) -> str | None:
    """Extract the instance key from headers or query string.
    
    Spec: §3 — header X-Chronos-Key with query-string fallback.
    
    Args:
        headers: Request headers.
        query_string: URL query string.
    
    Returns:
        The instance key, or None if not found.
    """
```

---

## G. Spec ambiguities and open questions

1. **CLI key storage (§3, §9.2):** The spec says the instance key is "generated on first run, printed once, stored Argon2-hashed." The CLI needs the key to authenticate, but the hash is irreversible. Where does the CLI read the key from? **Proposal:** Store the raw key in `~/.chronos/key` (file permissions `0600`) on first run, alongside the Argon2 hash in the database. The CLI reads from this file. Confirm with Manager.

2. **`chronos export` format (§9.2, §14):** §9.2 lists `export` as a command but does not specify its format or scope. §14 mentions "CSV export" as Milestone 4. **Proposal:** v1 exports JSON only. CSV export is deferred to Milestone 4. Confirm with Manager.

3. **`chronos say` server dependency (§9.2):** The `say` command sends text to the AI pipeline via `POST /api/say`. This requires the server to be running. What should `say` do if the server is not running? **Proposal:** Print an error and exit non-zero. The command is a client, not a standalone AI processor. Confirm with Manager.

4. **MCP transport (§8.4):** The spec says "MCP `/mcp`" but does not specify the transport (stdio, SSE, WebSocket). **Proposal:** Use HTTP with the `/mcp` endpoint, consistent with the REST API. Confirm with Manager.

5. **HUD screen routing (§9.1):** The spec lists 8 screens but does not specify how they are navigated. **Proposal:** A top navigation bar with anchor links (`#today`, `#timer`, etc.). The active screen is shown; others are hidden. Confirm with Manager.

6. **Calendar drag/resize (§9.1):** The spec says "Drag to move, resize to change duration" but does not specify the interaction model in detail. **Proposal:** HTML5 drag-and-drop for move; edge handles for resize. Each interaction commits via `POST /api/commands` with `update_event`. Confirm with Manager.

7. **WebSocket reconnection (§8.3):** The spec does not specify reconnection behavior. **Proposal:** Exponential backoff starting at 1s, max 30s. Show a "disconnected" banner in the HUD. Confirm with Manager.

8. **`get_week` and `get_month` in CLI (§9.2):** The spec shows `get day | timer | briefing` but the MCP tool set includes `get_week` and `get_month` (§C.24, §C.25). **Proposal:** The CLI `get` command supports `day`, `timer`, and `briefing` only, as specified in §9.2. `get_week` and `get_month` are available via MCP and the REST API but not the CLI. Confirm with Manager.

---

## H. Summary

This proposal covers the complete interface surface for Phase 4:

- **Web HUD** — 8 screens, dark flat styling, no build step, 1-minute calendar grid with expandable hour detail, zero-form input, mic that appends, timer controls with mode-dependent field visibility, instance key via query string only
- **CLI** — 9 commands (`serve`, `key-renew`, `db-upgrade`, `token-cost`, `export`, `say`, `get day/timer/briefing`), terse output, every command tested by execution, `serve` resolves `chronos.api.create_app` and forwards `--db`, `db-upgrade` invokes alembic via `sys.executable` with sqlite-vec and `CHRONOS_DB`
- **MCP** — 27 tools matching §5.5 exactly, adapts to injected executor, authenticated with instance key (header + query-string fallback), every call audited
- **Web mount helper** — `chronos/web/__init__.py` with `mount_hud(app, db_path)`
- **File layout** — 3 files in `chronos/web/`, 3 in `chronos/cli/`, 4 in `chronos/mcp/`, all with specified exports and DAG import graph

The proposal is detailed enough that a code agent can implement it without re-reading the spec. All decisions are cited to the spec section. All tool schemas reference the frozen Phase 1 contracts.
