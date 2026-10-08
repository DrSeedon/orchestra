#!/usr/bin/env bash
# emit job lines: label base oracle taskfile effort arm
declare -A B=([pidfd]="1fc6beb6 180a5a4f tests/test_pidfd_leaks.py V-543" [steer]="09d249ee b15940ba tests/test_durable_steering_562.py V-562" [costbase]="d80ec7d9 2dcbfba9 tests/test_p4_cost.py V-609" [stall]="429d26d1 4cc2e45c tests/test_stall_signals_642.py V-642" [ident]="13648c8f 0c3c0fcb tests/test_identity_drift.py V-575")
for spec in "$@"; do  # task:effort:arm:round
  IFS=: read t e a r <<<"$spec"; set -- ${B[$t]}
  echo "hang-$t-$e-$a-$r $1 $2 data/v767/task-$4.txt claude-haiku-5-5 $3 $e $a"
done
