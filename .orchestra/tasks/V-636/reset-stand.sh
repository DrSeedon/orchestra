#!/bin/bash
# V-636: перезапуск стенда с чистым разговором оркестратора и пустой рабочей папкой (тестовые файлы).
set -e
D=/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-reestr-demo/.orchestra/tasks/V-636
python3 -c "import json,sys; print(json.dumps({'scope':'/workspace/project','system_prompt':open(sys.argv[1]).read()}))" $D/stand-orchestrator-prompt.md > /tmp/v636_prompt.json
scp -q /tmp/v636_prompt.json $D/stand-orchestrator-tools.sql "root@${STAND_HOST:?set STAND_HOST}":/tmp/
ssh -o BatchMode=yes "root@${STAND_HOST:?set STAND_HOST}" 'set -e; cd /home/kesha/orchestra-reestr-demo
systemctl stop orchestra-reestr-demo
sudo -u kesha sqlite3 data/orchestra.db < /tmp/stand-orchestrator-tools.sql
systemctl start orchestra-reestr-demo; sleep 20
T=$(grep ^INTERNAL_TOKEN .env | cut -d= -f2)
curl -s -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d @/tmp/v636_prompt.json http://127.0.0.1:8888/api/sessions/orchestrator/prompt; echo
curl -s -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "{\"scope\":\"/workspace/project\"}" http://127.0.0.1:8888/api/sessions/orchestrator/clear-session; echo
for w in $(sqlite3 data/orchestra.db "select name from sessions where is_orchestrator=0"); do
  curl -s -X DELETE -H "Authorization: Bearer $T" "http://127.0.0.1:8888/api/sessions/$w?scope=%2Fworkspace%2Fproject&force=true"; echo " deleted $w"
done
cd /workspace/project
sudo -u kesha git checkout -q main
for b in $(sudo -u kesha git branch --format="%(refname:short)" | grep -v "^main$"); do sudo -u kesha git branch -q -D "$b"; done
sudo -u kesha git worktree prune
sudo -u kesha git clean -fdq
sudo -u kesha git status --short; sudo -u kesha git branch; ls
cd /home/kesha/orchestra-reestr-demo
sqlite3 data/orchestra.db "select name,status from sessions"'
