"""Write a wf_run spec exactly as mcp dynamic_workflow does (same runner, same fields) and print the command."""
import json, sys, uuid, shlex, os
from datetime import datetime, timezone
from pathlib import Path
tasks_file, tag, budget, max_calls, conc = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
RUNNER = Path("/home/kesha/orchestra"); REPO = Path("/tmp/v1114-empty2")
import subprocess
base = subprocess.check_output(["git","-C",str(REPO),"rev-parse","HEAD"],text=True).strip()
tasks = json.loads(Path(tasks_file).read_text())
for i,t in enumerate(tasks):
    t.setdefault("label", f"Task {i+1}"); t.setdefault("task_id", t.get("task_id") or f"task-{i+1}")
run_id = f"V-1114-{tag}-{uuid.uuid4().hex[:8]}"
spec = {"tasks": tasks, "mode": "parallel", "dashboard": {"created_at": datetime.now(timezone.utc).isoformat(),
        "task_id":"V-1114","repo":str(REPO),"budget_usd":float(budget),"max_calls":int(max_calls),"max_concurrency":int(conc)}}
d = RUNNER/"data"/"workflow-runs"/run_id; d.mkdir(parents=True)
(d/"request.json").write_text(json.dumps(spec, ensure_ascii=False, separators=(",",":")))
cmd = ["env","ORCHESTRA_TASK_ID=V-1114",f"ORCHESTRA_SCOPE={os.environ.get('ORCHESTRA_SCOPE','')}",str(RUNNER/".venv/bin/python"),str(RUNNER/"scripts/wf_run.py"),
 "--spec",str(d/"request.json"),"--run-id",run_id,"--budget-usd",budget,"--max-calls",max_calls,"--max-concurrency",conc,"--repo",str(REPO),"--base-commit",base]
print(run_id); print(shlex.join(cmd))
