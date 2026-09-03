"""Распределение латентности /api/memory/search в ЗДОРОВЫХ условиях (после подъёма
MemoryHigh 2G → 8G, 03.08.2026 18:21).

Зачем заново: прежние цифры (p99 = 14 460 мс) сняты под MemoryHigh=2G, когда весь реклейм
в cgroup был синхронным. Назначать дедлайн по ним — значит зашить в код константу,
описывающую уже несуществующую поломку.

Две фазы, потому что дедлайн нужен для ХВОСТА, а хвост делает очередь:
  A. последовательно — так ходит одиночный агент;
  B. 3 клиента параллельно — read-executor это ThreadPoolExecutor(max_workers=1)
     (app/rag_service.py:66), то есть запросы становятся в очередь, и хвост растёт
     не от сложности запроса, а от ожидания.

Условия (cgroup, фолты, RSS) пишутся в шапку: без них цифры снова протухнут молча.
"""
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8888"
CG = Path("/sys/fs/cgroup/system.slice/orchestra.service")
SCOPE = "/home/kesha/orchestra"
OUT = Path(__file__).resolve().parent

# запросы намеренно разные: короткие/длинные, частотные/редкие, рус/англ —
# латентность эмбеддера пропорциональна объёму текста (замер back: 40 симв = 86.7 мс,
# 780 симв = 1705 мс), поэтому один запрос распределения не даст
QUERIES = [
    "merge",
    "event loop stalls",
    "как чинили таймаут воркера",
    "почему дашборд показывает оверлей сервер перезагружается и что с heartbeat",
    "cgroup memory high direct reclaim",
    "RAG backfill",
    "квота лимит подписки 5h окно",
    "как мы решали проблему с прокси и телеграм ботом на VPS через proxychains",
    "codex review",
    "worktree",
]


def server_pid() -> int:
    out = subprocess.run(["pgrep", "-f", "uvicorn app.main"],
                         capture_output=True, text=True).stdout.split()
    real = [int(p) for p in out
            if Path(f"/proc/{p}/comm").read_text().strip() == "uvicorn"]
    if len(real) != 1:
        sys.exit(f"FAIL: ожидал один uvicorn, найдено {real}")
    return real[0]


def conditions(pid: int) -> dict:
    ev = dict(l.split() for l in (CG / "memory.events").read_text().splitlines())
    stat = Path(f"/proc/{pid}/stat").read_text().split()
    return {
        "pid": pid,
        "rss_mb": round(int(re.search(r"VmRSS:\s+(\d+)",
                                      Path(f"/proc/{pid}/status").read_text()).group(1)) / 1024),
        "cgroup_high_events": int(ev.get("high", 0)),
        "cgroup_oom_kill": int(ev.get("oom_kill", 0)),
        "memory_high": int((CG / "memory.high").read_text()),
        "memory_current_mb": round(int((CG / "memory.current").read_text()) / 2**20),
        "pgscan_direct": next((int(l.split()[1]) for l in (CG / "memory.stat").read_text().splitlines()
                               if l.startswith("pgscan_direct ")), 0),
        "minflt": int(stat[9]), "majflt": int(stat[11]),
        "loadavg": Path("/proc/loadavg").read_text().split()[:3],
    }


def search(client: httpx.Client, q: str, headers: dict) -> tuple[float, int, int, int]:
    """→ (мс, http-статус, число попаданий, длина запроса)"""
    t = time.perf_counter()
    try:
        r = client.post(f"{BASE}/api/memory/search", headers=headers,
                        json={"scope": SCOPE, "query": q, "limit": 5})
        ms = (time.perf_counter() - t) * 1000
        hits = len(r.json().get("results", [])) if r.status_code == 200 else -1
        return ms, r.status_code, hits, len(q)
    except Exception as e:
        return (time.perf_counter() - t) * 1000, -1, -1, len(q)


def stats(label: str, xs: list[float], out) -> None:
    if not xs:
        print(f"  {label}: НЕТ ДАННЫХ", file=out)
        return
    s = sorted(xs)
    def p(q): return s[min(int(len(s) * q), len(s) - 1)]
    print(f"  {label:22s} n={len(s):3d}  p50={p(.5):7.1f}  p90={p(.9):7.1f}  "
          f"p95={p(.95):7.1f}  p99={p(.99):8.1f}  max={max(s):8.1f} ms", file=out)


def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    nclients = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    token = next(l.split("=", 1)[1].strip()
                 for l in Path("/home/kesha/orchestra/.env").read_text().splitlines()
                 if l.startswith("INTERNAL_TOKEN="))
    headers = {"Authorization": f"Bearer {token}"}
    pid = server_pid()
    before = conditions(pid)

    seq: list[tuple[float, int, int, int]] = []
    with httpx.Client(timeout=60) as c:
        search(c, "warmup", headers)
        for _ in range(rounds):
            for q in QUERIES:
                seq.append(search(c, q, headers))

    par: list[tuple[float, int, int, int]] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        with httpx.Client(timeout=60) as c:
            for i in range(n):
                r = search(c, QUERIES[i % len(QUERIES)], headers)
                with lock:
                    par.append(r)

    threads = [threading.Thread(target=worker, args=(15,)) for _ in range(nclients)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    par_wall = time.perf_counter() - t0

    after = conditions(pid)
    path = OUT / f"search-latency-p{nclients}.log"
    with path.open("w") as out:
        print(f"=== ЛАТЕНТНОСТЬ /api/memory/search  {time.strftime('%Y-%m-%d %H:%M:%S')} "
              f"rounds={rounds} ===", file=out)
        for tag, cond in (("ДО", before), ("ПОСЛЕ", after)):
            print(f"--- условия {tag}: {json.dumps(cond, ensure_ascii=False)}", file=out)
        d = after["cgroup_high_events"] - before["cgroup_high_events"]
        print(f"--- срабатываний memory.high за замер: {d} "
              f"(если не 0 — условия НЕ здоровые, цифры не годятся для дедлайна)", file=out)
        print("--- A. последовательно (одиночный агент) ---", file=out)
        stats("все запросы", [x[0] for x in seq], out)
        short = [x[0] for x in seq if x[3] <= 30]
        long_ = [x[0] for x in seq if x[3] > 60]
        stats("короткие (<=30 симв)", short, out)
        stats("длинные (>60 симв)", long_, out)
        print(f"  статусы: {sorted({x[1] for x in seq})}  "
              f"попаданий на запрос: min={min(x[2] for x in seq)} "
              f"max={max(x[2] for x in seq)}", file=out)
        print(f"--- B. {nclients} клиент(ов) параллельно, {len(par)} запросов за {par_wall:.1f} с ---", file=out)
        stats("параллельно", [x[0] for x in par], out)
        print(f"  пропускная способность: {len(par)/par_wall:.1f} запросов/с", file=out)
        print("--- сырые значения (мс, последовательно) ---", file=out)
        print("  " + " ".join(f"{x[0]:.0f}" for x in seq), file=out)
        print("--- сырые значения (мс, параллельно) ---", file=out)
        print("  " + " ".join(f"{x[0]:.0f}" for x in par), file=out)
    print(f"написано: {path}")


if __name__ == "__main__":
    main()
