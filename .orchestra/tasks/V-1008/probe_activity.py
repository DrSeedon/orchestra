import asyncio, json, sys
sys.path.insert(0, ".")
from app.multicode_client import MultiCodeClient
async def main():
    model = sys.argv[1]; inst = sys.argv[2]
    async with MultiCodeClient.from_env() as c:
        t = await c.tool_call("t3_thread_launch", {"title":"v1008 activity probe","scratch":True,"runtimeMode":"full-access",
            "modelSelection":{"instanceId":inst,"model":model},
            "message":sys.argv[3]})
        tid, rid = t["threadId"], t["runId"]
        pos = 0; seen = []
        for _ in range(30):
            r = await c.tool_call("t3_thread_read", {"threadId": tid, "view": "activity", "afterPosition": pos, "limit": 50, "maxCharsPerItem": 400})
            for it in r["items"]:
                seen.append(it)
                print(it["position"], it["type"], it["status"], repr(it.get("title")), repr((it.get("text") or "")[:100]))
            pos = r.get("nextPosition", pos) or pos
            st = r["thread"]["status"]
            if st in ("completed","failed","interrupted","cancelled") and not r["items"]:
                break
            await asyncio.sleep(2)
        print("keys of read:", [k for k in r.keys()], "nextPosition", r.get("nextPosition"))
        await c.tool_call("t3_thread_organize", {"threadId": tid, "action": "archive"})
asyncio.run(main())
