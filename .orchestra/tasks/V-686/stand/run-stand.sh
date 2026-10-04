#!/bin/bash
# Fresh stand: new throwaway state dir each run, real dashboard code from a git-archive copy.
set -e
ROOT=/home/kesha/readme-stand-V686
STATE=$ROOT/state-$(date +%H%M%S)
mkdir -p "$STATE"
ln -sfn "$STATE" "$ROOT/state"
cd "$ROOT/orchestra"
exec env -i HOME=/srv/demo PATH=$ROOT/bin LANG=C.UTF-8 \
  GIT_AUTHOR_NAME=demo GIT_AUTHOR_EMAIL=demo@example.com GIT_COMMITTER_NAME=demo GIT_COMMITTER_EMAIL=demo@example.com \
  STAND="$STATE" PORT=8897 /home/kesha/orchestra/.venv/bin/python "$(dirname "$0")/stand.py" > "$STATE/server.log" 2>&1
