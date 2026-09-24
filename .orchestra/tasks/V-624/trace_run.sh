#!/usr/bin/env bash
# Полный прогон под bpftrace: кто и кому шлёт SIGKILL/SIGTERM/SIGINT (сигналы 2, 9, 15).
# usage: trace_run.sh <tag> [pytest args...]   (запускать через ssh kesha@localhost)
set -u
here=$(cd "$(dirname "$0")" && pwd)
tag=$1; shift
sudo -n bpftrace --unsafe -e '
tracepoint:signal:signal_generate /args->sig == 9 || args->sig == 15 || args->sig == 2/ {
  printf("%s sig=%d sender_pid=%d sender_comm=%s -> target_pid=%d target_comm=%s res=%d\n",
         strftime("%H:%M:%S", nsecs), args->sig, pid, comm, args->pid, args->comm, args->result);
  system("/tmp/v624c.sh %d", pid);
}' > "$here/signals-$tag.log" 2>&1 &
bt=$!
sleep 3
"$here/run_full.sh" "$tag" "$@"
sudo -n kill -INT "$bt"; sleep 1
