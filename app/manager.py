"""SessionManager — registry, lifecycle, persistence for all agent sessions."""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.session import AgentSession, AgentStatus
from app.workspace import create_worktree, remove_worktree
from app.tools import orchestra_server, worker_server, set_manager
from app.models import resolve_model
from app.db import (
    save_session, get_session_by_name, get_all_sessions,
    delete_session, get_stats, get_resumable_orchestrators, mark_stale_sessions,
)

logger = logging.getLogger(__name__)


_ORCH_PROMPT_PATH = Path(__file__).parent / "orchestrator_prompt.md"
_WORKER_PROMPT_PATH = Path(__file__).parent / "worker_prompt.md"
ORCHESTRATOR_SYSTEM_PROMPT = _ORCH_PROMPT_PATH.read_text() if _ORCH_PROMPT_PATH.exists() else ""
WORKER_SYSTEM_PROMPT = _WORKER_PROMPT_PATH.read_text() if _WORKER_PROMPT_PATH.exists() else ""


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, AgentSession] = {}
        set_manager(self)

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

        if is_orchestrator:
            mcp = {"orchestra": orchestra_server}
            final_prompt = system_prompt or ORCHESTRATOR_SYSTEM_PROMPT
        else:
            mcp = {"orchestra": worker_server}
            final_prompt = system_prompt or WORKER_SYSTEM_PROMPT

        session = AgentSession(
            id=session_id,
            name=name,
            scope=scope,
            cwd=cwd,
            model=model,
            system_prompt=final_prompt,
            is_orchestrator=is_orchestrator,
            mcp_servers=mcp,
        )
        save_session(session._to_db_dict())

        try:
            if use_worktree and repo_path:
                wt = create_worktree(repo_path, name, scope)
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

            await session.start()
            self.sessions[session.id] = session
            return session

        except Exception:
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
            await session.stop()

    async def remove(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            if session.status in (AgentStatus.RUNNING, AgentStatus.STARTING):
                await session.stop()
            if session.worktree_path:
                from app.workspace import remove_worktree
                remove_worktree(session.scope, session.worktree_path)
            del self.sessions[session_id]
        delete_session(session_id)

    def get(self, session_id: str) -> Optional[AgentSession]:
        return self.sessions.get(session_id)

    def get_by_name(self, name: str, scope: str) -> Optional[AgentSession]:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        return None

    async def ensure_loaded(self, name: str, scope: str) -> Optional[AgentSession]:
        session = self.get_by_name(name, scope)
        if session:
            return session
        db_row = get_session_by_name(name, scope)
        if not db_row:
            return None
        is_orch = bool(db_row.get("is_orchestrator"))
        if is_orch:
            mcp = {"orchestra": orchestra_server}
            prompt = db_row.get("system_prompt", "") or ORCHESTRATOR_SYSTEM_PROMPT
        else:
            mcp = {"orchestra": worker_server}
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
            await session.start()
            self.sessions[session.id] = session
            return session
        except Exception as e:
            logger.error(f"Failed to load session {name}: {e}")
            return None

    def _find_orchestrator_name(self, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.is_orchestrator and s.scope == scope:
                return s.name
        return None

    def list_sessions(self, scope: str | None = None) -> list[dict]:
        active = {s.id: s.to_dict() for s in self.sessions.values()
                  if scope is None or s.scope == scope}
        db_sessions = get_all_sessions(scope)
        result = []
        seen = set()
        for s in active.values():
            result.append(s)
            seen.add(s["id"])
        for s in db_sessions:
            if s["id"] not in seen:
                result.append(s)
        return result

    def stats(self, scope: str | None = None) -> dict:
        return get_stats(scope)

    async def auto_resume_orchestrators(self) -> None:
        orchestrators = get_resumable_orchestrators()
        resumed_ids = []
        for orch in orchestrators:
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
                    mcp_servers={"orchestra": orchestra_server},
                )
                await session.start()
                self.sessions[session.id] = session
                resumed_ids.append(session.id)
                logger.info(f"Resumed orchestrator: {orch['name']}")
            except Exception as e:
                logger.error(f"Failed to resume {orch['name']}: {e}")

        stale = mark_stale_sessions(resumed_ids)
        if stale:
            logger.info(f"Marked {stale} stale sessions as error")

    async def shutdown_all(self) -> None:
        for session in list(self.sessions.values()):
            try:
                if session.is_orchestrator:
                    if session._debounce_task and not session._debounce_task.done():
                        session._debounce_task.cancel()
                    if session._turn_task and not session._turn_task.done():
                        session._turn_task.cancel()
                        try:
                            await session._turn_task
                        except Exception:
                            pass
                    if session._client:
                        try:
                            await session._client.disconnect()
                        except Exception:
                            pass
                    session.status = AgentStatus.IDLE
                    session._persist()
                else:
                    await session.stop()
            except Exception:
                pass
        self.sessions.clear()
