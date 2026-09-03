import sqlite3,re,json,collections
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
W="l.ts >= datetime('now','-14 days')"
NAME=re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*):\s')
norm=lambda n: re.split(r'[ `]',(n or '').strip(),1)[0]
q=f'''select l.session_id,l.ts,l.tool_name,l.content from logs l
      join sessions s on s.id=l.session_id where l.type='tool' and {W} order by l.session_id,l.ts'''
rows=[]
for sid,ts,tn,content in c.execute(q):
    content=content or ''
    m=NAME.match(content); name=norm(tn or (m.group(1) if m else ''))
    if name=='FileChange': continue
    rows.append((sid,ts,name,content))
nxt=collections.Counter(); nxt_same=collections.Counter(); limits=[]
def path_of(content,name):
    try: b=json.loads(content.split(':',1)[1])
    except Exception: return None,None
    if name in ('Read','read_file','ReadFile'): return (b.get('file_path') or b.get('path')), b
    for k in ('file_path','path'):
        if isinstance(b.get(k),str): return b[k], b
    return None,b
for i,(sid,ts,name,content) in enumerate(rows):
    if name not in ('Read','read_file','ReadFile'): continue
    p,b=path_of(content,name)
    if not isinstance(p,str) or not re.search(r'(CLAUDE|AGENTS)\.md$',p.strip()): continue
    limits.append(b.get('limit'))
    for j in range(i+1, min(i+4,len(rows))):
        if rows[j][0]!=sid: break
        nname=rows[j][2]; np,_=path_of(rows[j][3],nname)
        nxt[nname]+=1
        if isinstance(np,str) and np.strip()==p.strip(): nxt_same[nname]+=1
        break
tot=sum(nxt.values())
print(f'=== следующее действие после чтения CLAUDE.md (n={tot}) ===')
for k,v in nxt.most_common(10): print(f'  {v:4}  {100*v/tot:5.1f}%  {k}')
print()
print('=== из них по ТОМУ ЖЕ файлу ===')
for k,v in nxt_same.most_common(8): print(f'  {v:4}  {k}')
import statistics
ls=[l for l in limits if isinstance(l,int)]
print()
print(f'=== размер слайса: n={len(ls)} медиана={statistics.median(ls)} среднее={statistics.mean(ls):.1f} max={max(ls)} сумма строк={sum(ls)}')
