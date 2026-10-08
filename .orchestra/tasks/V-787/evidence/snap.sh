#!/bin/bash
# usage: snap.sh label
U="kesha-bot-vps orchestra nginx ssh telegram-bot-api orchestra-proxy xray hysteria-server mtg tinyproxy"
echo "### $1 $(date -u +%FT%TZ)"
for s in system.slice; do echo "== $s"; systemctl show $s -p MemoryMin -p MemoryLow -p MemoryHigh -p MemoryMax -p CPUWeight -p IOWeight; for f in memory.min memory.low memory.high memory.max cpu.weight io.weight memory.current; do printf "  cg/%s=%s\n" $f "$(cat /sys/fs/cgroup/$s/$f 2>/dev/null)"; done; done
for u in $U; do echo "== $u.service"; systemctl show $u.service -p ControlGroup -p MainPID -p MemoryMin -p MemoryLow -p MemoryHigh -p MemoryMax -p CPUWeight -p IOWeight -p MemoryCurrent -p ActiveState -p DropInPaths
 cg=$(systemctl show $u.service -p ControlGroup --value); for f in memory.min memory.low memory.high memory.max cpu.weight io.weight; do printf "  cg/%s=%s\n" $f "$(cat /sys/fs/cgroup$cg/$f 2>/dev/null)"; done; done
for g in orchestra.service/orchestra-api orchestra.service/agents; do echo "== child $g"; for f in memory.min memory.low memory.high memory.max cpu.weight io.weight; do printf "  %s=%s\n" $f "$(cat /sys/fs/cgroup/system.slice/$g/$f 2>/dev/null)"; done; done
