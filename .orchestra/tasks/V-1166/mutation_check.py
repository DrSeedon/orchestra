"""Offline mutations against repository tests; restore source bytes after each case."""
from pathlib import Path
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[3]
evidence = Path(tempfile.mkdtemp(prefix="orchestra-v1166-native-mutations-", dir="/tmp"))
signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
cases = [
    ("advertised_effort_passthrough", "app/backend_codex.py",
     '            self.reasoning_effort = reasoning_effort\n',
     '            self.reasoning_effort = reasoning_effort if reasoning_effort in CODEX_REASONING_EFFORTS else "high"\n',
     "test_native_thread_and_turn_use_normal_backend_without_experiment_sandbox and ultra and eval-wire-test"),
    ("advertised_matrix_not_fixed_enum", "app/eval_admission.py",
     '        expected.update((model, effort) for effort in efforts)\n',
     '        if "ultra" in efforts:\n            raise ValueError("fixed legacy enum rejects advertised ultra")\n        expected.update((model, effort) for effort in efforts)\n',
     "test_dynamic_workflow_accepts_frozen_48_call_coding_stage"),
    ("native_no_experiment_sandbox", "app/backend_codex.py",
     '            thread_id = ((result.get("thread") or {}).get("id"))',
     '            if self._evaluation_actor_id:\n                raise RuntimeError("experiment sandbox confirmation required")\n            thread_id = ((result.get("thread") or {}).get("id"))',
     "test_native_thread_and_turn_use_normal_backend_without_experiment_sandbox"),
    ("late_identity", "app/eval_admission.py",
     '        check_slot(row["dispatch_slot_id"], row["run_id"])\n        check_task_identity(row)\n',
     '        check_slot(row["dispatch_slot_id"], row["run_id"])\n',
     "test_task_identity_revalidated_after_managed_connection"),
    ("frozen_plan_bound", "app/eval_admission.py",
     '        if invocation >= len(json.loads(row["plan"])):\n            raise ValueError("invocation outside the frozen task plan")\n',
     '', "test_offline_full_cohort_engine_adapter_http_ledger"),
]
uv = Path.home() / ".local/share/orchestra/tools/uv/0.11.28/bin/uv"
results = []
for name, filename, old, new, selected in cases:
    if len(sys.argv) > 1 and name not in sys.argv[1:]:
        continue
    source = root / filename
    original = source.read_bytes()
    backup = evidence / "source-originals" / filename
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(original)
    text = original.decode()
    assert text.count(old) == 1, (name, text.count(old))
    log = evidence / f"{name}.log"
    junit = evidence / f"{name}.xml"
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(evidence))
    env.pop("PYTHONPYCACHEPREFIX", None)
    env.pop("NOTIFY_SOCKET", None)
    try:
        source.write_text(text.replace(old, new))
        with log.open("wb") as output:
            completed = subprocess.run([str(uv), "run", "--frozen", "python", "-m", "pytest",
                "tests/test_eval_admission.py", "-q", "-p", "no:cacheprovider", "--timeout=15",
                "-k", selected, f"--basetemp={evidence / f'pytest-{name}'}", f"--junitxml={junit}"],
                cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=45)
    finally:
        source.write_bytes(original)
        assert source.read_bytes() == original
    killed = completed.returncode == 1 and "FAILED" in log.read_text()
    intended = None
    if name == "late_identity":
        cases_xml = ET.parse(junit).getroot().findall(".//testcase")
        failures = [case.find("failure") for case in cases_xml]
        intended = len(failures) == 2 and all(
            failure is not None and "late task identity change must prevent provider send" in failure.get("message", "")
            and "AttributeError" not in (failure.text or "") for failure in failures)
        killed = killed and intended
    result = {"case": name, "source": filename, "repository_test": "tests/test_eval_admission.py::" + selected,
              "returncode": completed.returncode, "killed": killed, "source_restored": True,
              "restored_source_sha256": hashlib.sha256(original).hexdigest(),
              "log": str(log), "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    if intended is not None:
        result.update(intended_send_boundary_assertion_failed=intended, junit=str(junit))
    results.append(result)
    (evidence / "receipt.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)
    if not killed:
        raise SystemExit("Mutation survived or test did not execute")
(evidence / "receipt.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
print(f"{len(results)} selected mutations killed; source restored; RAW={evidence}")
