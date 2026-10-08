#!/usr/bin/env bash
# V-656: one headless run of an old task on a given model, then the hidden oracle.
# Usage: run_one.sh <label> <base_commit> <oracle_commit> <task_file> <model> "<oracle test files...>"
set -u
label=$1 base=$2 oracle=$3 task_file=$(realpath "$4") model=$5 oracle_files=$6 effort=${7:-}
repo=/home/kesha/orchestra
out=$repo/data/v758/runs/$label
wt=$repo/data/v758/wt/$label
py=/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python
mkdir -p "$out" "$(dirname "$wt")"
# Isolated clone that holds only the base commit's ancestry: a linked worktree shares
# refs, and in the first round Sonnet 5 found the merged reference in `git log main`.
git -C "$repo" branch -f "v656-base-$label" "$base" >/dev/null
git clone -q --no-local --single-branch --branch "v656-base-$label" "$repo" "$wt" >"$out/worktree.log" 2>&1 || exit 2
git -C "$repo" branch -D "v656-base-$label" >/dev/null
git -C "$wt" remote remove origin

start=$(date +%s)
( cd "$wt" && timeout 5400 claude -p --model "$model" ${effort:+--effort "$effort"} --output-format json \
    --permission-mode bypassPermissions "$(cat "$task_file")" ) >"$out/result.json" 2>"$out/stderr.log"
echo "rc=$? seconds=$(( $(date +%s) - start ))" >"$out/run.txt"

git -C "$wt" add -A >/dev/null 2>&1
git -C "$wt" diff --cached --stat "$base" >"$out/diffstat.txt" 2>&1
git -C "$wt" diff "$base" >"$out/diff.patch" 2>&1
git -C "$wt" log --oneline "$base"..HEAD >"$out/commits.txt" 2>&1

# Model's own tests on its own tree
own=$(cd "$wt" && git diff --name-only "$base" -- 'tests/*.py' | tr '\n' ' ')
# An empty list would make pytest run the whole suite (34 min in round one).
if [ -n "$own" ]; then ( cd "$wt" && $py -m pytest -q -p no:cacheprovider $own ) >"$out/own_tests.txt" 2>&1
else echo "no test files changed" >"$out/own_tests.txt"; fi

# Hidden oracle: tests (and fixtures) from the merged reference solution
( cd "$wt" && for f in $oracle_files; do git -C "$repo" show "$oracle:$f" >"$f.oracle_tmp" && mv "$f.oracle_tmp" "$f"; done
  $py -m pytest -q -p no:cacheprovider $(printf '%s\n' $oracle_files | grep '^tests/.*\.py$' | tr '\n' ' ') ) >"$out/oracle_tests.txt" 2>&1
echo done >>"$out/run.txt"
