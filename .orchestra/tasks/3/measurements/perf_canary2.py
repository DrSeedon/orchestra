"""Канарейка event loop v2 — с записью условий прогона и с контрольным сервером.

Отличия от v1 (perf_canary.py), каждое — по делу:
  * инструмент сменён на /api/models. Он 100% in-memory (app/routes/system.py:341 —
    итерация по MODELS + provider_metadata_payload() + is_proxy_connected(), ни диска,
    ни БД, ни сети). Любая задержка выше ~1 мс на loopback = event loop НЕ КРУТИЛСЯ.
    Старый инструмент /api/role-icons на каждый запрос делает glob('*.md') + read_text()
    (app/prompting.py:103) — под I/O-нагрузкой он мерит свой же диск, а не loop.
  * контрольный сервер: отдельный asyncio-процесс, отвечающий из памяти на том же хосте.
    Стойка ТОЛЬКО у Orchestra → виноват её event loop. Стойка у обоих → тормозит машина
    (диск/планировщик), и RAG тут ни при чём.
  * условия прогона (RAG_ENABLED живого процесса, RSS, loadavg, /proc/pressure) пишутся
    в шапку лога ДО и ПОСЛЕ. Без них два прогона несравнимы.

Запуск: python perf_canary2.py <label> [seconds]   → пишет canary-<label>.log рядом.
"""
import json
import threading
import os
import re
import statistics
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8888"
CONTROL_PORT = 8899
URL = "/api/models"          # чистый инструмент: только время event loop
URL_LEGACY = "/api/role-icons"  # грязный, но сопоставим с canary.log из v1
CADENCE = 0.2
OUT_DIR = Path(__file__).resolve().parent
CG = Path("/sys/fs/cgroup/system.slice/orchestra.service")

CONTROL_SRC = """
import asyncio
async def h(r, w):
    await r.readuntil(b"\\r\\n\\r\\n")
    w.write(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\nConnection: keep-alive\\r\\n\\r\\nok")
    await w.drain()
    while True:
        try:
            await r.readuntil(b"\\r\\n\\r\\n")
        except Exception:
            return
        w.write(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\nConnection: keep-alive\\r\\n\\r\\nok")
        await w.drain()
async def m():
    s = await asyncio.start_server(h, "127.0.0.1", %d)
    async with s:
        await s.serve_forever()
asyncio.run(m())
""" % CONTROL_PORT


def server_pid() -> int:
    """PID НАСТОЯЩЕГО сервера. `pgrep -f 'uvicorn app.main'` матчит ещё и обёртку
    `uv run` (31 МБ, 2 потока, 0 onnx-мапингов) — снимешь условия с неё и будешь
    писать в лог чужие цифры. Дискриминатор — comm == "uvicorn"."""
    out = subprocess.run(["pgrep", "-f", "uvicorn app.main"],
                         capture_output=True, text=True).stdout.split()
    real = []
    for p in out:
        try:
            if Path(f"/proc/{p}/comm").read_text().strip() == "uvicorn":
                real.append(int(p))
        except OSError:
            pass
    if len(real) != 1:
        sys.exit(f"FAIL: ожидал ровно один процесс uvicorn, найдено {real} "
                 f"(все совпадения: {out})")
    return real[0]


