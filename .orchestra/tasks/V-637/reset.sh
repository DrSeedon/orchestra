#!/bin/bash
# restore the pristine local stand state (DB, task store, chat history, workspace) and restart the server
set -e
B=/home/kesha/bench-v637
touch $B/PAUSE
kill $(cat $B/uvicorn.pid) 2>/dev/null || true
P=$(cat $B/uvicorn.pid 2>/dev/null); for i in $(seq 60); do kill -0 $P 2>/dev/null || break; sleep 1; done
for x in $B/data/tasks $B/data/harness-sessions $B/data/orchestra.db*; do [ -e $x ] && trash $x; done
cp $B/pristine/orchestra.db $B/data/orchestra.db
cp -a $B/pristine/tasks $B/data/tasks
cp -a $B/pristine/harness-sessions $B/data/harness-sessions
cd /workspace/project
for w in $(git worktree list --porcelain | awk '/^worktree /{print $2}' | grep -v '^/workspace/project$'); do git worktree remove --force "$w"; done
git checkout -q main; git reset -q --hard $(cat $B/pristine/ws-head); git clean -fdq
for b in $(git branch --format='%(refname:short)' | grep -v '^main$'); do git branch -q -D "$b"; done
git worktree prune
for x in $B/stand/worktrees; do [ -e $x ] && trash $x; done; true
rm -f $B/PAUSE
for i in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:8912/ && break; sleep 1; done
sleep 3
