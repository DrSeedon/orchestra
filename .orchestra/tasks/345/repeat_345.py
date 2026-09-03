import sqlite3,re,json,collections
src=open('/tmp/classify4_345.py').read(); exec(src.split("q = f'''select l.session_id")[0])
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
W="l.ts >= datetime('now','-14 days')"
q=f'''select l.session_id,l.ts,l.tool_name,l.content,s.backend_type from logs l
      join sessions s on s.id=l.session_id where l.type='tool' and {W} order by l.session_id,l.ts'''
seen=collections.defaultdict(set); rep=collections.Counter(); rd=collections.Counter()
tot=0; sess_with_reads=set(); depth=collections.Counter()
percount=collections.defaultdict(collections.Counter)
for sid,ts,tn,content,bt in c.execute(q):
    content=content or ''
    m=NAME_RE.match(content); name=norm_name(tn or (m.group(1) if m else '<U>'))
    if name=='FileChange': continue
    tot+=1
    if name not in ('Read','read_file','ReadFile'): continue
    try: body=json.loads(content.split(':',1)[1])
    except Exception: continue
    p=body.get('file_path') or body.get('path')
    if not isinstance(p,str) or not p.strip(): continue
    p=p.strip().strip('"\'')
    rd[bt]+=1; sess_with_reads.add(sid); percount[sid][p]+=1
    if p in seen[sid]: rep[bt]+=1
    else: seen[sid].add(p)
R=sum(rd.values()); P=sum(rep.values())
print(f'знаменатель (все обращения агента): {tot}')
print(f'обращений тулом Read/read_file:      {R}  ({100*R/tot:.1f}% знаменателя)')
print(f'  из них ПОВТОРНЫХ чтений того же пути в той же сессии: {P}  ({100*P/R:.1f}% чтений, {100*P/tot:.2f}% знаменателя)')
for bt in rd: print(f'    {bt:8} чтений={rd[bt]:5}  повторов={rep[bt]:5}  ({100*rep[bt]/rd[bt]:.1f}%)')
print(f'  сессий с чтениями: {len(sess_with_reads)}')
worst=sorted(((cnt,sid,p) for sid,cc in percount.items() for p,cnt in cc.items()),reverse=True)[:5]
print('  самые перечитываемые файлы (раз, сессия):')
for cnt,sid,p in worst: print(f'    {cnt:3}x  {p[-70:]}')
