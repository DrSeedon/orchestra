"""Finite read-only verification of the recovered sources and preserved history."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from recover import OUT, ROOT, sha, snapshot


def main():
    sys.path.insert(0, str(ROOT))
    import app
    from app.secret_mask import mask_secrets

    imported = Path(app.__file__).resolve()
    assert imported == ROOT / "app/__init__.py"
    before = json.loads((OUT / "before-manifest.json").read_text())
    after = snapshot()
    actual = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    manifest = json.loads((OUT / "five-file-manifest.json").read_text())
    expected = sorted(item["path"] for item in manifest["files"])
    assert actual == expected, actual
    assert not (ROOT / ".git").exists()
    for item in manifest["files"]:
        assert sha((ROOT / item["path"]).read_bytes()) == item["final_sha256"]
    producer = json.loads((OUT / "producer-source-check.json").read_text())
    for item in producer:
        assert sha((ROOT / item["path"]).read_bytes()) == item["expected"]
    commands = {
        "pipeline-contract": [sys.executable, "scripts/check_pipeline_manifest.py", "--check"],
        "instruction-contract": [sys.executable, "scripts/check_instruction_contract.py"],
        "phase-b-dry-run": ["patch", "--dry-run", "--batch", "--fuzz=0", "-p1", "-i",
                            ".orchestra/tasks/V-1257/phase-b-specialist.patch"],
    }
    checks = {}
    for name, command in commands.items():
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=30)
        # Keep publication-facing artifacts free of account paths; verify the exact
        # imported absolute path above and retain its digest as reproducible evidence.
        output = (result.stdout + result.stderr).replace(str(ROOT), "<WORKSPACE>")
        (OUT / (name + ".log")).write_text(output + f"\nEXIT_CODE={result.returncode}\n")
        checks[name] = {"command": command, "exit_code": result.returncode}
        checks[name]["command"][0] = ("uv run --frozen python" if name != "phase-b-dry-run"
                                      else "patch")
    assert checks["pipeline-contract"]["exit_code"] == 0
    assert checks["phase-b-dry-run"]["exit_code"] == 0
    assert checks["instruction-contract"]["exit_code"] == 1
    assert "CLAUDE.md must be a symlink" in (OUT / "instruction-contract.log").read_text()
    assert not (ROOT / "CLAUDE.md").exists()
    assert snapshot() == after, "Read-only checks changed sources"
    historical = {p: digest for p, digest in before.items() if p.startswith(".orchestra/tasks/V-1257/")}
    assert all(after.get(p) == digest for p, digest in historical.items())
    logs = [p for p in historical if p.endswith(".log")]
    result = {
        "actual_source_changes": actual,
        "all_other_initial_files_byte_identical": True,
        "initial_files_checked": len(before),
        "producer_manifest_paths_matched": len(producer),
        "v1257_artifacts_unchanged": len(historical), "v1257_logs_unchanged": len(logs),
        "app_import_workspace_relative": "app/__init__.py",
        "app_absolute_import_path_sha256": hashlib.sha256(str(imported).encode()).hexdigest(),
        "app_absolute_import_exactly_workspace_app": True,
        "checks": checks, "phase_b_applied": False,
        "source_unchanged_after_checks": True, "broker_import_head": None,
    }
    (OUT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    flagged = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or "scratch" in path.relative_to(OUT).parts:
            continue
        text = path.read_text()
        if mask_secrets(text) != text:
            flagged.append(path.relative_to(OUT).as_posix())
    (OUT / "artifact-scan.json").write_text(json.dumps({
        "scanner": "app.secret_mask.mask_secrets (form-only; no secret inventory)",
        "flagged_paths": flagged, "scratch_excluded": True,
    }, indent=2) + "\n")
    assert not flagged, flagged
    print(json.dumps(result, indent=2))
    print("Artifact form-secret scan: PASS")


if __name__ == "__main__":
    main()
