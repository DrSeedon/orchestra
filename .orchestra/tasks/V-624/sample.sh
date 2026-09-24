#!/usr/bin/env bash
# Сэмплер процесса pytest: время, RSS kB, потоки, fd, прямые дети, все потомки, MemAvailable, последний тест.
# usage: sample.sh <pid> <log> <out.tsv>
pid=$1; log=$2; out=$3
start=$(date +%s)
while [ -r /proc/$pid/status ]; do
  rss=$(awk '/VmRSS/{print $2}' /proc/$pid/status)
  thr=$(awk '/Threads/{print $2}' /proc/$pid/status)
  fds=$(ls /proc/$pid/fd 2>/dev/null | wc -l)
  kids=$(pgrep -P "$pid" | wc -l)
  sess=$(ps -o pid= -s "$(ps -o sid= -p $pid | tr -d ' ')" 2>/dev/null | wc -l)
  avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  last=$(grep -a -E '::' "$log" | tail -1 | cut -c1-140)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(( $(date +%s) - start ))" "$rss" "$thr" "$fds" "$kids" "$sess" "$avail" "$last" >> "$out"
  sleep 5
done
echo "GONE after $(( $(date +%s) - start ))s" >> "$out"
