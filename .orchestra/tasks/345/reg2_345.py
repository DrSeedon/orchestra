import pickle, collections, random, statistics
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


import pickle, collections, random, statistics
per_turn=pickle.load(open('/tmp/per_turn.pkl','rb'))
bysid=collections.defaultdict(list)
for t in per_turn: bysid[t['sid']].append(t)
for sid,ts in bysid.items():
    ts.sort(key=lambda x:x['k']); acc=0
    for t in ts: t['prior']=acc; acc+=t['n_tools']; t['n2']=t['n_tools']**2

for rt in ('claude','codex'):
    rows=[t for t in per_turn if t['rt']==rt]
    print(f'================ {rt} ================')
    # базовая линия: ходы БЕЗ вызовов
    z=[t['cost'] for t in rows if t['n_tools']==0]
    print(f'  ходов с 0 вызовов: {len(z)}, медиана стоимости ${statistics.median(z):.3f}, среднее ${statistics.mean(z):.3f}')
    b,r2,_=ols(rows,'cost',['n_tools','prior']); print(f'  M2 линейная:  b_own={b[1]:.4f}  R2={r2:.3f}')
    bq,r2q,_=ols(rows,'cost',['n_tools','n2','prior'])
    print(f'  M4 квадрат:   cost = {bq[0]:.3f} + {bq[1]:.4f}*n + {bq[2]:.6f}*n^2 + {bq[3]:.5f}*prior  R2={r2q:.3f}')
    # предельная цена на разных n
    for n in (5,15,30):
        print(f'      предельная цена {n}-го вызова: ${bq[1]+2*bq[2]*n:.4f}')
    # ФИКСИРОВАННЫЕ ЭФФЕКТЫ СЕССИИ: внутрисессионное центрирование
    fe=[]
    for sid,ts in bysid.items():
        ts2=[t for t in ts if t['rt']==rt]
        if len(ts2)<3: continue
        mc=statistics.mean([t['cost'] for t in ts2]); mn=statistics.mean([t['n_tools'] for t in ts2])
        mp=statistics.mean([t['prior'] for t in ts2])
        for t in ts2: fe.append(dict(cost=t['cost']-mc, n_tools=t['n_tools']-mn, prior=t['prior']-mp))
    bf,r2f,nf=ols(fe,'cost',['n_tools','prior'])
    print(f'  M5 внутри сессии (FE, сессии >=3 ходов, n={nf}): b_own={bf[1]:.4f}  b_prior={bf[2]:.5f}  R2={r2f:.3f}')
    # НЕГ.КОНТРОЛЬ 2: чужой предиктор — n_tools случайного ДРУГОГО хода того же рантайма
    random.seed(77); pool=[t['n_tools'] for t in rows]
    fake=[dict(t, n_tools=random.choice(pool)) for t in rows]
    bfk,r2fk,_=ols(fake,'cost',['n_tools','prior'])
    print(f'  НЕГ.КОНТРОЛЬ-2 (чужой n_tools): b_own={bfk[1]:.4f}  R2={r2fk:.3f}')
    print()
# длины сессий — честно
print('=== длины сессий в ходах (за окно) ===')
for rt in ('claude','codex'):
    L=sorted(len([t for t in v if t['rt']==rt]) for v in bysid.values() if any(t['rt']==rt for t in v))
    print(f'  {rt}: сессий {len(L)}, медиана {statistics.median(L):.0f}, среднее {statistics.mean(L):.1f}, p90 {L[int(.9*len(L))-1]}, max {max(L)}')
