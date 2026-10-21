import pickle,sqlite3,collections,re
rows,known=pickle.load(open("rows.pkl","rb"))
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro",uri=True)
lo,hi='2026-10-07','2026-10-21T12'
J=collections.defaultdict(lambda:[0,0,set()])
for r in rows:
    if lo<=r[2]<hi:
        k=r[1]
        k=re.sub(r'^-home-kesha-orchestra-worktrees.*','WT',k)
        k=re.sub(r'^-home-kesha-orchestra-data.*','orch-data(bench)',k)
        k=re.sub(r'^-tmp.*','tmp',k); k=re.sub(r'^-home-kesha-bench.*','bench',k)
        J[k][0]+=r[5];J[k][1]+=r[7];J[k][2].add(r[0])
for k,v in sorted(J.items(),key=lambda kv:-kv[1][0])[:14]: print(k[:50],len(v[2]),round(v[0]/1e6,2),round(v[1]/1e6,1))
print("tot",sum(v[0] for v in J.values())/1e6,sum(v[1] for v in J.values())/1e6)
q=db.execute("""select case when s.cwd like '%worktrees%' then 'WT' when s.cwd like '%orchestra/data%' then 'data' else coalesce(s.cwd,'(no session row)') end k,count(distinct t.session_id),sum(t.output_tokens),sum(t.cache_create_tokens) from turn_usage t left join sessions s on s.id=t.session_id where t.runtime='claude' and t.ts>=? and t.ts<? group by 1 order by 3 desc""",(lo,hi)).fetchall()
for k,n,o,c in q: print("TU",k,n,round(o/1e6,2),round(c/1e6,1))
