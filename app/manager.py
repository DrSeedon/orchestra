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
from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
from app.models import resolve_model, backend_for_model
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


def get_active_profile(scope: str = "", parent_profile: str = "") -> str:
    """Определить активный профиль Claude для НОВОЙ сессии.

    Дети наследуют профиль родителя; корень / пусто → "" (профиль из env
    процесса). В отличие от пайплайна, дефолт — НЕ константа, а пустая строка.

    Профиль — DB/manager-концерн (не config), поэтому функция живёт здесь, а не
    в ``pipeline.py``. Сигнатура с ``scope`` зеркалит ``get_active_pipeline`` и
    оставлена под будущее чтение колонки ``sessions.profile`` по scope.
    """
    return parent_profile or ""


def _read_prompt(name: str) -> str:
    p = _PROMPTS_DIR / name
    return p.read_text() if p.exists() else ""


def _other_orchestrators_block(exclude_scope: str = "") -> str:
    try:
        orchs = [s for s in get_all_sessions()
                 if bool(s.get("is_orchestrator")) and s.get("scope") != exclude_scope]
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


def _workers_block(scope: str) -> str:
    try:
        workers = [s for s in get_all_sessions()
                   if not bool(s.get("is_orchestrator")) and s.get("scope") == scope]
        if not workers:
            return ""
        lines = ["## Your current workers",
                 "These workers exist in your project. Reuse idle ones instead of spawning new. Kill workers you no longer need (one-shot tasks done, wrong role, duplicate)."]
        for w in workers:
            name = w["name"]
            model = w.get("model", "?")
            status = w.get("status", "?")
            ctx = w.get("context_pct", 0) or 0
            desc = w.get("description", "")
            desc_part = f" | \"{desc}\"" if desc else ""
            lines.append(f"- **{name}** — {model} | {status} | ctx:{ctx}%{desc_part}")
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


_MODULES_DIR = _PROMPTS_DIR / "modules"


def _load_modules(module_names: list[str]) -> str:
    parts = []
    for name in module_names:
        p = _MODULES_DIR / f"{name}.md"
        if p.exists():
            parts.append(p.read_text().strip())
        else:
            logger.warning(f"Module '{name}' not found at {p}")
    return "\n\n".join(parts)


def _role_prompt_file(role: str) -> str:
    """Find the best prompt for a role. Parses frontmatter, returns body + modules.
    Falls back to 'worker' role if role file not found."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if role_path.exists():
        meta, body = _parse_role_frontmatter(role_path.read_text())
        if body:
            modules = meta.get("modules", [])
            if modules:
                body = body + "\n\n" + _load_modules(modules)
            return body
    if role != "worker":
        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
        if fallback.exists():
            meta, body = _parse_role_frontmatter(fallback.read_text())
            if body:
                modules = meta.get("modules", [])
                if modules:
                    body = body + "\n\n" + _load_modules(modules)
                return body
    return ""


_SKILLS_DIR = _PROMPTS_DIR / "skills"



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


def get_role_icons() -> dict[str, str]:
    roles_dir = _PROMPTS_DIR / "roles"
    icons = {}
    if roles_dir.is_dir():
        for f in sorted(roles_dir.glob("*.md")):
            meta, _ = _parse_role_frontmatter(f.read_text())
            if meta:
                name = meta.get("name", f.stem)
                icon = meta.get("icon", "")
                if icon:
                    icons[name] = icon
    return icons


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


def _UPSTREAM_ROLE_SYSTEM_PROMPT(role: str, scope: str = "") -> str:
    """Поведение апстрима 1:1 (frontmatter+glob из ``app/prompts/``).

    Fallback-ветка: вызывается из :func:`ROLE_SYSTEM_PROMPT`, когда манифест
    пайплайна отсутствует (``FileNotFoundError``). Сохранена дословно — гарантия,
    что при отсутствии ``pipelines/`` поведение идентично upstream (DECISIONS B4).
    """
    base = f"{_read_prompt('base.md')}\n\n{_role_prompt_file(role)}"
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

    Манифест-путь (есть ``pipelines/<pipeline>/``): статика через
    :func:`build_system_prompt` (ТОЛЬКО ``pipelines/<name>/prompts/`` — изоляция),
    затем для оркестратора — каталог ролей (фильтр ``can_spawn``) + блоки других
    оркестраторов/воркеров из БД.

    Fallback (``FileNotFoundError`` — манифеста нет, ИЛИ ``KeyError`` — роли нет
    в манифесте): делегируем в :func:`_UPSTREAM_ROLE_SYSTEM_PROMPT` (поведение
    апстрима 1:1, B4 — default/fail-open на worker/orchestrator).
    """
    try:
        base = build_system_prompt(pipeline, role, scope)
    except (FileNotFoundError, KeyError):
        # Нет манифеста (FileNotFoundError) ИЛИ роли нет в манифесте (KeyError):
        # делегируем в upstream-fallback (B4: default/fail-open 1:1 — upstream
        # допускал произвольную роль воркера с fallback на worker/orchestrator).
        return _UPSTREAM_ROLE_SYSTEM_PROMPT(role, scope)
    rr = get_role(pipeline, role)
    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
    if is_orch:
        catalog = _roles_catalog_from_manifest(pipeline, role)
        if catalog:
            base += f"\n\n{catalog}"
        others = _other_orchestrators_block(scope)
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


