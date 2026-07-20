"""SessionManager — registry, lifecycle, persistence for all agent sessions."""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.session import AgentSession, AgentStatus
from app.prompting import (
    is_orchestrator_role, safe_format_prompt,
    prompt_template_hash, inject_skills_to_worktree,
)

# Matches "task-42/worker-name" or "PAR-42/worker-name" — extracts task number from branch
_TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
from app.models import (
    CONTEXT_LIMITS,
    available_models_block,
    backend_for_model,
    cache_policy_for_runtime,
    resolve_model,
)
from app.pipeline import (
    DEFAULT_PIPELINE,
    build_system_prompt,
    get_active_pipeline,
    get_role,
    get_worktree_config,
    load_pipeline,
    resolve_role,
    template_path,
    validate_spawn,
)
from app.db import (
    save_session, get_session_by_name, get_all_sessions,
    delete_session, delete_archived_session, archive_session, get_stats,
)

logger = logging.getLogger(__name__)

from app.runtime_env import MCP_BASE_ENV, MCP_STDIO_CMD  # noqa: F401 — re-exported for callers

COLOR_PALETTE = [
    "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
    "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
]


def get_active_profile(scope: str = "", parent_profile: str = "") -> str:
    return parent_profile or ""


def _other_orchestrators_block(exclude_scope: str = "", caller_role: str = "") -> str:
    try:
        all_orchs = [s for s in get_all_sessions()
                     if bool(s.get("is_orchestrator")) and s.get("scope") != exclude_scope]
        if caller_role == "sub-orchestrator":
            orchs = [s for s in all_orchs if not s.get("parent_name")]
        else:
            orchs = all_orchs
        if not orchs:
            return ""
        lines = ["## Other orchestrators", "You can message other orchestrators via `send_message(to=\"Name\", message=\"...\")`:"]
        for o in orchs:
            name = o["name"]
            scope = o.get("scope", "")
            project = Path(scope).name if scope else "?"
            desc = o.get("description", "")
            desc_part = f" — {desc}" if desc else ""
            lines.append(f"- **{name}** — project: {project}{desc_part}")
        lines.append("")
        lines.append("Use this when the user says \"напиши оркестре X\", \"скажи Y оркестратору\", \"спроси у Z\", etc.")
        return "\n".join(lines)
    except Exception:
        return ""


def _workers_block(scope: str, orchestrator_name: str = "") -> str:
    try:
        workers = [s for s in get_all_sessions()
                   if not bool(s.get("is_orchestrator")) and s.get("scope") == scope]
        if not workers:
            return ""

        mine, others = [], []
        for w in workers:
            pn = w.get("parent_name", "")
            if not orchestrator_name or pn == orchestrator_name or not pn:
                mine.append(w)
            else:
                others.append(w)

        def _fmt(w, show_owner=False):
            n = w["name"]
            model = w.get("model", "?")
            status = w.get("status", "?")
            ctx = w.get("context_pct", 0) or 0
            desc = w.get("description", "")
            desc_part = f" | \"{desc}\"" if desc else ""
            owner_part = f" | owner: {w.get('parent_name', '?')}" if show_owner else ""
            return f"- **{n}** — {model} | {status} | ctx:{ctx}%{desc_part}{owner_part}"

        lines = ["## Your current workers",
                 "These workers exist in your project. Reuse idle ones instead of spawning new. Kill workers you no longer need (one-shot tasks done, wrong role, duplicate)."]
        for w in mine:
            lines.append(_fmt(w))

        if others:
            lines.append("")
            lines.append("## Other orchestrators' workers")
            lines.append("⚠️ These belong to other orchestrators. Do NOT send them tasks — message their orchestrator instead.")
            for w in others:
                lines.append(_fmt(w, show_owner=True))

        return "\n".join(lines)
    except Exception:
        return ""


def _fmt_role_catalog_entry(rr) -> str:
    """Форматировать одну запись каталога ролей из :class:`ResolvedRole`.

    Совпадает по форме с ``_roles_catalog`` (заголовок ### `name` (label) — model,
    описание, when/not_for). Источник полей — манифест (ResolvedRole), не frontmatter.
    """
    desc = (rr.description or "").strip().replace("\n", " ")
    entry = f"### `{rr.name}` ({rr.label}) — model: {rr.model}"
    if desc:
        entry += f"\n{desc}"
    if rr.when:
        entry += f"\n- ✅ **When**: {rr.when.strip()}"
    if rr.not_for:
        entry += f"\n- ❌ **Not for**: {rr.not_for.strip()}"
    skills = rr.skills
    if isinstance(skills, list) and skills:
        entry += f"\n- 🔧 **Skills**: {', '.join(skills)}"
    return entry


def _roles_catalog_from_manifest(pipeline: str, parent_role: str) -> str:
    """Каталог ролей оркестратору из манифеста, отфильтрованный по ``can_spawn``.

    B2: показываем ВСЕ роли из ``can_spawn`` родителя (включая под-оркестраторов).
    ``can_spawn=['*']`` → все роли пайплайна. Сортировка по ``order``. Закрывает
    дефект плоского ``_roles_catalog`` (показывал бы запретные роли).
    """
    cfg = load_pipeline(pipeline)
    parent = cfg.roles.get(parent_role)
    if parent is None:
        return ""
    if "*" in parent.can_spawn:
        # S1: wildcard НЕ включает саму роль-родителя (upstream _roles_catalog
        # пропускал orchestrator из своего же каталога воркеров).
        visible = [r for r in cfg.roles if r != parent_role]
    else:
        visible = list(parent.can_spawn)
    visible = [r for r in visible if r in cfg.roles]
    if not visible:
        return ""
    entries = [
        _fmt_role_catalog_entry(resolve_role(cfg, r))
        for r in sorted(visible, key=lambda r: cfg.roles[r].order)
    ]
    return ('## Available worker roles\nSpawn with `role="<name>"`. '
            'If no role specified, defaults to `worker`.\n\n' + "\n\n".join(entries))


