#!/bin/bash
# V-637 (runs ON the stand as root): checkpoint <name> | restore <name>. Checkpoint is taken while agents are idle.
set -e
cd /home/kesha/orchestra-reestr-demo
D=data/backups/v637-cp-$2
case "$1" in
checkpoint)
  sudo -u kesha mkdir -p $D
  sudo -u kesha sqlite3 data/orchestra.db ".backup $D/orchestra.db"
  sudo -u kesha tar -czf $D/data-extra.tgz -C data tasks harness-sessions
  sudo -u kesha tar -czf $D/workspace.tgz -C /workspace project
  sudo -u kesha tar -czf $D/worktrees.tgz worktrees
  echo "checkpoint $D";;
restore)
  test -f $D/orchestra.db
  systemctl stop orchestra-reestr-demo
  T=data/backups/v637-discarded-$(date -u +%H%M%S); sudo -u kesha mkdir -p $T
  for x in data/tasks data/harness-sessions data/orchestra.db data/orchestra.db-wal data/orchestra.db-shm worktrees /workspace/project; do [ -e $x ] && mv $x $T/ || true; done
  sudo -u kesha cp $D/orchestra.db data/orchestra.db
  sudo -u kesha tar -xzf $D/data-extra.tgz -C data
  sudo -u kesha tar -xzf $D/workspace.tgz -C /workspace
  sudo -u kesha tar -xzf $D/worktrees.tgz
  systemctl start orchestra-reestr-demo
  for i in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:8888/ && break; sleep 1; done; sleep 5
  echo "restored $D (discarded state in $T)";;
esac
