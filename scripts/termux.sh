#!/usr/bin/env bash
# Chronos Termux installer/runner (Android phone, Termux prefix).
# No service manager, no root. Wake lock is taken BEFORE the server starts —
# Android doze kills a backgrounded server otherwise.
set -euo pipefail

VENV_DIR="${CHRONOS_VENV:-$HOME/.chronos/venv}"
HOST="${CHRONOS_HOST:-127.0.0.1}"
PORT="${CHRONOS_PORT:-8080}"
DB="${CHRONOS_DB:-$HOME/.chronos/chronos.db}"

# Embedding model: roughly 274 MB, fetched in the foreground with a
# visible progress bar — never downloaded silently inside a request.
MODEL_MB=274
MODEL_URL="${CHRONOS_MODEL_URL:-}"
MODEL_DST="${CHRONOS_MODEL_DST:-$HOME/.chronos/model.onnx}"

usage() {
  cat <<'EOF'
Usage: termux.sh <doctor|install|fetch-model|run|status|stop>
  doctor       report what this phone supports
  install      pkg install deps + python3 -m venv + pip install -e .
  fetch-model  download the ~274 MB embedding model with progress
  run          termux-wake-lock, then chronos serve
  status       poll /api/health
  stop         kill the server, release the wake lock
EOF
}

cmd_doctor() {
  echo "is Termux: $([ -d /data/data/com.termux ] && echo yes || echo no)"
  command -v pkg >/dev/null && echo "pkg: yes" || echo "pkg: no"
  command -v termux-wake-lock >/dev/null && echo "termux-wake-lock: yes" || echo "termux-wake-lock: no"
  command -v python3 >/dev/null && python3 --version || echo "python3: missing"
}

cmd_install() {
  pkg update -y
  pkg install -y python git rust binutils libsqlite
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install -e "$(dirname "$(dirname "$(readlink -f "$0")")")"
  echo "installed into $VENV_DIR"
}

cmd_fetch_model() {
  if [ -z "$MODEL_URL" ]; then
    echo "error: set CHRONOS_MODEL_URL first (no model URL is hardcoded)" >&2
    exit 1
  fi
  echo "downloading ~274 MB embedding model with progress: $MODEL_DST"
  mkdir -p "$(dirname "$MODEL_DST")"
  # curl --progress-bar keeps progress visible; -C - resumes after a kill.
  curl --progress-bar -C - -o "$MODEL_DST" "$MODEL_URL"
  echo "model saved to $MODEL_DST"
}

cmd_run() {
  termux-wake-unlock 2>/dev/null || true
  termux-wake-lock
  echo "wake lock held; starting server"
  exec chronos serve --host "$HOST" --port "$PORT" --db "$DB"
}

cmd_status() {
  for _ in $(seq 1 10); do
    if curl -fsS "http://$HOST:$PORT/api/health" >/dev/null 2>&1; then
      echo "[health] UP"
      return 0
    fi
    sleep 1
  done
  echo "[health] DOWN"
  return 1
}

cmd_stop() {
  pkill -f "chronos serve" 2>/dev/null || true
  termux-wake-unlock 2>/dev/null || true
  echo "stopped"
}

case "${1:-}" in
  doctor) cmd_doctor ;;
  install) cmd_install ;;
  fetch-model) cmd_fetch_model ;;
  run) cmd_run ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  *) usage; exit 1 ;;
esac
