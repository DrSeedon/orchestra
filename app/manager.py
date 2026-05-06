"""SessionManager — registry, lifecycle, persistence for all agent sessions."""

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.session import AgentSession, AgentStatus
from app.workspace import create_worktree, remove_worktree
from app.models import resolve_model
from app.db import (
    save_session, get_session_by_name, get_all_sessions,
    delete_session, get_stats, get_resumable_orchestrators,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).parent.parent)
MCP_STDIO_CMD = [sys.executable, "-m", "app.mcp_stdio"]
MCP_BASE_ENV = {
    "PYTHONPATH": _PROJECT_ROOT,
    "HTTPS_PROXY": "http://127.0.0.1:12334",
    "HTTP_PROXY": "http://127.0.0.1:12334",
    "NO_PROXY": "localhost,127.0.0.1",
}

COLOR_PALETTE = [
    "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
    "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
]

_ORCH_PROMPT_PATH = Path(__file__).parent / "orchestrator_prompt.md"
_WORKER_PROMPT_PATH = Path(__file__).parent / "worker_prompt.md"
ORCHESTRATOR_SYSTEM_PROMPT = _ORCH_PROMPT_PATH.read_text() if _ORCH_PROMPT_PATH.exists() else ""
WORKER_SYSTEM_PROMPT = _WORKER_PROMPT_PATH.read_text() if _WORKER_PROMPT_PATH.exists() else ""