def _prompt_template_hash(role_or_orch) -> str:
    """Hash only the static template files (base.md + role.md + skills).
    Accepts role string or legacy bool (is_orchestrator)."""
    import hashlib
    if isinstance(role_or_orch, bool):
        role = "orchestrator" if role_or_orch else "worker"
    else:
        role = role_or_orch
    content = _read_prompt("base.md") + _role_prompt_file(role)
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -> None:
    """Идемпотентно скаффолдит doc-папку роли в docs_work/ по манифесту.

    Источник пути/шаблона — resolve_role(...).docs_dir (не хардкод). Если у роли
    нет docs_dir, docs_scaffold выключен, или requires=='feature' без feature —
    скаффолд пропускается. Манифеста нет (FileNotFoundError) → пропуск.
    """
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
    # B3: feature приходит из рантайм-ввода (API/MCP docs_feature) — может
    # содержать '../'. Проверяем containment в docs_work ПЕРЕД mkdir/write.
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


def _inject_skills_to_worktree(role: str, worktree_path: str) -> None:
    """Copy role skills into worktree/.claude/skills/ as native Claude CLI skills."""
    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
    if not role_path.exists():
        return
    meta, _ = _parse_role_frontmatter(role_path.read_text())
    skill_names = meta.get("skills", [])
    if not skill_names or not _SKILLS_DIR.is_dir():
        return
    wt = Path(worktree_path)
    for sname in skill_names:
        skill_src = _SKILLS_DIR / f"{sname}.md"
        if not skill_src.exists():
            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
            continue
        skill_dir = wt / ".claude" / "skills" / sname
        skill_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(skill_src, skill_dir / "SKILL.md")
    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")


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
        if not getattr(self, '_cleanup_task', None) or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_db_cleanup())

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
    def _auto_commit_if_dirty(repo_path: str) -> str:
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
        if get_session_by_name(name, scope):
            raise ValueError(f"session '{name}' already exists in scope '{scope}'")

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
        ownership_warning = ""
        if owned_dirs:
            conflicts = []
            for s in self.sessions.values():
                if s.scope == scope and s.status.value in ("idle", "running") and s.owned_dirs:
                    ov = dirs_overlap(owned_dirs, s.owned_dirs)
                    if ov:
                        conflicts.append((s.name, ov))
            if conflicts:
                ownership_warning = "; ".join(f"{n} owns {ov}" for n, ov in conflicts)
                logger.warning(f"owned_dirs overlap for new worker '{name}': {ownership_warning}")

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
            # v2.16: кастомный system_prompt ДОПИСЫВАЕТСЯ к базе роли, а не заменяет
            # её (раньше было `system_prompt or ROLE_SYSTEM_PROMPT(...)`).
            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
        else:
            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
            # Ownership (upstream): для воркера дописываем блок "трогай только это".
            prompt += self._ownership_prompt(owned_dirs)

        if not parent_id and parent_name:
            p_session = self.get_by_name(parent_name, scope)
            if p_session:
                parent_id = p_session.id if isinstance(p_session, AgentSession) else p_session.get("id", "")

        # R2: валидация спавна ДО любых side-effects (worktree/start).
        # Манифест-путь — validate_spawn (fail-closed/fail-open). Нет манифеста
        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
        parent_role = self._resolve_role(parent_name, scope) if parent_name else ""
        try:
            validate_spawn(pipeline, parent_role, role if explicit_role else "")
        except FileNotFoundError:
            if parent_role:
                whitelist = _role_can_spawn(parent_role)
                if whitelist is not None and role not in whitelist:
                    allowed = ", ".join(whitelist) if whitelist else "(none — terminal role)"
                    raise ValueError(
                        f"role '{parent_role}' is not allowed to spawn role '{role}'. "
                        f"Allowed: {allowed}"
                    )

        # Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).
        # Делаем ДО create_worktree, когда pipeline/role/parent_name уже определены.
        base_branch = self._resolve_base_branch(base_branch, pipeline, role, parent_name, scope)

        # Root orchestrators (no parent) always get a TG topic
        if is_orch and not parent_name:
            tg_topic = True

        custom_mcp = _parse_custom_mcp(mcp_servers)
        bt = backend_for_model(model)
        session = AgentSession(
            id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
            system_prompt=prompt, role=role,
            parent_id=parent_id, parent_name=parent_name,
            pipeline=pipeline, profile=profile,
            color="" if is_orch else self._pick_color(),
            mcp_servers=_make_mcp_config(name, scope, role, extra=custom_mcp),
            mcp_servers_custom=custom_mcp,
            backend_type=bt, task_id=task_id, description=description,
            owned_dirs=owned_dirs,
            tg_topic=tg_topic,
        )
        # R1: денормализуем is_orchestrator (kind манифеста / fallback) в хранимое поле.
        session.is_orchestrator = is_orch
        session._template_hash = _prompt_template_hash(role)
        session._spawn_warning = ownership_warning
        save_session(session._to_db_dict())

        if task_id and not is_orch:
            try:
                from app.tm import api_update_task
                api_update_task(task_id, status="in_progress")
            except Exception:
                pass

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
                # F1: при skills=="all" (sapto-pm) скиллы приходят через профиль
                # (CLAUDE_CONFIG_DIR + setting_sources), native-инъекция не нужна.
                # default/список/нет манифеста → инъекция как в upstream.
                try:
                    _rr = get_role(pipeline, role)
                    _skills = _rr.skills if _rr else None
                except FileNotFoundError:
                    _skills = None
                if _skills != "all":
                    await asyncio.to_thread(_inject_skills_to_worktree, role, wt.path)

            # Best-effort скаффолд doc-папки роли по манифесту (фильтрация внутри
            # функции: docs_scaffold/docs_dir/requires). cwd = итоговый (worktree
            # если создан, иначе исходный). Не должен валить create_session.
            try:
                await asyncio.to_thread(
                    _scaffold_role_docs, pipeline, session.cwd, role, docs_feature)
            except Exception as e:  # noqa: BLE001 — best-effort, как другие шаги
                logger.warning("docs scaffold failed for role '%s': %s", role, e)

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
        except BaseException:
            if session.worktree_path and repo_path:
                try:
                    await asyncio.to_thread(remove_worktree, repo_path, session.worktree_path)
                except Exception:
                    pass
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
        if not isinstance(session, AgentSession):
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
            session.mcp_servers = _make_mcp_config(name, new_scope, session.role,
                                                   extra=session.mcp_servers_custom)
            # No session._persist() here: change_scope() already wrote scope+cwd
            # synchronously in its transaction (the last writer after the drain).
        logger.info(f"Orchestrator '{name}' scope changed: {old_scope} → {new_scope}")
        return result

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
                parent_branch = getattr(ps, "branch", "") or (
                    ps.get("branch", "") if isinstance(ps, dict) else "")
            if not parent_branch:
                row = get_session_by_name(parent_name, scope)
                parent_branch = (row.get("branch") or "") if row else ""
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
        pipeline = db_row.get("pipeline", "") or ""
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
            worktree_path=wt_path, branch=db_branch,
            created_at=datetime.fromisoformat(db_row["created_at"]) if db_row.get("created_at") else datetime.now(timezone.utc),
            role=role,
            parent_id=db_row.get("parent_id", ""),
            parent_name=db_row.get("parent_name", ""),
            pipeline=db_row.get("pipeline", ""),
            profile=db_row.get("profile", ""),
            color="" if is_orch else (db_row.get("color") or self._pick_color()),
            mcp_servers=_make_mcp_config(db_row["name"], db_row["scope"], role, extra=custom_mcp),
            mcp_servers_custom=custom_mcp,
            backend_type=stored_bt, task_id=db_task_id,
            description=db_row.get("description", ""),
            owned_dirs=parse_owned_dirs(db_row.get("owned_dirs")),
            tg_topic=bool(db_row.get("tg_topic", 0)),
        )
        session.is_orchestrator = is_orch  # R1: восстановить денормализованное поле
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
                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
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
        async def _on_worker_idle(worker_name: str, worker_scope: str, last_texts: list[str], stop_reason: str = ""):
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
            was_waiting = {r["id"] for r in c.execute(
                "SELECT id FROM sessions WHERE status = 'waiting'"
            ).fetchall()}
            resumable = [dict(r) for r in c.execute(
                "SELECT * FROM sessions WHERE session_id IS NOT NULL "
                "AND status IN ('running', 'idle', 'waiting')"
            ).fetchall()]
            c.execute("UPDATE sessions SET status='idle' WHERE status IN ('running', 'waiting')")

        # R1: используем денормализованную колонку is_orchestrator (наши PM-роли
        # не входят в frozenset апстрима; колонка проставлена при спавне/миграции).
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

    async def shutdown_all(self) -> None:
        if getattr(self, '_cleanup_task', None) and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        for session in list(self.sessions.values()):
            try:
                await session.stop()
            except Exception:
                pass
        self.sessions.clear()
