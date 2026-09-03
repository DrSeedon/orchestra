"""Fit  points = a*Sol_tokens + b*Luna_tokens  over hourly buckets.
 b/a ~ 1/25 => pool tracks DOLLARS (Luna 25x cheaper on the pool too)
 b/a ~ 1    => pool tracks TOKENS (Luna no cheaper on the pool)
Non-negative least squares + bootstrap CI. No scipy: grid over the ratio.
"""
import sqlite3, collections, random, math
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
rows=db.execute("""SELECT ts, model, input_tokens, quota_primary_pct
                   FROM turn_usage WHERE runtime='codex' AND ts>='2026-08-16T07:26'
                   AND quota_primary_pct IS NOT NULL ORDER BY ts""").fetchall()
H=collections.defaultdict(lambda: {"l":0,"s":0,"p":[]})
for ts,model,inp,pct in rows:
    b=H[ts[:13]]
    if "luna" in model: b["l"]+=inp
    elif "sol" in model: b["s"]+=inp
    else: continue
    b["p"].append(pct)
prev=None; D=[]
for h in sorted(H):
    b=H[h]; cur=max(b["p"])
    if prev is not None and cur>prev and (b["l"]+b["s"])>0:
        D.append((b["s"]/1e6, b["l"]/1e6, cur-prev))
    prev=cur if prev is None else max(prev,cur)
print(f"hourly observations: {len(D)}   total points: {sum(d[2] for d in D):.0f}")
print(f"Sol Mtok: {sum(d[0] for d in D):.0f}   Luna Mtok: {sum(d[1] for d in D):.0f} "
      f"({sum(d[1] for d in D)/sum(d[0]+d[1] for d in D):.1%} of tokens)")

def fit(data):
    """grid over r=b/a; for each r, a = sum(y*x)/sum(x^2) with x = s + r*l"""
    best=None
    r=0.0
    while r<=1.5:
        num=sum(y*(s+r*l) for s,l,y in data)
        den=sum((s+r*l)**2 for s,l,y in data)
        if den>0:
            a=num/den
            ss=sum((y-a*(s+r*l))**2 for s,l,y in data)
            if best is None or ss<best[0]: best=(ss,r,a)
        r+=0.005
    return best[1], best[2]

r_hat,a_hat=fit(D)
print(f"\nbest fit: Luna weight / Sol weight = {r_hat:.3f}   (Sol: {1/a_hat:.1f} Mtok per point)")
print(f"  dollar-model predicts ratio 0.040 (=1/25)")
print(f"  token-model  predicts ratio 1.000")
random.seed(7)
boot=[]
for _ in range(600):
    samp=[random.choice(D) for _ in D]
    try: boot.append(fit(samp)[0])
    except Exception: pass
boot.sort()
print(f"  bootstrap 90% CI for ratio: [{boot[int(.05*len(boot))]:.3f}, {boot[int(.95*len(boot))]:.3f}]")
