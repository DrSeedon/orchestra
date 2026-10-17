import pickle,collections,bisect,datetime,re
res,sess,ars=pickle.load(open('/tmp/an/t2.pkl','rb'))
def T(s): return datetime.datetime.fromisoformat(s).timestamp()
# map auto-report deliveries by worker name
byname=collections.defaultdict(list)
for sid,i,ts,w in ars: byname[w].append(T(ts))
for w in byname: byname[w].sort()
W=[r for r in res if r['sid'] in sess and not sess[r['sid']][3]]  # not orchestrator
print('worker turns',len(W),'orch turns',len(res)-len(W))
cnt=collections.Counter()
matched=set()
for r in W:
    name=sess[r['sid']][0]; e=T(r['ts'])
    L=byname.get(name,[]); k=bisect.bisect_left(L,e-5)
    m = k<len(L) and L[k]<=e+600
    r['ar']=m
    if m: matched.add((name,L[k]))
    cat='explicit' if r['send'] else ('silent' if r['sil'] else 'neither')
    r['cat']=cat
    cnt[(r['ts'][:7],cat,m)]+=1
for k in sorted(cnt): print(k,cnt[k])
print('matched auto-report deliveries',len(matched),'of',len(ars))
tot=collections.Counter(r['cat'] for r in W); print(tot)
print('auto-reported turns',sum(r['ar'] for r in W))
# explicit+silent both
print('silent&send',sum(1 for r in W if r['sil'] and r['send']))
pickle.dump(W,open('/tmp/an/W.pkl','wb'))
