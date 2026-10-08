import json
import sqlite3
from pathlib import Path


DB_PATH = "/home/kesha/orchestra/data/orchestra.db"
PROCESS_PATH = Path(__file__).with_name("orchestra-cgroup-processes.json")
PIDS = {
    "painter-geometry": [736, 4131256],
    "painter-wall-v2": [1823051, 1823057, 1823080],
    "fix-ci-green": [865393, 881271],
    "balatro-vps": [1256326, 1332343, 1336221, 1340650, 2338767],
    "autobattler": [2334703],
    "seo-cro": [1545102, 2079424],
    "komandor-jupyter": [2682938, 2688110, 2697550],
    "xray": [1764588],
    "ssh": [578260, 1544432, 3185421],
}
NAMES = ["feat-workflow-tool", "painter-geometry", "painter-wall-v2", "fix-ci-green", "balatro-vps", "autobattler", "seo-cro", "b2b-tenders"]


db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
process_data = json.loads(PROCESS_PATH.read_text())
processes = {row["pid"]: row for row in process_data["processes"]}
sessions = []
for name in NAMES:
    sessions.extend(
        dict(row)
        for row in db.execute(
            """SELECT id,name,status,scope,cwd,worktree_path,cli_pid,cli_started_at,
                      created_at,finished_at,task_id,backend_type
               FROM sessions WHERE name=? ORDER BY created_at""",
            (name,),
        )
    )
for row in db.execute(
    """SELECT id,name,status,scope,cwd,worktree_path,cli_pid,cli_started_at,
              created_at,finished_at,task_id,backend_type
       FROM sessions WHERE cwd LIKE ? OR worktree_path LIKE ? ORDER BY created_at""",
    ("%komandor-data%", "%komandor-data%"),
):
    sessions.append(dict(row))
sessions_by_id = {row["id"]: row for row in sessions}

log_matches = []
for group, pids in PIDS.items():
    session_ids = set()
    for pid in pids:
        proc = processes.get(pid)
        if not proc:
            continue
        cwd = proc["cwd"].removesuffix(" (deleted)")
        for session in sessions:
            worktree = session.get("worktree_path") or ""
            if worktree and (cwd == worktree or cwd.startswith(worktree + "/")):
                session_ids.add(session["id"])
        env_sid = proc.get("env_ids", {}).get("ORCHESTRA_SESSION_ID")
        if env_sid:
            session_ids.add(env_sid)
    for session_id in session_ids:
        session = sessions_by_id.get(session_id)
        if not session:
            continue
        for pid in pids:
            needle = str(pid)
            rows = db.execute(
                """SELECT ts,type,tool_name,COUNT(*) AS hits
                   FROM logs WHERE session_id=? AND content LIKE ?
                   GROUP BY ts,type,tool_name ORDER BY ts""",
                (session_id, f"%{needle}%"),
            ).fetchall()
            if rows:
                log_matches.append(
                    {
                        "group": group,
                        "pid": pid,
                        "session_id": session_id,
                        "session_name": session["name"],
                        "status": session["status"],
                        "matches": [dict(row) for row in rows[:20]],
                        "match_groups": len(rows),
                    }
                )

feat = next((s for s in sessions if s["name"] == "feat-workflow-tool"), None)
feature_rows = []
if feat:
    rows = db.execute(
        """SELECT ts,type,tool_name,COUNT(*) AS hits
           FROM logs WHERE session_id=? AND (
               lower(content) LIKE '%cgroup%' OR
               lower(content) LIKE '%orchestra-api%' OR
               lower(content) LIKE '%delegateSubgroup%'
           ) GROUP BY ts,type,tool_name ORDER BY ts""",
        (feat["id"],),
    )
    feature_rows = [dict(row) for row in rows]

print(
    json.dumps(
        {
            "captured_process_epoch": process_data["captured_at_epoch"],
            "sessions": sessions,
            "per_pid_log_matches": log_matches,
            "feat_workflow_tool_cgroup_log_rows": feature_rows[:100],
            "feat_workflow_tool_cgroup_log_row_count": len(feature_rows),
            "per_pid_notes": {
                group: [
                    {
                        "pid": pid,
                        "cwd": processes.get(pid, {}).get("cwd"),
                        "cgroup": processes.get(pid, {}).get("cgroup"),
                        "db_session_candidates": [
                            s["name"]
                            for s in sessions
                            if (s.get("worktree_path") or "")
                            and processes.get(pid, {}).get("cwd", "").removesuffix(" (deleted)").startswith(s["worktree_path"])
                        ],
                    }
                    for pid in pids
                ]
                for group, pids in PIDS.items()
            },
        },
        ensure_ascii=False,
    )
)
