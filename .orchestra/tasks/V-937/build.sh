#!/bin/sh
# Полная сборка ролика вне cgroup платформы; ключ Deepgram читается из .env, не попадает в argv.
W=/home/kesha/orchestra/worktrees/home-kesha-orchestra/video-restart
D=$W/.orchestra/tasks/V-937
ssh -o BatchMode=yes kesha@localhost "choom -n 1000 -- sh -c 'export DEEPGRAM_API_KEY=\$(grep ^DEEPGRAM_API_KEY= /home/kesha/orchestra/.env | cut -d= -f2- | tr -d \"\\\"\"); /home/kesha/.local/share/orchestra-playwright/bin/python $W/scripts/video_artifact/make.py $D/scene.html --out $D'" > $D/build.log 2>&1
echo "EXIT=$?" >> $D/build.log
