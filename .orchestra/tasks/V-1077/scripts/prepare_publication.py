"""Pseudonymize only this private copy's runtime paths; retain full line structure and hashes."""
import hashlib
import json
import os
from pathlib import Path
import re

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[2]
broker_paths = [entry.partition("/.local/share/orchestra/tools/uv/")[0]
                for entry in os.environ["PATH"].split(os.pathsep)
                if "/.local/share/orchestra/tools/uv/" in entry]
if len(set(broker_paths)) != 1:
    raise RuntimeError("Provisioned broker uv directory must be unambiguous in PATH")
broker_home = broker_paths[0]
record_path = TASK / "publication-redactions.json"
record = json.loads(record_path.read_text()) if record_path.exists() else {
    "purpose": "Public path-only derivatives. Root retains prior-import verbatim worker logs and host execution logs privately before publication.",
    "rules": {"<WORKSPACE>": "private worker checkout root", "<BROKER_HOME>": "broker provisioning user home"},
    "revisions": [],
}
changes = []
remaining_paths = []
for path in sorted(TASK.rglob("*")):
    if not path.is_file() or path == record_path or any(part in {"tmp", "isolated-home", "__pycache__"} for part in path.relative_to(TASK).parts):
        continue
    raw = path.read_bytes()
    content = raw.decode("utf-8")
    replacements = 0
    for prefix, alias in ((str(ROOT), "<WORKSPACE>"), (broker_home, "<BROKER_HOME>")):
        replacements += content.count(prefix)
        content = content.replace(prefix, alias)
    if replacements:
        public = content.encode("utf-8")
        assert raw.count(b"\n") == public.count(b"\n")
        path.write_bytes(public)
        changes.append({"file": path.relative_to(TASK).as_posix(), "sha256_before": hashlib.sha256(raw).hexdigest(),
                        "sha256_after": hashlib.sha256(public).hexdigest(), "path_replacements": replacements,
                        "newline_count_unchanged": True})
    if re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+/", content):
        remaining_paths.append(path.relative_to(TASK).as_posix())
if changes:
    record["revisions"].append(changes)
record["remaining_personal_runtime_path_files"] = remaining_paths
record_path.write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({"files_pseudonymized": len(changes), "remaining_personal_runtime_path_files": remaining_paths}))
raise SystemExit(bool(remaining_paths))
