#!/usr/bin/env python3
"""#72 — что даёт потиповый потолок content. Пережатие живого ответа /api/logs/sync."""
import gzip, json, http.cookiejar, urllib.request, urllib.parse, collections

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env") if "=" in l and not l.startswith("#"))
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open("http://127.0.0.1:8888/login", urllib.parse.urlencode(
    {"username": env["DASHBOARD_USER"].strip(), "password": env["DASHBOARD_PASSWORD"].strip()}).encode())
data = json.loads(op.open("http://127.0.0.1:8888/api/logs/sync?after_id=0&tail=20&cap=16384").read())
logs = data["logs"]

def gz(obj):
    return len(gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode(), 6)) / 1024

def capped(types, cap):
    out = []
    for l in logs:
        c = (l.get("content") or "").encode()
        if l["type"] in types and len(c) > cap:
            out.append({**l, "content": c[:cap].decode(errors="ignore"), "trunc": len(c)})
        else:
            out.append(l)
    return out

base = gz(data)
print(f"как есть: {base:.1f} КБ gzip, {len(logs)} строк")

COLLAPSED = {"tool", "tool_result", "status"}
for cap in (2048, 1024, 512, 256, 128):
    rows = capped(COLLAPSED, cap)
    n = sum(1 for a, b in zip(rows, logs) if a is not b)
    print(f"  tool/tool_result/status ≤{cap:5d} Б → {gz({**data, 'logs': rows}):6.1f} КБ, обрезано строк {n:3d}/{len(logs)}")

print()
for cap in (1024, 512, 256):
    rows = capped(COLLAPSED | {"text", "user_message"}, cap)
    n = sum(1 for a, b in zip(rows, logs) if a is not b)
    print(f"  ВСЕ типы ≤{cap:5d} Б → {gz({**data, 'logs': rows}):6.1f} КБ, обрезано строк {n:3d}/{len(logs)}")

print()
for tail in (20, 10, 5):
    by = collections.defaultdict(list)
    for l in logs: by[l["session_id"]].append(l)
    keep = {id(x) for v in by.values() for x in v[-tail:]}
    for cap in (16384, 1024, 512):
        rows = [l for l in capped(COLLAPSED, cap) if id(logs[[id(z) for z in logs].index(id(l))] if False else l) or True]
        rows = capped(COLLAPSED, cap)
        rows = [r for r, l in zip(rows, logs) if id(l) in keep]
        print(f"  tail={tail:3d} + свёрнутые ≤{cap:5d} Б → {gz({**data, 'logs': rows}):6.1f} КБ, строк {len(rows)}")
