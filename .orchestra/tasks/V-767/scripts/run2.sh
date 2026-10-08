#!/usr/bin/env bash
# V-767: one headless run with an "arm" (ctl|dis|prm), hang detection, hidden oracle.
# Usage: run2.sh <label> <base> <oracle> <task_file> <model> "<oracle files>" <effort> <arm> [timeout_s]
set -u
label=$1 base=$2 oracle=$3 task_file=$(realpath "$4") model=$5 oracle_files=$6 effort=$7 arm=${8:-ctl} tmo=${9:-3600}
repo=/home/kesha/orchestra; root=$repo/data/v767
out=$root/runs/$label; wt=$root/wt/$label
py=/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python
mkdir -p "$out" "$(dirname "$wt")"
git -C "$repo" branch -f "v767-base-$label" "$base" >/dev/null
git clone -q --no-local --single-branch --branch "v767-base-$label" "$repo" "$wt" >"$out/worktree.log" 2>&1 || exit 2
git -C "$repo" branch -D "v767-base-$label" >/dev/null
git -C "$wt" remote remove origin
prompt=$(cat "$task_file")
extra=(); envs=()
case $arm in
  dis) extra=(--disallowedTools Monitor ScheduleWakeup CronCreate); envs=(CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 CLAUDE_CODE_DISABLE_CRON=1);;
  prm) prompt="$prompt

Рабочее правило среды: не используй фоновые запуски (run_in_background), Monitor и ScheduleWakeup. Все проверки запускай на переднем плане, каждую командой с timeout не более 10 минут, длинные прогоны дели на части. Закончи ход итоговым сообщением, не откладывая и не ожидая уведомлений.";;
esac
start=$(date +%s)
( cd "$wt" && env "${envs[@]}" claude -p --model "$model" --effort "$effort" --output-format json \
    --permission-mode bypassPermissions "${extra[@]}" -- "$prompt" ) >"$out/result.json" 2>"$out/stderr.log" &
pid=$!
# hang watch: result.json is written when the turn ends; a live process 180 s later is a linger
linger=0; resat=0
while kill -0 $pid 2>/dev/null; do
  sleep 10; now=$(date +%s)
  if [ -s "$out/result.json" ] && [ $resat = 0 ]; then resat=$now; fi
  if [ $resat != 0 ] && [ $((now-resat)) -ge 180 ]; then linger=1; pkill -TERM -P $pid; kill $pid 2>/dev/null; break; fi
  if [ $((now-start)) -ge $tmo ]; then pkill -TERM -P $pid; kill $pid 2>/dev/null; echo timeout >"$out/timeout.flag"; break; fi
done
wait $pid 2>/dev/null; rc=$?
p=$HOME/.claude/projects/-home-kesha-orchestra-data-v767-wt-$label
lastage=NA
if ls $p/*.jsonl >/dev/null 2>&1; then
  cat $p/*.jsonl >"$out/transcript.jsonl"; lastage=$(( $(date +%s) - $(stat -c %Y $p/*.jsonl | sort -n | tail -1) ))
fi
echo "rc=$rc seconds=$(( $(date +%s) - start )) linger=$linger resultat=$([ $resat = 0 ] && echo 0 || echo $((resat-start))) timeout=$([ -f $out/timeout.flag ] && echo 1 || echo 0) last_event_age_at_kill=$lastage arm=$arm effort=$effort" >"$out/run.txt"
git -C "$wt" add -A >/dev/null 2>&1
git -C "$wt" diff --cached --stat "$base" >"$out/diffstat.txt" 2>&1
git -C "$wt" diff --cached "$base" >"$out/diff.patch" 2>&1
own=$(cd "$wt" && git diff --cached --name-only "$base" -- 'tests/*.py' | tr '\n' ' ')
if [ -n "$own" ]; then ( cd "$wt" && timeout 900 $py -m pytest -q -p no:cacheprovider $own ) >"$out/own_tests.txt" 2>&1
else echo "no test files changed" >"$out/own_tests.txt"; fi
( cd "$wt" && for f in $oracle_files; do git -C "$repo" show "$oracle:$f" >"$f.oracle_tmp" && mv "$f.oracle_tmp" "$f"; done
  timeout 900 $py -m pytest -q -p no:cacheprovider $(printf '%s\n' $oracle_files | grep '^tests/.*\.py$' | tr '\n' ' ') ) >"$out/oracle_tests.txt" 2>&1
# free the tree
trash "$wt" "$p" 2>/dev/null; trash-rm "*data/v767/wt/$label" >/dev/null 2>&1
echo done >>"$out/run.txt"
