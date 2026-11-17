#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
ui_home="$(mktemp -d "$root/.orchestra/tasks/agy-acp-safe-20261117/ui-home.XXXXXX")"
trap 'rm -rf -- "$ui_home"' EXIT
sudo -n unshare --net -- /bin/bash -c '
  set -e
  /usr/sbin/ip link set lo up
  root="$1"; ui_home="$2"
  exec sudo -u kesha /usr/bin/env -i HOME="$ui_home" PATH=/usr/bin:/bin LANG=C.UTF-8 \
    ORCHESTRA_ACP_OFFLINE=1 /usr/bin/nice -n 10 "$root/.venv/bin/python" "$root/tests/antigravity_foreground_ui.py"
' offline-ui "$root" "$ui_home"
