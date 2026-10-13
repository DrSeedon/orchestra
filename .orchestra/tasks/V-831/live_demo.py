"""V-831 live check: a throwaway dashboard fed by a REAL CLI capture, screenshotted mid-write.

Run from the worktree root: PYTHONPATH=. uv run --frozen python .orchestra/tasks/V-831/live_demo.py
Uses its own temp DB/task store; never touches the production server or DB.
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

TASK = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp(prefix="v831-demo-"))
DB = WORK / "orchestra.db"
os.environ.update({
    "ORCHESTRA_DB_PATH": str(DB), "ORCHESTRA_TASK_REPOSITORY": str(WORK / "tasks"),
    "DASHBOARD_USER": "", "DASHBOARD_PASSWORD": "", "OWNER_MODE": "", "SSH_TUNNELS": "",
    "CLAUDE_CODE_TMPDIR": str(WORK), "ORCHESTRA_PROJECT_CATALOG": str(WORK / "projects.yaml"),
    "ORCHESTRA_PROJECT_CATALOG_ROOT": str(WORK / "scopes"), "TG_BRIDGE_TOKEN": "",
})
(WORK / "projects.yaml").write_text("version: 1\nprojects: []\n")
sys.path.insert(0, str(TASK.parents[2]))

from tests.test_frontend import _free_port, _seed_dashboard_db  # noqa: E402

_seed_dashboard_db(DB)

import uvicorn  # noqa: E402
from claude_agent_sdk._internal.message_parser import parse_message  # noqa: E402
from claude_agent_sdk import AssistantMessage, ToolUseBlock  # noqa: E402

from app.main import app  # noqa: E402
from app.deps import manager  # noqa: E402
from app.live_broker import broker  # noqa: E402
from app.backend_claude import ClaudeBackend  # noqa: E402
from app.events import AgentEvent  # noqa: E402
from app.session import AgentSession, AgentStatus  # noqa: E402

PORT = _free_port()
SHOTS = TASK / "screens"
SHOTS.mkdir(exist_ok=True)


async def drive():
    session = AgentSession(id="fe-orch-id", name="fe-orch", scope="/tmp/fe-scope", cwd="/tmp/fe-scope",
                           model="claude-opus-5-5[1m]", system_prompt="", is_orchestrator=True,
                           created_at=datetime.now(timezone.utc))
    session.status = AgentStatus.RUNNING
    manager.sessions[session.id] = session
    while not broker._subs.get(session.id):
        await asyncio.sleep(0.2)
    await asyncio.sleep(1.5)
    backend = ClaudeBackend(model="claude-haiku-5-5", cwd="/tmp")
    tool_id = ""
    tool_input = None
    lines = (TASK / "capture" / "stream.jsonl").read_text().splitlines()
    for line in lines:
        data = json.loads(line)
        if data.get("type") in ("user", "result", "system", "rate_limit_event"):
            continue
        msg = parse_message(data)
        if msg is None:
            continue
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, ToolUseBlock):
                    tool_id, tool_input = block.id, block.input
        for event in backend._convert(msg):
            session._handle_event(event)
        if data.get("type") == "stream_event":
            await asyncio.sleep(0.035)
    # The model's call finished; the CLI now runs it as a shell task with an output file.
    tasks = WORK / f"claude-{os.getuid()}" / "-tmp-fe-scope" / "sdk-demo" / "tasks"
    tasks.mkdir(parents=True)
    out = tasks / "bdemo1.output"
    proc = subprocess.Popen(
        ["bash", "-c", "for i in $(seq 1 40); do echo \"element $i: computing facts… ok\"; sleep 0.5; done"],
        stdout=out.open("wb"), stderr=subprocess.STDOUT)
    await asyncio.sleep(2.5)  # the CLI announces a shell task after a few seconds
    session._handle_event(AgentEvent(
        "subagent_start", f"{tool_input.get('description', 'Run script')} | type=local_bash | id=bdemo1 | "
        f"tool_use_id={tool_id}",
        metadata={"subagent_id": "bdemo1", "phase": "start", "task_type": "local_bash",
                  "description": tool_input.get("description", ""), "sdk_session_id": "sdk-demo",
                  "tool_use_id": tool_id}))
    while proc.poll() is None:
        await asyncio.sleep(0.5)
    session._handle_event(AgentEvent(
        "subagent_end", "done | type=local_bash | id=bdemo1 | status=completed",
        metadata={"subagent_id": "bdemo1", "task_type": "local_bash", "tool_use_id": tool_id,
                  "status": "completed"}))
    session._handle_event(AgentEvent("tool_result", out.read_text()[-2000:],
                                     metadata={"tool_use_id": tool_id, "is_error": False}))
    session.status = AgentStatus.IDLE


def browse():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script("localStorage.setItem('orch_lang','ru')")
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.wait_for_selector('.agent-item[data-agent-name="fe-orch"]', timeout=20000)
        page.click('.agent-item[data-agent-name="fe-orch"]')
        page.wait_for_selector(".live-tool-input-card", timeout=60000)
        time.sleep(18)
        page.screenshot(path=str(SHOTS / "1-writing-call.png"))
        card = page.locator(".live-tool-input-card")
        card.screenshot(path=str(SHOTS / "1-writing-call-card.png"))
        page.wait_for_selector(".tool-run-clock", timeout=90000)
        page.wait_for_selector(".codex-live-output", timeout=30000)
        time.sleep(6)
        page.screenshot(path=str(SHOTS / "2-running-with-output.png"))
        page.locator(".tool-running").first.screenshot(path=str(SHOTS / "2-running-bash-card.png"))
        page.locator("[data-subagent-id='bdemo1']").screenshot(path=str(SHOTS / "2-running-task-card.png"))
        page.wait_for_function("!document.querySelector('.tool-run-clock')", timeout=60000)
        time.sleep(1)
        page.screenshot(path=str(SHOTS / "3-finished.png"))
        logs = page.evaluate("JSON.stringify([...document.querySelectorAll('.live-tool-input-card')].length)")
        print("live cards left after finish:", logs)
        browser.close()


async def main():
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    serve = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.1)
    driver = asyncio.create_task(drive())
    await asyncio.to_thread(browse)
    await driver
    rows = sqlite3.connect(DB).execute(
        "select type, count(*) from logs where session_id='fe-orch-id' group by type").fetchall()
    print("persisted rows by type:", rows)
    server.should_exit = True
    await serve


asyncio.run(main())
