"""Verify reviewer blocking #1: is post-compaction re-reading elevated vs a control group?"""
import json, glob, os, re, collections
ROOT=os.path.expanduser("~/.codex/sessions")
PATH_RE=re.compile(r"[A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+\.(?:py|md|js|toml|yaml|yml|json|sql|html|css|txt|sh|rs)")
agg=collections.Counter()
for path in sorted(glob.glob(os.path.join(ROOT,"2026/08/*/*.jsonl"))):
    seq=[]; pend={}
    for line in open(path,errors="replace"):
        if '"compacted"' not in line and '"custom_tool_call' not in line and '"function_call' not in line:
            continue
        try: o=json.loads(line)
        except Exception: continue
        t=o.get("type"); p=o.get("payload") or {}
        if t=="compacted": seq.append(("comp",None))
        elif t=="response_item":
            pt=p.get("type")
            if pt in ("custom_tool_call","function_call"):
                inp=p.get("input") or p.get("arguments") or ""
                if not isinstance(inp,str): inp=json.dumps(inp,ensure_ascii=False)
                pend[p.get("call_id")]=set(PATH_RE.findall(inp[:20000]))
            elif pt in ("custom_tool_call_output","function_call_output"):
                out=p.get("output")
                n=sum(len(x.get("text","")) for x in out if isinstance(x,dict)) if isinstance(out,list) else (len(out) if isinstance(out,str) else 0)
                seq.append(("toolout",{"paths":pend.pop(p.get("call_id"),set()),"tokens":n//4}))
    comps=[i for i,(k,_) in enumerate(seq) if k=="comp"]
    seen=set()
    for i,(k,d) in enumerate(seq):
        if k!="toolout": continue
        if not comps:            seg="nocomp"      # control: sessions that never compacted
        elif any(c<i for c in comps): seg="post_comp"
        else:                    seg="precomp"     # control: same sessions, before 1st compaction
        agg[seg+"_tok"]+=d["tokens"]
        if d["paths"] & seen: agg[seg+"_rep"]+=d["tokens"]
        seen|=d["paths"]
for s in ("post_comp","precomp","nocomp"):
    tok,rep=agg[s+"_tok"],agg[s+"_rep"]
    print(f"{s:10s} tool-out tokens={tok:12,d}  repeat={rep:12,d}  share={rep/max(1,tok):6.1%}")
