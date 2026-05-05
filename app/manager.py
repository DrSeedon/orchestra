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
from app.tools import set_manager
from app.models import resolve_model
from app.db import (
    save_session, get_session_by_name, get_all_sessions,
    delete_session, get_stats, get_resumable_orchestrators, mark_stale_sessions,
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


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, AgentSession] = {}
        self.archived: dict[str, dict] = {}
        self._load_locks: dict[str, asyncio.Lock] = {}
        self._spawn_queue: asyncio.Queue = asyncio.Queue()
        self._spawn_task: asyncio.Task | None = None
        set_manager(self)

    def start_background_tasks(self) -> None:
        if not self._spawn_task or self._spawn_task.done():
            self._spawn_task = asyncio.create_task(self._spawn_worker_loop())
        asyncio.create_task(self._health_check_loop())

    async def _health_check_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            for session in list(self.sessions.values()):
                if session.status == AgentStatus.RUNNING and session._turn_task:
                    if session._turn_task.done():
                        try:
                            session._turn_task.result()
                        except Exception:
                            session.status = AgentStatus.ERROR
                            session._persist()
                            logger.warning(f"Health check: {session.name} task crashed")
                            self._on_session_error(session.id)

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
                    name=job["name"],
                    scope=job["repo_path"],
                    cwd=job["repo_path"],
                    model=job["model"],
                    system_prompt=job.get("system_prompt", ""),
                    use_worktree=True,
                    repo_path=job["repo_path"],
                )
                await session.send(job["task"])
                update_job(job_id, "succeeded")
                logger.info(f"Worker '{job['name']}' spawned (job {job_id})")
            except Exception as e:
                update_job(job_id, "failed", str(e))
                logger.error(f"Spawn '{job.get('name')}' failed (job {job_id}): {e}")
            finally:
                self._spawn_queue.task_done()

    def _on_session_error(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            self.archived[session_id] = session._to_db_dict()
            pass  # session error handled

    def load_archived(self) -> None:
        for row in get_all_sessions():
            if row["status"] in ("stopped", "error") and row["id"] not in self.sessions:
                self.archived[row["id"]] = row

    async def create_session(
        self,
        name: str,
        scope: str,
        cwd: str,
        model: str,
        system_prompt: str = "",
        use_worktree: bool = False,
        repo_path: str | None = None,
        is_orchestrator: bool = False,
    ) -> AgentSession:
        model = resolve_model(model)
        if not Path(cwd).is_dir():
            raise ValueError(f"cwd does not exist: {cwd}")

        existing = get_session_by_name(name, scope)
        if existing:
            raise ValueError(f"session '{name}' already exists in scope '{scope}'")

        session_id = str(uuid.uuid4())
        worktree_path = None
        branch = None

        mcp_env = {
            "ORCHESTRA_URL": "http://127.0.0.1:8888",
            "ORCHESTRA_SCOPE": scope,
            "ORCHESTRA_ROLE": name if is_orchestrator else "worker",
            "WORKER_NAME": name,
        }
        mcp = {"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": {**MCP_BASE_ENV, **mcp_env}, "alwaysLoad": True}}
        if is_orchestrator:
            final_prompt = system_prompt or ORCHESTRATOR_SYSTEM_PROMPT
        else:
            final_prompt = WORKER_SYSTEM_PROMPT + ("\n\n" + system_prompt if system_prompt else "")

        session = AgentSession(
            id=session_id,
            name=name,
            scope=scope,
            cwd=cwd,
            model=model,
            system_prompt=final_prompt,
            is_orchestrator=is_orchestrator,
            color=self._pick_color(),
            mcp_servers=mcp,
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
                    worker_name=name,
                    orchestrator_name=orch_name or "orchestrator",
                    scope=scope,
                    branch=session.branch or "main",
                )

            save_session(session._to_db_dict())

            session.on_error = self._on_session_error
            await session.start()
            self.sessions[session.id] = session
            return session

        except Exception:
            await session.stop()
            if session.worktree_path and repo_path:
                try:
                    remove_worktree(repo_path, session.worktree_path)
                except Exception:
                    pass
            session.status = AgentStatus.ERROR
            save_session(session._to_db_dict())
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

    async def stop(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            try:
                await session.stop()
                self.archived[session_id] = session._to_db_dict()
                self.sessions.pop(session_id, None)
            except Exception:
                session._persist()
                raise

    async def remove(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await session.stop()
            if session.worktree_path:
                from app.workspace import remove_worktree
                remove_worktree(session.scope, session.worktree_path)
        self.archived.pop(session_id, None)
        delete_session(session_id)

    def get(self, session_id: str) -> Optional[AgentSession]:
        return self.sessions.get(session_id)

    def get_by_name(self, name: str, scope: str) -> AgentSession | dict | None:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        for a in self.archived.values():
            if a["name"] == name and a["scope"] == scope:
                return a
        return None

    async def ensure_loaded(self, name: str, scope: str) -> Optional[AgentSession]:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        if any(a["name"] == name and a["scope"] == scope for a in self.archived.values()):
            return None
        key = f"{scope}:{name}"
        if key not in self._load_locks:
            self._load_locks[key] = asyncio.Lock()
        async with self._load_locks[key]:
            for s in self.sessions.values():
                if s.name == name and s.scope == scope:
                    return s
            db_row = get_session_by_name(name, scope)
            if not db_row:
                return None
            if db_row["status"] in ("stopped", "error"):
                return None
            is_orch = bool(db_row.get("is_orchestrator"))
            mcp_env = {
                "ORCHESTRA_URL": "http://127.0.0.1:8888",
                "ORCHESTRA_SCOPE": db_row["scope"],
                "ORCHESTRA_ROLE": db_row["name"] if is_orch else "worker",
                "WORKER_NAME": db_row["name"],
            }
            mcp = {"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": {**MCP_BASE_ENV, **mcp_env}, "alwaysLoad": True}}
            if is_orch:
                prompt = db_row.get("system_prompt", "") or ORCHESTRATOR_SYSTEM_PROMPT
            else:
                prompt = db_row.get("system_prompt", "") or WORKER_SYSTEM_PROMPT
            cwd = db_row["cwd"]
            wt_path = db_row.get("worktree_path")
            if cwd and not Path(cwd).is_dir():
                logger.warning(f"Session {name} cwd missing: {cwd}, falling back to scope")
                cwd = db_row["scope"]
                wt_path = None
            session = AgentSession(
                id=db_row["id"],
                name=db_row["name"],
                scope=db_row["scope"],
                cwd=cwd,
                model=db_row["model"],
                system_prompt=prompt,
                session_id=db_row.get("session_id"),
                cost_usd=db_row.get("cost_usd", 0),
                worktree_path=wt_path,
                branch=db_row.get("branch"),
                created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
                is_orchestrator=is_orch,
                mcp_servers=mcp,
            )
            try:
                session.on_error = self._on_session_error
                await session.start()
                self.sessions[session.id] = session
                return session
            except Exception as e:
                await session.stop()
                logger.error(f"Failed to load session {name}: {e}")
                return None

    def _pick_color(self) -> str:
        used = [s.color for s in self.sessions.values()]
        used += [a.get("color", "") for a in self.archived.values()]
        for c in COLOR_PALETTE:
            if c not in used:
                return c
        from collections import Counter
        counts = Counter(used)
        return min(COLOR_PALETTE, key=lambda c: counts.get(c, 0))

    def _find_orchestrator_name(self, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.is_orchestrator and s.scope == scope:
                return s.name
        return None

    def list_sessions(self, scope: str | None = None) -> list[dict]:
        result = []
        for s in self.sessions.values():
            if scope is None or s.scope == scope:
                result.append(s.to_dict())
        for a in self.archived.values():
            if scope is None or a["scope"] == scope:
                result.append(a.copy())
        return result

    def get_session_id(self, name: str, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.id
        for a in self.archived.values():
            if a["name"] == name and a["scope"] == scope:
                return a["id"]
        return None

    def find_worker(self, name: str, scope: str | None = None) -> AgentSession | None:
        for s in self.sessions.values():
            if s.name == name and not s.is_orchestrator:
                if scope is None or s.scope == scope:
                    return s
        return None

    def find_session_id_by_name(self, name: str, scope: str | None = None) -> str | None:
        for s in self.sessions.values():
            if s.name == name and (scope is None or s.scope == scope):
                return s.id
        for a in self.archived.values():
            if a["name"] == name and (scope is None or a["scope"] == scope):
                return a["id"]
        return None

    def archive_by_id(self, session_id: str, new_name: str) -> bool:
        if session_id in self.sessions:
            return False
        entry = self.archived.get(session_id)
        if not entry:
            from app.db import get_session
            entry = get_session(session_id)
        if not entry:
            return False
        updated = {**entry, "name": new_name, "status": "stopped"}
        save_session(updated)
        self.archived[session_id] = updated
        return True

    def stats(self, scope: str | None = None) -> dict:
        return get_stats(scope)

    async def auto_resume_orchestrators(self) -> None:
        from app.db import _conn
        with _conn() as c:
            c.execute("UPDATE sessions SET status='stopped' WHERE status='error'")
        orchestrators = get_resumable_orchestrators()
        resumed_ids = []
        for orch in orchestrators:
            if orch["id"] in self.sessions:
                logger.info(f"Orchestrator {orch['name']} already loaded, skipping")
                resumed_ids.append(orch["id"])
                continue
            if not Path(orch["cwd"]).is_dir():
                logger.warning(f"Skipping orchestrator {orch['name']}: cwd gone")
                continue
            try:
                session = AgentSession(
                    id=orch["id"],
                    name=orch["name"],
                    scope=orch["scope"],
                    cwd=orch["cwd"],
                    model=orch["model"],
                    system_prompt=orch.get("system_prompt", "") or ORCHESTRATOR_SYSTEM_PROMPT,
                    session_id=orch["session_id"],
                    cost_usd=orch.get("cost_usd", 0),
                    worktree_path=orch.get("worktree_path"),
                    branch=orch.get("branch"),
                    created_at=datetime.fromisoformat(orch["created_at"]) if orch.get("created_at") else datetime.now(timezone.utc),
                    is_orchestrator=True,
                    mcp_servers={"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "alwaysLoad": True, "env": {**MCP_BASE_ENV,
                        "ORCHESTRA_URL": "http://127.0.0.1:8888",
                        "ORCHESTRA_SCOPE": orch["scope"],
                        "ORCHESTRA_ROLE": orch["name"],
                        "WORKER_NAME": orch["name"],
                    }}},
                    on_error=self._on_session_error,
                )
                await session.start()
                self.sessions[session.id] = session
                resumed_ids.append(session.id)
                logger.info(f"Resumed orchestrator: {orch['name']}")
            except Exception as e:
                await session.stop()
                logger.error(f"Failed to resume {orch['name']}: {e}")

        stale = mark_stale_sessions(resumed_ids)
        if stale:
            logger.info(f"Marked {stale} stale sessions as error")
        self.load_archived()

    async def shutdown_all(self) -> None:
        for session in list(self.sessions.values()):
            try:
                if session.is_orchestrator:
                    await session.stop()
                    session.status = AgentStatus.IDLE
                    session._persist()
                else:
                    await session.stop()
                    self.archived[session.id] = session._to_db_dict()
            except Exception:
                pass
        self.sessions.clear()
