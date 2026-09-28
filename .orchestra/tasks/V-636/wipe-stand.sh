#!/bin/bash
# V-636: стереть на стенде историю прогонов (чаты, воркеры, задачи, журналы) после backup().
# Настройки, модели, учётные данные, проект и сам оркестратор остаются. Затем reset-stand.sh.
set -e
ssh -o BatchMode=yes "root@${STAND_HOST:?set STAND_HOST}" 'set -e; cd /home/kesha/orchestra-reestr-demo
systemctl stop orchestra-reestr-demo
S=$(date -u +%Y%m%dT%H%M%SZ)
sudo -u kesha mkdir -p data/backups
sudo -u kesha sqlite3 data/orchestra.db ".backup data/backups/orchestra-$S-before-wipe.db"
sudo -u kesha tar -czf data/backups/harness-sessions-$S-before-wipe.tgz -C data harness-sessions
# Задачи живут в Git-хранилище data/tasks, tm_tasks — лишь его проекция: без переноса хранилища
# стёртые задачи вернулись бы при следующей пересборке проекции. Пустое хранилище платформа
# создаёт сама при старте, если проекция пуста.
sudo -u kesha mv data/tasks data/backups/tasks-$S-before-wipe
sudo -u kesha sqlite3 data/orchestra.db "PRAGMA foreign_keys=ON; BEGIN;
delete from initial_deliveries; delete from message_deliveries;
delete from logs; delete from tool_errors; delete from turn_usage; delete from review_receipts;
delete from tm_tasks; delete from task_projection_meta;
delete from sqlite_sequence where name=\"tm_tasks\";
delete from sessions where is_orchestrator=0;
update sessions set task_id=\"\" where is_orchestrator=1;
COMMIT;"
for f in data/harness-sessions/*; do [ -e "$f" ] && sudo -u kesha rm -f "$f"; done
cd /workspace/project
for w in $(sudo -u kesha git worktree list --porcelain | awk "/^worktree /{print \$2}" | grep -v "^/workspace/project$"); do sudo -u kesha git worktree remove --force "$w"; done
echo "backup: /home/kesha/orchestra-reestr-demo/data/backups/orchestra-$S-before-wipe.db"'
"$(dirname "$0")/reset-stand.sh"
