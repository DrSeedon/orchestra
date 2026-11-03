"""Task-local pytest evidence: test the actual Phase B manifest without root writes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
MANIFEST = Path(".orchestra/pipelines/default/pipeline.yaml")
PATCH = ROOT / ".orchestra/tasks/V-1257/phase-b-specialist.patch"
STATE = {}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def tree_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def pytest_addoption(parser):
    parser.addoption("--v1259-phase", choices=("A", "B"), required=True)


def pytest_configure(config):
    import app
    from app import pipeline

    phase = config.getoption("--v1259-phase")
    original = (ROOT / MANIFEST).read_bytes()
    source_stat = (ROOT / MANIFEST).stat()
    assert Path(app.__file__).resolve() == ROOT / "app/__init__.py"
    assert yaml.safe_load(original)["roles"]["specialist"]["model"] == "hub-gpt-6.1-sol"
    STATE.update(phase=phase, original=original, pipeline=pipeline,
                 original_dir=pipeline.PIPELINES_DIR,
                 source_stat=(source_stat.st_ino, source_stat.st_mtime_ns, source_stat.st_size),
                 evidence={"phase": phase, "app_exact_workspace_import": True,
                           "app_absolute_import_path_sha256": sha(str(Path(app.__file__).resolve()).encode()),
                           "phase_a_source_sha256": sha(original),
                           "phase_b_patch_sha256": sha(PATCH.read_bytes())})
    active = ROOT / MANIFEST
    if phase == "B":
        temporary_root = OUT / "scratch/phase-b-source"
        destination = temporary_root / ".orchestra/pipelines/default"
        assert not destination.exists()
        shutil.copytree(ROOT / ".orchestra/pipelines/default", destination)
        STATE.update(temporary_root=temporary_root,
                     temporary_tree_before=tree_bytes(destination))
        command = ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)]
        dry = subprocess.run([command[0], "--dry-run", *command[1:]], cwd=temporary_root,
                             text=True, capture_output=True, timeout=30)
        (OUT / "phase-b-dry-run.log").write_text(dry.stdout + dry.stderr + f"\nEXIT_CODE={dry.returncode}\n")
        assert dry.returncode == 0
        applied = subprocess.run(command, cwd=temporary_root, text=True,
                                 capture_output=True, timeout=30)
        (OUT / "phase-b-temporary-apply.log").write_text(applied.stdout + applied.stderr
                                                       + f"\nEXIT_CODE={applied.returncode}\n")
        assert applied.returncode == 0
        active = temporary_root / MANIFEST
        data = yaml.safe_load(active.read_bytes())
        assert data["roles"]["specialist"]["model"] == "hub-gemini-4-argon"
        baseline = yaml.safe_load(original)
        # The exact saved patch changes only specialist model and description.
        data["roles"]["specialist"]["model"] = baseline["roles"]["specialist"]["model"]
        data["roles"]["specialist"]["description"] = baseline["roles"]["specialist"]["description"]
        assert data == baseline
        pipeline.PIPELINES_DIR = temporary_root / ".orchestra/pipelines"
    pipeline.load_pipeline.cache_clear()
    expected_model = "hub-gpt-6.1-sol" if phase == "A" else "hub-gemini-4-argon"
    assert pipeline.load_pipeline("default").roles["specialist"].model == expected_model
    assert pipeline.get_role("default", "specialist").model == expected_model
    contract = subprocess.run([sys.executable, "scripts/check_pipeline_manifest.py", "--check",
                               "--manifest", str(active)], cwd=ROOT, text=True,
                              capture_output=True, timeout=30)
    (OUT / f"phase-{phase.lower()}-pipeline-contract.log").write_text(
        (contract.stdout + contract.stderr).replace(str(ROOT), "<WORKSPACE>")
        + f"\nEXIT_CODE={contract.returncode}\n")
    # Preserve the separate required check result, including RED, while allowing
    # the affected tests to run. No source checker or test assertion is changed.
    STATE["evidence"].update(active_manifest_sha256=sha(active.read_bytes()),
                             actual_loaded_specialist_model=expected_model,
                             pipeline_contract_exit_code=contract.returncode,
                             actual_phase_b_manifest=phase == "B")


def pytest_collection_finish(session):
    frozen = [item.nodeid for item in session.items
              if "test_research_closure_modules_reach_orchestrator_prompts[" in item.nodeid]
    assert len(frozen) == 6, frozen
    STATE["evidence"].update(frozen_v1256_collected_nodeids=frozen,
                             total_collected=len(session.items))


def pytest_sessionfinish(session, exitstatus):
    STATE["evidence"]["pytest_exit_code"] = int(exitstatus)
    STATE["evidence"]["passed"] = len(session.config.pluginmanager.get_plugin("terminalreporter").stats.get("passed", []))


def pytest_unconfigure(config):
    if not STATE:
        return
    pipeline = STATE["pipeline"]
    try:
        pipeline.PIPELINES_DIR = STATE["original_dir"]
        pipeline.load_pipeline.cache_clear()
        if "temporary_root" in STATE:
            temporary_manifest = STATE["temporary_root"] / MANIFEST
            temporary_manifest.write_bytes(STATE["original"])
            assert tree_bytes(temporary_manifest.parent) == STATE["temporary_tree_before"]
            STATE["evidence"]["temporary_phase_b_tree_exactly_restored_to_phase_a"] = True
        current = (ROOT / MANIFEST).stat()
        assert (current.st_ino, current.st_mtime_ns, current.st_size) == STATE["source_stat"]
        assert (ROOT / MANIFEST).read_bytes() == STATE["original"]
        assert pipeline.PIPELINES_DIR == STATE["original_dir"]
        assert pipeline.get_role("default", "specialist").model == "hub-gpt-6.1-sol"
        pipeline.load_pipeline.cache_clear()
        STATE["evidence"].update(root_manifest_bytes_and_inode_mtime_size_unchanged=True,
                                 process_pipeline_pointer_restored=True,
                                 restored_loaded_specialist_model="hub-gpt-6.1-sol")
    finally:
        (OUT / f"phase-{STATE['phase'].lower()}-evidence.json").write_text(
            json.dumps(STATE["evidence"], indent=2) + "\n")
