#!/bin/bash
# #336: per-file cost of the #329 mapped set, exactly as the gate invokes pytest.
cd /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-merge-gate
PY=/home/kesha/orchestra/.venv/bin/python
OUT=/tmp/336-measure.txt
: > "$OUT"
FILES="tests/test_db.py tests/test_default_pipeline.py tests/test_manager.py tests/test_pipeline.py tests/test_quota_gate.py tests/test_worker_model_policy.py"
for f in $FILES; do
  s=$(date +%s.%N)
  PYTHONPATH=$PWD timeout 900 "$PY" -m pytest -q -m "not live_probe" "$f" > /tmp/336-one.log 2>&1
  rc=$?
  e=$(date +%s.%N)
  printf '%-40s rc=%-3s %8.2fs  %s\n' "$f" "$rc" "$(echo "$e - $s" | bc)" "$(tail -3 /tmp/336-one.log | tr '\n' ' ' | tail -c 120)" >> "$OUT"
done
s=$(date +%s.%N)
PYTHONPATH=$PWD timeout 900 "$PY" -m pytest -q -m "not live_probe" $FILES > /tmp/336-all.log 2>&1
rc=$?
e=$(date +%s.%N)
printf '%-40s rc=%-3s %8.2fs  %s\n' "ALL-6-IN-ONE-INVOCATION" "$rc" "$(echo "$e - $s" | bc)" "$(tail -3 /tmp/336-all.log | tr '\n' ' ' | tail -c 120)" >> "$OUT"
echo MEASURE-DONE >> "$OUT"
