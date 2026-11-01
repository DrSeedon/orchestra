"""Measure only the synthetic reproduction left by this task's test run."""
import json
import subprocess
import tarfile
from pathlib import Path

notes = Path(__file__).resolve().parent
case = notes / "tmp/hub/test_old_packaging_overflows_o0"
remote = case / "hub-0123456789abcdef"
full_old = notes / "tmp/measurement-old.tar"
with full_old.open("wb") as output:
    subprocess.run(["tar", "-cf", "-", "-C", str(remote), "--exclude=./.git", "--exclude=./.venv", "."],
                   stdout=output, stderr=subprocess.PIPE, check=True)
with tarfile.open(case / "new.tar") as handle:
    files = {member.name.removeprefix("./"): member.size for member in handle if member.isfile()}
evidence = {
    "kind": "synthetic only; not the real failed workspace",
    "scaled_transport_limit_bytes": 131072,
    "old_full_archive_bytes": full_old.stat().st_size,
    "old_stopped_temporary_file_bytes": (case / "old.tar").stat().st_size,
    "new_archive_bytes": (case / "new.tar").stat().st_size,
    "new_archive_regular_files": files,
    "remote_large_cache_files_still_present": {
        rel: (remote / rel).stat().st_size for rel in (
            "nested/.venv/lib/huge.bin", "web/node_modules/pkg/huge.bin", "venv/huge.bin",
            "tools/custom-env/lib/huge.bin")},
    "imported_app_path_normalized": "/remote/workspace/app/__init__.py",
    "real_failure_archive_size_and_composition": "unknown; parent/Seedon inventories separately",
}
(notes / "synthetic-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
full_old.unlink()
print(json.dumps(evidence, indent=2, sort_keys=True))
