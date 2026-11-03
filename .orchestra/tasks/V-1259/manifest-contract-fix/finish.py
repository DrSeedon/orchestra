"""Finite evidence for the authorized one-prompt manifest ownership correction."""
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
REL = ".orchestra/pipelines/default/prompts/modules/model-routing.md"
sys.path.insert(0, str(OUT.parent))
sys.path.insert(0, str(ROOT))
from recover import snapshot
import app
from app.secret_mask import mask_secrets


def sha(body):
    return hashlib.sha256(body).hexdigest()


def patch(old, new, source):
    return "".join(difflib.unified_diff(old.decode().splitlines(True),
                   new.decode().splitlines(True), fromfile=source, tofile="b/" + REL))


def main():
    assert Path(sys.executable).absolute().parent == ROOT / ".venv/bin"
    assert Path(app.__file__).resolve() == ROOT / "app/__init__.py"
    assert not (ROOT / ".git").exists()
    before = json.loads((OUT / "before-manifest.json").read_text())
    after = snapshot()
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    assert changed == [REL], changed
    original = (OUT / "before-model-routing.md").read_bytes()
    current = (ROOT / REL).read_bytes()
    # Scope proof, not prose acceptance: every byte outside the replaced three
    # lines must be identical, including the entire rest of the V-1257 section.
    old = (b'A separate `specialist` role in the `default` pipeline may use exact Orchestra model\n'
           b'`hub-gemini-4-argon`, mapped only to Hub provider `antigravity` and model\n'
           b'`gemini-4-argon` (Gemini 4 Argon). Use the existing paid Hub pool with no extra\n')
    new = (b'A separate `specialist` role in the `default` pipeline uses the model configured\n'
           b'by that role in the pipeline manifest. Its Gemini route maps only to Hub provider\n'
           b'`antigravity` and wire model `gemini-4-argon` (Gemini 4 Argon). Use the existing paid Hub pool with no extra\n')
    assert original.count(old) == 1 and current == original.replace(old, new, 1)
    prompt_files = list((ROOT / ".orchestra/pipelines/default/prompts").rglob("*.md"))
    assert all(b"hub-gemini-4-argon" not in path.read_bytes() for path in prompt_files)
    prior = json.loads((OUT / "prior-artifacts-manifest.json").read_text())
    assert all(sha((ROOT / path).read_bytes()) == digest for path, digest in prior.items())
    canonical = (OUT / "canonical-b9-model-routing.md").read_bytes()
    provenance = json.loads((OUT / "canonical-source.json").read_text())
    assert sha(canonical) == provenance["sha256"]
    (OUT / "one-prompt-fix.patch").write_text(patch(original, current, "a/" + REL))
    (OUT / "canonical-b9-to-final.patch").write_text(patch(canonical, current, "b9/" + REL))
    phases = {}
    for phase, model in (("a", "hub-gpt-6.1-sol"), ("b", "hub-gemini-4-argon")):
        result = json.loads((OUT / f"phase-{phase}-evidence.json").read_text())
        assert result["actual_loaded_specialist_model"] == model
        assert result["pytest_exit_code"] == result["pipeline_contract_exit_code"] == 0
        assert result["passed"] == result["total_collected"] == 149
        assert len(result["frozen_v1256_collected_nodeids"]) == 6
        assert result["root_manifest_bytes_and_inode_mtime_size_unchanged"]
        assert result["process_pipeline_pointer_restored"]
        assert result["restored_loaded_specialist_model"] == "hub-gpt-6.1-sol"
        log = (OUT / f"phase-{phase}-pytest.log").read_text()
        assert "149 passed" in log and "EXIT_CODE=0" in log
        result["wall_seconds_from_pytest"] = float(re.search(r"passed in ([\d.]+)s", log).group(1))
        phases[phase] = result
    assert phases["b"]["temporary_phase_b_tree_exactly_restored_to_phase_a"]
    assert phases["a"]["frozen_v1256_collected_nodeids"] == phases["b"]["frozen_v1256_collected_nodeids"]
    assert sha((ROOT / ".orchestra/pipelines/default/pipeline.yaml").read_bytes()) == phases["a"]["phase_a_source_sha256"] == phases["b"]["phase_a_source_sha256"]
    checked = subprocess.run([sys.executable, "scripts/check_instruction_contract.py"],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    output = (checked.stdout + checked.stderr).replace(str(ROOT), "<WORKSPACE>")
    (OUT / "instruction-contract.log").write_text(output + f"\nEXIT_CODE={checked.returncode}\n")
    assert checked.returncode == 1 and "CLAUDE.md must be a symlink" in output
    assert not (ROOT / "CLAUDE.md").exists()
    source_paths = {item["path"] for item in json.loads(
        (ROOT / ".orchestra/tasks/V-1257/recovery-source-manifest.json").read_text())["files"]}
    source_paths.update(item["path"] for item in json.loads(
        (OUT.parent / "five-file-manifest.json").read_text())["files"])
    source_paths.update(("scripts/check_pipeline_manifest.py", "scripts/check_instruction_contract.py",
                         "tests/conftest.py", "pyproject.toml", "uv.lock"))
    source_manifest = [{"path": path, "sha256": sha((ROOT / path).read_bytes()),
                        "unchanged_this_followup": path != REL} for path in sorted(source_paths)]
    (OUT / "final-source-shas.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
    scratch = OUT / "scratch"
    assert scratch.is_dir() and not scratch.is_symlink()
    shutil.rmtree(scratch)
    assert snapshot() == after
    verification = {
        "changed_source_paths": changed,
        "only_three_v1257_lines_replaced": True,
        "before_model_routing_sha256": sha(original), "final_model_routing_sha256": sha(current),
        "canonical_model_routing_sha256": sha(canonical),
        "all_other_initial_files_byte_identical": len(before) - 1,
        "prior_artifacts_byte_identical": len(prior),
        "app_registry_backend_and_checker_unchanged": True,
        "frozen_v1256_six_cases_unchanged_and_pass_in_both_states": True,
        "no_internal_argon_id_copy_in_prompt_files_checked": len(prompt_files),
        "phases": phases, "root_instruction_contract_exit_code": checked.returncode,
        "root_instruction_contract_blocker": "CLAUDE.md absent in sparse copy",
        "phase_b_hot_applied": False, "root_manifest_never_written": True,
        "scratch_removed": True, "broker_import_head": None, "merged_or_activated": False,
        "app_absolute_import_path_sha256": sha(str(Path(app.__file__).resolve()).encode()),
        "verification_python_executable_workspace_relative": str(Path(sys.executable).relative_to(ROOT)),
    }
    (OUT / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    report = f'''# V-1259 — DONE: Phase B manifest/prompt contract resolved

Only the new V-1257 paragraph in `{REL}` changed: three lines replaced.
The prompt now refers to the model configured by the `specialist` role in the
default pipeline manifest, while keeping exact external Hub provider/model
`antigravity/gemini-4-argon`. The manifest owns internal versioned model IDs;
runtime guards still own admission. No checker/allowlist, app/registry/backend,
alias/schema, test, role or manifest edits in this follow-up. All owner dates and
scope, funding/privacy/quota/task/project identity, history/recovery and staged
activation boundaries are byte-identical outside those three lines.

| Source evidence | SHA-256 |
|---|---|
| Before this prompt fix | `{sha(original)}` |
| Final model-routing.md | `{sha(current)}` |
| Exact public b9 canonical model-routing.md | `{sha(canonical)}` |
| Actual Phase A manifest (untouched) | `{phases['a']['active_manifest_sha256']}` |
| Actual temporary Phase B manifest tested, then exactly restored | `{phases['b']['active_manifest_sha256']}` |

Review delta: one-prompt-fix.patch. Full final prompt vs pinned public
`b9d893ec8babd4b2052ac1f497962e1966206bcb`: canonical-b9-to-final.patch;
canonical-source.json supplies URL and validated SHA. All relevant app/registry/
backend/pipeline/prompt/test/checker/lock source hashes: final-source-shas.json.

| Fresh completed offline check | Actual result | Evidence |
|---|---|---|
| Phase A actual Sol manifest: same affected and available contract test paths | 149 passed, {phases['a']['wall_seconds_from_pytest']} s, exit 0 | phase-a-pytest.log |
| Phase B actual temporary Argon manifest: same paths | 149 passed, {phases['b']['wall_seconds_from_pytest']} s, exit 0 | phase-b-pytest.log |
| Static manifest/prompt contract on actual Phase A | PASS, exit 0 | phase-a-pipeline-contract.log |
| Static manifest/prompt contract on actual temporary Phase B | PASS, exit 0 | phase-b-pipeline-contract.log |
| Unchanged Phase B patch dry-run, fuzz=0 | PASS, exit 0 | phase-b-dry-run.log |
| Six frozen V-1256 delivery cases, 2 roles × 3 modules | Unchanged; all six collected and passed in BOTH runs | phase-a-evidence.json, phase-b-evidence.json |
| Temporary tree and process pipeline pointer restored to Phase A | PASS; root manifest bytes/inode/mtime/size never changed | phase-b-evidence.json |
| Actual-root instruction contract | RED, exit 1: supplied copy lacks CLAUDE.md | instruction-contract.log |
| All other initial source/context files | {len(before)-1} byte-identical | before-manifest.json, verification.json |
| Previous task artifacts, including all red and 625/149 logs | {len(prior)} byte-identical | prior-artifacts-manifest.json |

No failed/skipped cases in these completed runs. Static Phase B now passes the
same unchanged canonical checker that previously rejected the copied internal ID.
Earlier red Phase B/pretest/root-instruction checks are preserved, not rewritten.
Root instruction checking still stops at the absent CLAUDE.md; complete-host
instruction/KB/link validation remains root's responsibility. No fabricated link.

Provisioned uv 0.11.28, default .venv, exact workspace app import, UV_OFFLINE=1
during tests, synthetic fixtures and process-local test Git identity. Serial,
nice=10/OOM score=1000, finite 180-second outer bound per test command. Repeated
only the same affected paths because the assembled routing prompt changed; no
full 625 repeat or full repository suite. The reused task-local plugin was copied
without changing its prior accepted version or prior evidence. It redirects only
the test process to a copied pipeline tree for Phase B, loads exact Argon before
tests, runs the real static checker on that manifest, and restores the tree and
pointer exactly afterward. Root source was never patched for Phase B.

Commands (in each test shell):

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
# Set task-local TMPDIR and PYTHONPATH to this manifest-contract-fix directory;
# UV_OFFLINE=1, PYTHONDONTWRITEBYTECODE=1, synthetic Git identity, no NOTIFY_SOCKET.
# Each pytest command ran with timeout 180s nice -n 10:
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=A --basetemp=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/pytest-a -o cache_dir=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/cache-a
uv run --frozen python -m pytest tests/test_default_pipeline.py tests/test_gemini_specialist_v1257.py tests/test_check_pipeline_manifest.py tests/test_instruction_contract.py -q -p phase_manifest_checks --v1259-phase=B --basetemp=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/pytest-b -o cache_dir=.orchestra/tasks/V-1259/manifest-contract-fix/scratch/cache-b
uv run --frozen python .orchestra/tasks/V-1259/manifest-contract-fix/finish.py
# Plugin runs with the same .venv Python and the actual selected manifest:
uv run --frozen python scripts/check_pipeline_manifest.py --check --manifest <phase-manifest>
# Phase B patch commands run ONLY in task-local copied source:
patch --dry-run --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
patch --batch --fuzz=0 -p1 -i <WORKSPACE>/.orchestra/tasks/V-1257/phase-b-specialist.patch
uv run --frozen python scripts/check_instruction_contract.py
```

Absolute app import was asserted as this exact workspace's app/__init__.py;
its absolute path SHA is `{verification['app_absolute_import_path_sha256']}`.
The handoff links the actual local app file. Task-owned test scratch was removed.
Artifact form-secret scan uses app.secret_mask without reading secret inventories.

Returned SOURCE integration is coherent for both phases; source is not merged or
activated. This copy has no .git and invents no new imported SHA; broker owns
committing the returned file. Root owns merge/complete-host instruction checking,
normal idle activation, live registry verification and admitted specialist smoke.
No real model/Hub turn, SSH/private DB, new worker/review, restart/deploy, Phase B
hot apply, paid calls, publication, git commit/push or live-state writes occurred.
'''
    (OUT / "report.md").write_text(report)
    flagged = [str(path.relative_to(OUT)) for path in OUT.rglob("*")
               if path.is_file() and mask_secrets(path.read_text()) != path.read_text()]
    (OUT / "artifact-scan.json").write_text(json.dumps({
        "scanner": "app.secret_mask.mask_secrets (form-only; no secret inventory)",
        "flagged_paths": flagged,
    }, indent=2) + "\n")
    assert not flagged, flagged
    print(f"PASS: one prompt changed; Phase A {phases['a']['passed']} and Phase B {phases['b']['passed']} tests passed")
    print(f"PASS: actual static checks in BOTH phases; {len(prior)} prior artifacts unchanged")
    print("Root instruction contract remains RED: missing CLAUDE.md; complete-host check belongs to root")


if __name__ == "__main__":
    main()
