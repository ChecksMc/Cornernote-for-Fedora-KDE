#!/usr/bin/env bash
set -euo pipefail

PURGE_CONFIG=0
if [[ "${1:-}" == "--purge-config" ]]; then
  PURGE_CONFIG=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--purge-config]" >&2
  exit 2
fi

CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"

systemctl --user disable --now cornernote.service >/dev/null 2>&1 || true
rm -f "${CONFIG_HOME}/systemd/user/cornernote.service"
rm -f "${HOME}/.local/bin/corner-note" "${HOME}/.local/bin/cornernote-daemon"
rm -f "${DATA_HOME}/applications/cornernote.desktop"
if [[ -n "${XDG_RUNTIME_DIR:-}" && -S "${XDG_RUNTIME_DIR}/cornernote.sock" ]]; then
  rm -f "${XDG_RUNTIME_DIR}/cornernote.sock"
fi
systemctl --user daemon-reload >/dev/null 2>&1 || true

if ((PURGE_CONFIG)); then
  rm -rf "${CONFIG_HOME}/cornernote"
  echo "CornerNote removed, including its saved configuration."
else
  echo "CornerNote removed. Saved settings remain in ${CONFIG_HOME}/cornernote."
  echo "Pass --purge-config to remove them too."
fi
