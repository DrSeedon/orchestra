"""V-923 candidate selection. Rule A (multi-file) + random arm B, seed 923. Writes cand.json and per-candidate inputs."""
import json,random,subprocess
G="/home/kesha/orchestra/.git"; T=".orchestra/tasks/V-914/"
rows=[json.loads(l) for l in open(T+"index.jsonl")]
PIL=set("8bd9bd60 9947ae37 c3e66f16 2ee5279f baaa4858 f1eafe04 cfdb1d0e d987193b fa1b1355 23ea33d8 8dd5befc 69a88105 4b185fdc 3b84786d bf70e3ad 12ed3d3d 96192b40 f590cdd1 88682bef 8b6c8b50".split())
def sh(*a): return subprocess.run(a,capture_output=True,text=True).stdout
out=[]
for r in rows:
    if not r["f2p"] or r["commit"] in PIL: continue
    rd=r["red_reason"]
    if "ImportError" in rd or "has no attribute" in rd or "cannot import" in rd: continue
    ns=[l.split("\t") for l in sh("git","--git-dir="+G,"diff","--numstat",r["parent"],r["commit"],"--","app","scripts","pyproject.toml").split("\n") if l]
    r["app_files"]=len(ns); r["app_lines"]=sum(int(a)+int(b) for a,b,_ in ns if a!="-")
    r["main_file"]=max(ns,key=lambda x:(int(x[0])+int(x[1])) if x[0]!="-" else 0)[2] if ns else ""
    out.append(r)
A=[r for r in out if r["priv_names"]<=6 and r["mock_count"]<=12 and r["app_files"]>=2 and 15<=r["app_lines"]<=500]
ids={r["commit"] for r in A}
B=[r for r in out if r["priv_names"]<=4 and r["mock_count"]<=8 and r["commit"] not in ids]
rng=random.Random(923); rng.shuffle(A); rng.shuffle(B)
for i,r in enumerate(A): r["arm"]="A"; r["order"]=i
for i,r in enumerate(B): r["arm"]="B"; r["order"]=i
cand=A+B
json.dump(dict(pool_A=len(A),pool_B=len(B),cand=cand),open(".orchestra/tasks/V-923/cand.json","w"),ensure_ascii=False,indent=1)
for r in cand:
    d=f"/home/kesha/bench923/cand/{r['commit']}"; import os; os.makedirs(d,exist_ok=True)
    msg=sh("git","--git-dir="+G,"log","-1","--format=%B",r["commit"])
    ad=sh("git","--git-dir="+G,"diff",r["parent"],r["commit"],"--","app","scripts","pyproject.toml")
    td=sh("git","--git-dir="+G,"diff",r["parent"],r["commit"],"--",*r["test_files"])
    open(d+"/input.md","w").write(f"# Commit message\n{msg}\n\n# Main changed file\n{r['main_file']}\n\n# App diff (truncated to 14000 chars)\n```diff\n{ad[:14000]}\n```\n\n# Test diff (truncated to 14000 chars)\n```diff\n{td[:14000]}\n```\n\n# Red reason on parent\n{r['red_reason'][:400]}\n")
print(len(A),len(B),len(cand))
