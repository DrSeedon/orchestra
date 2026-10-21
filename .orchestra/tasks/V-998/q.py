import pickle,sqlite3,bisect,math
rows,known=pickle.load(open("rows.pkl","rb"))
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro",uri=True)
tu=db.execute("select ts,quota_five_hour_pct,output_tokens,cache_create_tokens from turn_usage where runtime='claude' and ts>='2026-09-22' and quota_five_hour_pct is not null order by ts").fetchall()
def ep(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
J=sorted((ep(r[2]),r[5],r[7]) for r in rows if r[2]>='2026-09-22')
jt=[x[0] for x in J]
segs=[];cur=[tu[0]]
for r in tu[1:]:
    if r[1]<cur[-1][1]-0.5 or ep(r[0])-ep(cur[-1][0])>3600: segs.append(cur);cur=[r]
    else: cur.append(r)
segs.append(cur)
X1=[];X2=[];Y=[]
for s in segs:
    if len(s)<5: continue
    d=s[-1][1]-s[0][1]
    if d<3: continue
    t0,t1=ep(s[0][0]),ep(s[-1][0])
    a=bisect.bisect_right(jt,t0);b=bisect.bisect_right(jt,t1)
    jo=sum(x[1] for x in J[a:b])/1e6;jc=sum(x[2] for x in J[a:b])/1e6
    to=sum(r[2] for r in s[1:])/1e6;tc=sum(r[3] for r in s[1:])/1e6
    X1.append([tc,to]);X2.append([jc,jo]);Y.append(d)

def fit(X,Y):
    a=sum(x[0]*x[0] for x in X);b=sum(x[0]*x[1] for x in X);c=sum(x[1]*x[1] for x in X)
    u=sum(x[0]*y for x,y in zip(X,Y));v=sum(x[1]*y for x,y in zip(X,Y))
    det=a*c-b*b;k1=(u*c-v*b)/det;k2=(a*v-b*u)/det
    p=[k1*x[0]+k2*x[1] for x in X];m=sum(Y)/len(Y)
    r2=1-sum((y-q)**2 for y,q in zip(Y,p))/sum((y-m)**2 for y in Y)
    return k1,k2,r2,math.sqrt(sum((y-q)**2 for y,q in zip(Y,p))/len(Y))
print("windows",len(Y),"sum d",sum(Y))
for n,X in (("TU only",X1),("jsonl all",X2)):
    print(n,[round(v,3) for v in fit(X,Y)])
    print(" sum cc",round(sum(x[0] for x in X),1),"sum out",round(sum(x[1] for x in X),1))
k1,k2,_,_=fit(X1,Y)
res=[y-(k1*x[0]+k2*x[1]) for x,y in zip(X1,Y)]
un=[(b[0]-a[0]) for a,b in zip(X1,X2)]
n=len(res);mr=sum(res)/n;mu=sum(un)/n
cov=sum((r-mr)*(u-mu) for r,u in zip(res,un));
print("corr residual vs unseen cc(M)",round(cov/math.sqrt(sum((r-mr)**2 for r in res)*sum((u-mu)**2 for u in un)),3),"slope pp/M",round(cov/sum((u-mu)**2 for u in un),3))
# windows with unseen share >30%
hi=[(r,u) for r,u,x in zip(res,un,X1) if u>0.3*x[0] and u>5]
print("windows with big unseen",len(hi),"mean resid",round(sum(r for r,u in hi)/max(1,len(hi)),2),"overall rmse of resid", round(math.sqrt(sum(r*r for r in res)/n),2))
