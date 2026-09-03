"""Does the FastAPI event loop serialize the dashboard's idle polls?

Compares one-at-a-time latency against the exact burst the dashboard fires
every 3 s, plus the same burst with an SSE stream open.
"""
import asyncio, statistics, sys, time
import httpx

BASE = "http://127.0.0.1:8888"
TOKEN = open("/tmp/perf_token").read().strip()
H = {"Authorization": f"Bearer {TOKEN}"}
SCOPE = sys.argv[1] if len(sys.argv) > 1 else "/home/kesha/orchestra"

BURST = [
    f"/api/sessions?scope={SCOPE}",
    f"/api/stats?scope={SCOPE}",
    "/api/orchestrators",
    "/api/models",
]


async def timed(client, url):
    t = time.perf_counter()
    r = await client.get(BASE + url, headers=H)
    return (time.perf_counter() - t) * 1000, r.status_code, len(r.content)


def report(label, samples):
    s = sorted(samples)
    print(f"  {label:34s} n={len(s):3d} p50={s[len(s)//2]:7.1f} "
          f"p95={s[int(len(s)*0.95)]:7.1f} max={s[-1]:7.1f} ms")


async def sequential(client, rounds=10):
    out = {u: [] for u in BURST}
    for _ in range(rounds):
        for u in BURST:
            d, _, _ = await timed(client, u)
            out[u].append(d)
    return out


async def burst(client, rounds=10):
    out = {u: [] for u in BURST}
    for _ in range(rounds):
        res = await asyncio.gather(*[timed(client, u) for u in BURST])
        for u, (d, _, _) in zip(BURST, res):
            out[u].append(d)
        await asyncio.sleep(0.2)
    return out


async def sse_holder(stop, name, scope):
    async with httpx.AsyncClient(timeout=None) as c:
        try:
            async with c.stream("GET", f"{BASE}/api/sessions/{name}/stream",
                                params={"scope": scope, "after_id": 0, "limit": 100},
                                headers=H) as r:
                async for _ in r.aiter_bytes():
                    if stop.is_set():
                        return
        except Exception as e:
            print(f"  [sse holder ended: {type(e).__name__}]")


async def main():
    limits = httpx.Limits(max_connections=6, max_keepalive_connections=6)
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        print("=== A. one request at a time ===")
        for u, s in (await sequential(client)).items():
            report(u.split("?")[0], s)

        print("=== B. the dashboard's 4-request burst, in parallel ===")
        for u, s in (await burst(client)).items():
            report(u.split("?")[0], s)

        stop = asyncio.Event()
        tasks = [asyncio.create_task(sse_holder(stop, n, SCOPE)) for n in SSE_AGENTS]
        await asyncio.sleep(2)
        print(f"=== C. same burst with {len(SSE_AGENTS)} SSE streams open ===")
        for u, s in (await burst(client)).items():
            report(u.split("?")[0], s)
        stop.set()
        for t in tasks:
            t.cancel()


SSE_AGENTS = sys.argv[2].split(",") if len(sys.argv) > 2 else []
asyncio.run(main())
