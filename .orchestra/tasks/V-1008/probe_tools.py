import asyncio, json, os, sys
sys.path.insert(0, ".")
from app.multicode_client import MultiCodeClient
async def main():
    tok = open("/home/kesha/orchestra/data/secrets/multicode-oauth.token").read().strip()
    async with MultiCodeClient("http://127.0.0.1:14606", tok) as c:
        await c.initialize()
        r, _ = await c._post({"jsonrpc":"2.0","id":99,"method":"tools/list","params":{}})
        names = {}
        for t in r["result"]["tools"]:
            names[t["name"]] = t
        want = sys.argv[1:]
        if not want:
            print(sorted(names))
        for w in want:
            print(json.dumps(names[w], indent=1)[:int(__import__("os").environ.get("N","3500"))])
asyncio.run(main())
