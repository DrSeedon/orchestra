import json, os, re, glob, sys, collections
CL = glob.glob(os.path.expanduser("~/.claude/projects/*orchestra*/*.jsonl"))
CX = glob.glob(os.path.expanduser("~/.codex/sessions/2026/*/*/*.jsonl"))
events=[]  # (ts, agent, tool, argsjson)

def agent_from_cl(path):
    d=os.path.basename(os.path.dirname(path))
    m=re.search(r'python-orchestra-worktrees-[^/]*?-([a-z0-9\-]+)$', d)
    if m: return m.group(1)
    return "MAIN:"+d[-30:]

for p in CL:
    ag=agent_from_cl(p)
    try:
        for line in open(p, errors='replace'):
            if '"tool_use"' not in line: continue
            try: o=json.loads(line)
            except Exception: continue
            msg=o.get("message") or {}
            for b in (msg.get("content") or []):
                if isinstance(b,dict) and b.get("type")=="tool_use":
                    events.append((o.get("timestamp",""),ag,b.get("name",""),json.dumps(b.get("input",{}),ensure_ascii=False)))
    except Exception as e: print("ERR",p,e,file=sys.stderr)

for p in CX:
    cwd=None; ag=None
    try:
        for line in open(p, errors='replace'):
            if cwd is None and '"session_meta"' in line:
                try:
                    o=json.loads(line); cwd=o["payload"].get("cwd","")
                except Exception: cwd=""
                if "/orchestra" not in (cwd or ""): break
                ag=os.path.basename(cwd)
                continue
            if '"function_call"' not in line: continue
            try: o=json.loads(line)
            except Exception: continue
            pl=o.get("payload") or {}
            if pl.get("type")!="function_call": continue
            events.append((o.get("timestamp",""),ag or "?",pl.get("name",""),pl.get("arguments","")))
    except Exception as e: print("ERR",p,e,file=sys.stderr)

events.sort(key=lambda x:x[0])
print("events:",len(events),"agents:",len(set(e[1] for e in events)))
json.dump(events,open("/tmp/fcaudit/events.json","w"))
