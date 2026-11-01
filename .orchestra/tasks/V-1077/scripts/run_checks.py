"""Run the exact broker uv runner in a minimal environment, saving unmodified stdout/stderr."""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
UV = Path.home() / ".local/share/orchestra/tools/uv/0.11.28/bin/uv"
for directory in ("logs", "tmp", "isolated-home"):
    (TASK / directory).mkdir(exist_ok=True)
env = {
    "PATH": f"{UV.parent}:/usr/bin:/bin",
    "HOME": str(TASK / "isolated-home"),
    "TMPDIR": str(TASK / "tmp"),
    "PYTHONPATH": f"{TASK / 'scripts'}:{ROOT}",
    "PYTHONDONTWRITEBYTECODE": "1",
    "V1077_OFFLINE_CHECKS": "1",
    "UV_OFFLINE": "true",
    "UV_PYTHON_DOWNLOADS": "never",
    "LC_ALL": "C.UTF-8",
    "PYTEST_ADDOPTS": f"--basetemp={TASK / 'tmp' / sys.argv[1]} -p no:cacheprovider",
    "ORCHESTRA_DB_PATH": str(TASK / "tmp" / "unused.db"),
    "ORCHESTRA_TASK_REPOSITORY": str(TASK / "tmp" / "task-repository"),
}
label, *args = sys.argv[1:]
command = [str(UV), "run", "--frozen", "python", *args]
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
os.nice(15)
with (TASK / "logs" / f"{label}.stdout").open("wb") as out, (TASK / "logs" / f"{label}.stderr").open("wb") as err:
    result = subprocess.run(command, env=env, cwd=ROOT, stdout=out, stderr=err, timeout=180)
record = {"command": command, "cwd": str(ROOT), "exit_code": result.returncode,
          "isolated_env": env, "address_space_limit_bytes": 2 * 1024**3,
          "nice": os.getpriority(os.PRIO_PROCESS, 0)}
public_record = (json.dumps(record, indent=2) + "\n").replace(str(ROOT), "<WORKSPACE>")
public_record = public_record.replace(str(UV).partition("/.local/share/orchestra/tools/uv/")[0], "<BROKER_HOME>")
(TASK / "logs" / f"{label}.json").write_text(public_record)
print(f"{label}: exit={result.returncode}; logs/{label}.stdout and .stderr")
