import json
import os
import re
import time
from pathlib import Path


PIDS = [
    736, 4131256,
    1823051, 1823057, 1823080,
    865393, 881271,
    1256326, 1332343, 1336221, 1340650, 2334703, 2338767,
    1545102, 2079424,
    2682938, 2688110, 2697550,
    1764588,
    578260, 1544432, 3185421,
]
HZ = os.sysconf("SC_CLK_TCK")


def read_process(pid):
    process = Path("/proc") / str(pid)
    try:
        raw = (process / "stat").read_text()
        fields = raw[raw.rfind(")") + 2 :].split()
        status = (process / "status").read_text()
        rss = re.search(r"^VmRSS:\s+(\d+)", status, re.M)
        group_line = next(line for line in (process / "cgroup").read_text().splitlines() if line.startswith("0::"))
        return {
            "pid": pid,
            "ppid": int(fields[1]),
            "state": fields[0],
            "cpu_ticks": int(fields[11]) + int(fields[12]),
            "start_ticks": int(fields[19]),
            "rss_kb": int(rss.group(1)) if rss else 0,
            "comm": (process / "comm").read_text().strip(),
            "cgroup": group_line[3:],
        }
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, ValueError, AttributeError, StopIteration):
        return None


started_at = time.time()
started = {pid: read_process(pid) for pid in PIDS}
started_mono = time.monotonic()
time.sleep(10)
ended_at = time.time()
elapsed = time.monotonic() - started_mono
uptime_s = float(Path("/proc/uptime").read_text().split()[0])
ended = {pid: read_process(pid) for pid in PIDS}
hz = os.sysconf("SC_CLK_TCK")
rows = []
for pid in PIDS:
    before, after = started[pid], ended[pid]
    if before is None or after is None:
        rows.append({"pid": pid, "status": "not-running-at-one-snapshot"})
        continue
    rows.append(
        {
            **{key: after[key] for key in ("pid", "ppid", "state", "rss_kb", "comm", "cgroup")},
            "age_s": round(uptime_s - after["start_ticks"] / hz),
            "cpu_pct_one_core": round(max(0, after["cpu_ticks"] - before["cpu_ticks"]) / hz / elapsed * 100, 3),
            "window_s": round(elapsed, 3),
        }
    )
print(json.dumps({"start_epoch": started_at, "end_epoch": ended_at, "window_s": elapsed, "processes": rows}, ensure_ascii=False))
