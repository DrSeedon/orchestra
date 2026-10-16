"""Scores a finished run: open -> regex rules on final text; closed -> hidden pytest on edited tree."""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from tasks import TASKS, score_open
PY = "/home/kesha/orchestra/.venv/bin/python"

def run_hidden(task, tree):
    tmp = Path(tempfile.mkdtemp(prefix="v895-or-"))
    work = tmp / "w"
    shutil.copytree(tree, work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copy(HERE / "hidden" / f"test_{task}.py", work / f"test_{task}.py")
    env = {**os.environ, "PYTHONPATH": str(work), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([PY, "-m", "pytest", f"test_{task}.py", "-q", "-p", "no:cacheprovider",
                        "--rootdir", str(work)], cwd=work, env={**env}, capture_output=True, text=True, timeout=300)
    shutil.rmtree(tmp, ignore_errors=True)
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]

def score(task, final_text, tree):
    if TASKS[task]["kind"] == "open":
        return score_open(task, final_text or ""), ""
    return run_hidden(task, tree)
