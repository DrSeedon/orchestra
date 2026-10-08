#!/usr/bin/env bash
# V-758 small task. Usage: small_run.sh <label> <S1..S5> <model> <effort>
set -u
label=$1 task=$2 model=$3 effort=$4
repo=/home/kesha/orchestra; root=$repo/data/v758/small
commit=17a7d398b97ac538f4ac23bd34beb80015ded307
out=$root/runs/$label; wt=$repo/data/v758/wt-small/$label
mkdir -p "$out" "$(dirname "$wt")"
if [ "$task" = S5 ]; then
  mkdir -p "$wt" && cp -r "$root/inputs_master" "$wt/inputs" && git -C "$wt" init -q
else
  git -C "$repo" branch -f "v758-small-$label" "$commit" >/dev/null
  git clone -q --no-local --single-branch --branch "v758-small-$label" "$repo" "$wt" >"$out/worktree.log" 2>&1 || exit 2
  git -C "$repo" branch -D "v758-small-$label" >/dev/null
  git -C "$wt" remote remove origin
fi
start=$(date +%s)
( cd "$wt" && timeout 1800 codex exec -m "$model" --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --json "$(cat $root/task-$task.txt)" </dev/null ) >"$out/result.jsonl" 2>"$out/stderr.log"
echo "rc=$? seconds=$(( $(date +%s) - start ))" >"$out/run.txt"
git -C "$wt" add -A >/dev/null 2>&1; git -C "$wt" diff --cached >"$out/diff.patch" 2>&1
git -C "$wt" status --porcelain >"$out/status.txt" 2>&1
git -C "$wt" reset -q 2>/dev/null
python3 -c "import json,sys;m=[json.loads(l) for l in open('$out/result.jsonl') if l.startswith('{')];a=[x['item']['text'] for x in m if x.get('type')=='item.completed' and x['item'].get('type')=='agent_message'];json.dump({'result':a[-1] if a else ''},open('$out/result.json','w'))"; $root/oracle.py "$task" "$wt" "$out/result.json" "$commit" >"$out/oracle.json" 2>"$out/oracle.err"
echo done >>"$out/run.txt"
