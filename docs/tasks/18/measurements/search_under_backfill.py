import statistics, time
from pathlib import Path
import httpx
BASE="http://127.0.0.1:8888"; SCOPE="/home/kesha/orchestra"
tok=next(l.split("=",1)[1].strip() for l in Path("/home/kesha/orchestra/.env").read_text().splitlines() if l.startswith("INTERNAL_TOKEN="))
H={"Authorization":f"Bearer {tok}"}
lat=[]
end=time.perf_counter()+60
with httpx.Client(timeout=120) as c:
    while time.perf_counter()<end:
        t=time.perf_counter()
        try:
            r=c.post(f"{BASE}/api/memory/search",headers=H,json={"scope":SCOPE,"query":"event loop stalls dashboard","limit":5})
            lat.append(((time.perf_counter()-t)*1000,r.status_code))
        except Exception as e:
            lat.append(((time.perf_counter()-t)*1000,type(e).__name__))
        time.sleep(0.3)
s=sorted(x[0] for x in lat); p=lambda q: s[min(int(len(s)*q),len(s)-1)]
print(f"поиск ВО ВРЕМЯ индексации: n={len(s)} p50={p(.5):.1f} p90={p(.9):.1f} p95={p(.95):.1f} p99={p(.99):.1f} max={max(s):.1f} мс")
print(f"статусы: {sorted({str(x[1]) for x in lat})}")
print("сырьё:", " ".join(f"{x:.0f}" for x in s))
