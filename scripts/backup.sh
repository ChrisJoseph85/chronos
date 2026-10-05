#!/usr/bin/env bash
# Chronos backup: timestamped file copies of the SQLite database.
# Online backup with a WAL checkpoint + brief lock/busy-retry before copy
# (spec Chronos.md §2: backup is timestamped file copies).
#
# Assumption: the server is briefly quiesced (no write transaction in flight)
# but stays online — no shutdown required. The checkpoint folds the WAL back
# into the main db file so the `cp` below captures a consistent snapshot;
# the busy-retry loop waits out a momentary writer lock instead of copying
# a hot file mid-write.
set -euo pipefail

DB="${CHRONOS_DB:-$HOME/.chronos/chronos.db}"
BACKUP_DIR="${CHRONOS_BACKUP_DIR:-$HOME/.chronos/backups}"

if [ ! -f "$DB" ]; then
  echo "error: database not found at $DB" >&2
  exit 1
fi

# Fold the WAL into the main file first (TRUNCATE resets the WAL), waiting
# briefly if the database is locked by an in-flight writer.
checkpoint_wal() {
  python3 - "$DB" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1], timeout=5.0)
try:
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
finally:
    conn.close()
PY
}

ATTEMPT=1
while [ "$ATTEMPT" -le 10 ]; do
  if checkpoint_wal; then
    break
  fi
  if [ "$ATTEMPT" -eq 10 ]; then
    echo "error: database locked, checkpoint failed after retries" >&2
    exit 1
  fi
  sleep 0.5
  ATTEMPT=$((ATTEMPT + 1))
done

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/chronos-$STAMP.db"
cp "$DB" "$DEST"
echo "backup: $DEST"
