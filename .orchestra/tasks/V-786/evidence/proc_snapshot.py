import json
import os
import re
import time
from pathlib import Path


CGROUP = Path("/sys/fs/cgroup/system.slice/orchestra.service")
HZ = os.sysconf("SC_CLK_TCK")
UPTIME = float(Path("/proc/uptime").read_text().split()[0])
rows = []

for directory, subdirs, files in os.walk(CGROUP):
    if "cgroup.procs" not in files:
        continue
    relative = str(Path(directory).relative_to(CGROUP))
    for pid_text in (Path(directory) / "cgroup.procs").read_text().split():
        pid = int(pid_text)
        process = Path("/proc") / str(pid)
        try:
            raw_stat = (process / "stat").read_text()
            fields = raw_stat[raw_stat.rfind(")") + 2 :].split()
            status = (process / "status").read_text()
            rss = re.search(r"^VmRSS:\s+(\d+)", status, re.M)
            uid = re.search(r"^Uid:\s+(\d+)", status, re.M)
            ppid = int(fields[1])
            start_ticks = int(fields[19])
            state = fields[0]
            comm = (process / "comm").read_text().strip()
            try:
                cwd = os.readlink(process / "cwd")
            except OSError as error:
                cwd = f"<{type(error).__name__}>"
            try:
                executable = os.readlink(process / "exe")
            except OSError as error:
                executable = f"<{type(error).__name__}>"
            env_ids = {}
            try:
                env = (process / "environ").read_bytes().split(b"\0")
                for item in env:
                    key, sep, value = item.partition(b"=")
                    key = key.decode("ascii", "ignore")
                    if sep and key in {
                        "ORCHESTRA_SESSION_ID",
                        "ORCHESTRA_TASK_ID",
                        "ORCHESTRA_SCOPE",
                        "ORCHESTRA_SESSION_NAME",
                        "CODEX_HOME",
                        "CLAUDE_CONFIG_DIR",
                    }:
                        value = os.fsdecode(value)
                        if key in {"CODEX_HOME", "CLAUDE_CONFIG_DIR"}:
                            value = os.path.basename(value)
                        env_ids[key] = value
            except OSError:
                pass
            rows.append(
                {
                    "pid": pid,
                    "ppid": ppid,
                    "state": state,
                    "rss_kb": int(rss.group(1)) if rss else 0,
                    "uid": int(uid.group(1)) if uid else None,
                    "age_s": round(UPTIME - start_ticks / HZ),
                    "comm": comm,
                    "exe": executable,
                    "cwd": cwd,
                    "cgroup": relative or ".",
                    "env_ids": env_ids,
                }
            )
        except (OSError, ValueError, AttributeError):
            continue

print(
    json.dumps(
        {
            "captured_at_epoch": int(time.time()),
            "uptime_s": UPTIME,
            "processes": sorted(rows, key=lambda row: row["pid"]),
        },
        ensure_ascii=False,
    )
)
