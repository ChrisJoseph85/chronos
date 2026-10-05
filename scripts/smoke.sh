#!/usr/bin/env bash
# Phase 3 smoke: boots the real server and proves the contract over HTTP.
set -euo pipefail

PORT="${1:-8099}"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  if [[ -n "${DB_FILE:-}" && -f "${DB_FILE}" ]]; then
    rm -f "${DB_FILE}"
  fi
}
trap cleanup EXIT

DB_FILE="$(mktemp /tmp/chronos-smoke-XXXXXX.db)"
rm -f "${DB_FILE}"

BIN=".venv/bin/chronos"
if [[ ! -x "${BIN}" ]]; then
  BIN="$(command -v chronos || true)"
fi
if [[ -z "${BIN}" ]]; then
  echo "smoke: chronos binary not found" >&2
  exit 1
fi

"${BIN}" serve --host 127.0.0.1 --port "${PORT}" --db "${DB_FILE}" > "/tmp/chronos-smoke-${PORT}.log" 2>&1 &
SERVER_PID=$!

# Poll /api/health — never a blind sleep.
for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null

# Discover the printed instance key from server output.
KEY=""
for _ in $(seq 1 40); do
  sleep 0.25
  CANDIDATES="$(grep -oE '[A-Za-z0-9_-]{32,}' "/tmp/chronos-smoke-${PORT}.log" 2>/dev/null || true)"
  for cand in ${CANDIDATES}; do
    if curl -fsS -H "X-Chronos-Key: ${cand}" "http://127.0.0.1:${PORT}/api/settings" >/dev/null 2>&1; then
      KEY="${cand}"
      break 2
    fi
  done
done
if [[ -z "${KEY}" ]]; then
  echo "smoke: could not discover instance key" >&2
  exit 1
fi

# 401 without key.
CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/settings")"
[[ "${CODE}" == "401" ]] || { echo "smoke: expected 401 without key, got ${CODE}" >&2; exit 1; }

# 401 bad key.
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Chronos-Key: wrong-key-xyz' "http://127.0.0.1:${PORT}/api/settings")"
[[ "${CODE}" == "401" ]] || { echo "smoke: expected 401 bad key, got ${CODE}" >&2; exit 1; }

# 200 good key.
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "X-Chronos-Key: ${KEY}" "http://127.0.0.1:${PORT}/api/settings")"
[[ "${CODE}" == "200" ]] || { echo "smoke: expected 200 good key, got ${CODE}" >&2; exit 1; }

# One English sentence commits a real event, read back out of SQLite.
SAY_OUT="$(curl -fsS -H "X-Chronos-Key: ${KEY}" -H 'Content-Type: application/json' \
  -d '{"text":"Schedule math review tomorrow 4pm for 45 minutes"}' \
  "http://127.0.0.1:${PORT}/api/say")"
echo "${SAY_OUT}" | grep -q '"committed"[[:space:]]*:[[:space:]]*true' || { echo "smoke: say did not commit: ${SAY_OUT}" >&2; exit 1; }
COUNT="$(python3 -c "import sqlite3;print(sqlite3.connect('${DB_FILE}').execute('SELECT COUNT(*) FROM events WHERE soft_deleted = 0').fetchone()[0])")"
[[ "${COUNT}" -ge 1 ]] || { echo "smoke: no event rows in SQLite" >&2; exit 1; }

# Second timer start is 409.
curl -fsS -H "X-Chronos-Key: ${KEY}" -H 'Content-Type: application/json' \
  -d '{"label":"smoke-first","source":"smoke","mode":"stopwatch"}' \
  "http://127.0.0.1:${PORT}/api/timer/start" >/dev/null
CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "X-Chronos-Key: ${KEY}" -H 'Content-Type: application/json' \
  -d '{"label":"smoke-second","source":"smoke","mode":"stopwatch"}' \
  "http://127.0.0.1:${PORT}/api/timer/start")"
[[ "${CODE}" == "409" ]] || { echo "smoke: expected 409 second timer, got ${CODE}" >&2; exit 1; }

echo "smoke: OK (401/401/200, sentence committed, second timer 409)"
