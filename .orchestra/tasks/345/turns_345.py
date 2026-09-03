import sqlite3, collections
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
W14="datetime('now','-14 days')"
print('=== санитария turn_usage за 14 дней ===')
for r in c.execute(f"select ok, stop_reason, count(*) from turn_usage where ts>={W14} group by ok,stop_reason order by 3 desc limit 8"):
    print(f'  ok={r[0]} stop={str(r[1])[:28]:28} n={r[2]}')
print()
# окна ходов
turns=collections.defaultdict(list)
for sid,ts,rt,cost,i,o,cr,cc in c.execute(f'''select session_id,ts,runtime,cost_usd,input_tokens,output_tokens,
        cache_read_tokens,cache_create_tokens from turn_usage where ts>={W14} order by session_id,ts'''):
    turns[sid].append(dict(ts=ts,rt=rt,cost=cost or 0,inp=i or 0,out=o or 0,cr=cr or 0,cc=cc or 0))
# инструменты по времени
tools=collections.defaultdict(list)
for sid,ts in c.execute(f"select session_id,ts from logs where type='tool' and ts>={W14} order by session_id,ts"):
    tools[sid].append(ts)
attributed=0; orphan_before=0; total_tools=sum(len(v) for v in tools.values())
per_turn=[]
for sid, tl in turns.items():
    tt=tools.get(sid,[])
    prev=None; idx=0
    for k,t in enumerate(tl):
        lo=prev; hi=t['ts']
        n=0
        while idx<len(tt) and tt[idx]<=hi:
            if lo is None or tt[idx]>lo: n+=1; attributed+=1
            else: orphan_before+=1
            idx+=1
        t['n_tools']=n; t['k']=k; t['sid']=sid
        per_turn.append(t); prev=hi
    orphan_before += len(tt)-idx   # хвост после последнего хода
print(f'=== покрытие привязки ===')
print(f'  всего tool-строк:      {total_tools}')
print(f'  привязано к ходам:     {attributed} ({100*attributed/total_tools:.1f}%)')
print(f'  вне окон (сироты):     {total_tools-attributed} ({100*(total_tools-attributed)/total_tools:.1f}%)')
print(f'  ходов:                 {len(per_turn)}')
import pickle; pickle.dump(per_turn, open('/tmp/per_turn.pkl','wb'))
byrt=collections.Counter(t['rt'] for t in per_turn)
print('  ходов по рантайму:', dict(byrt))
zero=sum(1 for t in per_turn if t['n_tools']==0)
print(f'  ходов с 0 вызовов: {zero} ({100*zero/len(per_turn):.1f}%)')
