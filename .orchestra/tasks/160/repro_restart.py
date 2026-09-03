"""#160 repro: does a worker that was RUNNING at shutdown get woken after restart?

Pass/fail fixed BEFORE the run (no goalpost moving):
  PASS = worker that was running at shutdown receives a restart notice after auto_resume_all.
  FAIL = no notice (worker sits idle forever).

Two arms, same worker:
  A) graceful restart  — lifespan shutdown (shutdown_all) then startup (auto_resume_all)
  B) hard kill         — no shutdown_all at all (SIGKILL / OOM), then startup
"""
import asyncio, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


async def arm(graceful: bool) -> dict:
    tmp = Path(tempfile.mkdtemp())
    import app.db as db_mod
    db_mod.DB_PATH = tmp / "test.db"
    from app.db import init_db, save_session, _conn
    init_db()

    import app.workspace as ws
    (tmp / "worktrees").mkdir()
    ws.WORKTREE_ROOT = tmp / "worktrees"

    from app.manager import SessionManager
    from app.session import AgentSession, AgentStatus

    proj = tmp / "proj"; proj.mkdir()
    mgr = SessionManager()

    # A worker mid-turn: status RUNNING, live session_id.
    sess = AgentSession(
        id="w1", name="worker-1", scope=str(proj), cwd=str(proj),
        model="claude-opus-5[1m]", system_prompt="x", session_id="sdk-token-1",
        created_at=datetime.now(timezone.utc), role="worker", pipeline="default",
    )
    sess.status = AgentStatus.RUNNING
    sess._backend = None
    sess._disconnect_backend = AsyncMock()
    mgr.sessions[sess.id] = sess
    save_session(sess._to_db_dict())

    with _conn() as c:
        before = c.execute("SELECT status FROM sessions WHERE id='w1'").fetchone()["status"]

    # ── restart boundary ──
    if graceful:
        await mgr.shutdown_all()          # exactly what lifespan does on stop
        await sess._drain_persist()

    with _conn() as c:
        at_boot = c.execute("SELECT status FROM sessions WHERE id='w1'").fetchone()["status"]

    # fresh process
    mgr2 = SessionManager()
    woken = []
    mgr2.send = AsyncMock(side_effect=lambda sid, msg: woken.append((sid, msg)))
    await mgr2.auto_resume_all()
    await asyncio.sleep(17)               # stagger is 3 + rand(0,12)

    return {"graceful": graceful, "status_before_restart": before,
            "status_seen_by_startup": at_boot,
            "restored": "w1" in mgr2.sessions, "woken": len(woken)}


async def main():
    for graceful in (True, False):
        r = await arm(graceful)
        label = "A graceful restart (systemctl restart)" if graceful else "B hard kill (SIGKILL/OOM)"
        verdict = "PASS — woken" if r["woken"] else "FAIL — sits idle, nobody wakes it"
        print(f"\n{label}")
        print(f"  status before restart      : {r['status_before_restart']}")
        print(f"  status seen by auto_resume : {r['status_seen_by_startup']}")
        print(f"  session restored into list : {r['restored']}")
        print(f"  restart notices sent       : {r['woken']}  -> {verdict}")


asyncio.run(main())
