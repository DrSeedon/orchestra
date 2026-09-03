import pickle, collections, statistics, sqlite3
s=open('/tmp/reg_345.py').read(); exec(s[s.index('def ols'):s.index('# накопленные вызовы')])
per_turn=pickle.load(open('/tmp/per_turn.pkl','rb'))
# добираем ok/stop_reason (в pkl их нет)
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True)
okmap={}
for sid,ts,ok in c.execute("select session_id,ts,ok from turn_usage where ts>=datetime('now','-14 days')"):
    okmap[(sid,ts)]=ok
bysid=collections.defaultdict(list)
for t in per_turn: bysid[t['sid']].append(t)
for sid,ts in bysid.items():
    ts.sort(key=lambda x:x['k']); acc=0
    for t in ts: t['prior']=acc; acc+=t['n_tools']; t['ok']=okmap.get((t['sid'],t['ts']),1)
print('=== чувствительность к фильтру ok=0 ===')
for rt in ('claude','codex'):
    allr=[t for t in per_turn if t['rt']==rt]
    okr =[t for t in allr if t['ok']==1]
    b1,r1,n1=ols(allr,'cost',['n_tools','prior'])
    b2,r2,n2=ols(okr ,'cost',['n_tools','prior'])
    print(f'  {rt}: ВСЕ ходы n={n1} b_own={b1[1]:.4f} R2={r1:.3f}  |  только ok=1 n={n2} b_own={b2[1]:.4f} R2={r2:.3f}')
    print(f'        отброшено {n1-n2} ходов ({100*(n1-n2)/n1:.1f}%), сдвиг наклона {100*(b2[1]-b1[1])/b1[1]:+.1f}%')
