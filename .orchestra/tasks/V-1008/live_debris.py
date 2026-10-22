"""Live: an UNRECORDED hub project + directory older than the age floor is removed by the sweep."""
import asyncio, os, sys
sys.path.insert(0, ".")
from app import hub_workspace as hw
from app.backend_hub import sweep_orphans
from app.multicode_client import MultiCodeClient
async def main():
    ssh = hw.HubSsh.from_env(); root = await ssh.root()
    ws = "hub-9999999999999999"; d = f"{root}/{ws}"
    await ssh.run(f"mkdir -p {d} && echo debris > {d}/x.txt && touch -d '3 hours ago' {d}")
    async with MultiCodeClient.from_env() as mc:
        p = await mc.tool_call("t3_project_create", {"title": f"orchestra {ws}", "workspaceRoot": d})
        print("created debris project", bool(p["id"]))
    live = {open("/tmp/v1008-proof/current").read().strip()}
    print("report:", await sweep_orphans(live))
    print("hub dirs after:", [n for n, _ in await ssh.list_workspaces()])
    async with MultiCodeClient.from_env() as mc:
        pl = await mc.tool_call("t3_project_list", {"limit": 100})
        print("debris project still listed:", any(x["workspaceRoot"] == d for x in pl["projects"]))
asyncio.run(main())
