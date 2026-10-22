"""Live: print the events of one hub turn with timestamps; checks order and duplicates."""
import asyncio, sys, time
sys.path.insert(0, ".")
from app.backend_hub import HubBackend
async def main():
    repo = open("/tmp/v1008-proof/current").read().strip()
    b = HubBackend(sys.argv[1], repo); await b.connect()
    await b.send("Do these in order, each as a separate step: 1) run `sleep 8 && echo step-one`; 2) edit m.py so g() returns 5; "
                 "3) run `sleep 8 && echo step-two`; 4) reply with one sentence.")
    t0 = time.time(); seen = []
    async for ev in b.events():
        if ev.type == "turn_end": print(f"{time.time()-t0:5.1f}s [turn_end]"); continue
        print(f"{time.time()-t0:5.1f}s [{ev.type}] {ev.metadata.get('tool_use_id','')[-6:]} {ev.content[:90]!r}")
        seen.append((ev.type, ev.metadata.get("tool_use_id", "")))
    uses = [i for t, i in seen if t == "tool_use"]; res = [i for t, i in seen if t == "tool_result"]
    print("tool_use ids unique:", len(uses) == len(set(uses)), "| every use has one result:", sorted(uses) == sorted(res))
    await b.disconnect()
asyncio.run(main())
