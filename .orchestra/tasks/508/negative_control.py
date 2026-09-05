"""Offline candidate predicate; evaluates frozen read-only live metadata, never authorizes a merge."""
import json,sys,collections
from pathlib import Path
p=Path(__file__).resolve().parent;sys.path.insert(0,str(p.parents[2]))
from app.review_coverage import _reviewed_receipt,REVIEW_AUTHOR_OUTCOMES
x=json.loads((p/'sample.json').read_text());rs=x['receipts']
# Proposed subject identity only: same repository + nonempty raw production diff + exact paths.
# Does not claim full review context equivalence, or transfer skip/unavailable decisions.
def subject(r,s):
 return (r['scope']==s['scope'] and bool(s['production_diff_sha256']) and r['production_diff_sha256']==s['production_diff_sha256'] and r['production_paths_json']==s['production_paths_json'])
def reviewed(r,s):
 return subject(r,s) and _reviewed_receipt(r) and r['author_outcome'] in REVIEW_AUTHOR_OUTCOMES and bool(r['completed_at']) and r['completed_at']<=x['end']
subjects=[r for r in rs if r['subject_kind']=='implementation' and r['production_diff_sha256']]
# Label by mechanism: task-run or explicit skip never performed model review IN THIS RECEIPT.
negative=[r for r in rs if r['subject_kind']=='task_run' or r['coverage_outcome']=='skipped']
print('WINDOW',x['start'],x['end'])
print('SUBJECTS',len(subjects),'NEGATIVE_RECEIPTS',len(negative),'PAIRS',len(subjects)*len(negative))
print('NEGATIVE_CLASSES',dict(collections.Counter((r['subject_kind'],r['coverage_outcome']) for r in negative)))
print('IDENTITY_ONLY_FALSE_REVIEW_ADMISSIONS',sum(subject(r,s) for r in negative for s in subjects))
print('CANDIDATE_FALSE_REVIEW_ADMISSIONS',sum(reviewed(r,s) for r in negative for s in subjects))
positive=[r for r in subjects if _reviewed_receipt(r) and r['author_outcome'] in REVIEW_AUTHOR_OUTCOMES]
print('POSITIVE_SELF',len(positive),'ADMITTED',sum(reviewed(r,r) for r in positive))
print('CROSS_SESSION_TASK_MATCHES',sum(reviewed(r,s) for r in rs for s in subjects if (r['session_id'],r['task_id'])!=(s['session_id'],s['task_id'])))
# Adversarial, unreviewed candidate snapshots, synthetic mutation of metadata (NOT Git execution).
mutated=[]
for s in positive:
 for key,val in [('production_diff_sha256','0'*64),('production_paths_json','["app/unreviewed.py"]'),('scope',s['scope']+'/unreviewed')]:
  t=dict(s);t[key]=val;mutated.append(t)
print('SYNTHETIC_UNREVIEWED_SUBJECTS',len(mutated),'FALSE_ADMISSIONS',sum(any(reviewed(r,s) for r in rs) for s in mutated))
for r in negative:
 if any(subject(r,s) for s in subjects):
  print('IDENTITY_ONLY_COUNTEREXAMPLE',r['receipt_id'],r['task_id'],r['coverage_outcome'],r['production_diff_sha256'])
  break
print('LIMIT: no-review label applies to receipt, not proof that the same change was never reviewed elsewhere; no causal live rollout, no artifact semantic oracle.')

assert len(negative) > 0 and len(positive) > 0
assert sum(subject(r,s) for r in negative for s in subjects) > 0, "identity-only control no longer exposes false reviewed claims"
assert not any(reviewed(r,s) for r in negative for s in subjects), "unreviewed receipt admitted as reviewed"
assert all(reviewed(r,r) for r in positive), "eligible positive rejected"
assert not any(reviewed(r,s) for r in rs for s in mutated), "unreviewed subject mutation admitted"
