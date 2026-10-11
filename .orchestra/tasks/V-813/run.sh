#!/bin/sh
# V-813: identical read-only task on Sol 6.1 then Luna, limits probed before/after each run.
cd /home/kesha/orchestra/.orchestra/tasks/V-813
P=python3; PR=probe.py; OUT=runs
for M in gpt-6.1-sol gpt-6-luna; do
  $P $PR before-$M >> $OUT/probes.jsonl
  date -u +%FT%TZ > $OUT/$M.start
  timeout 1800 codex exec -m $M -c model_reasoning_effort='"high"' -s danger-full-access --ephemeral --skip-git-repo-check --json \
    -C /tmp/v813-wt -o $OUT/$M.answer.md - < prompt.txt > $OUT/$M.jsonl 2> $OUT/$M.stderr
  echo "rc=$?" > $OUT/$M.rc
  date -u +%FT%TZ > $OUT/$M.end
  sleep 90
  $P $PR after-$M >> $OUT/probes.jsonl
done
git -C /tmp/v813-wt status --short > $OUT/worktree-status.txt
echo V813_DONE
