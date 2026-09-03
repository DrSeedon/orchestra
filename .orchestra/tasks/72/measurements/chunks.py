#!/usr/bin/env python3
"""#72 — страница истории порциями: размер КАЖДОЙ порции по проводу против одного ответа."""
import http.cookiejar, urllib.request, urllib.parse, json, sys

BASE = "https://orchestra.seedon.ru"
env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env") if "=" in l and not l.startswith("#"))
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("Accept-Encoding", "gzip"), ("User-Agent", "Mozilla/5.0")]
op.open(f"{BASE}/login", urllib.parse.urlencode(
    {"username": env["DASHBOARD_USER"].strip(), "password": env["DASHBOARD_PASSWORD"].strip()}).encode())

def get(name, scope, before_id, limit):
    q = urllib.parse.urlencode({"scope": scope, "before_id": before_id, "limit": limit})
    r = op.open(f"{BASE}/api/sessions/{urllib.parse.quote(name)}/logs?{q}")
    body = r.read()
    import gzip as _g
    rows = json.loads(_g.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body)
    return len(body) / 1024, rows

scope = sys.argv[1]
for name in sys.argv[2:]:
    one, rows = get(name, scope, 2**31 - 1, 100)
    before, sizes, total = 2**31 - 1, [], 0
    for _ in range(4):
        kb, rs = get(name, scope, before, 25)
        if not rs: break
        sizes.append(kb); total += kb
        before = min(r["id"] for r in rs)
    print(f"{name:24s} одним ответом {one:6.1f} КБ ({len(rows)} строк) | порциями "
          f"{' + '.join(f'{x:.1f}' for x in sizes)} = {total:5.1f} КБ, макс порция {max(sizes):5.1f} КБ")
