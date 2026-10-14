from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time


root = Path(__file__).resolve().parents[4]
evidence = Path(__file__).resolve().parent
all_files = subprocess.run(
    ["git", "ls-files", "tests/test_*.py"],
    cwd=root,
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
files = sorted(all_files)[0::6]
(evidence / "ci_shard0.meta").write_text(
    f"shard=0/6\nfiles={len(files)}\n" + "\n".join(files) + "\n",
    encoding="utf-8",
)

env = os.environ.copy()
for name in ("ORCHESTRA_DB_PATH", "NOTIFY_SOCKET", "ORCHESTRA_TASK_REPOSITORY"):
    env.pop(name, None)
common = [
    sys.executable, "-m", "pytest", "-v", "-rf", "--timeout=30",
    "--durations=20", "-m", "not live_probe and not browser",
]
for label, xdist_args in (
    ("serial", ["-n", "0"]),
    ("xdist2", ["-n", "2", "--dist=loadscope"]),
):
    started = time.monotonic()
    result = subprocess.run(
        [*common, *xdist_args, *files],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    (evidence / f"ci_shard0_{label}.log").write_text(
        result.stdout + f"\nEXIT_CODE={result.returncode}\n",
        encoding="utf-8",
    )
    (evidence / f"ci_shard0_{label}.time").write_text(
        f"elapsed_s={elapsed:.3f}\nexit_code={result.returncode}\n",
        encoding="utf-8",
    )
    if result.returncode:
        raise SystemExit(result.returncode)
