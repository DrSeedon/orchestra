#!/usr/bin/env bash
# V-775 advisor matrix: 2 tasks x 5 arms x 3 repeats, 6 parallel
cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/research-anthropic-api
A=.orchestra/tasks/V-775/scripts/agent.py; PY=data/v775/venv/bin/python
H=claude-haiku-5-5; S=claude-sonnet-5-5; O=claude-opus-5-5
for r in 1 2 3; do
 for t in "pidfd 1fc6beb6 180a5a4f tests/test_pidfd_leaks.py" "ident 13648c8f 0c3c0fcb tests/test_identity_drift.py"; do
  set -- $t
  echo "$PY $A $1-H-r$r $2 $3 data/v775/task-$1.txt $H low none \"$4\""
  echo "$PY $A $1-HO-r$r $2 $3 data/v775/task-$1.txt $H low $O \"$4\""
  echo "$PY $A $1-HS-r$r $2 $3 data/v775/task-$1.txt $H low $S \"$4\""
  echo "$PY $A $1-S-r$r $2 $3 data/v775/task-$1.txt $S medium none \"$4\""
 done
done | xargs -P 2 -I{} bash -c 'nice -n 15 ionice -c 2 -n 7 {} 2>&1 | tail -1' | tee data/v775/matrix.log
