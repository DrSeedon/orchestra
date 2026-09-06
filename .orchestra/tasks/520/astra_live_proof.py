import asyncio, os, sys, time, uuid
sys.path.insert(0, os.getcwd())
import app.backend_codex as bc
from app.backend_codex import CodexBackend

SID = "astra-proof-" + uuid.uuid4().hex[:8]

async def main():
    home = bc._CODEX_HOME_ROOT / SID
    print(f"module   : {bc.__file__}")
    print(f"fresh home: {home} (exists={home.exists()})")
    be = CodexBackend(
        model="gpt-6-astra",
        cwd=os.getcwd(),
        system_prompt="You are a smoke test. Answer with one short line.",
        mcp_servers={"orchestra": {"command": "/bin/true", "args": [],
                                   "env": {"ORCHESTRA_SESSION_ID": SID}}},
        reasoning_effort="medium",
    )
    t0 = time.monotonic()
    await asyncio.wait_for(be.connect(), timeout=900)
    t_conn = time.monotonic() - t0
    pid = be._proc.pid if be._proc else None
    print(f"CONNECTED in {t_conn:.1f}s  thread_id={be._thread_id}  launcher_pid={pid}")
    os.system("pgrep -af 'codex.*app-server' | head -3")

    await be.send("Run exactly one command: `echo ASTRA_LIVE_OK`. Then reply with its output only.")
    text = []
    t1 = time.monotonic()
    async for ev in be.events():
        if ev.type in ("text", "assistant", "message"):
            text.append(str(ev.content))
        print(f"  event: {ev.type}: {str(ev.content)[:120]}")
        if ev.type in ("turn_complete", "result", "done", "turn_failed"):
            break
        if time.monotonic() - t1 > 600:
            print("  (timeout waiting for turn end)"); break
    print(f"ANSWER after {time.monotonic()-t1:.1f}s:\n{''.join(text)[:800]}")
    await be.disconnect()

asyncio.run(main())
