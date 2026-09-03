import pickle, collections, random, math, statistics
per_turn=pickle.load(open('/tmp/per_turn.pkl','rb'))

def ols(rows, ycol, xcols):
    """OLS без numpy: нормальные уравнения + гаусс. rows=list[dict]."""
    n=len(rows); k=len(xcols)+1
    X=[[1.0]+[float(r[c]) for c in xcols] for r in rows]
    y=[float(r[ycol]) for r in rows]
    XtX=[[sum(X[i][a]*X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    Xty=[sum(X[i][a]*y[i] for i in range(n)) for a in range(k)]
    M=[XtX[a][:]+[Xty[a]] for a in range(k)]
    for col in range(k):
        p=max(range(col,k), key=lambda r: abs(M[r][col]))
        if abs(M[p][col])<1e-12: return None
        M[col],M[p]=M[p],M[col]
        pv=M[col][col]
        M[col]=[v/pv for v in M[col]]
        for r in range(k):
            if r!=col and M[r][col]!=0:
                f=M[r][col]; M[r]=[a-f*b for a,b in zip(M[r],M[col])]
    beta=[M[a][k] for a in range(k)]
    yb=sum(y)/n
    ss_tot=sum((v-yb)**2 for v in y)
    pred=[sum(beta[a]*X[i][a] for a in range(k)) for i in range(n)]
    ss_res=sum((y[i]-pred[i])**2 for i in range(n))
    r2=1-ss_res/ss_tot if ss_tot>0 else float('nan')
    return beta, r2, n

# накопленные вызовы ДО текущего хода в той же сессии
bysid=collections.defaultdict(list)
for t in per_turn: bysid[t['sid']].append(t)
for sid,ts in bysid.items():
    ts.sort(key=lambda x:x['k']); acc=0
    for t in ts: t['prior']=acc; acc+=t['n_tools']

print('ЗНАМЕНАТЕЛЬ: ходы turn_usage за 14 дней с привязанными по времени tool-вызовами.')
print('Фильтр: без ok=0 (оборванные/ошибочные ходы) — они платные, но обрыв рвёт связь «вызовы→стоимость».')
print()
for rt in ('claude','codex'):
    rows=[t for t in per_turn if t['rt']==rt]
    print(f'================ {rt}  (ходов {len(rows)}) ================')
    med=statistics.median([t['n_tools'] for t in rows])
    print(f'  вызовов на ход: медиана {med}, среднее {statistics.mean([t["n_tools"] for t in rows]):.1f}')
    print(f'  стоимость хода: медиана ${statistics.median([t["cost"] for t in rows]):.3f}')
    # M1: только свои вызовы
    b,r2,n=ols(rows,'cost',['n_tools'])
    print(f'  M1  cost = {b[0]:.4f} + {b[1]:.4f}*n_tools                      R2={r2:.3f}')
    # M2: свои + накопленные (два канала)
    b,r2,n=ols(rows,'cost',['n_tools','prior'])
    print(f'  M2  cost = {b[0]:.4f} + {b[1]:.4f}*n_tools + {b[2]:.5f}*prior   R2={r2:.3f}')
    own,carry=b[1],b[2]
    # M3: канал контекста отдельно — cache_read как исход
    b3,r23,_=ols(rows,'cr',['n_tools','prior'])
    print(f'  M3  cache_read = {b3[0]:,.0f} + {b3[1]:,.0f}*n_tools + {b3[2]:,.0f}*prior  R2={r23:.3f}')
    # средняя длина сессии в ходах -> во сколько ходов «доедет» контекст
    lens=[len(v) for v in bysid.values() if v and v[0]['rt']==rt]
    ml=statistics.median(lens)
    print(f'  медиана длины сессии: {ml:.0f} ходов -> один вызов тащится в ~{ml/2:.0f} последующих ходов')
    print(f'  ПОЛНАЯ цена вызова = свой {own:.4f} + перенос {carry:.5f}*{ml/2:.0f} = ${own+carry*ml/2:.4f}')
    # НЕГАТИВНЫЙ КОНТРОЛЬ: перемешать n_tools внутри сессии
    random.seed(345); sl=[]
    for sid,ts in bysid.items():
        if not ts or ts[0]['rt']!=rt: continue
        vals=[t['n_tools'] for t in ts]; random.shuffle(vals)
        for t,v in zip(ts,vals): sl.append(dict(t, n_tools=v))
    bp,r2p,_=ols(sl,'cost',['n_tools','prior'])
    print(f'  НЕГ.КОНТРОЛЬ (n_tools перемешан внутри сессии):')
    print(f'      cost = {bp[0]:.4f} + {bp[1]:.4f}*n_tools + {bp[2]:.5f}*prior  R2={r2p:.3f}')
    print(f'      наклон свой: {b[1]:.4f} -> {bp[1]:.4f}  ({100*bp[1]/b[1]:.0f}% от настоящего)')
    print()
