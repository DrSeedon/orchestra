import json, re, math, glob, os, statistics as st
def fisher_exact(t):
    (a,b),(c,d)=t; n=a+b+c+d; r1=a+b; c1=a+c
    pr=lambda x: math.comb(r1,x)*math.comb(n-r1,c1-x)/math.comb(n,c1)
    p0=pr(a); return None, sum(pr(x) for x in range(max(0,c1-(n-r1)),min(r1,c1)+1) if pr(x)<=p0*(1+1e-9))
def wil(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z*z/n; c = (p + z*z/(2*n))/d; h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return (round(100*(c-h)), round(100*(c+h)))
key = json.load(open("label_key.json")); rev = {v: k for k, v in key.items()}
def js(t):
    m = re.search(r'\{.*\}', t, re.S)
    try: return json.loads(m.group(0))
    except Exception: return None
LAB = {m: json.load(open(f"label_{m}.json")) for m in ("sonnet", "luna")}
MAT = {m: json.load(open(f"match_{m}.json")) for m in ("sonnet", "luna")}
def fl(m, rid):
    j = js(LAB[m][rev[rid]]); return j["findings"] if j else None
rids = sorted(rev); out = {}
bad = [r for r in rids if r.startswith("bad-")]; clean = [r for r in rids if r.startswith("clean-")]
print("unparsed labels", [(m, r) for m in LAB for r in rids if fl(m, r) is None])
def real(m, r): return sum(1 for f in (fl(m, r) or []) if f.get("label") == "real")
def nf(m, r): return len(fl(m, r) or [])
for m in LAB:
    for nm, S in (("bad", bad), ("clean", clean)):
        F = sum(nf(m, r) for r in S); R = sum(real(m, r) for r in S)
        print(m, nm, "findings", F, "real", R, "diffs>=1real", sum(real(m, r) > 0 for r in S), "/", len(S), "diffs w/ finding", sum(nf(m, r) > 0 for r in S))
# precision on clean, both agree: per-review, count min of real counts (conservative) and per-finding agreement unavailable (claims differ) -> use min
for nm, S in (("bad", bad), ("clean", clean)):
    F = sum(round((nf("sonnet", r) + nf("luna", r))/2) for r in S)
    Rmin = sum(min(real("sonnet", r), real("luna", r)) for r in S); Ravg = sum(real("sonnet", r) + real("luna", r) for r in S)/2
    print(nm, "findings(avg labelers)", F, "real min-of-labelers", Rmin, "real avg", Ravg, "precision(min)", round(100*Rmin/max(F,1)), wil(Rmin, F), "precision(avg)", round(100*Ravg/max(F,1)))
# diffs with >=1 real, both labelers agree, either repeat
def anyreal(base, both=True):
    rs = [r for r in rids if r.rsplit(".r", 1)[0] == base]
    f = (lambda m: any(real(m, r) > 0 for r in rs))
    return (f("sonnet") and f("luna")) if both else (f("sonnet") or f("luna"))
bb = sorted({r.rsplit(".r", 1)[0] for r in bad}); cb = sorted({r.rsplit(".r", 1)[0] for r in clean})
for both in (True, False):
    kb = sum(anyreal(b, both) for b in bb); kc = sum(anyreal(c, both) for c in cb)
    print("both" if both else "either", "diffs>=1 real (any repeat) bad", kb, "/", len(bb), wil(kb, len(bb)), "clean", kc, "/", len(cb), wil(kc, len(cb)), "fisher p", round(fisher_exact([[kb, len(bb)-kb], [kc, len(cb)-kc]])[1], 3))
# recall (hit)
def hit(m, r): j = js(MAT[m][r]) or {}; return str(j.get("hit", "")).lower() == "yes"
for both in (True, False):
    perdiff = {}
    for b in bb:
        rs = [r for r in bad if r.rsplit(".r", 1)[0] == b]
        h = [(hit("sonnet", r) and hit("luna", r)) if both else (hit("sonnet", r) or hit("luna", r)) for r in rs]
        perdiff[b] = h
    k = sum(any(h) for h in perdiff.values()); per = sum(sum(h) for h in perdiff.values())
    print("recall", "both" if both else "either", "any-repeat", k, "/", len(bb), round(100*k/len(bb)), wil(k, len(bb)), "per-run", per, "/", len(bad), round(100*per/len(bad)))
    if both: print({b[4:]: h for b, h in perdiff.items()})
# labeler agreement on whether review has any real
ag = sum((real("sonnet", r) > 0) == (real("luna", r) > 0) for r in rids); print("agree any-real", ag, "/", len(rids))
# repeat consistency on verdicts / findings
def hasf(r): return nf("sonnet", r) > 0
print("repeat agreement of has-finding", sum(hasf(b+".r0") == hasf(b+".r1") for b in bb+cb), "/", len(bb+cb))
# cost
M = {os.path.basename(f)[:-10]: json.load(open(f)) for f in glob.glob("raw/*.meta.json")}
for nm, S in (("bad", bad), ("clean", clean)):
    t = [M[r]["usage"].get("input_tokens", 0)-M[r]["usage"].get("cached_input_tokens", 0)+M[r]["usage"].get("output_tokens", 0) for r in S]
    print(nm, "paid tok median", st.median(t), "sec median", st.median(M[r]["seconds"] for r in S))
