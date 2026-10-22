"""Live: native Sonnet -> hub Sonnet -> native Sonnet in one AgentSession (throwaway DB and repo).
Each turn asks for something only the earlier turns know."""
import asyncio, os, sys, tempfile
os.environ["ORCHESTRA_DB_PATH"] = tempfile.mkstemp(prefix="v1008-switch-", suffix=".db")[1]
sys.path.insert(0, ".")
from datetime import datetime, timezone
from app import db
db.init_db()
from app.events import MessageProvenance
import app.session as _session_module
from app.session import AgentSession, AgentStatus
# Proof harness only: our Claude quota gate is closed right now, and these are three tiny Haiku turns.
import app.quota_gate as _qg
_qg.require_worker_admission = lambda decision: None

NATIVE = os.environ.get("NATIVE_MODEL", "claude-haiku-5-5")
USER = MessageProvenance(origin="user", senders=("user",))

async def say(session, text, first=False):
    before = len(db.get_logs(session.id))
    if first:
        await session.start(text, provenance=USER)
    else:
        await session.send(text, provenance=USER)
    for _ in range(600):
        await asyncio.sleep(1)
        if session.status == AgentStatus.IDLE and any(r["type"] == "text" for r in db.get_logs(session.id)[before:]):
            break
    rows = db.get_logs(session.id)[before:]
    texts = [r["content"] for r in rows if r["type"] == "text"]
    tools = [r["content"][:70] for r in rows if r["type"] == "tool"]
    print(f"\n>>> [{session.model} / {session.backend_type}] {text[:90]}")
    for t in tools: print("    tool:", t)
    print("    reply:", (texts[-1] if texts else "(none)")[:400].replace("\n", " "))
    return texts[-1] if texts else ""

async def main():
    repo = open("/tmp/v1008-proof/current").read().strip()
    session = AgentSession(id="sw-1", name="switchw", scope=repo, cwd=repo, model=NATIVE,
                           system_prompt="You are a terse test worker.", role="worker",
                           created_at=datetime.now(timezone.utc))
    db.save_session(session._to_db_dict())   # the real manager persists the row before any log
    r1 = await say(session, "Remember this code word: PELICAN-4417. Create a file notes.txt containing it. Reply 'ok'.", first=True)
    print(await session.change_model("hub-claude-sonnet-5-5"))
    r2 = await say(session, "What code word did I ask you to remember earlier? Also add a line 'hub was here' to notes.txt and tell me the new line count.")
    print(await session.change_model(NATIVE))
    r3 = await say(session, "Which line did the previous agent add to notes.txt, and which code word was it asked about? Answer briefly from the conversation.")
    ok = ("PELICAN-4417" in r2, "hub was here" in r3.lower() and "PELICAN-4417" in r3)
    print("\nRESULT hub knew the earlier native turn:", ok[0], "| native knew the hub turn:", ok[1])
    await session._disconnect_backend()
asyncio.run(main())
