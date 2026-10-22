"""Live: mid-turn steer and interrupt on a real hub thread (haiku, throwaway repo)."""
import asyncio, os, sys, time
sys.path.insert(0, ".")
# hub settings come from the process environment (MULTICODE_*), never from this file
from app.backend_hub import HubBackend, release_for_worktree

async def drain(b, label):
    async for ev in b.events():
        if ev.type in ("text", "error", "turn_end"):
            print(f"{label} [{ev.type}] {ev.content[:400]!r}", ev.metadata.get("stop_reason", "") if ev.type == "turn_end" else "")

async def main():
    repo = open("/tmp/v1008-proof/current").read().strip()
    b = HubBackend("hub-claude-haiku-5-5", repo)
    await b.connect()
    # steer
    await b.send("Run the shell command `sleep 45` first, then reply with the single word DONE.")
    t = asyncio.create_task(drain(b, "steer-run"))
    await asyncio.sleep(25)
    t0 = time.time()
    await b.send("Change of plan: do not wait further; reply with exactly STEERED now.")
    await t
    print("steer run total after steer msg: %.0fs" % (time.time() - t0))
    # interrupt
    await b.send("Run the shell command `sleep 120`, then reply DONE.")
    t = asyncio.create_task(drain(b, "int-run"))
    await asyncio.sleep(20)
    t0 = time.time()
    await b.interrupt()
    await t
    print("interrupt returned %.0fs after interrupt()" % (time.time() - t0))
    await b.disconnect()
    print("released", await release_for_worktree(repo))
asyncio.run(main())
