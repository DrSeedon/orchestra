import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = "/home/kesha/orchestra/data/orchestra.db"
EVIDENCE = Path(__file__).parent
PROCESS_SNAPSHOT = json.loads((EVIDENCE / "orchestra-cgroup-processes.json").read_text())
PROCS = PROCESS_SNAPSHOT["processes"]
TARGET_PIDS = {736, 4131256, 1823051, 1823057, 1823080, 865393, 881271,
               1256326, 1332343, 1336221, 1340650, 2334703, 2338767,
               1545102, 2079424, 2682938, 2688110, 2697550, 1764588,
               578260, 1544432, 3185421}
db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

feat = db.execute("select id,name,status from sessions where name='feat-workflow-tool'").fetchone()
feat_events = []
if feat:
    rows = db.execute(
        """SELECT id,ts,type,tool_name,tool_use_id,content FROM logs
           WHERE session_id=? AND (
             lower(content) LIKE '%cgroup.procs%' OR
             lower(content) LIKE '%orchestra-api%' OR
             lower(content) LIKE '%delegateSubgroup%'
           ) ORDER BY id""",
        (feat["id"],),
    )
    for row in rows:
        content = row["content"] or ""
        numbers = {int(value) for value in __import__("re").findall(r"(?<!\d)\d{3,8}(?!\d)", content)}
        matched_pids = sorted(numbers & TARGET_PIDS)
        feat_events.append({
            "id": row["id"], "ts": row["ts"], "type": row["type"],
            "tool_name": row["tool_name"], "tool_use_id": row["tool_use_id"],
            "has_cgroup_procs": "cgroup.procs" in content,
            "has_write_marker": any(x in content.lower() for x in ("write_text", "echo", "printf", "mv", "tee")),
            "target_pids_mentioned": matched_pids,
            "mentions_agents_group": "/agents" in content,
            "content_length": len(content),
        })

session_rows = db.execute("select id,name,status,worktree_path,created_at,finished_at from sessions").fetchall()
by_pid = []
for proc in PROCS:
    pid = proc["pid"]
    if pid not in TARGET_PIDS:
        continue
    cwd = proc["cwd"].removesuffix(" (deleted)")
    matches = []
    for session in session_rows:
        worktree = session["worktree_path"] or ""
        if worktree and (cwd == worktree or cwd.startswith(worktree + "/")):
            matches.append(session)
    session_details = []
    start_epoch = PROCESS_SNAPSHOT["captured_at_epoch"] - proc["age_s"]
    for session in matches:
        near = db.execute(
            """SELECT id,ts,type,tool_name,tool_use_id,content FROM logs
               WHERE session_id=? AND julianday(ts) BETWEEN julianday(?)-0.0014 AND julianday(?)+0.0014
               ORDER BY id""",
            (session["id"], datetime.fromtimestamp(start_epoch, timezone.utc).isoformat(),
             datetime.fromtimestamp(start_epoch, timezone.utc).isoformat()),
        )
        near_rows = []
        for row in near:
            content = row["content"] or ""
            near_rows.append({
                "id": row["id"], "ts": row["ts"], "type": row["type"],
                "tool_name": row["tool_name"], "tool_use_id": row["tool_use_id"],
                "mentions_pid": str(pid) in content,
                "mentions_path": any(part in content for part in ("painter-geometry", "painter-wall-v2", "fix-ci-green", "balatro-vps", "autobattler", "seo-cro", "komandor-data", "xray", "ssh")),
                "mentions_launch": any(part in content.lower() for part in ("nohup", "setsid", "subprocess", "jupyter", "xray", "python3", "ssh")),
                "content_length": len(content),
            })
        session_details.append({
            "session_id": session["id"], "name": session["name"], "status": session["status"],
            "created_at": session["created_at"], "finished_at": session["finished_at"],
            "logs_near_process_start": near_rows,
        })
    by_pid.append({
        "pid": pid, "comm": proc["comm"], "cwd": cwd,
        "parent": proc["ppid"], "candidate_sessions": session_details,
    })

print(json.dumps({"feat_session": dict(feat) if feat else None,
                  "feature_cgroup_log_events": feat_events,
                  "per_pid_session_log_windows": by_pid}, ensure_ascii=False))