def conditions(pid: int) -> dict:
    """Условия прогона. RAG_ENABLED читается из ЖИВОГО процесса, а не из .env —
    .env могли поменять без рестарта, и тогда файл врёт про то, что мы измеряем."""
    env = dict(kv.split("=", 1) for kv in
               Path(f"/proc/{pid}/environ").read_bytes().decode(errors="replace").split("\0")
               if "=" in kv)
    status = Path(f"/proc/{pid}/status").read_text()
    rss_kb = int(re.search(r"VmRSS:\s+(\d+)", status).group(1))
    maps = Path(f"/proc/{pid}/maps").read_text()
    return {
        "pid": pid,
        "rag_enabled": env.get("RAG_ENABLED", "<unset>"),
        "rag_onnx_threads": env.get("RAG_ONNX_THREADS", "<unset>"),
        "rss_mb": round(rss_kb / 1024),
        # различать обязательно: .so — что onnxruntime ЗАГРУЖЕН в процесс,
        # *.onnx — что файл модели ещё и замаплен (fastembed читает его в кучу, поэтому 0)
        "onnxruntime_so_maps": len([l for l in maps.splitlines() if "onnxruntime" in l]),
        "onnx_model_maps": len([l for l in maps.splitlines() if l.rstrip().endswith(".onnx")]),
        "threads": int(re.search(r"Threads:\s+(\d+)", status).group(1)),
        # железо — в шапку обязательно: 03.08.2026 в 11:23 Contabo мигрировал сервер
        # 4 ядра/7.8 ГБ → 8 ядер/23 ГБ ПОСРЕДИ эксперимента, и половина замеров
        # оказалась снята на другой машине
        "nproc": os.cpu_count(),
        "mem_total_gb": round(int(re.search(r"MemTotal:\s+(\d+)",
                                            Path("/proc/meminfo").read_text()).group(1)) / 2**20, 1),
        "uptime_min": round(float(Path("/proc/uptime").read_text().split()[0]) / 60, 1),
        "loadavg": Path("/proc/loadavg").read_text().split()[:3],
        # фон соседей: сколько агентских процессов молотит рядом в момент замера.
        # -x по имени процесса, НЕ `pgrep -fc`: тот печатает одно число, и len(split())
        # всегда даёт 1 — зонд, возвращающий одно и то же при любом фоне, не зонд
        "agent_procs": len(subprocess.run(["pgrep", "-x", "claude|codex|node"],
                                          capture_output=True, text=True).stdout.split()),
        "pressure_io": Path("/proc/pressure/io").read_text().strip().splitlines(),
        "pressure_cpu": Path("/proc/pressure/cpu").read_text().strip().splitlines(),
    }


def drive_rag(stop: "threading.Event", headers: dict, out: list) -> None:
    """Нагружает RAG search'ем раз в 2 с, пока идёт канарейка.

    Без этого эксперимент пустой: на тихой машине RAG_ENABLED=true просто ЛЕЖИТ в памяти
    и ничего не считает — сравнивать «включённый, но простаивающий RAG» с выключенным
    бессмысленно. Проверяем именно РАБОТУ эмбеддера. При RAG off эндпоинт отвечает 503
    мгновенно (app/routes/memory.py:32) — это и есть контраст «работа vs нет работы».
    Покрывает только search-путь; backfill (реиндекс на merge) тяжелее и тут НЕ проверяется.
    """
    body = {"scope": "/home/kesha/orchestra", "query": "event loop stalls dashboard latency",
            "limit": 5}
    with httpx.Client(timeout=60) as c:
        while not stop.is_set():
            t = time.perf_counter()
            try:
                r = c.post(BASE + "/api/memory/search", json=body, headers=headers)
                out.append(((time.perf_counter() - t) * 1000, r.status_code))
            except Exception as e:
                out.append(((time.perf_counter() - t) * 1000, type(e).__name__))
            stop.wait(2.0)


def pct(s: list[float], p: float) -> float:
    return sorted(s)[min(int(len(s) * p), len(s) - 1)] if s else float("nan")


