#!/usr/bin/env bash
# V-758: Haiku 5.5 on the V-656/V-661 stand. Usage: launch_r.sh <suffix> <efforts...>
cd /home/kesha/orchestra || exit 1
R=${RUNNER:-data/v758/run_one.sh}; T=data/v758
sfx=$1; shift
TASKS=(
  "pidfd 1fc6beb6 180a5a4f tests/test_pidfd_leaks.py"
  "steer 09d249ee b15940ba tests/test_durable_steering_562.py"
  "costbase d80ec7d9 2dcbfba9 tests/test_p4_cost.py"
  "stall 429d26d1 4cc2e45c tests/test_stall_signals_642.py"
  "ident 13648c8f 0c3c0fcb tests/test_identity_drift.py"
)
declare -A FILE=([pidfd]=V-543 [steer]=V-562 [costbase]=V-609 [stall]=V-642 [ident]=V-575)
for row in "${TASKS[@]}"; do
  set -- $row
  for e in $EFFORTS; do
    $R "$1-${TAG:-h55}-$e$sfx" "$2" "$3" "$T/task-${FILE[$1]}.txt" "${MODEL:-claude-haiku-5-5}" "$4" "$e" &
  done
done
wait
for d in $T/runs/*; do echo "$d $(head -n1 $d/run.txt)"; done
