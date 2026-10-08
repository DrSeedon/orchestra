#!/usr/bin/env bash
# save transcripts, then remove finished run trees (trash + trash-rm own entries to free the disk)
cd /home/kesha/orchestra/data/v758
for d in runs/*; do l=$(basename $d)
  grep -q done $d/run.txt 2>/dev/null || continue
  [ -d wt/$l ] || continue
  p=$HOME/.claude/projects/-home-kesha-orchestra-data-v758-wt-$l
  [ -d $p ] && cat $p/*.jsonl > $d/transcript.jsonl 2>/dev/null
  trash wt/$l && trash-rm "*data/v758/wt/$l" >/dev/null 2>&1
done
