import json
import subprocess
from pathlib import Path


PROPERTIES = [
    "Id", "Description", "LoadState", "ActiveState", "SubState", "UnitFileState",
    "User", "MainPID", "FragmentPath", "WorkingDirectory", "ControlGroup", "Slice",
    "MemoryCurrent", "MemoryPeak", "MemoryHigh", "MemoryMax", "MemoryMin", "MemoryLow",
    "CPUUsageNSec", "CPUWeight", "CPUQuotaPerSecUSec", "OOMScoreAdjust", "Delegate",
    "Restart", "ActiveEnterTimestamp",
]
sample_path = Path(__file__).with_name("10s-sample.json")
sample = json.loads(sample_path.read_text())
cpu_now = sample.get("cpu_by_unit", {})
rss_by_pid = {}
process_snapshot = Path(__file__).with_name("orchestra-cgroup-processes.json")
if process_snapshot.exists():
    rss_by_pid = {row["pid"]: row["rss_kb"] for row in json.loads(process_snapshot.read_text())["processes"]}


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


unit_lines = run(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"])
units = []
for line in unit_lines.splitlines():
    columns = line.split(None, 4)
    if len(columns) < 4:
        continue
    units.append({"name": columns[0], "load": columns[1], "active": columns[2], "sub": columns[3],
                  "description": columns[4] if len(columns) > 4 else ""})

file_lines = run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"])
file_state = {}
for line in file_lines.splitlines():
    columns = line.split()
    if len(columns) >= 2:
        file_state[columns[0]] = columns[1]

loaded_names = [row["name"] for row in units if row["load"] == "loaded"]
show_output = run(["systemctl", "show", *loaded_names, *sum((["-p", prop] for prop in PROPERTIES), []), "--no-pager"])
properties_by_id = {}
for block in show_output.strip().split("\n\n"):
    props = {}
    for line in block.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value
    if props.get("Id"):
        properties_by_id[props["Id"]] = props

result = []
for unit in units:
    props = properties_by_id.get(unit["name"], {})
    cgroup = props.get("ControlGroup", "")
    rss_sum = cpu = process_count = 0
    for name, stats in cpu_now.items():
        if name == unit["name"]:
            cpu = stats["cpu_pct_one_core"]
            rss_sum = stats["rss_sum_kb"]
            process_count = stats["processes"]
            break
    result.append({
        **unit,
        "unit_file_state": file_state.get(unit["name"], "not-listed"),
        "user": props.get("User") or "root (systemd default)",
        "main_pid": int(props.get("MainPID", "0")) if props.get("MainPID", "0").isdigit() else 0,
        "working_directory": props.get("WorkingDirectory", ""),
        "fragment_path": props.get("FragmentPath", ""),
        "cgroup": cgroup,
        "memory_current_bytes": int(props["MemoryCurrent"]) if props.get("MemoryCurrent", "").isdigit() else 0,
        "memory_peak_bytes": int(props["MemoryPeak"]) if props.get("MemoryPeak", "").isdigit() else 0,
        "memory_high": props.get("MemoryHigh", ""),
        "memory_max": props.get("MemoryMax", ""),
        "memory_min": props.get("MemoryMin", ""),
        "memory_low": props.get("MemoryLow", ""),
        "cpu_usage_nsec_lifetime": int(props["CPUUsageNSec"]) if props.get("CPUUsageNSec", "").isdigit() else 0,
        "cpu_weight": props.get("CPUWeight", ""),
        "cpu_quota": props.get("CPUQuotaPerSecUSec", ""),
        "oom_score_adjust": props.get("OOMScoreAdjust", ""),
        "delegate": props.get("Delegate", ""),
        "restart": props.get("Restart", ""),
        "active_enter_timestamp": props.get("ActiveEnterTimestamp", ""),
        "rss_sum_kb_sampled": rss_sum,
        "cpu_pct_one_core_sampled": round(cpu, 3),
        "process_count_sampled": process_count,
    })

users = ["root", "tunnel", "kesha", "codexproxy"]
user_units = {}
for user in users:
    command = ["systemctl", "--user", "--machine", f"{user}@.host", "list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"]
    try:
        raw = run(command)
        user_units[user] = [line for line in raw.splitlines() if line.strip()]
    except subprocess.CalledProcessError as error:
        user_units[user] = {"error": error.stderr.strip()[:300]}

print(json.dumps({
    "sample_start_utc": sample.get("sample_start_utc"),
    "sample_end_utc": sample.get("sample_end_utc"),
    "sample_seconds": sample.get("window_s"),
    "loaded_service_count": len(units),
    "unit_file_count": len(file_state),
    "services": result,
    "user_services": user_units,
}, ensure_ascii=False))
