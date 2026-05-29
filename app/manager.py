"""SessionManager — registry, lifecycle, persistence for all agent sessions."""

import asyncio
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.session import AgentSession, AgentStatus, is_orchestrator_role

_TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
from app.workspace import create_worktree, remove_worktree
from app.models import resolve_model, backend_for_model
from app.db import (
    save_session, get_session_by_name, get_all_sessions,
    delete_session, archive_session, get_stats,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).parent.parent)
_MCP_SCRIPT = str(Path(__file__).parent / "mcp_stdio.py")
MCP_STDIO_CMD = [sys.executable, _MCP_SCRIPT]
MCP_BASE_ENV = {"PYTHONPATH": _PROJECT_ROOT}
for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "INTERNAL_TOKEN"):
    if os.environ.get(_k):
        MCP_BASE_ENV[_k] = os.environ[_k]

COLOR_PALETTE = [
    "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
    "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
]

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_IDENTITY_PLACEHOLDERS = re.compile(r"\{(worker_name|orchestrator_name|scope|branch)\}")


def _safe_format_prompt(template: str, **kwargs: str) -> str:
    """Substitute only known identity placeholders, leaving other {braces} intact."""
    return _IDENTITY_PLACEHOLDERS.sub(lambda m: kwargs.get(m.group(1), m.group(0)), template)


def _read_prompt(name: str) -> str:
    p = _PROMPTS_DIR / name
    return p.read_text() if p.exists() else ""


def _other_orchestrators_block(exclude_scope: str = "") -> str:
    try:
        orchs = [s for s in get_all_sessions()
                 if is_orchestrator_role(s.get("role", "worker")) and s.get("scope") != exclude_scope]
        if not orchs:
            return ""
        lines = ["## Other orchestrators", "You can message other orchestrators via `send_message(to=\"Name\", message=\"...\")`:"]
        for o in orchs:
            name = o["name"]
            scope = o.get("scope", "")
            project = Path(scope).name if scope else "?"
            lines.append(f"- **{name}** — project: {project}")
        lines.append("")
        lines.append("Use this when the user says \"напиши оркестре X\", \"скажи Y оркестратору\", \"спроси у Z\", etc.")
        return "\n".join(lines)
    except Exception:
        return ""


def _workers_block(scope: str) -> str:
    try:
        workers = [s for s in get_all_sessions()
                   if not is_orchestrator_role(s.get("role", "worker")) and s.get("scope") == scope]
        if not workers:
            return ""
        lines = ["## Your current workers",
                 "These workers exist in your project. Reuse idle ones instead of spawning new. Kill workers you no longer need (one-shot tasks done, wrong role, duplicate)."]
        for w in workers:
            name = w["name"]
            model = w.get("model", "?")
            status = w.get("status", "?")
            ctx = w.get("context_pct", 0) or 0
            lines.append(f"- **{name}** — {model} | {status} | ctx:{ctx}%")
        return "\n".join(lines)
    except Exception:
        return ""


def _parse_role_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from role .md file. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    body = parts[2].strip()
    return meta, body


def _role_prompt_file(role: str) -> str:
    """Find the best prompt for a role. Parses frontmatter, returns body only.
    If body is empty, uses `prompt:` field from frontmatter as fallback file."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if role_path.exists():
        meta, body = _parse_role_frontmatter(role_path.read_text())
        if body:
            return body
        fallback = meta.get("prompt", "")
        if fallback:
            return _read_prompt(fallback)
    if is_orchestrator_role(role):
        return _read_prompt("orchestrator.md")
    return _read_prompt("worker.md")


_SKILLS_DIR = _PROMPTS_DIR / "skills"


def _load_role_skills(role: str) -> str:
    """Load skills listed in role's frontmatter `skills:` field.
    Reads each skill .md from skills/ dir, strips frontmatter, returns combined text."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return ""
    meta, _ = _parse_role_frontmatter(role_path.read_text())
    skill_names = meta.get("skills", [])
    if not skill_names or not _SKILLS_DIR.is_dir():
        return ""
    parts = []
    for sname in skill_names:
        skill_path = _SKILLS_DIR / f"{sname}.md"
        if not skill_path.exists():
            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
            continue
        _, body = _parse_role_frontmatter(skill_path.read_text())
        if body:
            parts.append(body)
    if not parts:
        return ""
    return "## Skills\n\n" + "\n\n---\n\n".join(parts)


