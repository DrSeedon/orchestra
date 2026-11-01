import json, glob, math, collections, sys
R = [json.load(open(f)) for f in glob.glob("/home/kesha/orchestra/.orchestra/private/V-1106/runs/*/result.json")]
R = [r for r in R if not str(r["rep"]).startswith("p")]

def wilson(k, n, z=1.96):
    if n == 0: return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)

def newcombe(k1, n1, k2, n2):  # CI for p1-p2
    l1, u1 = wilson(k1, n1); l2, u2 = wilson(k2, n2); p1, p2 = k1 / n1, k2 / n2
    return (p1 - p2 - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), p1 - p2 + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))

def cnt(rs, f): return sum(1 for r in rs if f(r))
def fmt(k, n):
    lo, hi = wilson(k, n); return f"{k}/{n} = {k/n:.0%} [{lo:.0%}–{hi:.0%}]"
def diff(kt, nt, kb, nb):
    lo, hi = newcombe(kt, nt, kb, nb); return f"{(kt/nt-kb/nb):+.0%} [{lo:+.0%}…{hi:+.0%}]"

METRICS = {  # rule, kind -> list of (name, fn, good_direction)
 ("A", "benefit"): [("scope_violation", lambda r: r.get("scope_violation")), ("success", lambda r: r["success"])],
 ("A", "harm"): [("protection_missing", lambda r: r.get("protection_missing")), ("success", lambda r: r["success"])],
 ("B", "benefit"): [("redundant_checks>0", lambda r: (r.get("redundant_checks") or 0) > 0), ("success", lambda r: r["success"])],
 ("B", "harm"): [("protection_missing", lambda r: r.get("protection_missing")), ("success", lambda r: r["success"])],
 ("C", "benefit"): [("followed_code", lambda r: r.get("followed_code")), ("reported_discrepancy", lambda r: r["reported_discrepancy"]), ("success", lambda r: r["success"])],
 ("C", "harm"): [("owner/safety/migration overridden", lambda r: r.get("owner_overridden") if "owner_overridden" in r else r.get("protection_missing")), ("success", lambda r: r["success"])],
}
out = []
tot_cost = sum(r["cost"] or 0 for r in R); out.append(f"runs={len(R)}  api-equivalent cost=${tot_cost:.2f}")
for rule in "ABC":
    for kind in ("benefit", "harm"):
        rs = [r for r in R if r["rule"] == rule and r["kind"] == kind]
        if not rs: continue
        sids = sorted({r["scenario"] for r in rs})
        out.append(f"\n### Rule {rule} / {kind} scenarios ({', '.join(sids)})")
        base = [r for r in rs if r["arm"] == "base"]; tr = [r for r in rs if r["arm"] == rule]
        out.append(f"N per arm: base={len(base)} rule={len(tr)}")
        for name, fn in METRICS[(rule, kind)] + [("asked_regex (any)", lambda r: r["asked_regex"]), ("asked & not success", lambda r: r["asked_regex"] and not r["success"])]:
            kb, kt = cnt(base, fn), cnt(tr, fn)
            out.append(f"- {name}: base {fmt(kb, len(base))} | rule {fmt(kt, len(tr))} | diff {diff(kt, len(tr), kb, len(base))}")
        for k in ("turns", "out_tokens", "cost"):
            mb = sum(r[k] or 0 for r in base) / len(base); mt = sum(r[k] or 0 for r in tr) / len(tr)
            out.append(f"- mean {k}: base {mb:.3g} | rule {mt:.3g}")
        out.append("  per scenario (success base→rule | metric1 base→rule):")
        for sid in sids:
            b = [r for r in base if r["scenario"] == sid]; t = [r for r in tr if r["scenario"] == sid]
            m1 = METRICS[(rule, kind)][0]
            out.append(f"  - {sid}: success {cnt(b,lambda r:r['success'])}/{len(b)} → {cnt(t,lambda r:r['success'])}/{len(t)} | {m1[0]} {cnt(b,m1[1])}/{len(b)} → {cnt(t,m1[1])}/{len(t)}")
print("\n".join(out))
