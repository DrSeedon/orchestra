"""Live: persistent project copy. Two hub workers of one throwaway project; the second sends only the delta."""
import asyncio, json, os, sys, tempfile
sys.path.insert(0, ".")
from pathlib import Path
from app import hub_workspace as hw
from app.backend_hub import HubBackend, release_for_worktree

async def turn(b, text):
    await b.send(text)
    out = []
    async for ev in b.events():
        if ev.type == "status": print("   ", ev.content)
        if ev.type == "text": out.append(ev.content[:120].replace("\n", " "))
    print("    reply:", out[-1] if out else None)

async def main():
    root = Path(open("/tmp/v1008-proof/current").read().strip())
    for i in range(40): (root / f"mod{i}.py").write_text(f"VALUE = {i}\n" * 50)
    import subprocess; subprocess.run(["git", "-C", str(root), "add", "."], check=True); subprocess.run(["git", "-C", str(root), "commit", "-qm", "files"], check=True)
    table = Path(tempfile.mkstemp(suffix=".json")[1]); table.write_text(json.dumps({str(root): {"persistent": True}}))
    os.environ["MULTICODE_HUB_PROJECTS_FILE"] = str(table)
    w1 = HubBackend("hub-claude-haiku-5-5", str(root), scope=str(root)); await w1.connect()
    print("worker 1:"); await turn(w1, "Reply with the single word ready.")
    await release_for_worktree(str(root))
    print("worker 1 released; warm copy kept:", hw.BaseState.load(str(root)).manifest.__len__(), "files in the base manifest")
    (root / "mod3.py").write_text("VALUE = 333\n"); (root / "new.py").write_text("x = 1\n")
    w2 = HubBackend("hub-claude-haiku-5-5", str(root), scope=str(root)); await w2.connect()
    print("worker 2:"); await turn(w2, "Reply with the value in mod3.py and nothing else.")
    ssh = hw.HubSsh.from_env()
    print("hub dirs:", sorted(n for n in (await ssh.run(f"ls {await ssh.root()}")).decode().split()))
    await release_for_worktree(str(root))
    await hw.drop_base(str(root), ssh)
    print("after release + drop_base:", sorted((await ssh.run(f"ls {await ssh.root()}")).decode().split()))
asyncio.run(main())
