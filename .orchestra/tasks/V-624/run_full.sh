#!/usr/bin/env bash
# Полный прогон с записью RSS/потоков/fd процесса pytest каждые 5 с.
# usage: run_full.sh <tag> [extra pytest args...]
set -u
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/../../.."
tag=$1; shift
out=.orchestra/tasks/V-624
log=$out/full-$tag.log
mem=$out/mem-$tag.tsv
: > "$mem"
start=$(date +%s)
uv run --frozen python -m pytest tests/ -v -p no:cacheprovider -o faulthandler_timeout=240 "$@" > "$log" 2>&1 &
wrapper=$!
sleep 5
pid=$(pgrep -f -n "python -m pytest tests/ -v -p no:cacheprovider" || true)
echo "wrapper=$wrapper pytest_pid=$pid" >> "$mem"
while kill -0 "$wrapper" 2>/dev/null; do
  if [ -n "$pid" ] && [ -r /proc/$pid/status ]; then
    rss=$(awk '/VmRSS/{print $2}' /proc/$pid/status)
    thr=$(awk '/Threads/{print $2}' /proc/$pid/status)
    fds=$(ls /proc/$pid/fd 2>/dev/null | wc -l)
    kids=$(pgrep -P "$pid" | wc -l)
    avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
    last=$(grep -E '::' "$log" | tail -1 | cut -c1-120)
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(( $(date +%s) - start ))" "$rss" "$thr" "$fds" "$kids" "$avail" "$last" >> "$mem"
  fi
  sleep 5
done
wait "$wrapper"; rc=$?
echo "EXIT=$rc elapsed=$(( $(date +%s) - start ))s" | tee -a "$log" >> "$mem"
