"""Isolated Git probes of current subject resolver; no production mutation."""
import sys,subprocess,tempfile,json
from pathlib import Path
p=Path(__file__).resolve().parent;sys.path.insert(0,str(p.parents[2]))
from app.review_coverage import resolve_implementation_subject,production_snapshot
with tempfile.TemporaryDirectory(prefix='subject-probe-',dir=p) as d:
 def git(*args):
  r=subprocess.run(['git','-C',d,*args],capture_output=True,check=True);return r.stdout
 git('init','-b','master');git('config','user.name','receipt-probe');git('config','user.email','probe@invalid')
 Path(d,'README').write_text('base\n');git('add','.');git('commit','-m','base');base=git('rev-parse','HEAD').decode().strip()
 git('switch','-c','worker')
 Path(d,'app').mkdir();Path(d,'app/x.py').write_text('x = 1\n');git('add','.');git('commit','-m','production')
 for ref in ['main','master']:
  try:s=resolve_implementation_subject(d,ref);print('RESOLVE',ref,'OK',s['production_paths'])
  except ValueError as e:print('RESOLVE',ref,type(e).__name__,str(e))
 first=resolve_implementation_subject(d,'master')
 before=git('diff','--raw','--no-abbrev',base+'...HEAD')
 Path(d,'tests').mkdir();Path(d,'tests/test_x.py').write_text('assert False\n');git('add','.');git('commit','-m','unreviewed test change')
 second=production_snapshot(d,target_sha=base,worker_head=git('rev-parse','HEAD').decode().strip())
 print('UNREVIEWED_TEST_CHANGE',json.dumps({'production_identity_equal':first['production_diff_sha256']==second['production_diff_sha256'],'complete_raw_diff_equal':before==git('diff','--raw','--no-abbrev',base+'...HEAD')}))
 Path(d,'app/x.py').write_text('x = 2\n');git('add','.');git('commit','-m','unreviewed production change')
 third=production_snapshot(d,target_sha=base,worker_head=git('rev-parse','HEAD').decode().strip())
 print('UNREVIEWED_PRODUCTION_CHANGE_IDENTITY_EQUAL',second['production_diff_sha256']==third['production_diff_sha256'])
