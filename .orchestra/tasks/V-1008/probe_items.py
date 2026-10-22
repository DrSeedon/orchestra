import asyncio, json, sys
sys.path.insert(0, ".")
from app.multicode_client import MultiCodeClient
async def main():
    tok = open("/home/kesha/orchestra/data/secrets/multicode-oauth.token").read().strip()
    async with MultiCodeClient("http://127.0.0.1:14606", tok) as c:
        t = await c.tool_call("t3_thread_launch", {"title":"v1008 probe","scratch":True,"runtimeMode":"full-access","modelSelection":{"instanceId":"claudeAgent","model":"claude-haiku-5-5"},"message":"Reply with the word one."})
        tid = t["threadId"]
        await c.tool_call("t3_thread_wait", {"threadId":tid,"runId":t["runId"],"timeoutMs":60000})
        s = await c.tool_call("t3_thread_send", {"threadId":tid,"message":"Run `sleep 60` then say two.","mode":"auto"})
        await asyncio.sleep(8)
        await c.tool_call("t3_thread_interrupt", {"threadId":tid})
        w = await c.tool_call("t3_thread_wait", {"threadId":tid,"runId":s["runId"],"timeoutMs":30000})
        print("wait:", w)
        r = await c.tool_call("t3_thread_read", {"threadId":tid,"view":"messages","limit":50})
        for it in r["items"]:
            print({k:(v if k!="text" else str(v)[:60]) for k,v in it.items()})
        await c.tool_call("t3_thread_organize", {"threadId":tid,"action":"archive"})
asyncio.run(main())
