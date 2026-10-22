import asyncio, os, sys
sys.path.insert(0, ".")
# hub settings come from the process environment (MULTICODE_*), never from this file
from app.backend_hub import HubBackend
async def main():
    repo = open("/tmp/v1008-proof/current").read().strip()
    b = HubBackend(sys.argv[1], repo); await b.connect()
    await b.send("Change g() in m.py to return 3 and tell me the marker word QUOKKA-TRACE-6643.")
    async for ev in b.events():
        if ev.type in ("text", "error"): print(ev.type, ev.content[:300])
    print("WS", b.session_id)
    await b.disconnect()
asyncio.run(main())
