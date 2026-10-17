#!/bin/bash
# V-939 build: make.py outside the platform cgroup, marked "kill first" (choom 1000).
# Usage: run.sh [extra make.py args], e.g. run.sh --stress-only
set -euo pipefail
W=/home/kesha/orchestra/worktrees/home-kesha-orchestra/video-oom
K=${DEEPGRAM_API_KEY:-$(sed -n 's/^DEEPGRAM_API_KEY=//p' /home/kesha/orchestra/.env | tr -d '"')}
printf '%s\n' "$K" | ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- bash -c 'read -r K; cd $W/.orchestra/tasks/V-939 && DEEPGRAM_API_KEY=\$K /home/kesha/.local/share/orchestra-playwright/bin/python $W/scripts/video_artifact/make.py scene.html --out video $*'"
