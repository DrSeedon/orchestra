import re, sys, itertools
from pathlib import Path
root = Path(".orchestra/pipelines/default/prompts")
files = sorted(p for p in root.rglob("*.md") if "skills" not in p.parts)
def sents(text):
    out=[]
    for i,line in enumerate(text.splitlines(),1):
        s=line.strip()
        if not s or s.startswith(("#","```","|","<")): continue
        for part in re.split(r"(?<=[.!?])\s+", s.lstrip("-* ")):
            part=re.sub(r"[`*_]","",part).strip().lower()
            part=re.sub(r"\s+"," ",part)
            if len(part)>=45: out.append((i,part))
    return out
data={f:sents(f.read_text()) for f in files}
def toks(s): return set(re.findall(r"[a-zа-я0-9]+", s))
seen=set()
for (fa,sa),(fb,sb) in itertools.combinations(data.items(),2):
    for la,a in sa:
        ta=toks(a)
        for lb,b in sb:
            tb=toks(b)
            if not ta or not tb: continue
            j=len(ta&tb)/len(ta|tb)
            if j>=0.5:
                key=(str(fa),la,str(fb),lb)
                if key in seen: continue
                seen.add(key)
                print(f"J={j:.2f}\n  {fa.relative_to(root)}:{la}  {a[:130]}\n  {fb.relative_to(root)}:{lb}  {b[:130]}\n")
