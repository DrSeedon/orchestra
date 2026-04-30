"""Orchestra — AI Agent Orchestrator."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.manager import manager
from app.db import get_worker_logs, get_worker as db_get_worker, delete_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await manager.kill_all()


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
    return {**data, "logs": logs}


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