def summarize(label: str, s: list[float], out) -> None:
    if not s:
        print(f"  {label}: НЕТ ОТВЕТОВ", file=out)
        return
    print(f"  {label:16s} n={len(s):4d}  p50={pct(s,.5):8.1f}  p90={pct(s,.9):8.1f}  "
          f"p99={pct(s,.99):9.1f}  max={max(s):9.1f} ms", file=out)
    for thr in (50, 100, 250, 500, 1000, 2000, 5000):
        n = sum(1 for x in s if x > thr)
        mark = "   <<< порог фронта" if thr == 2000 else ""
        print(f"      >{thr:5d}ms: {n:4d} ({n/len(s)*100:5.1f}%){mark}", file=out)


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    # токен берём из .env живого сервера, а не из /tmp: /tmp вычищается, и прогон
    # падает на ровном месте между двумя половинами эксперимента
    env_file = Path("/home/kesha/orchestra/.env")
    token = next((l.split("=", 1)[1].strip() for l in env_file.read_text().splitlines()
                  if l.startswith("INTERNAL_TOKEN=")), "")
    if not token:
        sys.exit(f"FAIL: INTERNAL_TOKEN не найден в {env_file}")
    headers = {"Authorization": f"Bearer {token}"}

    drive = "--drive" in sys.argv

    pid = server_pid()
    before = conditions(pid)
    # контрольный сервер обязан быть НАШ и живой. Прогон D1 сгорел ровно на этом:
    # на порту висел процесс прошлого прогона, новый молча не забиндился, а потом старый
    # умер посреди замера → 119 ConnectError, и контрольная группа превратилась в мусор
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", CONTROL_PORT)) == 0:
            sys.exit(f"FAIL: порт {CONTROL_PORT} уже занят — добей контрольный процесс "
                     f"прошлого прогона, иначе мерить будешь чужой")
    ctl = subprocess.Popen([sys.executable, "-c", CONTROL_SRC],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", CONTROL_PORT)) != 0:
            ctl.terminate()
            sys.exit(f"FAIL: контрольный сервер не поднялся на {CONTROL_PORT}")

    driver_out: list = []
    stop = threading.Event()
    driver = None
    if drive:
        driver = threading.Thread(target=drive_rag, args=(stop, headers, driver_out), daemon=True)
        driver.start()

    lat: dict[str, list[float]] = {"orchestra": [], "control": [], "legacy": []}
    faults: list[tuple[float, int, int, int, int]] = []
    errors: list[str] = []
    stalls: list[tuple[float, str, float]] = []
    try:
        with httpx.Client(timeout=30) as c:
            c.get(BASE + URL, headers=headers)                       # прогрев соединения
            c.get(f"http://127.0.0.1:{CONTROL_PORT}/ping")
            t0 = time.perf_counter()
            tick = 0
            while time.perf_counter() - t0 < seconds:
                tick += 1
                # legacy-эндпоинт реже: он сам грузит диск, незачем добавлять нагрузку
                probes = [("orchestra", BASE + URL, headers),
                          ("control", f"http://127.0.0.1:{CONTROL_PORT}/ping", None)]
                if tick % 5 == 0:
                    probes.append(("legacy", BASE + URL_LEGACY, headers))
                # страничные фолты живого сервера на КАЖДОМ тике. Без привязки ко времени
                # нельзя отличить «фолты вообще есть» от «фолты именно в момент стойки»
                stat = Path(f"/proc/{pid}/stat").read_text().split()
                # + счётчики cgroup: срабатывания мягкого лимита и прямой реклейм.
                # Без них «фолты есть» не отличить от «нас душит memory.high»
                ev = dict(l.split() for l in (CG / "memory.events").read_text().splitlines())
                pg = next((int(l.split()[1]) for l in (CG / "memory.stat").read_text().splitlines()
                           if l.startswith("pgscan_direct ")), 0)
                faults.append((time.perf_counter() - t0, int(stat[9]), int(stat[11]),
                               int(ev.get("high", 0)), pg))
                for name, url, h in probes:
                    t = time.perf_counter()
                    try:
                        c.get(url, headers=h or {})
                        ms = (time.perf_counter() - t) * 1000
                        lat[name].append(ms)
                        if ms > 250:
                            stalls.append((time.perf_counter() - t0, name, ms))
                    except Exception as e:
                        errors.append(f"t={time.perf_counter()-t0:6.1f}s {name} "
                                      f"{type(e).__name__}: {e}")
                        lat[name].append(30000.0)
                time.sleep(max(0.0, CADENCE - (time.perf_counter() - t) % CADENCE))
    finally:
        stop.set()
        if driver:
            driver.join(timeout=65)
        ctl.terminate()

    after = conditions(pid)
    out_path = OUT_DIR / f"canary-{label}.log"
    with out_path.open("w") as out:
        print(f"=== CANARY v2 label={label} seconds={seconds} cadence={CADENCE}s "
              f"drive={'RAG search 1/2s' if drive else 'нет'} "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===", file=out)
        print(f"инструмент: {URL} (in-memory) | контроль: 127.0.0.1:{CONTROL_PORT}/ping "
              f"(отдельный процесс) | legacy: {URL_LEGACY} (читает диск)", file=out)
        for tag, cond in (("ДО", before), ("ПОСЛЕ", after)):
            print(f"--- условия {tag}: {json.dumps(cond, ensure_ascii=False)}", file=out)
        print("--- результаты ---", file=out)
        for name in ("orchestra", "control", "legacy"):
            summarize(name, lat[name], out)
        if lat["orchestra"] and lat["control"]:
            print(f"  медиана orchestra/control = "
                  f"{statistics.median(lat['orchestra'])/max(statistics.median(lat['control']),1e-6):.1f}×",
                  file=out)
        if drive:
            codes: dict = {}
            for _, st in driver_out:
                codes[st] = codes.get(st, 0) + 1
            lat_ok = [ms for ms, st in driver_out if st == 200]
            print(f"--- нагрузка RAG: {len(driver_out)} запросов /api/memory/search, "
                  f"ответы {codes} ---", file=out)
            # если тут не 200 — эмбеддер не работал, и прогон как тест H1 пустой
            summarize("rag-search(200)", lat_ok, out)
        if len(faults) > 2:
            dur = faults[-1][0] - faults[0][0]
            print(f"--- страничные фолты сервера: minflt {(faults[-1][1]-faults[0][1])/dur:.0f}/с, "
                  f"majflt {(faults[-1][2]-faults[0][2])/dur:.0f}/с ---", file=out)
            print(f"--- cgroup {CG.name}: memory.high срабатываний "
                  f"{(faults[-1][3]-faults[0][3])/dur:.0f}/с, pgscan_direct "
                  f"{(faults[-1][4]-faults[0][4])/dur:.0f}/с, "
                  f"лимит high={int((CG/'memory.high').read_text()):,} "
                  f"current={int((CG/'memory.current').read_text()):,} ---", file=out)
            # ключевая проверка механизма: рвутся ли фолты ИМЕННО в тиках со стойкой
            s_min, s_maj, n_min, n_maj = [], [], [], []
            for i in range(1, min(len(faults), len(lat["orchestra"]))):
                dmin, dmaj = faults[i][1] - faults[i-1][1], faults[i][2] - faults[i-1][2]
                (s_min if lat["orchestra"][i] > 250 else n_min).append(dmin)
                (s_maj if lat["orchestra"][i] > 250 else n_maj).append(dmaj)
            if s_min and n_min:
                print(f"  в тиках СО стойкой (n={len(s_min)}):  медиана minflt={statistics.median(s_min):8.0f}"
                      f"  majflt={statistics.median(s_maj):6.0f}", file=out)
                print(f"  в тиках БЕЗ стойки  (n={len(n_min)}):  медиана minflt={statistics.median(n_min):8.0f}"
                      f"  majflt={statistics.median(n_maj):6.0f}", file=out)
            else:
                print("  стоек нет — сравнивать не с чем", file=out)
        print(f"--- стойки >250 мс: {len(stalls)} ---", file=out)
        for t, name, ms in stalls[:80]:
            print(f"  t={t:7.1f}s {name:10s} {ms:9.1f}ms", file=out)
        print(f"--- ошибки: {len(errors)} ---", file=out)
        for e in errors[:40]:
            print(f"  {e}", file=out)
    print(f"написано: {out_path}")


if __name__ == "__main__":
    main()
