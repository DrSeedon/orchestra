import sqlite3, json, re, collections, sys
DB="/mnt/data/Projects/Python/orchestra/data/orchestra.db"
c=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
sess={r[0]:(r[1],r[2],r[3]) for r in c.execute("SELECT id,name,role,model FROM sessions")}
rows=list(c.execute("SELECT session_id,ts,type,content FROM logs WHERE type IN ('tool','tool_result','text','user_message') ORDER BY id"))
print("total rows",len(rows))

def parse_tool(content):
    m=re.match(r'^([A-Za-z_0-9]+):\s*(\{.*)$',content,re.S)
    if not m: return None,None
    name=m.group(1)
    try: args=json.loads(m.group(2))
    except Exception: args={}
    return name,args

# 1. tool frequency by role
freq=collections.Counter()
for sid,ts,t,content in rows:
    if t!='tool': continue
    nm,args=parse_tool(content)
    if not nm: continue
    role=sess.get(sid,("?","?","?"))[1]
    freq[(role,nm)]+=1
print("\n=== TOOL FREQ (full-cycle) ===")
for (role,nm),n in freq.most_common():
    if role=='full-cycle': print(f"{n:5d}  {nm}")
