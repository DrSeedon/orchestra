#!/bin/bash
# For each task: snapshot + regression tests from the fix commit must FAIL on the snapshot (bug present, reproducible by test).
declare -A FIX=([T1]=8239760c [T2]=bec4f378 [T3]=e86fc63f [T4]=fbc9e40d [T5]=10698051 [T6]=17a7d398 [T7]=d1bd9580 [T8]=495eb220 [K1]=4b185fdc [K2]=16ebb5e1 [K3]=a43f2686 [K4]=cb96eb6f)
cd /home/kesha/bench906; rm -rf val; mkdir val
for k in T1 T2 T3 T4 T5 T6 T7 T8 K1 K2 K3 K4; do
  c=${FIX[$k]}; cp -r fx/$k val/$k
  files=$(git -C /home/kesha/orchestra show $c --name-only --format= -- tests)
  for f in $files; do git -C /home/kesha/orchestra show $c:$f > val/$k/$f; done
  (cd val/$k && PYTHONPATH=. timeout 600 /home/kesha/orchestra/.venv/bin/python -m pytest $files -q -x --no-header -p no:cacheprovider 2>&1 | tail -6 > ../$k.out; echo "$k: $(tail -1 ../$k.out)")
done
