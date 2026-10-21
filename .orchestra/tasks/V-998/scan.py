import json,glob,os,sqlite3,collections,sys
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro",uri=True)
known=set()
for sid,hist in db.execute("select session_id,session_id_history from sessions"):
    if sid: known.add(sid)
    try:
        for h in json.loads(hist or '[]'):
            known.add(h if isinstance(h,str) else h.get('session_id',''))
    except Exception: pass
tu_sess=set(r[0] for r in db.execute("select distinct session_id from turn_usage"))
print("known sdk ids",len(known))
rows=[]
for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    sid=os.path.basename(f)[:-6]
    seen={}
    for line in open(f,errors='ignore'):
        try: o=json.loads(line)
        except: continue
        m=o.get('message')
        if o.get('type')!='assistant' or not isinstance(m,dict) or 'usage' not in m: continue
        mid=m.get('id') or o.get('uuid')
        seen[mid]=(o.get('timestamp',''),m.get('model',''),m['usage'])
    if not seen: continue
    for mid,(ts,mod,u) in seen.items():
        rows.append((sid,os.path.basename(os.path.dirname(f)),ts,mod,u.get('input_tokens',0),u.get('output_tokens',0),u.get('cache_read_input_tokens',0),u.get('cache_creation_input_tokens',0)))
import pickle;pickle.dump((rows,known),open("rows.pkl","wb"))
print(len(rows),min(r[2] for r in rows),max(r[2] for r in rows))
