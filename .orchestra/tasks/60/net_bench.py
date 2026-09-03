"""#60 — сетевая цена дашборда с машины юзера, без единого пикселя браузера.

Меряет то, что не зависит от загрузки CPU: рукопожатие, TTFB на каждый запрос по уже
открытому HTTP/2-соединению, байты. Ровно те URL, которые дашборд запрашивает на первый
заход (список снят браузером на VPS).

Запуск на ноуте: nice -n 15 python3 net_bench.py <urls.txt> <out.json>
Логин/пароль читаются из stdin одной строкой "user:password" — чтобы не светить в ps.
"""
import json, subprocess, sys, time

urls = [u.strip() for u in open(sys.argv[1]) if u.strip()]
out_path = sys.argv[2]
user, _, password = sys.stdin.readline().strip().partition(":")
BASE = "https://orchestra.seedon.ru"
COOKIE = "/mnt/data/perf60/cookie.txt"

FMT = ("%{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} "
       "%{time_total} %{size_download} %{http_code} %{http_version}\n")


def run(args):
    return subprocess.run(args, capture_output=True, text=True).stdout


# 1. холодное соединение: DNS + TCP + TLS до первого байта
cold = []
for _ in range(5):
    o = run(["curl", "-s", "-o", "/dev/null", "-w", FMT, BASE + "/login"]).split()
    cold.append([float(x) for x in o[:5]])
    time.sleep(0.3)

# 2. логин
run(["curl", "-s", "-o", "/dev/null", "-c", COOKIE, "-X", "POST", BASE + "/login",
     "-d", f"username={user}&password={password}"])

# 3. все запросы первого захода — ОДНИМ вызовом curl, то есть по одному
#    HTTP/2-соединению, как это делает браузер
args = ["curl"]
for i, u in enumerate(urls):
    if i:
        args.append("--next")
    args += ["-s", "--compressed", "-b", COOKIE, "-o", "/dev/null", "-w", FMT, u]
t0 = time.time()
lines = [l for l in run(args).splitlines() if l.strip()]
wall = time.time() - t0

per = []
for u, l in zip(urls, lines):
    f = l.split()
    per.append({"url": u, "dns": float(f[0]), "connect": float(f[1]), "tls": float(f[2]),
                "ttfb": float(f[3]), "total": float(f[4]), "bytes": int(f[5]),
                "code": int(f[6]), "http": f[7]})

json.dump({"cold_handshake": cold, "wall_all_urls_s": wall, "requests": per,
           "loadavg": open("/proc/loadavg").read().split()[:3],
           "mem_available_kb": int([l for l in open("/proc/meminfo")
                                    if l.startswith("MemAvailable")][0].split()[1])},
          open(out_path, "w"), ensure_ascii=False, indent=1)
print(f"URL: {len(per)}, суммарно {sum(p['bytes'] for p in per)/1024:.0f} КБ, wall {wall:.2f} с")
print("TTFB медиана", sorted(p["ttfb"] for p in per)[len(per) // 2])
