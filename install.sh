#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/cornernote"
APP_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"

echo "CornerNote source: ${PROJECT_DIR}"
if [[ "${XDG_SESSION_TYPE:-}" != "wayland" ]]; then
  echo "Warning: this installer expects a KDE Wayland session."
fi

missing=()
for package in python3-gobject python3-cairo gtk-layer-shell; do
  if command -v rpm >/dev/null && ! rpm -q "${package}" >/dev/null 2>&1; then
    missing+=("${package}")
  fi
done
if ((${#missing[@]})); then
  echo "Missing Fedora packages: ${missing[*]}"
  echo "Install them with: sudo dnf install ${missing[*]}"
  exit 1
fi
python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("GtkLayerShell", "0.1"); from gi.repository import Gtk, GtkLayerShell' || {
  echo "GTK 3 / GtkLayerShell introspection is unavailable. Install python3-gobject and gtk-layer-shell." >&2
  exit 1
}

mkdir -p "${BIN_DIR}" "${CONFIG_DIR}" "${APP_DIR}" "${UNIT_DIR}"
if [[ ! -e "${CONFIG_DIR}/config.json" ]]; then
  install -m 0644 "${PROJECT_DIR}/config.example.json" "${CONFIG_DIR}/config.json"
fi
install -m 0755 "${PROJECT_DIR}/corner-note" "${BIN_DIR}/corner-note"
cat > "${BIN_DIR}/cornernote-daemon" <<EOF
#!/usr/bin/env bash
export CORNERNOTE_CONFIG="\${XDG_CONFIG_HOME:-\${HOME}/.config}/cornernote/config.json"
exec /usr/bin/python3 "${PROJECT_DIR}/src/main.py"
EOF
chmod 0755 "${BIN_DIR}/cornernote-daemon"

sed "s|^Exec=.*|Exec=${BIN_DIR}/corner-note toggle|" \
  "${PROJECT_DIR}/cornernote.desktop" > "${APP_DIR}/cornernote.desktop"
cat > "${UNIT_DIR}/cornernote.service" <<EOF
[Unit]
Description=CornerNote quick-note overlay
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=${BIN_DIR}/cornernote-daemon
Restart=on-failure
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=graphical-session.target
EOF

chmod 0755 "${PROJECT_DIR}/corner-note" "${PROJECT_DIR}/install.sh"
systemctl --user daemon-reload
systemctl --user enable cornernote.service
echo
echo "Installed. Start it with: systemctl --user start cornernote"
echo "Bind a global shortcut in System Settings → Shortcuts → Add New → Command or URL"
echo "Command: ${BIN_DIR}/corner-note toggle"
echo "Uninstall with: ${PROJECT_DIR}/uninstall.sh"
