"""Normalize captured host paths, check publication forms, remove synthetic DBs."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
(TASK / "tmp").mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "tests/conftest.py"))
from app.secret_mask import mask_secrets
from scripts.secret_scan import scan_text

manifest = TASK / "stdout-normalization.json"
records = json.loads(manifest.read_text()) if manifest.exists() else {}
records.pop("final-evidence.txt", None)  # this command's active stdout is still being written
for path in sorted(TASK.glob("*.txt")):
    if path.name == "final-evidence.txt":
        continue
    raw = path.read_bytes()
    if records.get(path.name, {}).get("published_stdout_sha256") == hashlib.sha256(raw).hexdigest():
        continue
    normalized = raw.decode().replace(str(ROOT), "/<hub-copy>")
    # Python's abbreviated task repr can contain only the start of a host path.
    normalized = re.sub(r"/home/[^\s'\"<>)]*", "/<hub-copy-path>", normalized)
    normalized = mask_secrets(normalized)
    path.write_text(normalized)
    records[path.name] = {
        "original_stdout_sha256": hashlib.sha256(raw).hexdigest(),
        "published_stdout_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "normalization_changed_bytes": raw != normalized.encode(),
    }
manifest.write_text(json.dumps(records, indent=2) + "\n")

source = (ROOT / "app/db.py").read_text()
current = source[source.index("def search_logs("):source.index("\ndef get_log_context(")]
baseline = (TASK / "baseline_search.py").read_text()
diff = list(difflib.unified_diff(baseline.splitlines(True), current.splitlines(True),
                               fromfile="before/app/db.py:search_logs", tofile="after/app/db.py:search_logs"))
route = (ROOT / "app/routes/sessions.py").read_text()
route_before = route.replace("from starlette.concurrency import run_in_threadpool\n", "")
route_before = route_before.replace(
    "    # The worker owns the SQLite connection for its entire lifetime. AnyIO bounds\n"
    "    # concurrent workers; cancellation never closes a connection from the loop.\n"
    "    result = await run_in_threadpool(\n        search_logs,\n",
    "    result = search_logs(\n",
)
assert route_before != route
diff.extend(difflib.unified_diff(route_before.splitlines(True), route.splitlines(True),
                               fromfile="before/app/routes/sessions.py", tofile="after/app/routes/sessions.py"))
(TASK / "implementation.diff").write_text("".join(diff))

shutil.rmtree(TASK / "tmp")
shutil.rmtree(TASK / "__pycache__", ignore_errors=True)
paths = [ROOT / p for p in ("app/db.py", "app/routes/sessions.py", "CHANGELOG.md",
                          "tests/test_log_search_v1078.py")]
paths.extend(p for p in TASK.rglob("*") if p.is_file())
findings = []
for path in paths:
    body = path.read_text()
    findings.extend(scan_text(body, str(path.relative_to(ROOT))))
assert not findings, "\n".join(findings)
print("Publication secret-form scan: clean; checked source and task artifacts only.")
print("Captured stdout retained; hub host paths normalized; original-byte hashes recorded.")
print("Core implementation diff saved; temporary synthetic databases and task caches removed.")
