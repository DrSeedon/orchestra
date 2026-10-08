#!/bin/bash
# samples processes in cron.service cgroup every 1s for $1 seconds
d=/sys/fs/cgroup/system.slice/cron.service
c0=$(awk '/usage_usec/{print $2}' $d/cpu.stat); t0=$(date +%s.%N)
for i in $(seq 1 $1); do
  for p in $(cat $d/cgroup.procs); do
    echo "$(date +%T) $(ps -o pid=,etimes=,rss=,user=,comm= -p $p) :: $(tr '\0' ' ' </proc/$p/cmdline 2>/dev/null | cut -c1-150)"
  done
  sleep 2
done
c1=$(awk '/usage_usec/{print $2}' $d/cpu.stat); t1=$(date +%s.%N)
echo "CPU_PCT_ONE_CORE $(echo "($c1-$c0)/1000000/($t1-$t0)*100" | bc -l)"
echo "MEM_PEAK $(cat $d/memory.peak) CUR $(cat $d/memory.current)"
