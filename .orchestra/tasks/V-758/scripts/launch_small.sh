#!/usr/bin/env bash
# usage: launch_small.sh <suffix>
cd /home/kesha/orchestra/data/v758/small || exit 1
sfx=$1
for t in S1 S2 S3 S4 S5; do
  for cfg in "h55:claude-haiku-5-5:low" "h55:claude-haiku-5-5:medium" "h55:claude-haiku-5-5:max" "s55:claude-sonnet-5-5[1m]:low" "s55:claude-sonnet-5-5[1m]:medium"; do
    IFS=: read tag model eff <<<"$cfg"
    ./small_run.sh "$t-$tag-$eff$sfx" $t "$model" $eff &
  done
  ./small_run_luna.sh "$t-luna-default$sfx" $t gpt-6-luna default &
done
wait
echo ALLDONE
