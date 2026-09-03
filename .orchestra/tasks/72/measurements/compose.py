#!/usr/bin/env python3
"""#72 — из чего состоит ответ /api/logs/sync. Метод #65: пережать ЖИВОЙ ответ вариантами."""
import gzip, json, http.cookiejar, urllib.request, urllib.parse, collections, sys

env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env") if "=" in l and not l.startswith("#"))
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.open("http://127.0.0.1:8888/login", urllib.parse.urlencode(
    {"username": env["DASHBOARD_USER"].strip(), "password": env["DASHBOARD_PASSWORD"].strip()}).encode())
URL = "http://127.0.0.1:8888/api/logs/sync?after_id=0&tail=20&cap=16384"
raw = op.open(URL).read()
data = json.loads(raw)
logs, live = data["logs"], data["live_sessions"]

def gz(obj):
    return len(gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode(), 6))

print(f"строк {len(logs)}, сессий в ответе {len(set(l['session_id'] for l in logs))}, live_sessions {len(live)}")
print(f"raw {len(raw)/1024:.1f} КБ, gzip {gz(data)/1024:.1f} КБ")

# вклад полей: сколько байт gzip уходит, если поле выбросить целиком
base = gz(data)
print("\nвклад поля (gzip, КБ) — сколько отвалится, если поле убрать:")
for field in ["content", "type", "ts", "id", "session_id", "event_id", "trunc"]:
    v = {**data, "logs": [{k: x for k, x in l.items() if k != field} for l in logs]}
    print(f"  {field:11s} −{(base - gz(v))/1024:6.1f}")
v = {**data, "live_sessions": []}
print(f"  live_sessions −{(base - gz(v))/1024:6.1f}")

# вклад по типу строки
by_type = collections.Counter()
bytes_type = collections.Counter()
for l in logs:
    by_type[l["type"]] += 1
    bytes_type[l["type"]] += len((l.get("content") or "").encode())
print("\nстроки по типу (шт / raw КБ content / gzip КБ, если тип выбросить):")
for t, n in by_type.most_common():
    v = {**data, "logs": [l for l in logs if l["type"] != t]}
    print(f"  {t:14s} {n:5d}  {bytes_type[t]/1024:8.1f}  −{(base - gz(v))/1024:6.1f}")

# распределение длин content
lens = sorted(len((l.get("content") or "").encode()) for l in logs)
n = len(lens)
print(f"\ncontent байт: медиана {lens[n//2]}, p90 {lens[int(n*0.9)]}, p99 {lens[int(n*0.99)]}, max {lens[-1]}")
print(f"обрезанных строк (trunc): {sum(1 for l in logs if 'trunc' in l)}")

# сколько весит хвост длинных строк
for cap in (16384, 4096, 2048, 1024, 512):
    v = {**data, "logs": [{**l, "content": (l.get("content") or "").encode()[:cap].decode(errors="ignore")} for l in logs]}
    print(f"  cap={cap:6d} → gzip {gz(v)/1024:6.1f} КБ")

# сколько дают разные tail (эмуляция: последние N строк каждой сессии из уже полученного)
by_sess = collections.defaultdict(list)
for l in logs:
    by_sess[l["session_id"]].append(l)
print()
for tail in (20, 10, 5, 3, 1, 0):
    keep = [x for v in by_sess.values() for x in v[-tail:]] if tail else []
    v = {**data, "logs": sorted(keep, key=lambda x: x["id"])}
    print(f"  tail={tail:3d} → строк {len(keep):5d}, gzip {gz(v)/1024:6.1f} КБ")
