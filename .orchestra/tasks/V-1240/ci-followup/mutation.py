"""Prove both native deferral and case normalization; restore exact source bytes."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[4]
TASK = ROOT / '.orchestra/tasks/V-1240/ci-followup'
SOURCE = ROOT / 'app/models.py'
original = SOURCE.read_bytes()
lookup = b'spec = MODEL_SPECS.get(model_id) or COMPAT_MODEL_SPECS.get(model_id)'
normalization = (b'    if spec is None:\n'
                 b'        spec = MODEL_SPECS.get(normalized) or COMPAT_MODEL_SPECS.get(normalized)\n'
                 b'        if spec is not None:\n'
                 b'            model_id = spec.id\n')
assert original.count(lookup) == original.count(normalization) == 1
variants = [
    ('eager-registry', original.replace(lookup, b'spec = get_model_spec(model_id)'), 6, 25),
    ('raw-case', original.replace(normalization, b''), 1, 30),
]
tests = [
    'tests/test_hub_sol_only_v1240.py::test_native_runtime_identity_validation_stays_with_its_owner',
    'tests/test_hub_sol_only_v1240.py::test_all_non_sol_hub_requests_refuse_even_with_old_enabled_flags',
    'tests/test_hub_sol_only_v1240.py::test_sol_stays_admitted_with_existing_config_and_catalog_gates',
    'tests/test_hub_sol_only_v1240.py::test_sol_metadata_follows_case_insensitive_canonical_resolution',
]
runner = shutil.which('uv')
assert runner and '/orchestra/tools/uv/0.11.28/' in runner
env = dict(os.environ)
for key in json.loads((TASK/'child-test-env.json').read_text())['removed_keys']:
    env.pop(key, None)
command = [runner,'run','--frozen','python','-m','pytest',*tests,'-q','--tb=short']
results = []
for name, mutant, expected_failed, expected_passed in variants:
    try:
        SOURCE.write_bytes(mutant)
        result = subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
        output = result.stdout + result.stderr
        (TASK/f'raw/final-mutation-{name}.log').write_text(output)
    finally:
        SOURCE.write_bytes(original)
    assert SOURCE.read_bytes() == original
    assert result.returncode == 1, output
    failures = re.findall(r'^FAILED (tests/[^\n]+)',output,re.M)
    assert len(failures) == expected_failed, output
    assert all(('test_native_runtime_identity_validation_stays_with_its_owner' in node
                or 'test_sol_metadata_follows_case_insensitive_canonical_resolution' in node)
               for node in failures), output
    assert f'{expected_failed} failed, {expected_passed} passed' in output, output
    results.append(dict(mutation=name,exit_code=result.returncode,summary=output.splitlines()[-1],
                        failed_nodes=failures,mutant_sha256=hashlib.sha256(mutant).hexdigest()))
control = subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
(TASK/'raw/final-mutation-restored.log').write_text(control.stdout + control.stderr)
assert control.returncode == 0, control.stdout + control.stderr
before = hashlib.sha256(original).hexdigest()
restored = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
assert before == restored
proof = dict(tests=tests,mutations=results,before_sha256=before,restored_sha256=restored,
             restored_exit_code=control.returncode,restored_summary=(control.stdout+control.stderr).splitlines()[-1])
(TASK/'final-mutation-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({k:v for k,v in proof.items() if k not in {'tests','mutations'}},indent=2))
for result in results: print(result['mutation']+': '+result['summary'])
