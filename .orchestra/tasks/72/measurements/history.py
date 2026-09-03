#!/usr/bin/env python3
"""#72 — из чего состоит страница истории агента (/api/sessions/<name>/logs?limit=100)."""
import gzip, json, http.cookiejar, urllib.request, urllib.parse, collections, sys

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env") if "=" in l and not l.startswith("#"))
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open("http://127.0.0.1:8888/login", urllib.parse.urlencode(
    {"username": env["DASHBOARD_USER"].strip(), "password": env["DASHBOARD_PASSWORD"].strip()}).encode())

def gz(obj):
    return len(gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode(), 6)) / 1024

name, scope = sys.argv[1], sys.argv[2]
q = urllib.parse.urlencode({"scope": scope, "before_id": 2**31 - 1, "limit": 100})
rows = json.loads(op.open(f"http://127.0.0.1:8888/api/sessions/{urllib.parse.quote(name)}/logs?{q}").read())
print(f"{name}: строк {len(rows)}, gzip {gz(rows):.1f} КБ")
print("поля:", ", ".join(sorted(rows[0].keys())) if rows else "—")
base = gz(rows)
for f in sorted(rows[0].keys()) if rows else []:
    print(f"  {f:14s} −{base - gz([{k: v for k, v in r.items() if k != f} for r in rows]):6.1f} КБ")
by = collections.Counter(r["type"] for r in rows)
print("\nпо типам (шт / gzip, если выбросить):")
for t, n in by.most_common():
    print(f"  {t:14s} {n:4d}  −{base - gz([r for r in rows if r['type'] != t]):6.1f} КБ")
print("\nпотолок content для свёрнутых типов (tool/tool_result/status):")
for cap in (2048, 1024, 512, 256):
    out, cut = [], 0
    for r in rows:
        c = (r.get("content") or "").encode()
        if r["type"] in {"tool", "tool_result", "status"} and len(c) > cap:
            out.append({**r, "content": c[:cap].decode(errors="ignore"), "trunc": len(c)}); cut += 1
        else:
            out.append(r)
    print(f"  ≤{cap:5d} Б → {gz(out):6.1f} КБ, обрезано {cut:3d}/{len(rows)}")
