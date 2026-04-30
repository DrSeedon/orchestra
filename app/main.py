"""Orchestra — AI Agent Orchestrator."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.manager import manager
from app.orchestrator import orchestrator
from app.db import get_worker_logs, get_worker as db_get_worker, delete_worker, add_callback, get_unread_callbacks, mark_callbacks_read


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await manager.kill_all()
    await orchestrator.stop()


app = FastAPI(title="Orchestra", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    workers = manager.list_all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "workers": workers,
        "active": manager.active_count(),
    })


@app.get("/api/workers")
async def api_workers():
    return manager.list_all()


@app.get("/api/workers/{name}")
async def api_worker(name: str):
    w = manager.get(name)
    if w:
        data = w.to_dict()
        logs = [{"ts": l.ts.isoformat(), "type": l.type, "content": l.content} for l in w.logs[-100:]]
    else:
        data = db_get_worker(name)
        if not data:
            return JSONResponse({"error": "not found"}, 404)
        logs = get_worker_logs(name, limit=100)
    sysprompt = ""
    live = manager.get(name)
    if live and live.system_prompt:
        sysprompt = live.system_prompt
    elif data.get("system_prompt"):
        sysprompt = data["system_prompt"]
    return {**data, "logs": logs, "system_prompt": sysprompt}


@app.post("/api/workers/spawn")
async def api_spawn(request: Request):
    body = await request.json()
    name = body["name"]
    task = body["task"]
    repo_path = body["repo_path"]
    model = body.get("model", "claude-sonnet-4-6")
    worker = await manager.spawn(name, task, repo_path, model)
    return worker.to_dict()


@app.post("/api/workers/{name}/inject")
async def api_inject(name: str, request: Request):
    body = await request.json()
    ok = await manager.inject(name, body["message"])
    return {"ok": ok}


@app.post("/api/workers/{name}/interrupt")
async def api_interrupt(name: str):
    await manager.interrupt(name)
    return {"ok": True}


@app.post("/api/workers/{name}/kill")
async def api_kill(name: str):
    await manager.kill(name)
    return {"ok": True}


@app.delete("/api/workers/{name}")
async def api_remove(name: str):
    await manager.remove(name)
    delete_worker(name)
    return {"ok": True}


@app.get("/api/stats")
async def api_stats():
    return manager.stats()


@app.post("/api/workers/{name}/callback")
async def api_callback(name: str, request: Request):
    body = await request.json()
    msg = body.get("message", "")
    cb_id = add_callback(name, msg)
    return {"ok": True, "id": cb_id}


@app.get("/api/callbacks")
async def api_get_callbacks():
    return get_unread_callbacks()


@app.post("/api/callbacks/read")
async def api_mark_read():
    count = mark_callbacks_read()
    return {"marked": count}


# === Orchestrator endpoints ===

@app.post("/api/orchestrator/start")
async def api_orch_start(request: Request):
    body = await request.json() if await request.body() else {}
    cwd = body.get("cwd", "/mnt/data/Projects/Python/Parsing")
    await orchestrator.start(cwd)
    return {"ok": True, "status": "connected"}


@app.post("/api/orchestrator/spawn")
async def api_orch_spawn(request: Request):
    body = await request.json()
    info = await orchestrator.spawn_worker(
        name=body["name"],
        task=body["task"],
        repo_path=body["repo_path"],
        model=body.get("model", "claude-sonnet-4-6"),
    )
    asyncio.create_task(orchestrator.listen())
    return info


@app.post("/api/orchestrator/send")
async def api_orch_send(request: Request):
    body = await request.json()
    await orchestrator.send(body["message"])
    return {"ok": True}


@app.get("/api/orchestrator/status")
async def api_orch_status():
    return {
        "connected": orchestrator._connected,
        "session_id": orchestrator._session_id,
        "workers": orchestrator._workers,
    }