def _role_can_spawn(role: str):
    """Return the can_spawn whitelist for a role, or None if unrestricted.
    None  = field absent OR malformed -> no restriction (spawn anything)
    []    = empty list                -> terminal role (spawn nothing)
    [...] = whitelist of allowed child roles
    """
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return None
    meta, _ = _parse_role_frontmatter(role_path.read_text())
    if "can_spawn" not in meta:
        return None
    val = meta["can_spawn"]
    if not isinstance(val, list):
        logger.warning(f"role '{role}' has non-list can_spawn ({val!r}); treating as unrestricted")
        return None
    return [str(x) for x in val]


def _skills_catalog() -> str:
    """Build catalog of available skills from skills/ directory for orchestrator."""
    if not _SKILLS_DIR.is_dir():
        return ""
    entries = []
    for f in sorted(_SKILLS_DIR.glob("*.md")):
        meta, _ = _parse_role_frontmatter(f.read_text())
        name = meta.get("name", f.stem)
        desc = meta.get("description", "").strip().replace("\n", " ")
        entries.append(f"- `{name}` — {desc}")
    if not entries:
        return ""
    return "## Available skills (for roles)\nSkills are auto-injected into worker prompts via `skills:` in role frontmatter.\n" + "\n".join(entries)


def _roles_catalog() -> str:
    """Build a catalog of available worker roles from roles/ directory frontmatter.
    Injected into orchestrator prompt so it knows what roles exist."""
    roles_dir = _PROMPTS_DIR / "roles"
    if not roles_dir.is_dir():
        return ""
    entries = []
    for f in sorted(roles_dir.glob("*.md")):
        meta, _ = _parse_role_frontmatter(f.read_text())
        if not meta or meta.get("name") == "orchestrator":
            continue
        name = meta.get("name", f.stem)
        label = meta.get("label", name)
        model = meta.get("model", "any")
        desc = meta.get("description", "").strip().replace("\n", " ")
        when = meta.get("when", "").strip()
        not_for = meta.get("not_for", "").strip()
        skills_list = meta.get("skills", [])
        entry = f"### `{name}` ({label}) — model: {model}\n{desc}"
        if when:
            entry += f"\n- ✅ **When**: {when}"
        if not_for:
            entry += f"\n- ❌ **Not for**: {not_for}"
        if skills_list:
            entry += f"\n- 🔧 **Skills**: {', '.join(skills_list)}"
        entries.append(entry)
    if not entries:
        return ""
    return "## Available worker roles\nSpawn with `role=\"<name>\"`. If no role specified, defaults to `worker`.\n\n" + "\n\n".join(entries)


def ROLE_SYSTEM_PROMPT(role: str, scope: str = "") -> str:
    base = f"{_read_prompt('base.md')}\n\n{_role_prompt_file(role)}"
    skills = _load_role_skills(role)
    if skills:
        base += f"\n\n{skills}"
    if is_orchestrator_role(role):
        catalog = _roles_catalog()
        if catalog:
            base += f"\n\n{catalog}"
        skills_cat = _skills_catalog()
        if skills_cat:
            base += f"\n\n{skills_cat}"
        others = _other_orchestrators_block(scope)
        if others:
            base += f"\n\n{others}"
        workers = _workers_block(scope)
        if workers:
            base += f"\n\n{workers}"
    return base


def ORCHESTRATOR_SYSTEM_PROMPT(scope: str = "") -> str:
    return ROLE_SYSTEM_PROMPT("orchestrator", scope)


def WORKER_SYSTEM_PROMPT() -> str:
    return ROLE_SYSTEM_PROMPT("worker")


def _prompt_template_hash(role_or_orch) -> str:
    """Hash only the static template files (base.md + role.md + skills).
    Accepts role string or legacy bool (is_orchestrator)."""
    import hashlib
    if isinstance(role_or_orch, bool):
        role = "orchestrator" if role_or_orch else "worker"
    else:
        role = role_or_orch
    content = _read_prompt("base.md") + _role_prompt_file(role) + _load_role_skills(role)
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _parse_custom_mcp(raw) -> dict:
    """Sanitize custom MCP servers (from DB JSON string or a dict).
    Returns a dict with the `orchestra` key stripped. Non-dict input -> {}."""
    if not raw:
        return {}
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("invalid mcp_servers_custom JSON; ignoring")
            return {}
    if not isinstance(raw, dict):
        logger.warning(f"mcp_servers_custom is not an object ({type(raw).__name__}); ignoring")
        return {}
    return {k: v for k, v in raw.items() if k != "orchestra"}


