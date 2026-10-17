#!/bin/bash
# Сборка V-938 вне cgroup платформы; ключ Deepgram идёт через stdin, не в командной строке.
W=/home/kesha/orchestra/worktrees/home-kesha-orchestra/video-sparse
K=${DEEPGRAM_API_KEY:-$(grep -m1 '^DEEPGRAM_API_KEY=' /home/kesha/orchestra/.env | cut -d= -f2-)}
printf '%s\n' "$K" | ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- bash -c 'read -r K; cd $W/.orchestra/tasks/V-938 && DEEPGRAM_API_KEY=\$K ~/.local/share/orchestra-playwright/bin/python $W/scripts/video_artifact/make.py scene.html --out video $*'"
