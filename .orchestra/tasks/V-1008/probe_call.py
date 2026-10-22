import asyncio, json, sys
sys.path.insert(0, ".")
from app.multicode_client import MultiCodeClient
async def main():
    tok = open("/home/kesha/orchestra/data/secrets/multicode-oauth.token").read().strip()
    name = sys.argv[1]; args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    async with MultiCodeClient("http://127.0.0.1:14606", tok) as c:
        r = await c.tool_call(name, args)
        print(json.dumps(r, indent=1, ensure_ascii=False)[:int(sys.argv[3]) if len(sys.argv)>3 else 6000])
asyncio.run(main())
