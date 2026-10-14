import csv
import json
import re
import sqlite3
import subprocess
from collections import defaultdict, Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
source = subprocess.run(
    ["git", "show", "e303361d:.orchestra/tasks/V-840/evidence/tool_calls_7d.csv"],
    capture_output=True, text=True, check=True,
).stdout
calls = [r for r in csv.DictReader(source.splitlines()) if r["tool_name"] == "Bash"]
db = sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
db.row_factory = sqlite3.Row
db.execute("PRAGMA query_only=ON")
call_ids = {int(call["call_id"]) for call in calls}
logs = db.execute(
    """SELECT l.id,l.session_id,l.content,s.name,s.scope
       FROM logs l LEFT JOIN sessions s ON s.id=l.session_id
       WHERE l.type='tool' AND l.tool_name='Bash'
         AND l.id BETWEEN ? AND ?""",
    (min(call_ids), max(call_ids)),
).fetchall()
log_by_id = {row["id"]: row for row in logs if row["id"] in call_ids}
tokens = {
    "find": r"(^|[;&|\s])find(\s|$)",
    "rg": r"(^|[;&|\s])rg(\s|$)",
    "grep": r"(^|[;&|\s])grep(\s|$)",
    "sed": r"(^|[;&|\s])sed(\s|$)",
    "cat": r"(^|[;&|\s])cat(\s|$)",
}

def situation(command: str) -> str:
    low = command.lower()
    if re.search(r"(^|[;&| ])sleep\s+\d|time\.sleep\(|await asyncio\.sleep", low): return "sleep/wait"
    if any(x in low for x in ("runserver", "uvicorn", "npm run dev", "vite --host", "http.server")): return "foreground server/process"
    if any(x in low for x in ("pytest ", "npm test", "pnpm test", "node --test", "playwright test")): return "tests/checks"
    if any(x in low for x in ("git worktree", "sparse-checkout", "sparse_convert.py")): return "worktree/copy"
    if any(x in low for x in ("curl ", "wget ", "http://", "https://")): return "network/http"
    if any(x in low for x in ("fio ", "dd if=", "iostat", "vmstat")): return "disk/measurement"
    if re.search(r"(^|[ /])(ffmpeg|manim|blender)(\s|$)", low) or any(x in low for x in ("npm run build", "pnpm build", "vite build", "build_script.py", "render_script.py", "render.py")): return "build/render"
    if any(x in low for x in ("sqlite", "orchestra.db", "sql ")): return "database"
    if any(x in low for x in ("git status", "git diff", "git log", "git show", "git branch")): return "git inspection"
    if any(re.search(r"(^|[;&| ])" + re.escape(x) + r"(\s|$)", low) for x in tokens): return "file/search"
    if re.search(r"(^|[;&| ])(python|python3|node)\b", low): return "custom Python/Node scripts"
    return "other shell"

groups = defaultdict(list)
for call in calls:
    rec = log_by_id.get(int(call["call_id"]))
    try:
        body = rec["content"] or ""
        command = json.loads(body[body.index("{"):]).get("command", "")
    except (ValueError, json.JSONDecodeError, TypeError):
        command = ""
    low = str(command).lower()
    if situation(str(command)) != "file/search":
        continue
    if not any(re.search(pattern, low) for pattern in tokens.values()):
        continue
    session = rec
    projects = (session["scope"] or "").rstrip("/").split("/")
    project = projects[-1] if projects else ""
    scrubbed = re.sub(
        r"(?i)([\w.-]*(?:token|secret|password|passwd|api[_-]?key|authorization|cookie)[\w.-]*\s*[=:]\s*)([\"']?)[^\s,;\"']+",
        r"\1[REDACTED]", str(command),
    )
    scrubbed = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~-]+", r"\1[REDACTED]", scrubbed)
    scrubbed = re.sub(r"https?://[^\s/@:]+:[^\s/@]+@", "https://[REDACTED]@", scrubbed)
    scrubbed = re.sub(r"/home/kesha/[^\s\"']+", "<workspace-path>", scrubbed)
    scrubbed = scrubbed.replace("\n", " ")[:240].rstrip()
    base = {
        "call_id": call["call_id"], "session_id": call["session_id"],
        "session_name": session["name"] if session else "",
        "project": project, "runtime": call["runtime"], "call_ts": call["call_ts"],
        "duration_s": float(call["duration_s"]), "command": scrubbed,
    }
    for tool, pattern in tokens.items():
        if re.search(pattern, low):
            groups[(tool, call["runtime"])].append(base)

with (OUT / "file_search_commands_7d.csv").open("w", newline="") as f:
    fields = ["tool", "runtime", "calls", "sum_s", "p50_s", "p90_s", "max_s", "top_projects", "example_session", "example_ts", "example_s", "example_command"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for (tool, runtime), rows in sorted(groups.items()):
        durations = sorted(x["duration_s"] for x in rows)
        def pct(q): return durations[max(0, int(len(durations) * q + .999999) - 1)]
        examples = sorted(rows, key=lambda x: x["duration_s"], reverse=True)
        projects = Counter(x["project"] for x in rows)
        writer.writerow({
            "tool": tool, "runtime": runtime, "calls": len(rows),
            "sum_s": round(sum(durations), 3), "p50_s": round(pct(.5), 3),
            "p90_s": round(pct(.9), 3), "max_s": round(durations[-1], 3),
            "top_projects": "; ".join(f"{k}:{v}" for k, v in projects.most_common(5)),
            "example_session": examples[0]["session_name"],
            "example_ts": examples[0]["call_ts"], "example_s": round(examples[0]["duration_s"], 3),
            "example_command": examples[0]["command"],
        })

print("calls_in_overlapping_command_groups")
for (tool, runtime), rows in sorted(groups.items()):
    d = sorted(x["duration_s"] for x in rows)
    print(tool, runtime, len(rows), round(sum(d), 1), round(d[len(d)//2], 2), round(d[int(.9*(len(d)-1))], 2), round(d[-1], 2))
db.rollback()
db.close()
