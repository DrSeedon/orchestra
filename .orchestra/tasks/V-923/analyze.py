import json,math,collections
r=[json.loads(l) for l in open("runs.jsonl")]
T=json.load(open("tasks.json")); C={json.loads(l)["task"]:json.loads(l) for l in open("control.jsonl")}
def wilson(k,n,z=1.96):
    if n==0: return (0,1)
    p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return (max(0,c-h),min(1,c+h))
by=collections.defaultdict(list)
for x in r: by[x["task"]].append(x)
rows=[]
for t in T["tasks"]:
    xs=by[t["id"]]; ed=[x for x in xs if x["run_ok"] and not x["no_edit"]]
    k=sum(x["accepted"] for x in ed); n=len(ed); lo,hi=wilson(k,n)
    stop="ceiling" if n==3 and k==3 else "floor" if n==3 and k==0 else "full"
    if n<3: stop="incomplete"
    ctl=C[t["id"]]
    window = "in30-60" if n>=10 and 0.3<=k/n<=0.6 else ("near" if n>=10 and lo<=0.6 and hi>=0.3 and 0.25<=k/n<=0.7 else "")
    t.update(attempts=len(xs),n_edit=n,accepted=k,no_edit=sum(x["no_edit"] for x in xs),rate=round(k/n,3) if n else None,ci95=[round(lo,3),round(hi,3)],
      stop=stop,paid_tokens_total=sum(x["paid_tokens"] for x in xs),paid_tokens_mean=round(sum(x["paid_tokens"] for x in xs)/len(xs)),
      contamination_flagged=sum(x["contamination_flag"] for x in xs),control=dict(parent_red=ctl["parent_red"],reference_green=ctl["reference_green"]),calibration=window)
    rows.append(t)
json.dump(T,open("tasks.json","w"),ensure_ascii=False,indent=1)
print("id  arm k/n  ci  stop paid_mean noedit flag")
for t in rows: print(t["id"],t["arm"],f'{t["accepted"]}/{t["n_edit"]}',t["ci95"],t["stop"],t["paid_tokens_mean"],t["no_edit"],t["contamination_flagged"],t["calibration"])
tot=sum(x["paid_tokens"] for x in r); print("runs",len(r),"paid",tot,"mean",tot//len(r),"usd_api_eq",round(sum(x["cost_usd_api_equiv"] or 0 for x in r),2),"sec_mean",round(sum(x["seconds"] for x in r)/len(r),1))
for arm in "AB":
    s=[t for t in rows if t["arm"]==arm]; print(arm,len(s),"tasks; first-3 mean rate",round(sum(sum(1 for x in by[t["id"]] if x["accepted"]) for t in s)/sum(len(by[t["id"]]) for t in s),3),
      collections.Counter(t["stop"] for t in s))
