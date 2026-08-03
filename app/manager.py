"""SessionManager — registry, lifecycle, persistence for all agent sessions."""

import asyncio
import json
import logging
import os
import re
import sqlite3
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
from app.workspace import (
    create_worktree, discard_prepared_worktree, remove_worktree,
    parse_owned_dirs, dirs_overlap,
    validate_repo_root, resolve_base_branch as resolve_git_base_branch,
)
from app.models import (
    CONTEXT_LIMITS,
    available_models_block,
    backend_for_model,
    cache_policy_for_runtime,
    get_model_spec,
    resolve_model,
    runtime_for_record,
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
    get_session, get_session_by_name, get_all_sessions, publish_ready_session,
    archive_session, get_stats, update_session_lifecycle,
)

logger = logging.getLogger(__name__)

from app.runtime_env import MCP_BASE_ENV, MCP_STDIO_CMD  # noqa: F401 — re-exported for callers

COLOR_PALETTE = [
    "#818cf8", "#34d399", "#f97316", "#38bdf8", "#f472b6",
    "#a78bfa", "#fbbf24", "#2dd4bf", "#fb7185", "#4ade80",
]


async def _wait_owned_task(task: asyncio.Task) -> asyncio.CancelledError | None:
    """Wait without letting caller cancellation penetrate an owned operation."""
    cancellation = None
    current = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if current is not None and current.cancelling():
                cancellation = cancellation or error
                while current.cancelling():
                    current.uncancel()
            elif task.done():
                break
            else:
                raise
        except BaseException:
            break
    return cancellation


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
    except (sqlite3.Error, KeyError, TypeError):
        # Возвращать "" нельзя: пустой блок читается агентом как "других оркестраторов
        # нет", а не как "список не собрался". Деградируем ГРОМКО — в лог и в промпт.
        logger.exception(
            f"prompt block 'other orchestrators' failed for scope={exclude_scope!r}"
        )
        return ("## Other orchestrators\n"
                "⚠️ Orchestrator list unavailable (internal error) — "
                "use `list_orchestrators` before assuming there are none.")


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
                 "These workers exist in your project. Reuse idle ones instead of spawning new; lifecycle and kill decisions follow the orchestration Kill gate."]
        for w in mine:
            lines.append(_fmt(w))

        if others:
            lines.append("")
            lines.append("## Other orchestrators' workers")
            lines.append("⚠️ These belong to other orchestrators. Do NOT send them tasks — message their orchestrator instead.")
            for w in others:
                lines.append(_fmt(w, show_owner=True))

        return "\n".join(lines)
    except (sqlite3.Error, KeyError, TypeError):
        # Пустой блок агент читает как "воркеров нет" и плодит дубликаты вместо
        # переиспользования живых. Молчать здесь дороже, чем признать сбой.
        logger.exception(f"prompt block 'workers' failed for scope={scope!r}")
        return ("## Your current workers\n"
                "⚠️ Worker list unavailable (internal error) — "
                "use `list_agents` before spawning, you may already have workers.")


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
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
        # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
        self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None

    def get_session_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def start_background_tasks(self) -> None:
        # log retention REMOVED by owner decision: agent history is research data. The old
        # `_periodic_db_cleanup` dropped logs older than 7 days every 6h, silently destroying
        # every transcript past a week while `sessions` rows survived since May. Never restore
        if not getattr(self, '_wt_cleanup_task', None) or self._wt_cleanup_task.done():
            self._wt_cleanup_task = asyncio.create_task(self._periodic_worktree_cleanup())

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
        normalized_scope = scope.rstrip("/")
        key = (normalized_scope, name)
        lock = self._spawn_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await self._create_session_locked(
                name=name,
                scope=normalized_scope,
                cwd=cwd,
                model=model,
                system_prompt=system_prompt,
                use_worktree=use_worktree,
                repo_path=repo_path,
                is_orchestrator=is_orchestrator,
                role=role,
                task_id=task_id,
                description=description,
                base_branch=base_branch,
                parent_id=parent_id,
                parent_name=parent_name,
                mcp_servers=mcp_servers,
                pipeline=pipeline,
                profile=profile,
                docs_feature=docs_feature,
                owned_dirs=owned_dirs,
                tg_topic=tg_topic,
            )

    async def _create_session_locked(self, name: str, scope: str, cwd: str, model: str,
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
        spawn_repo_path = ""
        spawn_git_common_dir = ""
        existing = get_session_by_name(name, scope)
        if existing:
            st = existing.get("status", "?")
            ctx = existing.get("context_pct", 0) or 0
            raise ValueError(f"worker '{name}' already exists ({st}, ctx:{ctx}%). Use send_message instead")
        if use_worktree and not repo_path:
            raise ValueError("repo_path required when use_worktree=True")
        if use_worktree:
            repo_root = validate_repo_root(repo_path)
            repo_path = str(repo_root)
            spawn_repo_path = repo_path
            spawn_git_common_dir = str((repo_root / ".git").resolve())

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
        if use_worktree and repo_path:
            base_branch = self._resolve_base_branch(
                base_branch, pipeline, role, parent_name, scope, repo_path,
            )

        task_identity = None
        if task_id and not is_orch:
            from app.tm import resolve_scoped_task_identity
            task_identity = await asyncio.to_thread(
                resolve_scoped_task_identity, scope, task_id,
            )
            task_id = str(task_identity["par_number"])

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
            base_branch=base_branch,
            owned_dirs=owned_dirs,
            tg_topic=tg_topic,
        )
        session.is_orchestrator = is_orch
        session._template_hash = prompt_template_hash(role)
        session._spawn_warning = ""
        session._spawn_repo_path = spawn_repo_path
        session._spawn_git_common_dir = spawn_git_common_dir

        prepared_worktree = None

        async def prepare() -> None:
            nonlocal prepared_worktree
            if use_worktree and repo_path:
                # Worktree-конфиг из манифеста (симлинки + copies). Нет манифеста
                # → None → create_worktree использует upstream-fallback (PROJECT_FILES).
                try:
                    worktree_cfg = get_worktree_config(pipeline)
                except FileNotFoundError:
                    worktree_cfg = None
                wt = await asyncio.to_thread(
                    create_worktree, repo_path, name, task_id, base_branch, worktree_cfg)
                prepared_worktree = wt
                session.cwd = wt.path
                session.worktree_path = wt.path
                session.branch = wt.branch
                try:
                    _rr = get_role(pipeline, role)
                    _skills = _rr.skills if _rr else None
                except FileNotFoundError:
                    _skills = None
                if bt == "claude" and _skills and _skills != "all":
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
                    scope=scope, branch=session.branch or session.base_branch,
                )
                session.on_idle = self._make_idle_callback(scope)

            await session.start(persist=False)

        async def compensate() -> None:
            errors: list[str] = []
            try:
                await session.abort_unpublished()
            except Exception as error:
                errors.append(f"session abort: {type(error).__name__}: {error}")
            if prepared_worktree is not None and repo_path:
                try:
                    await asyncio.to_thread(
                        discard_prepared_worktree, repo_path, prepared_worktree,
                    )
                except Exception as error:
                    errors.append(f"Git cleanup: {type(error).__name__}: {error}")
            if errors:
                raise RuntimeError("; ".join(errors))

        async def compensate_after(error: BaseException) -> None:
            try:
                await compensate()
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"spawn failed ({type(error).__name__}: {error}); "
                    f"compensation failed: {cleanup_error}"
                ) from error

        prepare_task = asyncio.create_task(prepare())
        prepare_cancelled = await _wait_owned_task(prepare_task)
        try:
            prepare_task.result()
        except BaseException as prepare_error:
            primary_error = prepare_cancelled or prepare_error
        else:
            primary_error = prepare_cancelled
        if primary_error is not None:
            cleanup_task = asyncio.create_task(compensate_after(primary_error))
            await _wait_owned_task(cleanup_task)
            cleanup_task.result()
            raise primary_error

        async def finalize() -> AgentSession:
            try:
                await asyncio.to_thread(
                    publish_ready_session, session._to_db_dict(),
                )
            except BaseException as publish_error:
                await compensate_after(publish_error)
                raise

            self.sessions[session.id] = session

            if task_identity:
                from app.tm import api_update_task_if_current
                try:
                    task_status = await asyncio.to_thread(
                        api_update_task_if_current,
                        task_identity,
                        status="in_progress",
                        worker_session_id=session.id,
                    )
                except Exception as task_error:
                    detail = str(task_error) or type(task_error).__name__
                    task_status = {"ok": False, "error": detail}
                if not task_status.get("ok"):
                    detail = task_status.get("error") or "unknown task update failure"
                    session._spawn_warning = (
                        f"worker is ready, but task #{task_id} was not updated: {detail}"
                    )
                    logger.warning(session._spawn_warning)
            return session

        finalize_task = asyncio.create_task(finalize())
        await _wait_owned_task(finalize_task)
        return finalize_task.result()

    async def _auto_switch_before_delivery(self, session: AgentSession) -> None:
        if not session.needs_switch:
            return
        if session.status != AgentStatus.IDLE:
            raise RuntimeError(
                f"worker is {session.status.value} — cannot auto-switch before delivery"
            )
        if not session.worktree_path:
            raise RuntimeError("auto-switch failed: session has no worktree")

        async with session._lifecycle_lock:
            if not session.needs_switch:
                return
            if session.status != AgentStatus.IDLE:
                raise RuntimeError(
                    f"worker is {session.status.value} — cannot auto-switch before delivery"
                )

            from app.workspace import inspect_worktree_identity, switch_worktree_branch
            import time

            try:
                base_branch = await asyncio.to_thread(
                    resolve_git_base_branch,
                    session.worktree_path,
                    session.base_branch,
                )
            except Exception as error:
                detail = str(error) or type(error).__name__
                raise RuntimeError(
                    f"auto-switch failed: base resolution raised "
                    f"{type(error).__name__}: {detail}"
                ) from error
            adhoc_id = str(int(time.time()))[-6:]
            new_branch = f"adhoc-{adhoc_id}/{session.name}"
            try:
                result = await asyncio.to_thread(
                    switch_worktree_branch,
                    session.worktree_path,
                    new_branch,
                    base_branch,
                    force=True,
                )
            except Exception as error:
                detail = str(error) or type(error).__name__
                session.task_id = ""
                session.needs_switch = True
                try:
                    actual_branch, _actual_head = await asyncio.to_thread(
                        inspect_worktree_identity, session.worktree_path,
                    )
                except Exception as inspect_error:
                    inspect_detail = str(inspect_error) or type(inspect_error).__name__
                    detail = f"{detail}; actual Git state unavailable: {inspect_detail}"
                else:
                    try:
                        await self.persist_lifecycle(
                            session,
                            branch=actual_branch,
                            base_branch=base_branch,
                            task_id="",
                            needs_switch=True,
                        )
                    except Exception as persist_error:
                        session.branch = actual_branch
                        session.base_branch = base_branch
                        session.task_id = ""
                        session.needs_switch = True
                        persist_detail = (
                            str(persist_error) or type(persist_error).__name__
                        )
                        detail = (
                            f"{detail}; quarantine persistence failed: {persist_detail}"
                        )
                raise RuntimeError(
                    f"auto-switch failed: Git switch raised "
                    f"{type(error).__name__}: {detail}"
                ) from error
            if not result.get("ok"):
                detail = result.get("error") or "Git switch returned no error detail"
                if result.get("state") == "rollback_failed":
                    actual_branch = result.get("actual_branch") or session.branch or ""
                    try:
                        await self.persist_lifecycle(
                            session,
                            branch=actual_branch,
                            base_branch=base_branch,
                            task_id="",
                            needs_switch=True,
                        )
                    except Exception as persist_error:
                        session.branch = actual_branch
                        session.base_branch = base_branch
                        session.task_id = ""
                        session.needs_switch = True
                        persist_detail = str(persist_error) or type(persist_error).__name__
                        detail = f"{detail}; quarantine persistence failed: {persist_detail}"
                raise RuntimeError(f"auto-switch failed: {detail}")

            switched_branch = result.get("branch") or new_branch
            try:
                await self.persist_lifecycle(
                    session,
                    branch=switched_branch,
                    base_branch=base_branch,
                    task_id="",
                    needs_switch=False,
                )
            except Exception as persist_error:
                first_detail = str(persist_error) or type(persist_error).__name__
                try:
                    await self.persist_lifecycle(
                        session,
                        branch=switched_branch,
                        base_branch=base_branch,
                        task_id="",
                        needs_switch=True,
                    )
                except Exception as quarantine_error:
                    session.branch = switched_branch
                    session.base_branch = base_branch
                    session.task_id = ""
                    session.needs_switch = True
                    quarantine_detail = (
                        str(quarantine_error) or type(quarantine_error).__name__
                    )
                    first_detail = (
                        f"{first_detail}; quarantine persistence failed: "
                        f"{quarantine_detail}"
                    )
                raise RuntimeError(
                    f"auto-switch failed: lifecycle persistence failed: {first_detail}"
                ) from persist_error

            logger.info(
                "auto-switch %s to %s before delivery", session.name, switched_branch,
            )

    async def send(self, session_id: str, message: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(f"session not found: {session_id}")

        async def deliver() -> None:
            async with self.get_session_lock(session_id):
                if self.sessions.get(session_id) is not session:
                    raise KeyError(f"session changed before delivery: {session_id}")
                await self._auto_switch_before_delivery(session)
                await session.send(message)

        delivery_task = asyncio.create_task(deliver())
        await _wait_owned_task(delivery_task)
        delivery_task.result()

    async def interrupt(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            await session.interrupt()

    async def stop_worker(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            await session.interrupt()

    async def remove(self, session_id: str) -> None:
        from app.bg_jobs import bg_manager
        await bg_manager.cancel_by_session(session_id)
        session = self.sessions.get(session_id)
        if session is None:
            row = get_session(session_id)
            if row is None:
                return
            session = self._hydrate_row(row)
        if session.loaded:
            await session._disconnect_backend()
        if session.worktree_path:
            await asyncio.to_thread(
                remove_worktree,
                session.scope,
                session.worktree_path,
            )
        archive_session(session_id)
        self.sessions.pop(session_id, None)

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
            await self.remove(row["id"])

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
            base_branch=row.get("base_branch") or "",
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else datetime.now(timezone.utc),
            role=row.get("role") or "worker",
            parent_id=row.get("parent_id") or "",
            parent_name=row.get("parent_name") or "",
            pipeline=row.get("pipeline") or "",
            profile=row.get("profile") or "",
            backend_type=runtime_for_record(row),
            runtime_handoff=row.get("runtime_handoff") or "",
            last_summary=row.get("last_summary") or "",
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

    async def persist_lifecycle(
        self,
        session: AgentSession,
        *,
        branch: str,
        base_branch: str,
        task_id: str,
        needs_switch: bool,
    ) -> None:
        """Persist one Git lifecycle snapshot for loaded or detached sessions."""
        if session.loaded:
            await session._drain_persist()
        session.branch = branch
        session.base_branch = base_branch
        session.task_id = task_id
        session.needs_switch = needs_switch
        updated = await asyncio.to_thread(
            update_session_lifecycle,
            session.id,
            branch=branch,
            base_branch=base_branch,
            task_id=task_id,
            needs_switch=needs_switch,
        )
        if not updated:
            raise RuntimeError(f"cannot persist lifecycle for session {session.id}")
        if session.db_row is not None:
            session.db_row.update(
                branch=branch,
                base_branch=base_branch,
                task_id=task_id,
                needs_switch=int(needs_switch),
            )

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
                             parent_name: str, scope: str, repo_path: str) -> str:
        """Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).

        Explicit base wins. ``strategy=parent`` uses the parent's actual branch;
        ``strategy=main`` and missing parents use the repository's verifiable mainline.
        """
        if base_branch:
            return resolve_git_base_branch(repo_path, base_branch)
        try:
            rr = get_role(pipeline, role)
        except FileNotFoundError:
            rr = None
        if rr is None or rr.base_branch_strategy == "main":
            return resolve_git_base_branch(repo_path)
        parent_branch = ""
        if parent_name:
            ps = self.get_by_name(parent_name, scope)
            if ps is not None:
                parent_branch = ps.branch or ""
        if not parent_branch:
            logger.warning(
                "base_branch_strategy=parent, но у родителя '%s' нет ветки — "
                "resolving repository mainline",
                parent_name)
            return resolve_git_base_branch(repo_path)
        return resolve_git_base_branch(repo_path, parent_branch)

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
        stored_bt = db_row.get("backend_type") or expected_bt
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
            base_branch=db_row.get("base_branch") or "",
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
            last_summary=db_row.get("last_summary") or "",
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
        session.needs_switch = bool(db_row.get("needs_switch") or 0)
        raw_hist = db_row.get("session_id_history") or "[]"
        try:
            session.session_id_history = json.loads(raw_hist) if isinstance(raw_hist, str) else raw_hist
        except (json.JSONDecodeError, TypeError):
            session.session_id_history = []
        pct = db_row.get("context_pct", 0) or 0
        tokens = db_row.get("context_tokens", 0) or 0
        if pct or tokens:
            max_t = get_model_spec(db_row["model"]).context_length
            session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": max_t}
        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
        if not is_orch:
            current_prompt = safe_format_prompt(
                current_prompt,
                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                scope=db_row["scope"],
                branch=db_row.get("branch") or db_row.get("base_branch") or "",
            )
        if old_prompt and old_prompt != current_prompt:
            formatted_base = safe_format_prompt(
                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                scope=db_row["scope"],
                branch=db_row.get("branch") or db_row.get("base_branch") or "",
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
            await self.send(orch_session.id, msg)
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
            r.update(cache_policy_for_runtime(runtime_for_record(r)))
        return result

    def get_session_id(self, name: str, scope: str) -> str | None:
        for s in self.sessions.values():
            if s.name == name and s.scope == scope:
                return s.id
        db_row = get_session_by_name(name, scope)
        return db_row["id"] if db_row else None

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
            await self.send(
                session.id,
                "[system] Orchestra server restarted. "
                "Your session was restored — continue where you left off."
            )
            logger.info(f"Restart notice injected: {session.name}")
        except Exception as e:
            logger.warning(f"Failed to inject restart notice to {session.name}: {e}")

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
        self._session_locks.clear()
