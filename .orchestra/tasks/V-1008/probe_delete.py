import asyncio, json, os, sys
sys.path.insert(0, ".")
from app import hub_workspace as hw
from app.multicode_client import MultiCodeClient, MultiCodeError
async def main():
    ws = sys.argv[1]
    st = hw.WorkspaceState.load(ws)
    tok = open("/home/kesha/orchestra/data/secrets/multicode-oauth.token").read().strip()
    async with MultiCodeClient("http://127.0.0.1:14606", tok) as c:
        async def probe(label):
            pl = await c.tool_call("t3_project_list", {"limit": 100})
            print(label, "project listed:", st.project_id in [p["id"] for p in pl["projects"]],
                  "| all projects:", len(pl["projects"]))
            for kw in ({}, {"settled": True}):
                try:
                    tl = await c.tool_call("t3_thread_list", {"projectId": st.project_id, "limit": 50, **kw})
                    print(label, "thread_list", kw, [t["threadId"] for t in tl["threads"]])
                except MultiCodeError as e:
                    print(label, "thread_list", kw, "ERR", str(e)[:120])
            try:
                await c.tool_call("t3_thread_read", {"threadId": st.thread_id, "view": "messages", "limit": 5})
                print(label, "thread_read: STILL READABLE")
            except MultiCodeError as e:
                print(label, "thread_read ERR:", str(e)[:150])
        await probe("before")
        r = await c.tool_call("t3_project_delete", {"projectId": st.project_id, "force": True})
        print("deleted ->", {k: r.get(k) for k in ("id", "deletedAt")})
        await asyncio.sleep(3)
        await probe("after")
asyncio.run(main())
