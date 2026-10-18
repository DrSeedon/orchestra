#!/bin/sh
# Сборка вертикального ролика вне cgroup платформы.
D=/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-video-sound/.orchestra/tasks/V-949
ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- /home/kesha/.local/share/orchestra-playwright/bin/python /home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-video-sound/scripts/video_artifact/make.py $D/scene.html --out $D --format vertical --hook 'Рестарт без потерь: пауза 40 секунд'" > $D/build.log 2>&1
echo "EXIT=$?" >> $D/build.log
