"""Verify the fixed evidence and numerical solver without provider calls."""
import gzip,hashlib,importlib.util,json,math,pathlib,re,runpy,sys
P=pathlib.Path(__file__).resolve().parent
raw=gzip.open(P/'telemetry.json.gz','rb').read();meta=json.loads((P/'extraction.json').read_text())
assert hashlib.sha256(raw).hexdigest()==meta['uncompressed_sha256']
D=json.loads(raw);assert len(D['turns'])==meta['turns'] and len(D['snapshots'])==meta['snapshots']
# Read only definitions to validate the analytical solver without repeating the full run.
src=(P/'analyze.py').read_text();ns={};exec(src[src.index('def solve('):src.index('def intervals(')],{'math':math,'st':__import__('statistics'),'itertools':__import__('itertools')},ns)
# solve() is an independent linear-system check; QR below checks real-data OLS.
a=[[4.,1.,2.],[1.,3.,0.],[2.,0.,5.]];want=[2.,-1.,3.];b=[sum(x*y for x,y in zip(row,want)) for row in a]
assert max(abs(x-y) for x,y in zip(ns['solve'](a,b),want))<1e-10
import csv
rows=list(csv.DictReader((P/'intervals.csv').open()));K=['input_tokens','cache_read_tokens','cache_create_tokens','output_tokens']
rows=[r for r in rows if int(r['n']) and not int(r['haiku']) and sum(float(r[k]) for k in K)>0]
X=[[float(r[k]) for r in rows] for k in K];y=[float(r['delta']) for r in rows]
# Modified Gram-Schmidt QR, an independent algorithm from normal equations.
Q=[];R=[[0.]*4 for _ in range(4)]
for j,col in enumerate(X):
 v=col[:]
 for i,q in enumerate(Q):
  R[i][j]=sum(x*z for x,z in zip(q,v));v=[z-R[i][j]*x for z,x in zip(v,q)]
 R[j][j]=math.sqrt(sum(z*z for z in v));Q.append([z/R[j][j] for z in v])
c=[sum(x*z for x,z in zip(q,y)) for q in Q];beta=[0.]*4
for i in range(3,-1,-1):beta[i]=(c[i]-sum(R[i][j]*beta[j] for j in range(i+1,4)))/R[i][i]
expected=json.loads((P/'regression.json').read_text())['3h_shift0']['ols']['coef']
assert max(abs(a-b) for a,b in zip(beta,expected))<1e-9
sys.path.insert(0,str(P.parents[2]))
from app.secret_mask import mask_secrets
import app.secret_mask
for p in P.iterdir():
 if p.suffix in ['.gz','.json','.log','.csv']:
  text=gzip.open(p,'rt').read() if p.suffix=='.gz' else p.read_text()
  assert mask_secrets(text)==text, f'secret-shaped content: {p.name}'
for p in [P/'research.md',P.parents[1]/'kb'/'token-efficiency.md']:
 for rel in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if not rel.startswith(('http:','https:')):assert (p.parent/rel).exists(),rel
print('PASS frozen extraction SHA-256 and counts')
print('PASS linear solver synthetic known solution')
print('PASS independent QR matches main OLS; maximum coefficient difference',max(abs(a-b) for a,b in zip(beta,expected)))
print('PASS numerical raw artifacts secret-shape filter; module',app.secret_mask.__file__)
print('PASS local report and KB links')
