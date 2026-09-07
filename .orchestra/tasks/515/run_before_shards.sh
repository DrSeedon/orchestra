#!/usr/bin/env bash
set -u

root=".orchestra/tasks/515/raw/before-shards"
for shard in 1 2 3 4 5 6; do
  mapfile -t files < "$root/shard-$shard.txt"
  /usr/bin/time -v -o "$root/shard-$shard.time" \
    uv run pytest -vv --tb=short --timeout=30 "${files[@]}" \
    > "$root/shard-$shard.log" 2>&1
  rc=$?
  printf '%s\n' "$rc" > "$root/shard-$shard.rc"
  printf 'SHARD=%s RC=%s\n' "$shard" "$rc"
  tail -n 2 "$root/shard-$shard.log"
done

git status --short -- uv.lock > "$root/worktree-status-after.txt"
uv run python .orchestra/tasks/430/parse_baseline_shards.py --dir "$root"
