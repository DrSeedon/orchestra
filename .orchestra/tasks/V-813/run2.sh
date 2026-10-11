#!/bin/sh
# V-813 block 2: 3x Sol 6.1 then 3x Luna, probes around each block for 1% quantization.
cd /home/kesha/orchestra/.orchestra/tasks/V-813
OUT=runs/block2; mkdir -p $OUT
for M in gpt-6.1-sol gpt-6-luna; do
  python3 probe.py block2-before-$M >> $OUT/probes.jsonl
  for i in 1 2 3; do
    date -u +%FT%TZ > $OUT/$M.$i.start
    timeout 1800 codex exec -m $M -c model_reasoning_effort='"high"' -s danger-full-access --ephemeral --skip-git-repo-check --json \
      -C /tmp/v813-wt -o $OUT/$M.$i.answer.md - < prompt.txt > $OUT/$M.$i.jsonl 2> $OUT/$M.$i.stderr
    echo "rc=$?" > $OUT/$M.$i.rc
    date -u +%FT%TZ > $OUT/$M.$i.end
  done
  sleep 90
  python3 probe.py block2-after-$M >> $OUT/probes.jsonl
done
git -C /tmp/v813-wt status --short > $OUT/worktree-status.txt
echo V813_BLOCK2_DONE
