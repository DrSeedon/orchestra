import json,os,re,glob,sys
CL=glob.glob(os.path.expanduser("~/.claude/projects/*orchestra*/*.jsonl"))
CX=glob.glob(os.path.expanduser("~/.codex/sessions/2026/*/*/*.jsonl"))
out=[]
def ag_cl(p):
    d=os.path.basename(os.path.dirname(p))
    m=re.search(r'python-orchestra-worktrees-[^/]*?-([a-z0-9\-]+)$',d)
    return m.group(1) if m else "MAIN:"+d[-30:]
for p in CL:
    ag=ag_cl(p)
    for line in open(p,errors='replace'):
        if '"user"' not in line: continue
        try:o=json.loads(line)
        except Exception: continue
        if o.get("type")!="user": continue
        m=o.get("message") or {}
        c=m.get("content")
        txt=""
        if isinstance(c,str): txt=c
        elif isinstance(c,list):
            txt=" ".join(b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text")
        txt=txt.strip()
        if not txt or txt.startswith("<") or "tool_result" in txt[:40]: continue
        out.append((o.get("timestamp",""),ag,txt[:1500]))
for p in CX:
    cwd=None;ag=None
    for line in open(p,errors='replace'):
        if cwd is None and '"session_meta"' in line:
            try:o=json.loads(line);cwd=o["payload"].get("cwd","")
            except Exception: cwd=""
            if "/orchestra" not in (cwd or ""): break
            ag=os.path.basename(cwd); continue
        if '"user_message"' not in line and '"role":"user"' not in line: continue
        try:o=json.loads(line)
        except Exception: continue
        pl=o.get("payload") or {}
        txt=""
        if pl.get("type")=="user_message": txt=pl.get("message","")
        elif pl.get("type")=="message" and pl.get("role")=="user":
            cc=pl.get("content") or []
            txt=" ".join(b.get("text","") for b in cc if isinstance(b,dict) and "text" in b)
        txt=(txt or "").strip()
        if not txt or txt.startswith("<"): continue
        out.append((o.get("timestamp",""),ag or "?",txt[:1500]))
out.sort()
json.dump(out,open("/tmp/fcaudit/inbound.json","w"))
print("inbound msgs:",len(out))
