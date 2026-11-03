"""Restore the old global workflow fetch response and observe a behavioral failure."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
TASK=Path(__file__).parent
SOURCE=ROOT/'tests/test_workflow_cards.py'
original=SOURCE.read_bytes()
needle=(b'            if (path !== detailPath && path !== `${detailPath}/results/0`) {\n'
        b'                return fallbackFetch(url, options);\n'
        b'            }\n')
assert original.count(needle)==1
mutant=original.replace(needle,b'')
node='tests/test_workflow_cards.py::test_workflow_fixture_preserves_refresh_when_unrelated_get_follows'
command=[sys.executable,str(TASK/'run_checks.py'),node,'--tb=short']
try:
    SOURCE.write_bytes(mutant)
    result=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
    output=result.stdout
    (TASK/'raw/mutation-global-fetch.log').write_text(output)
finally:
    SOURCE.write_bytes(original)
assert SOURCE.read_bytes()==original
assert result.returncode==1,output
assert 'AssertionError' in output and '1 failed' in output,output
# The intended assertion compares the unrelated response payload, not wording,
# timing, CSS, or a copied implementation.
assert "{'background': True}" in output,output
control=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
(TASK/'raw/mutation-restored.log').write_text(control.stdout)
assert control.returncode==0,control.stdout
proof=dict(node=node,mutation='remove the workflow endpoint filter, restoring global workflow response injection',
           intended_assertion='unrelated API returns its independent background payload',
           mutated_exit=result.returncode,restored_exit=control.returncode,
           mutated_summary=next(line for line in output.splitlines() if 'failed in' in line),
           restored_summary=next(line for line in control.stdout.splitlines() if 'passed in' in line),
           before_sha256=hashlib.sha256(original).hexdigest(),mutant_sha256=hashlib.sha256(mutant).hexdigest(),
           restored_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
(TASK/'mutation-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
