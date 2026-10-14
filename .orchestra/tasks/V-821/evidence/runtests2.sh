#!/bin/bash
cd /tmp/v821c/wt/tmp-v821c-orchestra/smoke-orchestra
nice -n 15 timeout 1500 /home/kesha/orchestra/.venv/bin/python -m pytest $(cat /home/kesha/orchestra/worktrees/home-kesha-orchestra/disk-audit/.orchestra/tasks/V-821/evidence/testfiles.txt) -q -p no:cacheprovider --timeout=120 -m "not live_probe" > /home/kesha/orchestra/worktrees/home-kesha-orchestra/disk-audit/.orchestra/tasks/V-821/evidence/pytest-sparse-rule.log 2>&1
tail -3 /home/kesha/orchestra/worktrees/home-kesha-orchestra/disk-audit/.orchestra/tasks/V-821/evidence/pytest-sparse-rule.log
