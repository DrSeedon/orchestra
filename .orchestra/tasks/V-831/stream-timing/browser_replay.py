"""V-831: what the browser paints when real CLI streams arrive with their real timing.

Replays timestamped CLI captures (cli_capture.py output) through the production path
ClaudeBackend._convert → AgentSession → broker → SSE → dashboard JS, and samples in the page,
every animation frame, the visible length of the live tool-input card and the streaming text
bubble. Own temp DB, pytest-guarded env; never touches the production server.

Run from the worktree root:
  PYTHONPATH=. uv run --frozen python .orchestra/tasks/V-831/stream-timing/browser_replay.py <label> <capture.jsonl>...
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp(prefix="v831-replay-"))
DB = WORK / "orchestra.db"
os.environ.update({
    "ORCHESTRA_DB_PATH": str(DB), "ORCHESTRA_TASK_REPOSITORY": str(WORK / "tasks"),
    "DASHBOARD_USER": "", "DASHBOARD_PASSWORD": "", "OWNER_MODE": "", "SSH_TUNNELS": "",
    "ORCHESTRA_PROJECT_CATALOG": str(WORK / "projects.yaml"),
    "ORCHESTRA_PROJECT_CATALOG_ROOT": str(WORK / "scopes"), "TG_BRIDGE_TOKEN": "",
})
(WORK / "projects.yaml").write_text("version: 1\nprojects: []\n")
sys.path.insert(0, str(HERE.parents[3]))

from tests.test_frontend import _free_port, _seed_dashboard_db  # noqa: E402

_seed_dashboard_db(DB)

import uvicorn  # noqa: E402
from claude_agent_sdk._internal.message_parser import parse_message  # noqa: E402

from app.main import app  # noqa: E402
from app.deps import manager  # noqa: E402
from app.live_broker import broker  # noqa: E402
from app.backend_claude import ClaudeBackend  # noqa: E402
from app.session import AgentSession, AgentStatus  # noqa: E402

LABEL, CAPTURES = sys.argv[1], sys.argv[2:]
PORT = _free_port()
SAMPLER = """
window.__samples = [];
(function loop(){
  const tool = document.querySelector('.live-tool-input-body');
  const text = document.querySelector('.streaming');
  window.__samples.push([performance.now(), tool ? tool.textContent.length : -1,
                         text ? text.textContent.replace('▍','').length : -1]);
  requestAnimationFrame(loop);
})();
"""


async def drive(ready: asyncio.Event, done: asyncio.Event):
    session = AgentSession(id="fe-orch-id", name="fe-orch", scope="/tmp/fe-scope", cwd="/tmp/fe-scope",
                           model="claude-opus-5-5[1m]", system_prompt="", is_orchestrator=True,
                           created_at=datetime.now(timezone.utc))
    session.status = AgentStatus.RUNNING
    manager.sessions[session.id] = session
    while not broker._subs.get(session.id):
        await asyncio.sleep(0.1)
    await ready.wait()
    for capture in CAPTURES:
        backend = ClaudeBackend(model="claude-opus-5-5", cwd="/tmp")
        rows = [json.loads(line) for line in open(capture)]
        start = time.monotonic()
        for row in rows:
            data = row["line"]
            if data.get("type") != "stream_event":
                continue  # partials only: the measured thing is the live view
            delay = row["t"] - (time.monotonic() - start) - rows[0]["t"]
            if delay > 0:
                await asyncio.sleep(delay)
            msg = parse_message(data)
            if msg is not None:
                for event in backend._convert(msg):
                    session._handle_event(event)
        await asyncio.sleep(1.5)
    done.set()


def browse(loop, ready, done):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script("localStorage.setItem('orch_lang','ru')")
        page.goto(f"http://127.0.0.1:{PORT}/")
        page.wait_for_selector('.agent-item[data-agent-name="fe-orch"]', timeout=20000)
        page.click('.agent-item[data-agent-name="fe-orch"]')
        time.sleep(2)
        page.evaluate(SAMPLER)
        loop.call_soon_threadsafe(ready.set)
        shot = 0
        while not done.is_set():
            time.sleep(0.25)
            if shot < 3 and page.locator(".live-tool-input-card").count():
                time.sleep(2)
                page.screenshot(path=str(HERE / f"replay-{LABEL}-{shot}.png"))
                shot += 3
        samples = page.evaluate("window.__samples")
        browser.close()
    (HERE / f"replay-{LABEL}-samples.json").write_text(json.dumps(samples))
    return samples


def summarize(samples, column, name):
    q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))] if xs else None
    series = [(t, s[column]) for s in samples for t in [s[0]] if s[column] >= 0]
    changes = []
    for (t0, a), (t1, b) in zip(series, series[1:]):
        if b > a:
            changes.append((t1, b - a))
    if not changes:
        return f"{name}: no growth observed"
    jumps = [c for _, c in changes]
    stalls = [round(b[0] - a[0]) for a, b in zip(changes, changes[1:])]
    return (f"{name}: paint updates={len(changes)} chars/update p50/p90/max={q(jumps,.5)}/{q(jumps,.9)}/{max(jumps)} "
            f"ms between updates p50/p90/max={q(stalls,.5)}/{q(stalls,.9)}/{max(stalls) if stalls else 0}")


async def main():
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    serve = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.1)
    ready, done = asyncio.Event(), asyncio.Event()
    driver = asyncio.create_task(drive(ready, done))
    samples = await asyncio.to_thread(browse, asyncio.get_running_loop(), ready, done)
    await driver
    report = [f"label={LABEL} captures={CAPTURES} frames_sampled={len(samples)}",
              summarize(samples, 1, "tool-input card"), summarize(samples, 2, "text bubble")]
    (HERE / f"replay-{LABEL}.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    server.should_exit = True
    await serve


asyncio.run(main())