def ROLE_SYSTEM_PROMPT(pipeline: str, role: str, scope: str = "") -> str:
    """Системный промпт роли: статика слоёв пайплайна + динамика (каталог/блоки).

    Единственный источник — ``pipelines/<pipeline>/prompts/`` через
    :func:`build_system_prompt`. Для оркестратора добавляется каталог ролей
    (фильтр ``can_spawn``) + блоки других оркестраторов/воркеров из БД.

    Fail loud: нет манифеста или роли нет в манифесте → :class:`ValueError`.
    Legacy-fallback на ``app/prompts/`` удалён (единый источник = pipelines).
    """
    try:
        base = build_system_prompt(pipeline, role, scope)
    except (FileNotFoundError, KeyError) as e:
        raise ValueError(
            f"role '{role}' not resolvable in pipeline '{pipeline}': {e!r}. "
            f"Define it in pipelines/{pipeline}/pipeline.yaml + prompts/roles/{role}.md"
        ) from e
    rr = get_role(pipeline, role)
    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
    if is_orch:
        catalog = _roles_catalog_from_manifest(pipeline, role)
        if catalog:
            base += f"\n\n{catalog}"
        base += f"\n\n{available_models_block()}"
        others = _other_orchestrators_block(scope, caller_role=role)
        if others:
            base += f"\n\n{others}"
        workers = _workers_block(scope)
        if workers:
            base += f"\n\n{workers}"
    return base


def ORCHESTRATOR_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE, scope: str = "") -> str:
    return ROLE_SYSTEM_PROMPT(pipeline, "orchestrator", scope)


def WORKER_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE) -> str:
    return ROLE_SYSTEM_PROMPT(pipeline, "worker")



def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -> None:
    try:
        rr = get_role(pipeline, role)
    except FileNotFoundError:
        return
    if rr is None or not rr.docs_scaffold or rr.docs_dir is None:
        return
    dd = rr.docs_dir
    if dd.requires == "feature" and not feature:
        return
    rel = dd.path.replace("{feature}", feature) if feature else dd.path
    base_docs = (Path(cwd) / "docs_work").resolve()
    target = (base_docs / rel).resolve()
    try:
        target.relative_to(base_docs)
    except ValueError:
        logger.warning("scaffold: путь '%s' выходит за docs_work — пропуск", rel)
        return
    target.mkdir(parents=True, exist_ok=True)
    dashboard = target / "dashboard.md"
    if dashboard.exists() or not dd.template:
        return
    tpl = template_path(pipeline, dd.template)
    if not tpl.is_file():
        return
    content = tpl.read_text()
    if feature:
        content = content.replace("{feature}", feature)
    dashboard.write_text(content)


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


