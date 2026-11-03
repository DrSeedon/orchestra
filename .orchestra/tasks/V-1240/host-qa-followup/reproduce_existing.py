"""Bounded same-node old/new reproduction with identical controlled late GET."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[4];TASK=Path(__file__).parent
source=ROOT/'tests/test_workflow_cards.py';current=source.read_bytes()
old=(TASK/'raw/local-tests__test_workflow_cards.py.baseline').read_bytes()
node='tests/test_workflow_cards.py::test_dynamic_workflow_call_renders_detail_card_and_expands_answer'
results=[]
for label,content in [('old-observer',old),('fixed-observer',current)]:
    env=dict(os.environ);env['V1240_FORCE_LATE_WORKFLOW_GET']='1';env['V1240_PROBE_LABEL']=label
    try:
        source.write_bytes(content)
        command=[sys.executable,str(TASK/'run_checks.py'),node,'-p','workflow_probe','--tb=short']
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
        (TASK/f'raw/workflow-{label}.log').write_text(result.stdout)
    finally:
        source.write_bytes(current)
    results.append({'variant':label,'exit_code':result.returncode})
assert source.read_bytes()==current
assert results[0]['exit_code']==1 and results[1]['exit_code']==0,results
oldproof=json.loads((TASK/'raw/workflow-old-observer-probe.json').read_text())
assert oldproof['late_get_events'] and oldproof['late_get_events'][0]['rendered'] is True
assert oldproof['late_get_events'][0]['lastUrl'].endswith('/api/v1240-background-fixture')
newproof=json.loads((TASK/'raw/workflow-fixed-observer-probe.json').read_text())
assert newproof['late_get_events'] and '/api/bg/workflows/V-776-fixture' in newproof['late_get_events'][0]['requested']
proof={'same_test_node':node,'controlled_stimulus':'one unrelated GET after actual workflow refresh/render',
       'variants':results,'old_card_rendered':True,'old_last_url_overwritten':True,
       'fixed_detail_request_retained':True,'source_restored_sha256':hashlib.sha256(current).hexdigest(),
       'original_30000ms_wait_unchanged':True,'production_polling_changed':False}
(TASK/'same-node-repro-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
