"""Live: orphan sweep keeps the live worker's workspace and releases the dead one; prints a hub-side report."""
import asyncio, sys
sys.path.insert(0, ".")
from app import hub_workspace as hw
from app.backend_hub import sweep_orphans
async def main():
    live = {open("/tmp/v1008-proof/current").read().strip()}
    ssh = hw.HubSsh.from_env()
    print("hub dirs before:", [n for n, _ in await ssh.list_workspaces()])
    report = await sweep_orphans(live)
    print("report:", report)
    print("hub dirs after:", [n for n, _ in await ssh.list_workspaces()])
    print("local records:", sorted(p.stem for p in hw.STATE_DIR.glob("hub-*.json")))
asyncio.run(main())
