#!/usr/bin/env python3
"""#72 — размер ПО ПРОВОДУ через домен (nginx gzip), а не локальная оценка."""
import http.cookiejar, urllib.request, urllib.parse, sys, json

BASE = "https://orchestra.seedon.ru"
env = dict(l.split("=", 1) for l in open("/home/kesha/orchestra/.env") if "=" in l and not l.startswith("#"))
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
op.addheaders = [("Accept-Encoding", "gzip"), ("User-Agent", "Mozilla/5.0")]
op.open(f"{BASE}/login", urllib.parse.urlencode(
    {"username": env["DASHBOARD_USER"].strip(), "password": env["DASHBOARD_PASSWORD"].strip()}).encode())

def wire(path):
    r = op.open(BASE + path)
    body = r.read()
    return len(body) / 1024, r.headers.get("Content-Encoding", "—")

for path in sys.argv[1:]:
    kb, enc = wire(path)
    print(f"{kb:8.1f} КБ  ({enc})  {path}")
