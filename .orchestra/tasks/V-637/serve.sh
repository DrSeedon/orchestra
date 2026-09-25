#!/bin/bash
# isolated env: nothing from the parent Orchestra process leaks in. Restarts uvicorn when it exits (reset.sh kills it).
while [ ! -e /home/kesha/bench-v637/STOP ]; do
env -i HOME=/home/kesha/bench-v637/home PATH=/home/kesha/.local/bin:/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 bash -c '
cd /home/kesha/bench-v637/stand
set -a; . ./.env; set +a
export ORCHESTRA_TASK_REPOSITORY=/home/kesha/bench-v637/data/tasks
echo $$ > /home/kesha/bench-v637/uvicorn.pid
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8912 >> /home/kesha/bench-v637/server.log 2>&1'
sleep 1
done
