"""Does the Codex weekly pool charge by DOLLARS (model-weighted) or by TOKENS (flat)?
Discriminator: group hours by Luna token share. Luna is 25x cheaper per token in $.
 - pool ~ dollars  => $/point stays flat, tokens/point RISES in Luna-heavy hours
 - pool ~ tokens   => tokens/point stays flat, $/point FALLS in Luna-heavy hours
"""
import sqlite3, collections
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
rows=db.execute("""SELECT ts, model, cost_usd, input_tokens, quota_primary_pct
                   FROM turn_usage WHERE runtime='codex' AND ts>='2026-08-16T07:26'
                   AND quota_primary_pct IS NOT NULL ORDER BY ts""").fetchall()
# hourly buckets
H=collections.defaultdict(lambda: {"luna":0,"sol":0,"usd":0.0,"pcts":[]})
for ts,model,usd,inp,pct in rows:
    h=ts[:13]; b=H[h]
    if "luna" in model: b["luna"]+=inp
    elif "sol" in model: b["sol"]+=inp
    else: continue
    b["usd"]+=usd or 0.0
    b["pcts"].append(pct)
hours=sorted(H)
# delta points per hour = max(pct) of this hour - max(pct) of previous hour; drop resets/negatives
prev=None; recs=[]
for h in hours:
    b=H[h]; cur=max(b["pcts"])
    if prev is not None and cur>=prev:
        d=cur-prev
        tok=b["luna"]+b["sol"]
        if d>0 and tok>0:
            recs.append({"h":h,"d":d,"tok":tok,"usd":b["usd"],
                         "lshare":b["luna"]/tok})
    prev=max(prev,cur) if prev is not None else cur
G=collections.defaultdict(lambda: {"d":0.0,"tok":0,"usd":0.0,"n":0})
for r in recs:
    g = "luna-heavy >30%" if r["lshare"]>0.30 else ("mixed 5-30%" if r["lshare"]>0.05 else "sol-pure <5%")
    x=G[g]; x["d"]+=r["d"]; x["tok"]+=r["tok"]; x["usd"]+=r["usd"]; x["n"]+=1
print(f"{'group':18s} {'hrs':>4s} {'points':>7s} {'Mtok':>8s} {'$':>9s} {'Mtok/pt':>9s} {'$/pt':>8s}")
for g in ("sol-pure <5%","mixed 5-30%","luna-heavy >30%"):
    x=G[g]
    if not x["n"]: continue
    print(f"{g:18s} {x['n']:4d} {x['d']:7.0f} {x['tok']/1e6:8.0f} {x['usd']:9.0f} "
          f"{x['tok']/1e6/x['d']:9.1f} {x['usd']/x['d']:8.2f}")
