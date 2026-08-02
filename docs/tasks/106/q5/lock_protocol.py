import json
import subprocess
from datetime import datetime, timezone

from run_evaluation import RESULTS, ROOT, SOURCE_FILES, source_hashes


paths = [str(ROOT / name) for name in SOURCE_FILES]
dirty = subprocess.run(
    ["git", "status", "--porcelain", "--", *paths],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=True,
).stdout.strip()
if dirty:
    raise SystemExit(f"source files are not committed:\n{dirty}")

output = RESULTS / "preregistration-lock.json"
if output.exists():
    raise SystemExit(f"lock already exists: {output}")
RESULTS.mkdir(parents=True, exist_ok=True)
payload = {
    "source_commit": subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip(),
    "locked_at": datetime.now(timezone.utc).isoformat(),
    "source_sha256": source_hashes(),
    "decision_rule": "All eight protocol gates must pass on Q5 alone; Q4 outputs are not pooled.",
}
output.write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