def _make_mcp_config(name: str, scope: str, is_orch: bool) -> dict:
    env = {
        **MCP_BASE_ENV,
        "ORCHESTRA_URL": "http://127.0.0.1:8888",
        "ORCHESTRA_SCOPE": scope,
        "ORCHESTRA_ROLE": name if is_orch else "worker",
        "WORKER_NAME": name,
    }
    return {"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": env, "alwaysLoad": True}}


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, AgentSession] = {}
        self._spawn_queue: asyncio.Queue = asyncio.Queue()
        self._spawn_task: asyncio.Task | None = None

    def start_background_tasks(self) -> None:
        if not self._spawn_task or self._spawn_task.done():
            self._spawn_task = asyncio.create_task(self._spawn_worker_loop())

    async def enqueue_worker_spawn(self, **job) -> None:
        await self._spawn_queue.put(job)

    async def _spawn_worker_loop(self) -> None:
        from app.db import update_job
        while True:
            job = await self._spawn_queue.get()
            job_id = job.get("job_id", "?")
            try:
                update_job(job_id, "executing")
                await asyncio.sleep(0.5)
                session = await self.create_session(
                    name=job["name"], scope=job["repo_path"], cwd=job["repo_path"],
                    model=job["model"], system_prompt=job.get("system_prompt", ""),
                    use_worktree=True, repo_path=job["repo_path"],
                )
                await session.send(job["task"])
                update_job(job_id, "succeeded")
                logger.info(f"Worker '{job['name']}' spawned (job {job_id})")
            except Exception as e:
                update_job(job_id, "failed", str(e))
                logger.error(f"Spawn '{job.get('name')}' failed (job {job_id}): {e}")
            finally:
                self._spawn_queue.task_done()

    # ── Session CRUD ──

    async def create_session(self, name: str, scope: str, cwd: str, model: str,
                             system_prompt: str = "", use_worktree: bool = False,
                             repo_path: str | None = None, is_orchestrator: bool = False) -> AgentSession:
        scope = scope.rstrip("/")
        cwd = cwd.rstrip("/")
        model = resolve_model(model)
        if not Path(cwd).is_dir():
            raise ValueError(f"cwd does not exist: {cwd}")
        if get_session_by_name(name, scope):
            raise ValueError(f"session '{name}' already exists in scope '{scope}'")

        if is_orchestrator:
            prompt = system_prompt or ORCHESTRATOR_SYSTEM_PROMPT
        else:
            prompt = WORKER_SYSTEM_PROMPT + ("\n\n" + system_prompt if system_prompt else "")

        session = AgentSession(
            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
            system_prompt=prompt, is_orchestrator=is_orchestrator,
            color=self._pick_color(), mcp_servers=_make_mcp_config(name, scope, is_orchestrator),
        )
        save_session(session._to_db_dict())

        try:
            if use_worktree and repo_path:
                wt = await asyncio.to_thread(create_worktree, repo_path, name, scope)
                session.cwd = wt.path
                session.worktree_path = wt.path
                session.branch = wt.branch

            if not is_orchestrator:
                orch_name = self._find_orchestrator_name(scope)
                session.system_prompt = session.system_prompt.format(
                    worker_name=name, orchestrator_name=orch_name or "orchestrator",
                    scope=scope, branch=session.branch or "main",
                )
                session.on_idle = self._make_idle_callback(scope)

            save_session(session._to_db_dict())
            await session.start()
            self.sessions[session.id] = session
            return session
        except Exception:
            delete_session(session.id)
            raise

    async def send(self, session_id: str, message: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(f"session not found: {session_id}")
        await session.send(message)

    async def interrupt(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            await session.interrupt()

    async def unload(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await session.stop()

    async def remove(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await session.stop()
            if session.worktree_path:
                try:
                    await asyncio.to_thread(remove_worktree, session.scope, session.worktree_path)
                except Exception:
                    pass
        delete_session(session_id)

    async def remove_scope(self, scope: str) -> None:
        to_remove = [s for s in self.sessions.values() if s.scope == scope]
        for s in to_remove:
            await self.remove(s.id)
        for row in get_all_sessions(scope):
            delete_session(row["id"])

    # ── Lookups ──

    def get(self, session_id: str) -> Optional[AgentSession]:
        return self.sessions.get(session_id)

    def get_by_name(self, name: str, scope: str) -> AgentSession | dict | None:
        scope = scope.rstrip("/")
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        db_row = get_session_by_name(name, scope)
        return db_row

    async def ensure_loaded(self, name: str, scope: str) -> Optional[AgentSession]:
        scope = scope.rstrip("/")
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        db_row = get_session_by_name(name, scope)
        if not db_row:
            return None
        return await self._load_from_db(db_row)

    async def _load_from_db(self, db_row: dict) -> AgentSession:
        is_orch = bool(db_row.get("is_orchestrator"))
        prompt = db_row.get("system_prompt", "") or (ORCHESTRATOR_SYSTEM_PROMPT if is_orch else WORKER_SYSTEM_PROMPT)
        cwd = db_row.get("cwd") or db_row["scope"]
        if not Path(cwd).is_dir():
            cwd = db_row["scope"]
        session = AgentSession(
            id=db_row["id"], name=db_row["name"], scope=db_row["scope"], cwd=cwd,
            model=db_row["model"], system_prompt=prompt,
            session_id=db_row.get("session_id"), cost_usd=db_row.get("cost_usd", 0),
            worktree_path=db_row.get("worktree_path"), branch=db_row.get("branch"),
            created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
            is_orchestrator=is_orch,
            mcp_servers=_make_mcp_config(db_row["name"], db_row["scope"], is_orch),
        )
        pct = db_row.get("context_pct", 0) or 0
        tokens = db_row.get("context_tokens", 0) or 0
        if pct or tokens:
            session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": 200000}
        if not is_orch:
            session.on_idle = self._make_idle_callback(db_row["scope"])
        await session.start()
        self.sessions[session.id] = session
        return session

    def _find_orchestrator_name(self, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.is_orchestrator and s.scope == scope:
                return s.name
        return None

    def _make_idle_callback(self, scope: str):
        async def _on_worker_idle(worker_name: str, worker_scope: str, last_texts: list[str]):
            orch = self._find_orchestrator_name(scope)
            if not orch:
                return
            orch_session = next((s for s in self.sessions.values() if s.name == orch), None)
            if not orch_session:
                return
            summary = "\n".join(last_texts[-3:]) if last_texts else "(no output)"
            msg = f"[auto-report from {worker_name}] Worker finished without reporting. Last output:\n{summary}"
            logger.info(f"Auto-report: {worker_name} → {orch}")
            await orch_session.send(msg)
        return _on_worker_idle

    # ── Listings ──

    def list_sessions(self, scope: str | None = None) -> list[dict]:
        result = []
        seen = set()
        for s in self.sessions.values():
            if scope is None or s.scope == scope:
                result.append(s.to_dict())
                seen.add(s.id)
        for row in get_all_sessions(scope):
            if row["id"] not in seen:
                result.append(row)
        return result

    def get_session_id(self, name: str, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.id
        db_row = get_session_by_name(name, scope)
        return db_row["id"] if db_row else None

    def find_worker(self, name: str, scope: str | None = None) -> AgentSession | None:
        for s in self.sessions.values():
            if s.name == name and not s.is_orchestrator and (scope is None or s.scope == scope):
                return s
        return None

    def find_session_id_by_name(self, name: str, scope: str | None = None) -> str | None:
        for s in self.sessions.values():
            if s.name == name and (scope is None or s.scope == scope):
                return s.id
        for row in get_all_sessions(scope):
            if row["name"] == name:
                return row["id"]
        return None

    def _pick_color(self) -> str:
        used = [s.color for s in self.sessions.values()]
        for c in COLOR_PALETTE:
            if c not in used:
                return c
        from collections import Counter
        counts = Counter(used)
        return min(COLOR_PALETTE, key=lambda c: counts.get(c, 0))

    def stats(self, scope: str | None = None) -> dict:
        return get_stats(scope)

    # ── Startup / Shutdown ──

    async def auto_resume_orchestrators(self) -> None:
        from app.db import _conn
        with _conn() as c:
            c.execute("UPDATE sessions SET status='idle' WHERE status != 'idle'")
        for orch in get_resumable_orchestrators():
            if orch["id"] in self.sessions:
                continue
            if not Path(orch["cwd"]).is_dir():
                continue
            try:
                await self._load_from_db(orch)
                logger.info(f"Resumed orchestrator: {orch['name']}")
            except Exception as e:
                logger.error(f"Failed to resume {orch['name']}: {e}")

    async def shutdown_all(self) -> None:
        for session in list(self.sessions.values()):
            try:
                await session.stop()
            except Exception:
                pass
        self.sessions.clear()
