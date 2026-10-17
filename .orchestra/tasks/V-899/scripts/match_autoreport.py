import pickle,collections,bisect,datetime
res,sess,ars=pickle.load(open('/tmp/an/t2.pkl','rb'))
W=pickle.load(open('/tmp/an/W.pkl','rb'))
def T(s): return datetime.datetime.fromisoformat(s).timestamp()
byname=collections.defaultdict(list)
for r in W: byname[sess[r['sid']][0]].append((T(r['ts']),r))
for n in byname: byname[n].sort(key=lambda x:x[0])
used=set(); cat=collections.Counter(); unm=0; lag=[]
for sid,i,ts,w in sorted(ars,key=lambda a:a[1]):
    d=T(ts); L=byname.get(w,[]); ks=[x[0] for x in L]
    k=bisect.bisect_right(ks,d+5)-1
    best=None
    while k>=0 and d-ks[k]<=300:
        if id(L[k][1]) not in used: best=L[k][1]; break
        k-=1
    if best is None: unm+=1; continue
    used.add(id(best)); cat[best['cat']]+=1; lag.append(d-T(best['ts']))
print('one-to-one: deliveries',len(ars),'matched',len(used),'unmatched',unm,dict(cat))
import statistics; print('lag median',statistics.median(lag))
tk=collections.Counter()
for r in W:
    t=r['trig']; kind=(t[0],t[1]) if t else ('none','')
    tk[(kind,r['cat'], id(r) in used)]+=1
for k,v in sorted(tk.items(),key=lambda x:-x[1])[:40]: print(v,k)
pickle.dump(used and [r for r in W if id(r) in used],open('/tmp/an/AR.pkl','wb'))
