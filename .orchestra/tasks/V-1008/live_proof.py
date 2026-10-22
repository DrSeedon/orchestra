"""Live proof driver: runs HubBackend directly against the real hub on a throwaway repo."""
import asyncio, os, sys, time
sys.path.insert(0, ".")
os.environ.update({
    "MULTICODE_MCP_BASE": "http://127.0.0.1:14606",
    "MULTICODE_MCP_TOKEN_FILE": "/home/kesha/orchestra/data/secrets/multicode-oauth.token",
    "MULTICODE_HUB_SSH": "<hub-user>@<hub-host>",
    "MULTICODE_HUB_SSH_KEY": "/home/kesha/.ssh/multicode_hub_vps",
})
from app.backend_hub import HubBackend, release_for_worktree

async def turn(b, msg):
    await b.send(msg)
    async for ev in b.events():
        print(f"[{ev.type}] {ev.content[:1500]}")
        if ev.type == "turn_end":
            print({k: ev.metadata[k] for k in ("ok", "stop_reason", "session_id", "cost_usd", "billing_mode")})

async def main():
    repo = open("/tmp/v1008-proof/current").read().strip()
    model = sys.argv[1]
    b = HubBackend(model, repo)
    await b.connect()
    await turn(b, "Fix the bug in calc.py so that test_calc.py passes. Run `python3 -m pytest -q` or plain python asserts if pytest is missing.")
    sid = b.session_id
    print("SESSION", sid)
    if len(sys.argv) > 2 and sys.argv[2] == "followup":
        await turn(b, "Now also add a sub(a, b) function to calc.py and a test for it in test_calc.py.")
    await b.disconnect()
    if len(sys.argv) > 2 and sys.argv[2] == "release" or (len(sys.argv) > 3 and sys.argv[3] == "release"):
        print("released", await release_for_worktree(repo))
asyncio.run(main())
