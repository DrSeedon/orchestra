#!/bin/bash
# #336: повтор ключевого числа (#329 набор одним вызовом) на менее нагруженной машине.
# Пишет load average рядом с результатом — без него число несравнимо с первым замером.
cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge-gate
PY=/home/kesha/orchestra/.venv/bin/python
OUT=/tmp/336-measure2.txt
FILES="tests/test_db.py tests/test_default_pipeline.py tests/test_manager.py tests/test_pipeline.py tests/test_quota_gate.py tests/test_worker_model_policy.py"
{
  echo "load-before: $(cut -d' ' -f1-3 /proc/loadavg)  pytest-procs: $(pgrep -c -f 'm pytest' || echo 0)"
  s=$(date +%s.%N)
  PYTHONPATH=$PWD timeout 1200 "$PY" -m pytest -q -m "not live_probe" $FILES > /tmp/336-all2.log 2>&1
  rc=$?
  e=$(date +%s.%N)
  printf 'ALL-6-IN-ONE rc=%s %.2fs  %s\n' "$rc" "$(echo "$e - $s" | bc)" "$(tail -2 /tmp/336-all2.log | tr '\n' ' ')"
  echo "load-after:  $(cut -d' ' -f1-3 /proc/loadavg)  pytest-procs: $(pgrep -c -f 'm pytest' || echo 0)"
  echo MEASURE2-DONE
} > "$OUT" 2>&1
