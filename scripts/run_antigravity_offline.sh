#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
stand_home="$(mktemp -d "$root/.orchestra/tasks/agy-acp-safe-20261116/offline-home.XXXXXX")"
# No provider/account environment; only an ephemeral network namespace is changed.
sudo -n unshare --net -- /bin/bash -c '
  set -e
  /usr/sbin/ip link set lo up
  root="$1"; stand_home="$2"; shift 2
  exec sudo -u kesha /usr/bin/env -i HOME="$stand_home" PATH=/usr/bin:/bin LANG=C.UTF-8 \
    ORCHESTRA_ACP_OFFLINE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    ORCHESTRA_DB_PATH="$stand_home/orchestra.db" \
    /usr/bin/nice -n 10 /home/kesha/orchestra/.venv/bin/python \
    "$root/scripts/run_antigravity_offline.py" "$@"
' offline-namespace "$root" "$stand_home" "$@"
