# Chronos backend API — frozen (backend-only)

**2026-10-05. This is the contract your 3-4 clients build against in parallel. It does not change without a version bump. No web UI. REST + WebSocket + MCP only.**

Base: `http://127.0.0.1:8080`. Time: DB = UTC epoch ms `INTEGER`; API = ISO-8601 with offset. Timezone = one instance `instance.timezone`. Grid = 1 minute, snap on write.

## Auth

- One instance key, Argon2-hashed, printed once on first `chronos serve`.
- Header `X-Chronos-Key`, fallback `?key=` (MCP only). Never logged.
- `GET /api/health` is the ONLY open route. Everything else 401 without key, 401 bad key. `POST /api/keys/renew` rotates + drops WS with 4001.

## REST

```
POST /api/say        {text, device_id?} -> {intent, tool_calls[], proposal_id?, committed, events[], message}
POST /api/commands   {tool, arguments, device_id?} -> {tool, result, events[], proposal_id?}
POST /api/voice      multipart audio -> {transcript}
GET  /api/events?from=ISO&to=ISO -> Event[]
GET  /api/nodes?parent=&tag= -> Node[]
GET  /api/buckets?level=Y|M|W|D&date= -> Bucket[]
GET  /api/briefing?date=YYYY-MM-DD -> {date, unallocated_tasks, rollover, due_reviews, question?}
GET  /api/search?q=&limit= -> Node[]
GET  /api/reminders -> Reminder[] (pending, by fire_at_ms)
POST /api/timer/start {node_id?,label,mode,target_ms?,source} -> TimerSession (409 if one running; stopwatch ignores target_ms)
POST /api/timer/stop  {source} -> TimerSession (409 if none)
GET  /api/timer?node_id= -> TimerSession|null
GET  /api/timer/summary?node_id= -> {node_total_ms, descendant_total_ms, project_total_ms} (pomodoro breaks excluded)
GET  /api/timer/presets -> Preset[] (always includes 25/5x4)
POST /api/timer/presets {name,focus_minutes,break_minutes,cycles} -> Preset (append)
GET  /api/stats -> {counts, streaks} (no token-cost — removed)
GET  /api/settings -> dict (hides key hash)
PUT  /api/settings {k:v} -> dict (merge, not replace)
POST /api/keys/renew -> {new_key}
GET  /api/health -> {status:"ok", version, db_path, uptime_seconds}
```

`/api/say` never silently commits ambiguous input: proposal + at most one `question`. Unimplemented tool never returns `success:true`.

## WebSocket `/ws`

Auth on upgrade, then `accept()`. Reject = 4001.
- `client -> {hello key device} | {say text} | {accept|reject|skip proposal_id}`
- `server -> {state} | {patch ops[]} | {proposal} | {question} | {timer} | {queued} | {retrying}`
- Every mutation broadcasts to all clients.

## MCP `/mcp` (HTTP)

Same 27 tools as `TOOL_SCHEMAS`, adapted to injected `ToolDispatcher.dispatch`. Same auth, same validation as voice. Every call writes `audit` row.

Tools: `create_node update_node delete_node link_nodes tag_node untag_node create_event update_event delete_event schedule_series delete_series reschedule_series search_nodes check_conflict find_free_slots get_free_time create_schedule update_schedule pause_schedule start_timer stop_timer log_time get_day get_week get_month get_briefing ask_question`.

Rules: absolute ISO dates only; series = one call; no move tool; hard blocks + overlaps resolved in code; series must be bounded (`max_count` and/or `ends_on_ms`); tags never on projects.

## Errors

`401 Missing/Invalid key`, `409 timer running`, `422 schema`, `500 internal (redacted)`. `overlap: half-open [from,to)`. `soft_deleted` never conflicts.

## Startup (proot-distro)

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/chronos serve --host 127.0.0.1 --port 8080 --db ~/.chronos/chronos.db
curl -fsS http://127.0.0.1:8080/api/health
```

Docker (unverified here, CI-owned): `docker compose up --build`, volume `chronos-data:/data`, `.env` via `env_file required:false`, healthcheck `/api/health`.
