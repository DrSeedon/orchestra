import sqlite3, collections, statistics, json, re, pickle
src=open('docs/tasks/345/classify4_345.py').read()
exec(src.split("q = f'''select l.session_id")[0])
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
W14="datetime('now','-14 days')"
turns=collections.defaultdict(list)
for sid,ts,rt in c.execute(f"select session_id,ts,runtime from turn_usage where ts>={W14} order by session_id,ts"):
    turns[sid].append((ts,rt))
tools=collections.defaultdict(list)
for sid,ts,tn,cn in c.execute(f"select session_id,ts,tool_name,content from logs where type='tool' and ts>={W14} order by session_id,ts"):
    cn=cn or ''; m=NAME_RE.match(cn); name=norm_name(tn or (m.group(1) if m else ''))
    if name=='FileChange': continue
    tools[sid].append((ts,classify(name,cn)))
pos=collections.defaultdict(list); by_rt_pos=collections.defaultdict(lambda: collections.defaultdict(list))
for sid,tl in turns.items():
    tt=tools.get(sid,[]); idx=0; prev=None
    for ts,rt in tl:
        grp=[]
        while idx<len(tt) and tt[idx][0]<=ts:
            if prev is None or tt[idx][0]>prev: grp.append(tt[idx][1])
            idx+=1
        for k,cat in enumerate(grp):
            pos[cat].append(k+1); by_rt_pos[rt][cat].append(k+1)
        prev=ts
print('=== позиция вызова ВНУТРИ хода (1 = первый) ===')
print('чем ПОЗЖЕ вызов, тем больше контекста он перечитывает, тем он дороже\n')
allp=[p for v in pos.values() for p in v]
print(f'{"категория":14} {"n":>7} {"медиана":>8} {"среднее":>8}')
for cat,v in sorted(pos.items(), key=lambda x:-len(x[1])):
    print(f'  {cat:12} {len(v):7} {statistics.median(v):8.1f} {statistics.mean(v):8.1f}')
print(f'  {"ВСЕ":12} {len(allp):7} {statistics.median(allp):8.1f} {statistics.mean(allp):8.1f}')
print()
for rt in ('claude','codex'):
    d=by_rt_pos[rt]
    r=d.get('разведка',[]); w=d.get('работа',[])
    if not r or not w: continue
    print(f'  {rt}: разведка среднее место {statistics.mean(r):.1f} (n={len(r)}), работа {statistics.mean(w):.1f} (n={len(w)}), служебное {statistics.mean(d.get("служебное",[1])):.1f}')