def _make_mcp_config(name: str, scope: str, role: str = "worker", extra: dict | None = None) -> dict:
    env = {
        **MCP_BASE_ENV,
        "ORCHESTRA_URL": "http://127.0.0.1:8888",
        "ORCHESTRA_SCOPE": scope,
        "ORCHESTRA_ROLE": role,
        "WORKER_NAME": name,
    }
    cfg = {"orchestra": {"command": MCP_STDIO_CMD[0], "args": MCP_STDIO_CMD[1:], "env": env, "alwaysLoad": True}}
    if extra:
        for k, v in extra.items():
            if k == "orchestra":
                logger.warning("custom MCP server 'orchestra' would override Orchestra MCP — ignored")
                continue
            cfg[k] = v
    return cfg


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, AgentSession] = {}
        self._spawn_queue: asyncio.Queue = asyncio.Queue()
        self._spawn_task: asyncio.Task | None = None
        self._session_locks: dict[str, asyncio.Lock] = {}

    def get_session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

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
                    role=job.get("role", "worker"),
                    task_id=job.get("task_id", ""),
                    description=job.get("description", ""),
                    parent_name=job.get("parent_name", ""),
                    mcp_servers=job.get("mcp_servers"),
                )
                await session.send(job["task"])
                update_job(job_id, "succeeded")
                logger.info(f"Worker '{job['name']}' spawned (job {job_id})")
            except Exception as e:
                update_job(job_id, "failed", str(e))
                logger.error(f"Spawn '{job.get('name')}' failed (job {job_id}): {e}")
            finally:
                self._spawn_queue.task_done()

    @staticmethod
    def _auto_commit_if_dirty(repo_path: str):
        import subprocess
        r = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
        if r.stdout.strip():
            subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "wip: auto-save before worker spawn"], cwd=repo_path, capture_output=True)
            logger.info(f"Auto-committed dirty working tree in {repo_path}")

    # ── Session CRUD ──

    async def create_session(self, name: str, scope: str, cwd: str, model: str,
                             system_prompt: str = "", use_worktree: bool = False,
                             repo_path: str | None = None, is_orchestrator: bool = False,
                             role: str = "", task_id: str = "", description: str = "",
                             base_branch: str = "main",
                             parent_id: str = "", parent_name: str = "",
                             mcp_servers: dict | None = None) -> AgentSession:
        scope = scope.rstrip("/")
        cwd = cwd.rstrip("/")
        model = resolve_model(model)
        if not Path(cwd).is_dir():
            raise ValueError(f"cwd does not exist: {cwd}")
        if get_session_by_name(name, scope):
            raise ValueError(f"session '{name}' already exists in scope '{scope}'")

        if not role:
            role = "orchestrator" if is_orchestrator else "worker"
        is_orch = is_orchestrator_role(role)

        if is_orch:
            prompt = system_prompt or ROLE_SYSTEM_PROMPT(role, scope)
        else:
            prompt = ROLE_SYSTEM_PROMPT(role) + ("\n\n" + system_prompt if system_prompt else "")

        if not parent_name and not is_orch:
            parent_name = self._find_orchestrator_name(scope) or ""
        if not parent_id and parent_name:
            p_session = self.get_by_name(parent_name, scope)
            if p_session:
                parent_id = p_session.id if isinstance(p_session, AgentSession) else p_session.get("id", "")

        if parent_name:
            parent_role = self._resolve_role(parent_name, scope)
            if parent_role:
                whitelist = _role_can_spawn(parent_role)
                if whitelist is not None and role not in whitelist:
                    allowed = ", ".join(whitelist) if whitelist else "(none — terminal role)"
                    raise ValueError(
                        f"role '{parent_role}' is not allowed to spawn role '{role}'. "
                        f"Allowed: {allowed}"
                    )

        custom_mcp = _parse_custom_mcp(mcp_servers)
        bt = backend_for_model(model)
        session = AgentSession(
            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
            system_prompt=prompt, role=role,
            parent_id=parent_id, parent_name=parent_name,
            color="" if is_orch else self._pick_color(),
            mcp_servers=_make_mcp_config(name, scope, role, extra=custom_mcp),
            mcp_servers_custom=custom_mcp,
            backend_type=bt, task_id=task_id, description=description,
        )
        session._template_hash = _prompt_template_hash(role)
        save_session(session._to_db_dict())

        if task_id and not is_orch:
            try:
                from app.tm import api_update_task
                api_update_task(task_id, status="in_progress")
            except Exception:
                pass

        try:
            if use_worktree and repo_path:
                await asyncio.to_thread(self._auto_commit_if_dirty, repo_path)
                wt = await asyncio.to_thread(create_worktree, repo_path, name, scope, task_id, base_branch)
                session.cwd = wt.path
                session.worktree_path = wt.path
                session.branch = wt.branch

            if not is_orch:
                orch_name = parent_name or self._find_orchestrator_name(scope)
                session.system_prompt = _safe_format_prompt(
                    session.system_prompt,
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

    async def stop_worker(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            await session.interrupt()

    async def unload(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await session.stop()

    async def remove(self, session_id: str) -> None:
        from app.bg_jobs import bg_manager
        await bg_manager.cancel_by_session(session_id)
        session = self.sessions.pop(session_id, None)
        if session:
            await session._disconnect_backend()
            if session.worktree_path:
                try:
                    await asyncio.to_thread(remove_worktree, session.scope, session.worktree_path)
                except Exception:
                    pass
        delete_session(session_id)

    async def remove_scope(self, scope: str, delete_tg_topics: bool = False) -> dict:
        orch_names: list[str] = []
        for s in self.sessions.values():
            if s.scope == scope and s.is_orchestrator and s.name not in orch_names:
                orch_names.append(s.name)
        for row in get_all_sessions(scope):
            if is_orchestrator_role(row.get("role", "worker")) and row["name"] not in orch_names:
                orch_names.append(row["name"])

        to_remove = [s for s in self.sessions.values() if s.scope == scope]
        for s in to_remove:
            await self.remove(s.id)
        for row in get_all_sessions(scope):
            archive_session(row["id"])

        tg_result: dict = {}
        if delete_tg_topics and orch_names:
            from app import tg_bridge
            tg_result = await tg_bridge.remove_topics_for_orchs(orch_names)
        return {"tg": tg_result}

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

    def _resolve_role(self, name: str, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.role
        row = get_session_by_name(name, scope)
        return row.get("role") if row else None

    async def ensure_loaded(self, name: str, scope: str) -> Optional[AgentSession]:
        scope = scope.rstrip("/")
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        db_row = get_session_by_name(name, scope)
        if not db_row:
            return None
        return await self._load_from_db(db_row)

    async def ensure_loaded_any(self, name: str) -> Optional[AgentSession]:
        for s in self.sessions.values():
            if s.name == name:
                return s
        for row in get_all_sessions():
            if row["name"] == name:
                return await self._load_from_db(row)
        return None

    async def _load_from_db(self, db_row: dict) -> AgentSession:
        role = db_row.get("role") or ("orchestrator" if db_row.get("is_orchestrator") else "worker")
        is_orch = is_orchestrator_role(role)
        old_prompt = db_row.get("system_prompt", "")
        current_prompt = ROLE_SYSTEM_PROMPT(role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(role)
        cwd = db_row.get("cwd") or db_row["scope"]
        if not Path(cwd).is_dir():
            cwd = db_row["scope"]
        expected_bt = backend_for_model(db_row["model"])
        stored_bt = db_row.get("backend_type", "claude") or "claude"
        if stored_bt != expected_bt:
            logger.warning(f"backend mismatch for {db_row['name']}: stored={stored_bt}, model implies={expected_bt}. Using {expected_bt}.")
            stored_bt = expected_bt
        db_branch = db_row.get("branch")
        db_task_id = db_row.get("task_id") or ""
        wt_path = db_row.get("worktree_path")
        if wt_path and Path(wt_path).is_dir():
            actual = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=wt_path, capture_output=True, text=True,
            )
            if actual.returncode == 0:
                actual_branch = actual.stdout.strip()
                if actual_branch != db_branch:
                    db_branch = actual_branch
                    m = _TASK_BRANCH_RE.match(actual_branch)
                    db_task_id = m.group(1) if m else ""

        custom_mcp = _parse_custom_mcp(db_row.get("mcp_servers_custom"))
        session = AgentSession(
            id=db_row["id"], name=db_row["name"], scope=db_row["scope"], cwd=cwd,
            model=db_row["model"], system_prompt=old_prompt or current_prompt,
            session_id=db_row.get("session_id"), cost_usd=db_row.get("cost_usd", 0),
            cost_usd_cached=db_row.get("cost_usd_cached", 0),
            worktree_path=wt_path, branch=db_branch,
            created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
            role=role,
            parent_id=db_row.get("parent_id", ""),
            parent_name=db_row.get("parent_name", ""),
            color="" if is_orch else (db_row.get("color") or self._pick_color()),
            mcp_servers=_make_mcp_config(db_row["name"], db_row["scope"], role, extra=custom_mcp),
            mcp_servers_custom=custom_mcp,
            backend_type=stored_bt, task_id=db_task_id,
            description=db_row.get("description", ""),
        )
        pct = db_row.get("context_pct", 0) or 0
        tokens = db_row.get("context_tokens", 0) or 0
        if pct or tokens:
            from app.models import CONTEXT_LIMITS
            max_t = CONTEXT_LIMITS.get(db_row["model"], 200000)
            session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": max_t}
        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
        if not is_orch:
            current_prompt = _safe_format_prompt(
                current_prompt,
                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                scope=db_row["scope"], branch=db_row.get("branch") or "main",
            )
        if old_prompt and old_prompt != current_prompt:
            formatted_base = _safe_format_prompt(
                ROLE_SYSTEM_PROMPT(role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(role),
                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                scope=db_row["scope"], branch=db_row.get("branch") or "main",
            )
            if old_prompt.startswith(formatted_base) and len(old_prompt) > len(formatted_base):
                custom_part = old_prompt[len(formatted_base):]
                current_prompt = current_prompt + custom_part
        session._current_prompt = current_prompt
        session._template_hash = db_row.get("template_hash") or _prompt_template_hash(role)
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

    def _context_warning(self, worker_name: str) -> str:
        session = next((s for s in self.sessions.values() if s.name == worker_name), None)
        if not session:
            return ""
        pct = session._last_context.get("percentage", 0)
        if pct >= 90:
            return f"\n⚠️ CONTEXT CRITICAL: {pct}% — do NOT send more tasks to this worker"
        return ""

    def _make_idle_callback(self, scope: str):
        async def _on_worker_idle(worker_name: str, worker_scope: str, last_texts: list[str]):
            orch = self._find_orchestrator_name(scope)
            if not orch:
                return
            orch_session = next((s for s in self.sessions.values() if s.name == orch), None)
            if not orch_session:
                return
            summary = "\n".join(last_texts[-3:]) if last_texts else "(no output)"
            ctx = self._context_warning(worker_name)
            worker_session = next((s for s in self.sessions.values() if s.name == worker_name), None)
            sr = ""
            if worker_session and worker_session._turn_logs:
                for log in reversed(worker_session._turn_logs):
                    if "stop_reason=" in log:
                        sr = f" ({log.strip()})"
                        break
            msg = f"[from:{worker_name}] [auto-report]{sr} Finished without explicit report. Last output:\n{summary}{ctx}"
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

    async def auto_resume_all(self) -> None:
        from app.db import _conn
        with _conn() as c:
            was_running = {r["id"] for r in c.execute(
                "SELECT id FROM sessions WHERE status = 'running'"
            ).fetchall()}
            resumable = [dict(r) for r in c.execute(
                "SELECT * FROM sessions WHERE session_id IS NOT NULL "
                "AND status IN ('running', 'idle')"
            ).fetchall()]
            c.execute("UPDATE sessions SET status='idle' WHERE status != 'idle'")

        orchs = [r for r in resumable if is_orchestrator_role(r.get("role", "orchestrator" if r.get("is_orchestrator") else "worker"))]
        workers = [r for r in resumable if not is_orchestrator_role(r.get("role", "orchestrator" if r.get("is_orchestrator") else "worker"))]

        for row in orchs:
            if row["id"] in self.sessions:
                continue
            if not Path(row.get("cwd") or row["scope"]).is_dir():
                continue
            try:
                session = await self._load_from_db(row)
                logger.info(f"Resumed orchestrator: {row['name']}")
                if row["id"] in was_running:
                    asyncio.create_task(self._inject_restart_notice(session))
            except Exception as e:
                logger.error(f"Failed to resume {row['name']}: {e}")

        for row in workers:
            if row["id"] in self.sessions:
                continue
            if not Path(row.get("cwd") or row["scope"]).is_dir():
                continue
            try:
                session = await self._load_from_db(row)
                logger.info(f"Resumed worker: {row['name']}")
                if row["id"] in was_running:
                    asyncio.create_task(self._inject_restart_notice(session))
            except Exception as e:
                logger.error(f"Failed to resume worker {row['name']}: {e}")

    async def _inject_restart_notice(self, session: AgentSession) -> None:
        import random
        await asyncio.sleep(3 + random.uniform(0, 12))
        try:
            await session.send(
                "[system] Orchestra server restarted. "
                "Your session was restored — continue where you left off."
            )
            logger.info(f"Restart notice injected: {session.name}")
        except Exception as e:
            logger.warning(f"Failed to inject restart notice to {session.name}: {e}")

    async def auto_resume_orchestrators(self) -> None:
        await self.auto_resume_all()

    async def shutdown_all(self) -> None:
        for session in list(self.sessions.values()):
            try:
                await session.stop()
            except Exception:
                pass
        self.sessions.clear()
