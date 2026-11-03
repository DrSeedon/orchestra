"""Verify the two test fixes, immutable accepted sources, both phases and history."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
sys.path.insert(0, str(OUT.parent))
sys.path.insert(0, str(ROOT))
from recover import snapshot
from app.secret_mask import mask_secrets


def sha(body):
    return hashlib.sha256(body).hexdigest()


def main():
    assert Path(sys.executable).absolute().parent == ROOT / ".venv/bin"
    before = json.loads((OUT / "before-manifest.json").read_text())
    after = snapshot()
    changes = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    expected = ["tests/test_default_pipeline.py", "tests/test_gemini_specialist_v1257.py"]
    assert changes == expected, changes
    canonical = (OUT / "canonical-test-default-pipeline.py.txt").read_bytes()
    old = (b'        assert set(cfg.roles) == {\n'
           b'            "orchestrator", "sub-orchestrator", "worker",\n'
           b'            "full-cycle", "reducer"}')
    new = old.replace(b'"reducer"}', b'"reducer", "specialist"}')
    assert canonical.count(old) == 1
    assert (ROOT / expected[0]).read_bytes() == canonical.replace(old, new, 1)
    phases = {}
    for phase, model in (("a", "hub-gpt-6.1-sol"), ("b", "hub-gemini-4-argon")):
        item = json.loads((OUT / f"phase-{phase}-evidence.json").read_text())
        assert item["pytest_exit_code"] == 0
        assert item["actual_loaded_specialist_model"] == model
        assert item["passed"] == item["total_collected"]
        assert len(item["frozen_v1256_collected_nodeids"]) == 6
        assert item["pipeline_contract_exit_code"] == (0 if phase == "a" else 1)
        assert item["root_manifest_bytes_and_inode_mtime_size_unchanged"]
        assert item["process_pipeline_pointer_restored"]
        assert item["restored_loaded_specialist_model"] == "hub-gpt-6.1-sol"
        log = (OUT / f"phase-{phase}-pytest.log").read_text()
        assert f"{item['passed']} passed" in log and "EXIT_CODE=0" in log
        item["wall_seconds_from_pytest"] = float(re.search(r"passed in ([\d.]+)s", log).group(1))
        phases[phase] = item
    assert phases["b"]["temporary_phase_b_tree_exactly_restored_to_phase_a"]
    assert "quotes manifest model 'hub-gemini-4-argon'" in (OUT / "phase-b-pipeline-contract.log").read_text()
    assert phases["a"]["frozen_v1256_collected_nodeids"] == phases["b"]["frozen_v1256_collected_nodeids"]
    assert phases["a"]["phase_a_source_sha256"] == phases["b"]["phase_a_source_sha256"]
    accepted = json.loads((OUT.parent / "five-file-manifest.json").read_text())
    for item in accepted["files"]:
        assert sha((ROOT / item["path"]).read_bytes()) == item["final_sha256"]
    prior = json.loads((OUT / "prior-artifacts-manifest.json").read_text())
    assert all(sha((ROOT / path).read_bytes()) == digest for path, digest in prior.items())
    patch = []
    manifest = []
    for path in expected:
        original = (OUT / "before" / path).read_bytes()
        current = (ROOT / path).read_bytes()
        delta = list(difflib.ndiff(original.decode().splitlines(), current.decode().splitlines()))
        manifest.append({"path": path, "before_sha256": sha(original), "final_sha256": sha(current),
                         "added_lines": sum(line.startswith("+ ") for line in delta),
                         "removed_lines": sum(line.startswith("- ") for line in delta)})
        patch.extend(difflib.unified_diff(original.decode().splitlines(True),
                     current.decode().splitlines(True), fromfile="a/" + path, tofile="b/" + path))
    (OUT / "two-test-fixes.patch").write_text("".join(patch))
    root_contract = subprocess.run([sys.executable, "scripts/check_instruction_contract.py"],
                                   cwd=ROOT, text=True, capture_output=True, timeout=30)
    root_output = (root_contract.stdout + root_contract.stderr).replace(str(ROOT), "<WORKSPACE>")
    (OUT / "instruction-contract.log").write_text(root_output + f"\nEXIT_CODE={root_contract.returncode}\n")
    assert root_contract.returncode == 1 and "CLAUDE.md must be a symlink" in root_output
    assert not (ROOT / "CLAUDE.md").exists()
    scratch = OUT / "scratch"
    assert scratch.is_dir() and not scratch.is_symlink()
    shutil.rmtree(scratch)
    assert snapshot() == after
    result = {
        "reported_accepted_generation": "6f7f5117de49a59dab6c5d108e3f3d42b5b1f1d4",
        "generation_source": "root follow-up message; this no-.git copy cannot verify commit identity",
        "new_import_head": None, "merged": False,
        "exactly_two_test_sources_changed_this_followup": manifest,
        "accepted_five_recovery_files_unchanged": accepted["files"],
        "all_other_initial_sources_unchanged": True,
        "prior_task_artifacts_byte_identical": len(prior),
        "prior_625_log_unchanged": True, "frozen_v1256_byte_exact_except_role_set_addition": True,
        "phases": phases, "root_instruction_contract_exit_code": root_contract.returncode,
        "root_instruction_contract_blocker": "CLAUDE.md absent on arrival",
        "scratch_removed": True, "root_manifest_never_written": True,
        "phase_b_integration_ready": False,
        "additional_integration_blocker": "Phase B static manifest contract rejects existing model-routing.md:47 quoting hub-gemini-4-argon; no source expansion authorized",
        "phase_b_initial_pretest_attempt_exit_code": 3,
        "verification_python_executable_workspace_relative": str(Path(sys.executable).relative_to(ROOT)),
    }
    (OUT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    rows = "\n".join(f"| `{item['path']}` | +{item['added_lines']}/−{item['removed_lines']} | `{item['final_sha256']}` |"
                     for item in manifest)
    report = f'''# V-1259 — two test fixes complete; Phase B static contract blocked

**New integration blocker: Phase B static manifest contract is RED.** Existing
model-routing.md:47 quotes `hub-gemini-4-argon`; once the saved Phase B patch
puts that ID in the actual manifest, the unchanged canonical checker rejects it.
This was reported immediately; no production source or guard was changed beyond
the two authorized test files. Root must resolve this separately before calling
Phase B integration green. Affected tests pass in both states; that does not
override this independent required check.

Root reported accepted source generation `6f7f5117de49a59dab6c5d108e3f3d42b5b1f1d4`,
not yet merged. This follow-up changes exactly two test files; the five previously
accepted recovery files, producer app/rules and all other source remain unchanged.
No new import/commit SHA is available in this no-.git worker copy.

1. Recovered tests/test_default_pipeline.py from exact public main
   `b9d893ec8babd4b2052ac1f497962e1966206bcb`, with ONLY specialist added to the
   exact expected-role set. Entire frozen V-1256 research-closure test and its
   2 roles × 3 modules parametrization are byte-exact. All six cases collected
   and passed in both phases. Canonical URL and SHA: canonical-source.json.
2. Specialist pipeline contract now accepts exactly Sol or exact Argon and
   requires the resolved model to equal the declared model. Removed the
   stage-specific Argon-string-absence assertion and unused Path import.
   Existing can_spawn, parent, skills, effort, disabled tool, prompt delivery,
   other-role Sol, admission, privacy, quota, recovery and history assertions
   remain. No prose-string acceptance added.

| Changed source | Actual diff | Final SHA-256 |
|---|---:|---|
{rows}

Exact follow-up diff: two-test-fixes.patch. Full final SHA set for these two tests
and the five unchanged accepted recovery files: verification.json. Source snapshot
compares every initial non-environment/cache file, not only named target paths.

Actual tested manifest SHA-256: Phase A `{phases['a']['active_manifest_sha256']}`;
temporary Phase B `{phases['b']['active_manifest_sha256']}`. Exact restoration
returns the temporary manifest to the same Phase A SHA; the root manifest was
never written (bytes and inode/mtime/size unchanged).

| Actual offline check | Result | Evidence |
|---|---|---|
| Phase A on actual root Sol manifest, affected test files + available contract tests | {phases['a']['passed']} passed, {phases['a']['wall_seconds_from_pytest']} s, exit 0 | phase-a-pytest.log, phase-a-evidence.json |
| Phase B on a task-local actual manifest patched by the unchanged saved patch, same tests | {phases['b']['passed']} passed, {phases['b']['wall_seconds_from_pytest']} s, exit 0 | phase-b-pytest.log, phase-b-evidence.json |
| Static manifest contract on actual Phase A | PASS, exit 0 | phase-a-pipeline-contract.log |
| Static manifest contract on actual temporary Phase B | RED, exit 1: existing model-routing.md:47 quotes manifest model ID | phase-b-pipeline-contract.log |
| Phase B patch dry-run, fuzz=0 | PASS, exit 0 | phase-b-dry-run.log |
| Temporary Phase B tree restored byte-for-byte to copied Phase A; process-local pipeline pointer restored | PASS | phase-b-evidence.json |
| Root Phase A manifest bytes and inode/mtime/size unchanged throughout both runs | PASS | phase-a-evidence.json, phase-b-evidence.json |
| Actual-root instruction script | RED, exit 1: missing CLAUDE.md in sparse copy | instruction-contract.log |
| Old V-1257 and earlier V-1259 artifacts | {len(prior)} byte-identical; earlier 625-pass log and missing-CLAUDE red preserved | prior-artifacts-manifest.json, verification.json |

Both runs used provisioned uv 0.11.28 and default .venv, UV_OFFLINE=1,
serial/nice=10/OOM score=1000, 180-second outer timeout each. No failed or skipped
cases in either completed test run. The separate Phase B static check remains
red. Included checker tests still exercise their canonical real-root Phase A and
synthetic fixtures; the independent `--manifest` check above is the actual Phase B
contract result. No repeat of the 625-case set or full suite.
Exact app import was asserted against this workspace's app/__init__.py;
absolute resolved path SHA is in both evidence JSONs. The final handoff links
the actual absolute local app file. Tests used synthetic fixtures, not live DB,
provider turns, SSH, restart or service state.

Commands (prepend provisioned uv PATH in each test shell; prepend this task's
final-integration directory to PYTHONPATH for the task-local evidence plugin):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
# UV_OFFLINE=1, task-local TMPDIR; each test command: timeout 180s nice -n 10
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=A --basetemp=.orchestra/tasks/V-1259/final-integration/scratch/pytest-a -o cache_dir=.orchestra/tasks/V-1259/final-integration/scratch/cache-a
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=B --basetemp=.orchestra/tasks/V-1259/final-integration/scratch/pytest-b -o cache_dir=.orchestra/tasks/V-1259/final-integration/scratch/cache-b
uv run --frozen python .orchestra/tasks/V-1259/final-integration/finalize_followup.py
# Plugin runs --dry-run and applies this same patch ONLY inside task-local copied source:
patch --dry-run --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
patch --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
# Same .venv Python runs static checks on each phase's actual manifest:
uv run --frozen python scripts/check_pipeline_manifest.py --check --manifest <phase-manifest>
uv run --frozen python scripts/check_instruction_contract.py
```

phase_manifest_checks.py only redirects the in-process pipeline root for Phase B;
it verifies the exact loaded Argon model before tests, checks all native/default/
other-role YAML data unchanged except saved specialist model/description delta,
and restores the temporary manifest, tree and pointer afterward. It never edits
the actual root manifest. Task-owned scratch was removed after verification.

Remaining limit: complete-host root instruction/KB/link check, merge, normal idle
activation, live registry and normal admitted specialist smoke remain root's work.
The newly found Phase B manifest/prompt contract conflict also requires root action.
Phase B has NOT been hot-applied or activated. Source identity is accepted, not
merged. No new models/review/spawn, paid calls, restart/deploy, publication,
private DB/SSH, commit or push. Existing privacy/publication guards are unchanged.
Two unsuccessful preparatory attempts are retained: the mechanical recovery-anchor
script stopped before source writes (corrected unique anchor, notes.md); the first
Phase B pytest attempt exited 3 BEFORE collection because the task plugin aborted
on the real static-check failure. Its error/evidence are phase-b-pretest-error.log,
phase-b-pretest-error-evidence.json and phase-b-pretest-contract.log. Only the
workspace account path in that new error log was normalized; the original log
hash/size are preserved. The task plugin then recorded the separate red checker
without aborting the independent affected tests; no canonical guard/test assertion
was weakened or skipped. The original 625-case log and earlier red root check
remain byte-identical.
'''
    (OUT / "report.md").write_text(report)
    flagged = []
    for path in OUT.rglob("*"):
        if path.is_file() and mask_secrets(path.read_text()) != path.read_text():
            flagged.append(str(path.relative_to(OUT)))
    (OUT / "artifact-scan.json").write_text(json.dumps({
        "scanner": "app.secret_mask.mask_secrets (form-only, no secret inventory)",
        "flagged_paths": flagged,
    }, indent=2) + "\n")
    assert not flagged, flagged
    print(f"Affected tests: phase A {phases['a']['passed']} passed, phase B {phases['b']['passed']} passed; exactly two test changes")
    print(f"PASS: five accepted recovery files and {len(prior)} prior artifacts unchanged")
    print("Root instruction contract RED: missing CLAUDE.md; root full-host check remains")
    print("Phase B static manifest contract RED: model-routing.md:47 quotes hub-gemini-4-argon; source scope not expanded")


if __name__ == "__main__":
    main()
