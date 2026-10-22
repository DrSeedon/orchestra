import asyncio, os, sys
sys.path.insert(0, ".")
os.environ.update({
    "MULTICODE_MCP_BASE": "http://127.0.0.1:14606",
    "MULTICODE_MCP_TOKEN_FILE": "/home/kesha/orchestra/data/secrets/multicode-oauth.token",
    "MULTICODE_HUB_SSH": "<hub-user>@<hub-host>",
    "MULTICODE_HUB_SSH_KEY": "/home/kesha/.ssh/multicode_hub_vps",
})
from app import hub_workspace as hw
from app.backend_hub import release_for_worktree
from app.multicode_client import MultiCodeClient
async def main():
    repo = open("/tmp/v1008-proof/current").read().strip()
    ssh = hw.HubSsh.from_env()
    root = await ssh.root()
    print("before:", (await ssh.run(f"ls {root}")).decode().split())
    print("released:", await release_for_worktree(repo))
    print("after:", (await ssh.run(f"ls {root} 2>&1; true")).decode().split())
    async with MultiCodeClient.from_env() as c:
        r = await c.tool_call("t3_project_list", {"limit": 50})
        print("hub projects titled orchestra*:", [p["title"] for p in r["projects"] if str(p.get("title","")).startswith("orchestra hub-")])
    print("state files left:", list(hw.STATE_DIR.glob("hub-*.json")))
asyncio.run(main())
