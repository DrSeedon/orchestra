import sqlite3,re,json,collections,os
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
W="l.ts >= datetime('now','-14 days')"
NAME=re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*):\s'); norm=lambda n: re.split(r'[ `]',(n or '').strip(),1)[0]
q=f'''select l.session_id,l.ts,l.tool_name,l.content from logs l join sessions s on s.id=l.session_id
      where l.type='tool' and {W} order by l.session_id,l.ts'''
rows=[(sid,ts,norm(tn or (NAME.match(cn or '').group(1) if NAME.match(cn or '') else '')),cn or '')
      for sid,ts,tn,cn in c.execute(q)]
seen=collections.defaultdict(set); rep=[]
for i,(sid,ts,name,cn) in enumerate(rows):
    if name not in ('Read','read_file','ReadFile'): continue
    try: b=json.loads(cn.split(':',1)[1])
    except Exception: continue
    p=b.get('file_path') or b.get('path')
    if not isinstance(p,str) or not p.strip(): continue
    p=p.strip().strip('"\'')
    if p in seen[sid]: rep.append((i,sid,p,b))
    else: seen[sid].add(p)
cache={}; tot=0; missing=0; got=0
for i,sid,p,b in rep:
    if p not in cache:
        try: cache[p]=open(p,'rb').read().split(b'\n')
        except Exception: cache[p]=None
    L=cache[p]
    if L is None: missing+=1; continue
    o=b.get('offset') or 1; lim=b.get('limit') or len(L)
    seg=L[max(0,o-1):max(0,o-1)+lim]
    tot+=sum(len(x)+1 for x in seg); got+=1
print(f'повторных чтений: {len(rep)}; файл найден на диске у {got}, отсутствует у {missing}')
print(f'суммарно прочитано (по найденным): {tot} байт = {tot/1024:.0f} КБ')
est_tok=tot/4.0   # смешанный код+кириллица, консервативно 4 байта/токен
print(f'оценка токенов (~4 Б/ток, консервативно): {est_tok:,.0f}')
print(f'цена как fresh input у opus5 ($5/Mtok): ${est_tok/1e6*5:.2f}')
print(f'доля от расхода claude за 14 дней ($4285): {100*est_tok/1e6*5/4285:.4f}%')
