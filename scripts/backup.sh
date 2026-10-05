#!/usr/bin/env bash
# Chronos backup: timestamped file copies of the SQLite database.
# Copy the file and you have a backup — that is the whole story (spec §2).
set -euo pipefail

DB="${CHRONOS_DB:-$HOME/.chronos/chronos.db}"
BACKUP_DIR="${CHRONOS_BACKUP_DIR:-$HOME/.chronos/backups}"

if [ ! -f "$DB" ]; then
  echo "error: database not found at $DB" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/chronos-$STAMP.db"
cp "$DB" "$DEST"
echo "backup: $DEST"
