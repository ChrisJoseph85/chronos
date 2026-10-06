#!/usr/bin/env bash
# Chronos desktop installer — user level only.
# NEVER uses sudo. NEVER edits ~/.config/hypr/ (prints snippets as text only).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HOME}/.local/share/chronos-desktop/.venv"

if command -v uv >/dev/null 2>&1; then
  echo "[install] creating venv with uv: ${VENV}"
  uv venv "${VENV}"
  uv pip install --python "${VENV}/bin/python" -e "${HERE}"
else
  echo "[install] creating venv with python3: ${VENV}"
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install -e "${HERE}"
fi

mkdir -p "${HOME}/.config/autostart"
cat > "${HOME}/.config/autostart/chronos-desktop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Chronos Desktop
Comment=Chronos timer/planner bar (Omarchy/Hyprland)
Exec=${VENV}/bin/chronos-desktop
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
EOF
echo "[install] wrote ${HOME}/.config/autostart/chronos-desktop.desktop"

# Launcher entry: autostart/ is executed at login but never indexed by app
# launchers — without this file the app is invisible in wofi/rofi/menus.
mkdir -p "${HOME}/.local/share/applications"
cat > "${HOME}/.local/share/applications/chronos-desktop.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Chronos Desktop
Comment=Chronos timer/planner bar (Omarchy/Hyprland)
Exec=${VENV}/bin/chronos-desktop
Terminal=false
Categories=Utility;
EOF
echo "[install] wrote ${HOME}/.local/share/applications/chronos-desktop.desktop"
command -v update-desktop-database >/dev/null 2>&1 \
  && update-desktop-database "${HOME}/.local/share/applications" \
  || true

cat <<'EOF'
[install] Optional Hyprland bits — apply manually, installer never edits hypr/:

  # ~/.config/hypr/hyprland.conf — keep the bar floating on top:
  windowrulev2 = float, class:^(chronos-desktop)$, title:^(Chronos Bar)$
  windowrulev2 = pin,   class:^(chronos-desktop)$, title:^(Chronos Bar)$

  # ~/.config/hypr/autostart.lua (if you use it) — launch on login:
  -- o.launch_on_start = o.launch_on_start or {}
  -- table.insert(o.launch_on_start, os.getenv("HOME") .. "/.local/share/chronos-desktop/.venv/bin/chronos-desktop")
EOF
echo "[install] done. Run: ${VENV}/bin/chronos-desktop --smoke"
