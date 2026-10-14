#!/bin/bash
# runs the same test files in full and sparse clone, same interpreter, imports from clone cwd
cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/disk-audit/.orchestra/tasks/V-821/evidence
F=$(cat testfiles.txt)
for k in full sparse; do
  cd /tmp/v821/orchestra-t-$k
  nice -n 15 timeout 1500 /home/kesha/orchestra/.venv/bin/python -m pytest $F -q -p no:cacheprovider --timeout=120 -m "not live_probe" > /tmp/v821/pytest-$k.log 2>&1
  echo "$k rc=$?"; tail -3 /tmp/v821/pytest-$k.log
  cd - >/dev/null
done
