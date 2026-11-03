"""Synthetic V-1160 trigger replay: steer -> deferred interrupt -> WAITING -> mailbox.

Run from the copy root:  uv run --frozen python .orchestra/tasks/V-1160/repro_trigger.py
No provider, no live DB: temp SQLite, real CodexBackend with a fake JSON-RPC transport.
"""

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app import bg_jobs, db, mailbox, message_deliveries  # noqa: E402
from app.events import MessageProvenance  # noqa: E402

USER = MessageProvenance(origin="user", senders=("user",), subtype="dashboard")


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(dir=Path(__file__).parent))
    db.DB_PATH = tmp / "repro.db"
    db.init_db()
    logs: list[tuple[str, str, dict]] = []

    import app.session as session_module
    session_module.save_session = lambda *_a, **_k: None

    def add_log(session_id, ts, kind, content, *args, **kwargs):
        logs.append((kind, content, kwargs))
        return len(logs)

    session_module.add_log = add_log
    from app.backend_codex import CodexBackend
    from app.session import AgentSession, AgentStatus

    session = AgentSession(
        id="orch-1160", name="orch", scope="/scope-1160", cwd=str(tmp),
        model="gpt-6-luna", system_prompt="SYSTEM PROMPT " * 50,
        created_at=datetime.now(timezone.utc),
    )
    session.is_orchestrator = True
    session.backend_type = "codex"
    session.session_id = "thread-1160"
    session._prompt_injected = True
    requests: list[tuple[str, dict]] = []
    backend = CodexBackend(model="gpt-6-luna", cwd=str(tmp))
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = "thread-1160"
    backend._active_turn_id = "turn-A"
    turn_no = 0

    async def request(method, params):
        nonlocal turn_no
        requests.append((method, params))
        if method == "turn/start":
            turn_no += 1
            return {"turn": {"id": f"turn-B{turn_no}"}}
        return {}

    backend._request = request
    session._backend = backend
    session.status = AgentStatus.RUNNING
    session._turn_start = 1.0
    session._persist = lambda: None
    session._hibernate.schedule = lambda: None
    bg_jobs.bg_manager = SimpleNamespace(has_active_jobs=lambda sid: sid == session.id)

    # Two owner steers into the running native turn (non-durable path: backup rows).
    await session.send("owner steer 1", provenance=USER)
    await session.send("owner steer 2", provenance=USER)
    print("mailbox after steers:", [(m["body"], m["provenance"].subtype) for m in mailbox.pending("orch", "/scope-1160")])

    control = {
        "kind": "deferred_job", "origin": "orchestra.bg_jobs", "job_id": "bg-1160",
        "event_id": "bgjob:v1:bg-1160:completed", "turn_control": "interrupt",
    }
    await backend._notifications.put({"method": "item/completed", "params": {
        "threadId": "thread-1160", "turnId": "turn-A",
        "item": {"id": "tool-1", "type": "mcpToolCall", "server": "orchestra",
                 "tool": "codex_review", "arguments": {},
                 "result": {"content": [], "structuredContent": {"result": control, "error": None},
                            "isError": False}}}})
    await backend._notifications.put({"method": "turn/completed", "params": {
        "threadId": "thread-1160", "turn": {"id": "turn-A", "status": "interrupted", "items": []}}})
    await asyncio.wait_for(session._turn_event_loop(), timeout=2)
    await asyncio.sleep(1.0)
    print("status:", session.status)
    print("requests:", [m for m, _ in requests])
    for method, params in requests:
        if method == "turn/start":
            print("turn/start input:\n", params["input"][0]["text"])
    print("logs:")
    for kind, content, _ in logs:
        print(f"  {kind}: {content[:160]!r}")
    print("mailbox now:", mailbox.pending("orch", "/scope-1160"))


asyncio.run(main())
