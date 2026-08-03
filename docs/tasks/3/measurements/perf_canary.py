"""Event-loop stall canary.

Hits the cheapest endpoint on a fixed 200 ms cadence for N seconds.
The endpoint itself is ~6 ms, so any latency above that is the FastAPI
event loop being busy with something else (agent turns, SSE polls, DB).
"""
import asyncio, sys, time
import httpx

BASE = "http://127.0.0.1:8888"
H = {"Authorization": f"Bearer {open('/tmp/perf_token').read().strip()}"}
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
URL = sys.argv[2] if len(sys.argv) > 2 else "/api/role-icons"


async def main():
    lat = []
    async with httpx.AsyncClient(timeout=30) as c:
        await c.get(BASE + URL, headers=H)  # warm the connection
        end = time.perf_counter() + SECONDS
        while time.perf_counter() < end:
            t = time.perf_counter()
            try:
                await c.get(BASE + URL, headers=H)
                lat.append(((time.perf_counter() - t) * 1000, t))
            except Exception as e:
                lat.append((30000.0, t))
                print("err", type(e).__name__)
            await asyncio.sleep(0.2)
    ms = sorted(x[0] for x in lat)
    n = len(ms)
    print(f"canary {URL}  n={n} over {SECONDS}s")
    print(f"  p50={ms[n//2]:.1f}  p90={ms[int(n*.9)]:.1f}  p99={ms[int(n*.99)]:.1f}  max={ms[-1]:.1f} ms")
    for thr in (50, 100, 250, 500, 1000):
        k = sum(1 for m in ms if m > thr)
        print(f"  >{thr:5d}ms: {k:4d} ({k/n*100:5.1f}%)")
    t0 = lat[0][1]
    spikes = [(round(t - t0, 1), round(m)) for m, t in lat if m > 250]
    print(f"  stalls >250ms at t=: {spikes[:40]}")


asyncio.run(main())