def _make_mcp_config(name: str, scope: str, role: str = "worker",
                     parent_name: str = "", extra: dict | None = None) -> dict:
    env = {
        **MCP_BASE_ENV,
        "ORCHESTRA_URL": "http://127.0.0.1:8888",
        "ORCHESTRA_SCOPE": scope,
        "ORCHESTRA_ROLE": role,
        "ORCHESTRA_ACCESS_MODE": "full",
        "WORKER_NAME": name,
        "PARENT_NAME": parent_name,
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
        # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
        self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None

    def get_session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def start_background_tasks(self) -> None:
        if not self._spawn_task or self._spawn_task.done():
            self._spawn_task = asyncio.create_task(self._spawn_worker_loop())
        if not getattr(self, '_cleanup_task', None) or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_db_cleanup())
        if not getattr(self, '_wt_cleanup_task', None) or self._wt_cleanup_task.done():
            self._wt_cleanup_task = asyncio.create_task(self._periodic_worktree_cleanup())

    async def enqueue_worker_spawn(self, **job) -> None:
        await self._spawn_queue.put(job)

    async def _spawn_worker_loop(self) -> None:
        from app.db import update_job
        while True:
            job = await self._spawn_queue.get()
            job_id = job.get("job_id", "?")
            try:
                update_job(job_id, "executing")
                # Brief yield: lets the MCP tool that enqueued this job return its
                # response to the agent before the spawn starts writing to the DB
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
                session.last_task_sender = job.get("parent_name", "")
                await session.send(job["task"])
                update_job(job_id, "succeeded")
                logger.info(f"Worker '{job['name']}' spawned (job {job_id})")
            except Exception as e:
                update_job(job_id, "failed", str(e))
                logger.error(f"Spawn '{job.get('name')}' failed (job {job_id}): {e}")
            finally:
                self._spawn_queue.task_done()

    @staticmethod
    def _auto_commit_if_dirty(repo_path: str) -> str:
        # Worktrees branch from HEAD of the source repo — if it's dirty, the new
        # worktree inherits unstaged junk. Auto-commit gives the worker a clean base.
        import subprocess, datetime
        r = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
        if r.returncode != 0:
            logger.error(f"auto-commit git status failed in {repo_path}: {r.stderr.strip()}")
            return f"FAILED to check repo status (git status rc={r.returncode}) — spawn proceeds, auto-save NOT run"
        if not r.stdout.strip():
            return ""
        files = [l[3:] for l in r.stdout.strip().splitlines()]
        cur = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo_path, capture_output=True, text=True)
        branch = cur.stdout.strip() or "(detached HEAD)"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = (f"WIP: auto-saved uncommitted changes before worker spawn ({ts})\n\n"
               f"Orchestra committed {len(files)} dirty path(s) in the source repo checkout "
               f"(branch {branch}) to give the new worker a clean base. Review and amend/reset "
               f"if this buried work-in-progress:\n"
               + "\n".join(f"- {f}" for f in files))
        add = subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True, text=True)
        if add.returncode != 0:
            logger.error(f"auto-commit git add failed in {repo_path}: {add.stderr.strip()}")
            return f"FAILED to auto-save dirty source repo (git add rc={add.returncode}) — spawn proceeds on DIRTY base"
        commit = subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, capture_output=True, text=True)
        if commit.returncode != 0:
            logger.error(f"auto-commit failed in {repo_path}: {commit.stderr.strip()}")
            return (f"FAILED to auto-save dirty source repo (git commit rc={commit.returncode}: "
                    f"{commit.stderr.strip()[:120]}) — spawn proceeds, changes NOT committed")
        logger.warning(f"Auto-committed {len(files)} dirty path(s) in {repo_path} (branch {branch}) before spawn")
        return f"auto-committed {len(files)} dirty file(s) (branch {branch}) before spawn — review the WIP commit"

    @staticmethod
    def _ownership_prompt(owned_dirs: list[str]) -> str:
        if not owned_dirs:
            return ""
        lines = "\n".join(f"- {d}/" for d in owned_dirs)
        return ("\n\n## Directory ownership\n"
                "You OWN these directories — edit ONLY files under them:\n"
                f"{lines}\n"
                "Do NOT touch files outside your owned directories. "
                "If the task requires it — STOP and ask the orchestrator.")

    # ── Session CRUD ──

    async def create_session(self, name: str, scope: str, cwd: str, model: str,
                             system_prompt: str = "", use_worktree: bool = False,
                             repo_path: str | None = None, is_orchestrator: bool = False,
                             role: str = "", task_id: str = "", description: str = "",
                             base_branch: str = "",
                             parent_id: str = "", parent_name: str = "",
                             mcp_servers: dict | None = None,
                             pipeline: str = "", profile: str = "",
                             docs_feature: str = "",
                             owned_dirs: list | None = None,
                             tg_topic: bool = False) -> AgentSession:
        scope = scope.rstrip("/")
        cwd = cwd.rstrip("/")
        model = resolve_model(model)
        if not Path(cwd).is_dir():
            raise ValueError(f"cwd does not exist: {cwd}")
        existing = get_session_by_name(name, scope)
        if existing:
            st = existing.get("status", "?")
            ctx = existing.get("context_pct", 0) or 0
            raise ValueError(f"worker '{name}' already exists ({st}, ctx:{ctx}%). Use send_message instead")
        # An archived row still holds UNIQUE(name, scope) but get_session_by_name hides it →
        # INSERT would IntegrityError. Free the slot (its logs cascade — it's gone anyway).
        delete_archived_session(name, scope)

        # Явно ли указана роль: генерик-воркер (role не задан) валидируется как
        # unrouted (child_role="") — им управляет allow_unrouted_workers родителя.
        explicit_role = bool(role)
        if not role:
            role = "orchestrator" if is_orchestrator else "worker"

        # Активный пайплайн: явный аргумент главнее, иначе наследуем от родителя
        # (или DEFAULT_PIPELINE для корня). parent_name тут — только явно переданный;
        # для воркеров без parent_name он доразрешается ниже (auto-find).
        explicit_pipeline = bool(pipeline)
        parent_pipeline = self._resolve_pipeline(parent_name, scope) if parent_name else ""
        pipeline = pipeline or get_active_pipeline(scope, parent_pipeline=parent_pipeline)

        # Активный профиль Claude: явный аргумент главнее, иначе наследуем от
        # родителя (пусто для корня → env процесса). Зеркало логики pipeline.
        explicit_profile = bool(profile)
        parent_profile = self._resolve_profile(parent_name, scope) if parent_name else ""
        profile = profile or get_active_profile(scope, parent_profile=parent_profile)

        # R1: is_orchestrator из манифеста (kind), fallback на frozenset апстрима.
        is_orch = self._role_is_orchestrator(pipeline, role)

        # Ownership (upstream): нормализуем owned_dirs и предупреждаем о пересечении
        # с другими живыми воркерами в этом scope (warning, НЕ блок).
        owned_dirs = parse_owned_dirs(owned_dirs)
        if owned_dirs:
            seen_ids: set[str] = set()
            for s in self.sessions.values():
                if s.scope == scope and s.status.value in ("idle", "running", "waiting") and s.owned_dirs:
                    seen_ids.add(s.id)
                    ov = dirs_overlap(owned_dirs, s.owned_dirs)
                    if ov:
                        raise ValueError(
                            f"owned_dirs overlap with '{s.name}': {', '.join(ov)}. "
                            f"Use different dirs or kill '{s.name}' first"
                        )
            for row in get_all_sessions(scope):
                if row["id"] in seen_ids:
                    continue
                if (row.get("status") or "") not in ("idle", "running", "waiting"):
                    continue
                row_dirs = parse_owned_dirs(row.get("owned_dirs"))
                if row_dirs:
                    ov = dirs_overlap(owned_dirs, row_dirs)
                    if ov:
                        raise ValueError(
                            f"owned_dirs overlap with '{row['name']}': {', '.join(ov)}. "
                            f"Use different dirs or kill '{row['name']}' first"
                        )

        if not parent_name and not is_orch:
            parent_name = self._find_orchestrator_name(scope) or ""
            if parent_name and not explicit_pipeline:
                # Доразрешили родителя авто-поиском — воркер наследует его пайплайн.
                parent_pipeline = self._resolve_pipeline(parent_name, scope)
                pipeline = get_active_pipeline(scope, parent_pipeline=parent_pipeline)
                is_orch = self._role_is_orchestrator(pipeline, role)
            if parent_name and not explicit_profile:
                # Тот же авто-найденный родитель — воркер наследует и его профиль.
                parent_profile = self._resolve_profile(parent_name, scope)
                profile = get_active_profile(scope, parent_profile=parent_profile)

        if is_orch:
            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
        else:
            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
            prompt += self._ownership_prompt(owned_dirs)

        # Worker persistent memory: docs/workers/{name}.md or docs/workers/{role}.md
        # Survives kill/respawn/compact — worker writes rules here, they auto-inject next time
        worker_memory = self._load_worker_memory(name, role, scope)
        if worker_memory:
            prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"

        if not parent_id and parent_name:
            p_session = self.get_by_name(parent_name, scope)
            if p_session:
                parent_id = p_session.id

        # R2: валидация спавна ДО любых side-effects (worktree/start). Только
        # манифест-путь (validate_spawn) — legacy frontmatter-fallback (role_can_spawn
        # из app/prompts) удалён. Нет манифеста → FileNotFoundError пробрасывается
        # (fail loud, единый источник = pipelines/).
        parent_role = self._resolve_role(parent_name, scope) if parent_name else ""
        validate_spawn(pipeline, parent_role, role if explicit_role else "")

        # Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).
        # Делаем ДО create_worktree, когда pipeline/role/parent_name уже определены.
        base_branch = self._resolve_base_branch(base_branch, pipeline, role, parent_name, scope)

        # Root orchestrators get a dedicated TG topic so users can message them
        # directly from Telegram without knowing worker names
        if is_orch and not parent_name:
            tg_topic = True

        custom_mcp = _parse_custom_mcp(mcp_servers)
        bt = backend_for_model(model)
        _rr_effort = get_role(pipeline, role)
        raw_effort = getattr(_rr_effort, "effort", None) if _rr_effort else None
        effort = raw_effort if isinstance(raw_effort, str) and raw_effort else None
        session = AgentSession(
            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
            system_prompt=prompt, role=role,
            parent_id=parent_id, parent_name=parent_name,
            pipeline=pipeline, profile=profile,
            color="" if is_orch else self._pick_color(),
            mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name, extra=custom_mcp),
            mcp_servers_custom=custom_mcp,
            backend_type=bt, effort=effort, task_id=task_id, description=description,
            owned_dirs=owned_dirs,
            tg_topic=tg_topic,
        )
        session.is_orchestrator = is_orch
        session._template_hash = prompt_template_hash(role)
        session._spawn_warning = ""
        save_session(session._to_db_dict())

        if task_id and not is_orch:
            try:
                from app.tm import api_update_task
                api_update_task(task_id, status="in_progress")
            except Exception as e:
                logger.warning(f"task #{task_id} → in_progress failed on spawn: {e}")

        try:
            if use_worktree and repo_path:
                wip_note = await asyncio.to_thread(self._auto_commit_if_dirty, repo_path)
                if wip_note:
                    session._spawn_warning = (session._spawn_warning + "; " + wip_note).strip("; ")
                # Worktree-конфиг из манифеста (симлинки + copies). Нет манифеста
                # → None → create_worktree использует upstream-fallback (PROJECT_FILES).
                try:
                    worktree_cfg = get_worktree_config(pipeline)
                except FileNotFoundError:
                    worktree_cfg = None
                wt = await asyncio.to_thread(
                    create_worktree, repo_path, name, scope, task_id, base_branch, worktree_cfg)
                session.cwd = wt.path
                session.worktree_path = wt.path
                session.branch = wt.branch
                try:
                    _rr = get_role(pipeline, role)
                    _skills = _rr.skills if _rr else None
                except FileNotFoundError:
                    _skills = None
                if _skills and _skills != "all":
                    await asyncio.to_thread(inject_skills_to_worktree, _skills, wt.path)

            try:
                await asyncio.to_thread(
                    _scaffold_role_docs, pipeline, session.cwd, role, docs_feature)
            except Exception:
                logger.warning("docs scaffold failed for role '%s'", role)

            if not is_orch:
                orch_name = parent_name or self._find_orchestrator_name(scope)
                session.system_prompt = safe_format_prompt(
                    session.system_prompt,
                    worker_name=name, orchestrator_name=orch_name or "orchestrator",
                    scope=scope, branch=session.branch or "main",
                )
                session.on_idle = self._make_idle_callback(scope)

            save_session(session._to_db_dict())
            await session.start()
            self.sessions[session.id] = session
            return session
        except BaseException:
            if session.worktree_path and repo_path:
                try:
                    await asyncio.to_thread(remove_worktree, repo_path, session.worktree_path)
                except Exception as e:
                    logger.warning(
                        f"worktree cleanup failed after spawn error ({session.worktree_path}): {e}",
                        exc_info=True)
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
                except Exception as e:
                    logger.warning(
                        f"worktree cleanup failed on remove ({session.worktree_path}): {e}",
                        exc_info=True)
        archive_session(session_id)

    async def change_orchestrator_scope(self, name: str, old_scope: str,
                                         new_scope: str, new_cwd: str) -> dict:
        """Move an idle, worker-free orchestrator to a new scope/cwd.

        Updates DB (db.change_scope), then rebuilds the runtime: kills the old MCP
        subprocess via _disconnect_backend(), swaps scope/cwd/mcp_servers, and lets
        the backend lazily reconnect on the next send() with the new ORCHESTRA_SCOPE.
        session_id is preserved → context survives.
        """
        old_scope = old_scope.rstrip("/")
        new_scope = new_scope.rstrip("/")
        new_cwd = new_cwd.rstrip("/")
        session = self.get_by_name(name, old_scope)
        # live-only: detached hydrate has no backend/MCP to rebuild
        if not session or not session.loaded:
            return {"error": f"orchestrator '{name}' not loaded in scope '{old_scope}'"}
        if not session.is_orchestrator:
            return {"error": f"'{name}' is not an orchestrator — scope change is orchestrator-only"}
        if not Path(new_cwd).is_dir():
            return {"error": f"new_cwd does not exist: {new_cwd}"}

        live_workers = self._live_workers_in_scope(old_scope)
        if live_workers:
            return {"error": f"cannot change scope: live workers in '{old_scope}' — "
                             f"merge+kill first: {', '.join(live_workers)}"}

        # Hold the session lifecycle lock so a concurrent send() cannot flip
        # the session IDLE→RUNNING between the idle check and the disconnect.
        # (send() only starts a fresh turn inside this same lock.)
        async with session._lifecycle_lock:
            if session.status.value == "running":
                return {"error": "cannot change scope while running — wait for idle"}

            # Re-check under the lock right before the DB write to shrink the
            # worker-spawn TOCTOU window (a spawn could have landed since the
            # pre-lock scan). Full closure needs a scope-level spawn lock.
            live_workers = self._live_workers_in_scope(old_scope)
            if live_workers:
                return {"error": f"cannot change scope: live workers appeared in '{old_scope}' — "
                                 f"merge+kill first: {', '.join(live_workers)}"}

            # Stop the backend (no new persists from this session) and drain any
            # in-flight _persist() BEFORE the transaction, so change_scope()'s
            # synchronous scope+cwd write is the last writer. Otherwise a stale
            # queued persist (snapshot cwd=/old) could land after the transaction
            # and clobber cwd, leaving scope=/new + cwd=/old on disk.
            await session._disconnect_backend()
            await session._drain_persist()

            from app.db import change_scope
            result = change_scope(session.id, old_scope, new_scope, new_cwd)
            if not result.get("ok"):
                return result

            session.scope = new_scope
            session.cwd = new_cwd
            # Migrate CLI session file so resume works in new cwd
            if session.session_id:
                self._migrate_cli_session(session.session_id, old_scope, new_scope)
            session.mcp_servers = _make_mcp_config(name, new_scope, session.role,
                                                   parent_name=session.parent_name,
                                                   extra=session.mcp_servers_custom)
            session._persist()
            if session._persist_task:
                await asyncio.gather(session._persist_task, return_exceptions=True)
        logger.info(f"Orchestrator '{name}' scope changed: {old_scope} → {new_scope}")
        return result

    @staticmethod
    def _migrate_cli_session(session_id: str, old_scope: str, new_scope: str) -> None:
        """Copy CLI session files from old project dir to new so resume works after scope change."""
        cli_base = Path.home() / ".claude" / "projects"
        old_dir = cli_base / old_scope.replace("/", "-").lstrip("-")
        new_dir = cli_base / new_scope.replace("/", "-").lstrip("-")
        if not old_dir.is_dir():
            return
        import shutil
        new_dir.mkdir(parents=True, exist_ok=True)
        for f in old_dir.glob(f"{session_id}*"):
            shutil.copy2(f, new_dir / f.name)
            logger.info(f"migrated CLI session file: {f.name} → {new_dir}")

    def _live_workers_in_scope(self, scope: str) -> list[str]:
        """Names of active (idle/running/waiting) workers in scope, from both the
        in-memory registry and the DB (catches unloaded-but-active worker rows).
        Deduplicated by session id."""
        active = ("idle", "running", "waiting")
        seen_ids: set[str] = set()
        names: set[str] = set()
        for s in self.sessions.values():
            if s.scope == scope and not s.is_orchestrator and s.status.value in active:
                seen_ids.add(s.id)
                names.add(s.name)
        for row in get_all_sessions(scope):
            if row["id"] in seen_ids:
                continue
            if is_orchestrator_role(row.get("role", "worker")):
                continue
            if (row.get("status") or "") in active:
                names.add(row["name"])
        return sorted(names)

    def _live_children(self, parent_name: str, scope: str) -> list[str]:
        """Names of active (idle/running/waiting) children spawned by ``parent_name``
        in ``scope``, from both the in-memory registry and the DB (catches
        unloaded-but-active rows). Deduplicated by session id. Used to block
        killing a parent that still has live sub-workers (would orphan them)."""
        if not parent_name:
            return []
        active = ("idle", "running", "waiting")
        seen_ids: set[str] = set()
        names: set[str] = set()
        for s in self.sessions.values():
            if s.scope == scope and s.parent_name == parent_name and s.status.value in active:
                seen_ids.add(s.id)
                names.add(s.name)
        for row in get_all_sessions(scope):
            if row["id"] in seen_ids:
                continue
            if (row.get("parent_name") or "") != parent_name:
                continue
            if (row.get("status") or "") in active:
                names.add(row["name"])
        return sorted(names)

    async def remove_scope(self, scope: str, delete_tg_topics: bool = False) -> dict:
        orch_names: list[str] = []
        for s in self.sessions.values():
            if s.scope == scope and s.is_orchestrator and s.name not in orch_names:
                orch_names.append(s.name)
        for row in get_all_sessions(scope):
            if bool(row.get("is_orchestrator")) and row["name"] not in orch_names:
                orch_names.append(row["name"])

        to_remove = [s for s in self.sessions.values() if s.scope == scope]
        for s in to_remove:
            await self.remove(s.id)
        for row in get_all_sessions(scope):
            archive_session(row["id"])

        tg_result: dict = {}
        if delete_tg_topics and orch_names and self.tg_topics_remover:
            tg_result = await self.tg_topics_remover(orch_names)
        return {"tg": tg_result}

    # ── Lookups ──

    def get(self, session_id: str) -> Optional[AgentSession]:
        return self.sessions.get(session_id)

    def get_by_name(self, name: str, scope: str) -> AgentSession | None:
        """Live session from registry, or detached hydrate from DB. Never a dict."""
        scope = scope.rstrip("/")
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s
        db_row = get_session_by_name(name, scope)
        return self._hydrate_row(db_row) if db_row else None

    @staticmethod
    def _hydrate_row(row: dict) -> AgentSession:
        """DB row → detached AgentSession (loaded=False). Data only: no start(),
        no prompt assembly, no git — unlike the heavy resume path (_resume_session)."""
        try:
            status = AgentStatus(row.get("status") or "idle")
        except ValueError:
            status = AgentStatus.IDLE
        s = AgentSession(
            id=row["id"], name=row["name"], scope=row["scope"],
            cwd=row.get("cwd") or row["scope"],
            model=row.get("model") or "",
            system_prompt=row.get("system_prompt") or "",
            status=status,
            session_id=row.get("session_id"),
            cost_usd=row.get("cost_usd") or 0.0,
            cost_usd_cached=row.get("cost_usd_cached") or 0.0,
            _context_cost=row.get("context_cost") or 0.0,
            worktree_path=row.get("worktree_path"),
            branch=row.get("branch"),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(timezone.utc),
            role=row.get("role") or "worker",
            parent_id=row.get("parent_id") or "",
            parent_name=row.get("parent_name") or "",
            pipeline=row.get("pipeline") or "",
            profile=row.get("profile") or "",
            backend_type=row.get("backend_type") or "claude",
            runtime_handoff=row.get("runtime_handoff") or "",
            task_id=row.get("task_id") or "",
            description=row.get("description") or "",
            owned_dirs=parse_owned_dirs(row.get("owned_dirs")),
            tg_topic=bool(row.get("tg_topic") or 0),
            effort=row.get("effort") or None,
            loaded=False,
            db_row=row,
        )
        if row.get("is_orchestrator") is not None:
            s.is_orchestrator = bool(row.get("is_orchestrator"))
        raw_hist = row.get("session_id_history") or "[]"
        try:
            s.session_id_history = json.loads(raw_hist) if isinstance(raw_hist, str) else raw_hist
        except (json.JSONDecodeError, TypeError):
            s.session_id_history = []
        s.needs_switch = bool(row.get("needs_switch") or 0)
        s.progress_pct = row.get("progress_pct") or 0
        s.progress_status = row.get("progress_status") or ""
        s.total_turns = row.get("total_turns") or 0
        s.total_input_tokens = row.get("total_input_tokens") or 0
        s.total_output_tokens = row.get("total_output_tokens") or 0
        s.total_cache_read_tokens = row.get("total_cache_read_tokens") or 0
        s.total_cache_create_tokens = row.get("total_cache_create_tokens") or 0
        s.total_tool_calls = row.get("total_tool_calls") or 0
        s._last_context = {
            "percentage": row.get("context_pct", 0) or 0,
            "total_tokens": row.get("context_tokens", 0) or 0,
            "max_tokens": 0,
        }
        return s

    _UPDATABLE_FIELDS = frozenset({"description", "system_prompt", "tg_topic"})

    def update_session_fields(self, name: str, scope: str, **fields) -> AgentSession | None:
        """Update simple session fields atomically for the caller.
        Live session → setattr + _persist(); detached → direct DB UPDATE."""
        unknown = set(fields) - self._UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"non-updatable fields: {sorted(unknown)}")
        found = self.get_by_name(name, scope)
        if not found:
            return None
        if found.loaded:
            for k, v in fields.items():
                setattr(found, k, v)
            found._persist()
        else:
            from app.db import _conn
            sets = ", ".join(f"{k}=?" for k in fields)
            vals = [int(v) if isinstance(v, bool) else v for v in fields.values()]
            with _conn() as c:
                c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*vals, found.id))
        return found

    def _resolve_role(self, name: str, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.role
        row = get_session_by_name(name, scope)
        return row.get("role") if row else None

    def _resolve_pipeline(self, name: str, scope: str) -> str:
        """Пайплайн сессии ``name`` (для наследования детьми). '' если не найдена."""
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.pipeline or ""
        row = get_session_by_name(name, scope)
        return (row.get("pipeline") or "") if row else ""

    def _resolve_profile(self, name: str, scope: str) -> str:
        """Профиль Claude сессии ``name`` (для наследования детьми). '' если не найдена."""
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.profile or ""
        row = get_session_by_name(name, scope)
        return (row.get("profile") or "") if row else ""

    def _resolve_base_branch(self, base_branch: str, pipeline: str, role: str,
                             parent_name: str, scope: str) -> str:
        """Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).

        Приоритеты:
        - явно переданная ``base_branch`` важнее стратегии манифеста (B3);
        - нет манифеста / ``strategy=main`` → ``"main"`` (back-compat с апстримом);
        - ``strategy=parent`` → ветка рабочего дерева родителя; если её нет —
          fallback на ``"main"`` с warning (корневой Хаб без worktree и т.п.).
        """
        # B3: явно переданная ветка важнее стратегии манифеста.
        if base_branch:
            return base_branch
        try:
            rr = get_role(pipeline, role)
        except FileNotFoundError:
            rr = None
        # Нет манифеста / стратегия main → от main (back-compat, default 1:1 upstream).
        if rr is None or rr.base_branch_strategy == "main":
            return "main"
        # strategy == "parent": ветка рабочего дерева родителя.
        parent_branch = ""
        if parent_name:
            ps = self.get_by_name(parent_name, scope)
            if ps is not None:
                parent_branch = ps.branch or ""
        if not parent_branch:
            logger.warning(
                "base_branch_strategy=parent, но у родителя '%s' нет ветки — fallback на main",
                parent_name)
            return "main"
        return parent_branch

    @staticmethod
    def _role_is_orchestrator(pipeline: str, role: str) -> bool:
        """R1: is_orchestrator из kind манифеста; fallback на frozenset апстрима.

        Манифеста нет (FileNotFoundError) или роли нет в нём → ``is_orchestrator_role``.
        """
        try:
            rr = get_role(pipeline, role)
        except FileNotFoundError:
            rr = None
        if rr is not None:
            return rr.is_orchestrator
        return is_orchestrator_role(role)

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
        # Old rows (migrated) store pipeline='' → normalize to DEFAULT_PIPELINE.
        # Without this, ROLE_SYSTEM_PROMPT('') now fails loud (legacy fallback removed)
        # and resume/load of pre-pipeline sessions would break.
        pipeline = db_row.get("pipeline") or DEFAULT_PIPELINE
        # R1: is_orch из манифеста пайплайна (kind) при наличии; иначе хранимая
        # колонка is_orchestrator (денормализована при спавне); иначе frozenset.
        is_orch = self._role_is_orchestrator(pipeline, role)
        try:
            if get_role(pipeline, role) is None:
                is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
        except FileNotFoundError:
            is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
        old_prompt = db_row.get("system_prompt", "")
        current_prompt = ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
        worker_memory = self._load_worker_memory(db_row["name"], role, db_row["scope"])
        if worker_memory:
            current_prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"
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
            actual = await asyncio.to_thread(
                subprocess.run,
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
            _context_cost=db_row.get("context_cost", 0),
            worktree_path=wt_path, branch=db_branch,
            created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
            role=role,
            parent_id=db_row.get("parent_id", ""),
            parent_name=db_row.get("parent_name", ""),
            pipeline=db_row.get("pipeline", ""),
            profile=db_row.get("profile", ""),
            color="" if is_orch else (db_row.get("color") or self._pick_color()),
            mcp_servers=_make_mcp_config(db_row["name"], db_row["scope"], role,
                                         parent_name=db_row.get("parent_name", ""), extra=custom_mcp),
            mcp_servers_custom=custom_mcp,
            backend_type=stored_bt, effort=db_row.get("effort") or None,
            runtime_handoff=db_row.get("runtime_handoff") or "",
            task_id=db_task_id,
            description=db_row.get("description", ""),
            owned_dirs=parse_owned_dirs(db_row.get("owned_dirs")),
            tg_topic=bool(db_row.get("tg_topic", 0)),
        )
        session.total_turns = db_row.get("total_turns") or 0
        session.total_input_tokens = db_row.get("total_input_tokens") or 0
        session.total_output_tokens = db_row.get("total_output_tokens") or 0
        session.total_cache_read_tokens = db_row.get("total_cache_read_tokens") or 0
        session.total_cache_create_tokens = db_row.get("total_cache_create_tokens") or 0
        session.total_tool_calls = db_row.get("total_tool_calls") or 0
        session.is_orchestrator = is_orch  # R1: восстановить денормализованное поле
        raw_hist = db_row.get("session_id_history") or "[]"
        try:
            session.session_id_history = json.loads(raw_hist) if isinstance(raw_hist, str) else raw_hist
        except (json.JSONDecodeError, TypeError):
            session.session_id_history = []
        pct = db_row.get("context_pct", 0) or 0
        tokens = db_row.get("context_tokens", 0) or 0
        if pct or tokens:
            max_t = CONTEXT_LIMITS.get(db_row["model"], 200000)
            session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": max_t}
        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
        if not is_orch:
            current_prompt = safe_format_prompt(
                current_prompt,
                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                scope=db_row["scope"], branch=db_row.get("branch") or "main",
            )
        if old_prompt and old_prompt != current_prompt:
            formatted_base = safe_format_prompt(
                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                scope=db_row["scope"], branch=db_row.get("branch") or "main",
            )
            if old_prompt.startswith(formatted_base) and len(old_prompt) > len(formatted_base):
                custom_part = old_prompt[len(formatted_base):]
                current_prompt = current_prompt + custom_part
        session._current_prompt = current_prompt
        session._template_hash = db_row.get("template_hash") or prompt_template_hash(role)
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
        async def _on_worker_idle(
                worker_name: str,
                worker_scope: str,
                last_texts: list[str],
                stop_reason: str = "",
                turn_ok: bool = True):
            worker_session = next((s for s in self.sessions.values() if s.name == worker_name), None)
            parent = worker_session.parent_name if worker_session else None
            orch = parent or self._find_orchestrator_name(scope)
            if not orch:
                return
            orch_session = next((s for s in self.sessions.values() if s.name == orch), None)
            if not orch_session:
                return
            summary = "\n".join(last_texts[-3:]) if last_texts else "(no output)"
            ctx = self._context_warning(worker_name)
            sr = f" (stop_reason={stop_reason})" if stop_reason else ""
            outcome = (
                "Finished without explicit report"
                if turn_ok
                else "Turn failed before an explicit report"
            )
            msg = (
                f"[from:{worker_name}] [auto-report]{sr} {outcome}. "
                f"Last output:\n{summary}{ctx}"
            )
            logger.info(f"Auto-report: {worker_name} → {orch}")
            await orch_session.send(msg)
        return _on_worker_idle

    # ── Listings ──

    def list_sessions(self, scope: str | None = None) -> list[dict]:
        from app.db import get_last_turn_map
        result = []
        seen = set()
        for s in self.sessions.values():
            if scope is None or s.scope == scope:
                result.append(s.to_dict())
                seen.add(s.id)
        for row in get_all_sessions(scope):
            if row["id"] not in seen:
                result.append(row)
        # Cache-timer metadata is runtime-derived; Codex exposes only an approximate window.
        turn_map = get_last_turn_map()
        for r in result:
            r["last_turn_ts"] = turn_map.get(r["id"])
            runtime = r.get("backend_type") or r.get("runtime") or r.get("backend") or "claude"
            r.update(cache_policy_for_runtime(runtime))
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

    @staticmethod
    def _load_worker_memory(name: str, role: str, scope: str) -> str:
        """Load persistent memory from docs/workers/{name}.md or docs/workers/{role}.md.

        Workers write their learned rules here; the file survives kill/respawn/compact
        and auto-injects into system_prompt on next spawn.
        """
        base = Path(scope)
        for filename in (f"{name}.md", f"{role}.md" if role else None):
            if not filename:
                continue
            path = base / "docs" / "workers" / filename
            if path.is_file():
                try:
                    content = path.read_text().strip()
                    if content:
                        logger.info(f"Loaded worker memory: {path} ({len(content)} chars)")
                        return content
                except Exception as e:
                    logger.warning(f"Failed to read worker memory {path}: {e}")
        return ""

    def _pick_color(self) -> str:
        # Check both in-memory sessions AND DB to avoid duplicates on concurrent spawn / resume
        used = {s.color for s in self.sessions.values() if s.color}
        for row in get_all_sessions():
            if row.get("color"):
                used.add(row["color"])
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
            was_waiting = {r["id"] for r in c.execute(
                "SELECT id FROM sessions WHERE status = 'waiting'"
            ).fetchall()}
            resumable = [dict(r) for r in c.execute(
                "SELECT * FROM sessions WHERE session_id IS NOT NULL "
                "AND status IN ('running', 'idle', 'waiting')"
            ).fetchall()]
            # Reset to idle before loading: prevents any session from resuming
            # as 'running' (the backend process died on server restart)
            c.execute("UPDATE sessions SET status='idle' WHERE status IN ('running', 'waiting')")

        # R1: load orchestrators first — workers need their parent_name resolved,
        # and the orchestrator's on_idle callback registered before workers resume
        orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
        workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]

        for row in orchs:
            if row["id"] in self.sessions:
                continue
            if not Path(row.get("cwd") or row["scope"]).is_dir():
                continue
            try:
                session = await self._load_from_db(row)
                logger.info(f"Resumed orchestrator: {row['name']}")
                if row["id"] in was_waiting:
                    from app.bg_jobs import bg_manager
                    if bg_manager and bg_manager.has_active_jobs(row["id"]):
                        session.status = AgentStatus.WAITING
                        session._persist()
                elif row["id"] in was_running:
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
                if row["id"] in was_waiting:
                    from app.bg_jobs import bg_manager
                    if bg_manager and bg_manager.has_active_jobs(row["id"]):
                        session.status = AgentStatus.WAITING
                        session._persist()
                elif row["id"] in was_running:
                    asyncio.create_task(self._inject_restart_notice(session))
            except Exception as e:
                logger.error(f"Failed to resume worker {row['name']}: {e}")

    async def _inject_restart_notice(self, session: AgentSession) -> None:
        import random
        # Random stagger: if N agents resume simultaneously they'd all hit the SDK
        # concurrently and cause a connection storm; spread them over 15s
        await asyncio.sleep(3 + random.uniform(0, 12))
        try:
            await session.send(
                "[system] Orchestra server restarted. "
                "Your session was restored — continue where you left off."
            )
            logger.info(f"Restart notice injected: {session.name}")
        except Exception as e:
            logger.warning(f"Failed to inject restart notice to {session.name}: {e}")

    async def _periodic_db_cleanup(self) -> None:
        CLEANUP_INTERVAL = 6 * 3600
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                from app.db import cleanup_old_logs
                deleted = await asyncio.to_thread(cleanup_old_logs, 7)
                if deleted:
                    logger.info(f"DB cleanup: deleted {deleted} old log entries")
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"DB cleanup failed: {e}")

    async def _periodic_worktree_cleanup(self) -> None:
        WT_CLEANUP_INTERVAL = 24 * 3600
        try:
            from app.workspace import cleanup_stale_worktrees
            removed = await asyncio.to_thread(cleanup_stale_worktrees)
            if removed:
                logger.info(f"Startup worktree cleanup: removed {len(removed)} stale worktree(s)")
        except Exception as e:
            logger.warning(f"Startup worktree cleanup failed: {e}")
        while True:
            try:
                await asyncio.sleep(WT_CLEANUP_INTERVAL)
                from app.workspace import cleanup_stale_worktrees
                removed = await asyncio.to_thread(cleanup_stale_worktrees)
                if removed:
                    logger.info(f"Periodic worktree cleanup: removed {len(removed)} stale worktree(s)")
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"Periodic worktree cleanup failed: {e}")

    async def shutdown_all(self) -> None:
        background_tasks = [
            task for task in (
                self._spawn_task,
                getattr(self, '_cleanup_task', None),
                getattr(self, '_wt_cleanup_task', None),
            )
            if task is not None
        ]
        for task in background_tasks:
            if not task.done():
                task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        self._spawn_task = None
        self._cleanup_task = None
        self._wt_cleanup_task = None
        sessions = list(self.sessions.values())
        results = await asyncio.gather(
            *(session.stop() for session in sessions),
            return_exceptions=True,
        )
        for session, result in zip(sessions, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "session '%s' stop failed on shutdown: %s",
                    session.name,
                    result,
                )
        self.sessions.clear()
        # asyncio primitives bind lazily to their first event loop. Lifespan may be
        # entered again by TestClient or an embedded server in the same process.
        self._spawn_queue = asyncio.Queue()
        self._session_locks.clear()
