#!/usr/bin/env bash
# Chronos Termux launcher (Android phone, Termux prefix).
# Termux's own python must NEVER run the app (version drift is the bug).
# `pkg` is used ONLY for host bootstrap (proot-distro itself).
# Everything app-side happens INSIDE the distro via uv with a pinned
# interpreter (default 3.14.7, override with CHRONOS_PYTHON).
# No service manager, no root. Wake lock is taken BEFORE the server starts —
# Android doze kills a backgrounded server otherwise.
set -euo pipefail

# proot-distro names instances by distro, not by free choice: the login name
# IS the distro name. We default to ubuntu; override with CHRONOS_DISTRO.
# A user-visible label "chronos" cannot be used as the instance name.
DISTRO="${CHRONOS_DISTRO:-ubuntu}"
PYTHON_PIN="${CHRONOS_PYTHON:-3.14.7}"

VENV_DIR="${CHRONOS_VENV:-$HOME/.chronos/venv}"
HOST="${CHRONOS_HOST:-127.0.0.1}"
PORT="${CHRONOS_PORT:-8080}"
DB="${CHRONOS_DB:-$HOME/.chronos/chronos.db}"
REPO_ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"

# Embedding model: roughly 274 MB, fetched in the foreground with a
# visible progress bar — never downloaded silently inside a request.
# The fetch runs INSIDE the distro (curl there), never on the Termux prefix.
MODEL_MB=274
MODEL_URL="${CHRONOS_MODEL_URL:-}"
MODEL_DST="${CHRONOS_MODEL_DST:-$HOME/.chronos/model.onnx}"

usage() {
  cat <<'EOF'
Usage: termux.sh <doctor|install|fetch-model|run|status|stop>
  doctor       report proot-distro + instance presence and host tooling
  install      host bootstrap (proot-distro) + distro install + uv venv
  fetch-model  download the ~274 MB embedding model with progress (inside distro)
  run          termux-wake-lock, then serve inside the distro
  status       poll /api/health from outside the distro
  stop         kill the server, release the wake lock
EOF
}

has_instance() {
  proot-distro list 2>/dev/null | grep -q "$DISTRO"
}

cmd_doctor() {
  echo "is Termux: $([ -d /data/data/com.termux ] && echo yes || echo no)"
  command -v pkg >/dev/null && echo "pkg: yes" || echo "pkg: no"
  command -v termux-wake-lock >/dev/null && echo "termux-wake-lock: yes" || echo "termux-wake-lock: no"
  command -v proot-distro >/dev/null && echo "proot-distro: yes" || echo "proot-distro: no"
  if command -v proot-distro >/dev/null 2>&1; then
    proot-distro list || echo "proot-distro list: failed"
    if has_instance; then
      echo "instance ($DISTRO): present"
    else
      echo "instance ($DISTRO): missing"
    fi
  else
    echo "instance ($DISTRO): unknown (no proot-distro)"
  fi
}

cmd_install() {
  # Host bootstrap ONLY: proot-distro itself. App python never comes from here.
  pkg update -y
  pkg install -y proot-distro
  # Check-before-install: only install the distro when the instance is missing.
  if proot-distro list | grep -q "$DISTRO"; then
    echo "instance $DISTRO already present"
  else
    proot-distro install "$DISTRO"
  fi
  # Everything app-side happens INSIDE the distro.
  proot-distro login "$DISTRO" -- sh -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
  # Pinned interpreter inside the distro (default 3.14.7).
  proot-distro login "$DISTRO" -- sh -c "\$HOME/.local/bin/uv python install $PYTHON_PIN"
  # uv python install 3.14.7 is the pinned default above (CHRONOS_PYTHON overrides).
  proot-distro login "$DISTRO" -- sh -c "cd '$REPO_ROOT' && \$HOME/.local/bin/uv venv '$VENV_DIR' && \$HOME/.local/bin/uv pip install -e ."
  echo "installed inside $DISTRO ($VENV_DIR)"
}

cmd_fetch_model() {
  if [ -z "$MODEL_URL" ]; then
    echo "error: set CHRONOS_MODEL_URL first (no model URL is hardcoded)" >&2
    exit 1
  fi
  echo "downloading ~274 MB embedding model with progress inside $DISTRO: $MODEL_DST"
  # Visible progress inside the distro; -C - resumes after a kill.
  # Never fetched silently inside a request.
  proot-distro login "$DISTRO" -- sh -c "mkdir -p '$(dirname "$MODEL_DST")' && curl --progress-bar -C - -o '$MODEL_DST' '$MODEL_URL'"
  echo "model saved to $MODEL_DST"
}

cmd_run() {
  termux-wake-unlock 2>/dev/null || true
  termux-wake-lock
  echo "wake lock held; starting server inside $DISTRO"
  exec proot-distro login "$DISTRO" -- sh -c "exec chronos serve --host '$HOST' --port '$PORT' --db '$DB'"
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
