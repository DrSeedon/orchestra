Reading additional input from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /home/maxim/.codex/memories]
reasoning effort: high
reasoning summaries: none
session id: 019e90ee-e6f5-7cc2-a913-3d1b9eacdc86
--------
user
Review this git diff for a merge of Vadim's pipeline-as-config PR onto main. Focus on:
1. Lost functionality from either side (main's guards, PR's pipeline features)
2. Import errors or circular dependencies
3. Broken tests or test expectations
4. Security issues (path traversal in pipeline/worktree)
5. Race conditions or state issues

This is a MERGE commit — both sides should be preserved.

 app/backend_claude.py                              |   37 +-
 app/db.py                                          |   64 +-
 app/main.py                                        |   70 +-
 app/manager.py                                     |  317 +-
 app/mcp_stdio.py                                   |    4 +-
 app/pipeline.py                                    |  487 ++
 app/session.py                                     |   62 +
 app/static/js/app.js                               |  145 +-
 app/templates/dashboard.html                       |   30 +
 app/workspace.py                                   |   83 +-
 docs/tasks/pipeline-rebase/codex-review-plan.md    | 7528 ++++++++++++++++++++
 docs/tasks/pipeline-rebase/plan.md                 |  148 +
 docs/tasks/pipeline-rebase/research.md             |  104 +
 pipelines/default/pipeline.yaml                    |   73 +
 pipelines/default/prompts/base.md                  |   56 +
 pipelines/default/prompts/modules/git-workflow.md  |   30 +
 pipelines/default/prompts/modules/orchestration.md |  192 +
 pipelines/default/prompts/modules/report-format.md |   26 +
 pipelines/default/prompts/roles/full-cycle.md      |   79 +
 pipelines/default/prompts/roles/orchestrator.md    |    8 +
 .../default/prompts/roles/sub-orchestrator.md      |   11 +
 pipelines/default/prompts/roles/worker.md          |   48 +
 pipelines/default/prompts/skills/codex-debate.md   |  376 +
 pipelines/default/prompts/skills/html-artifacts.md |   64 +
 pipelines/default/prompts/skills/vps-deploy.md     |   58 +
 pipelines/tasks-pm/pipeline.yaml                   |   25 +
 pipelines/tasks-pm/prompts/_pipeline.md            |   65 +
 pipelines/tasks-pm/prompts/base.md                 |   46 +
 pipelines/tasks-pm/prompts/roles/analyst.md        |   28 +
 .../tasks-pm/prompts/roles/base-orchestrator.md    |   51 +
 pipelines/tasks-pm/prompts/roles/coder.md          |   17 +
 pipelines/tasks-pm/prompts/roles/pm-fichi.md       |   53 +
 pipelines/tasks-pm/prompts/roles/pm-glava.md       |   47 +
 pipelines/tasks-pm/prompts/roles/secretary.md      |  115 +
 pipelines/tasks-pm/prompts/roles/tester.md         |   40 +
 pipelines/tasks-pm/prompts/roles/worker.md         |    6 +
 pipelines/tasks-pm/templates/analysis.md           |   30 +
 pipelines/tasks-pm/templates/impl.md               |   37 +
 pipelines/tasks-pm/templates/pm.md                 |   51 +
 pipelines/tasks-pm/templates/sprint.md             |   31 +
 pipelines/tasks-pm/templates/testing.md            |   35 +
 pyproject.toml                                     |    1 +
 scripts/extract-manifest.py                        |  200 +
 tests/test_api.py                                  |  151 +-
 tests/test_db.py                                   |  123 +
 tests/test_default_equals_upstream.py              |  238 +
 tests/test_default_pipeline.py                     |  335 +
 tests/test_manager.py                              |  638 +-
 tests/test_mcp_stdio.py                            |    6 +-
 tests/test_pipeline.py                             |  786 ++
 tests/test_scaffold.py                             |  131 +
 tests/test_session.py                              |  283 +-
 tests/test_tasks_pm_pipeline.py                    |   94 +
 tests/test_workspace.py                            |   99 +
 uv.lock                                            |  785 +-
 55 files changed, 14195 insertions(+), 452 deletions(-)

Key files changed:
- app/manager.py: prompt functions deduplicated, pipeline params added
- app/main.py: imports fixed, PR's new endpoints preserved
- app/backend_claude.py: inherit_claude_md + user_mcp merged
- tests/*: reviewer/watcher removed, module refs updated to prompting.py

diff --git a/app/backend_claude.py b/app/backend_claude.py
index 90af6d4..d3d6132 100644
--- a/app/backend_claude.py
+++ b/app/backend_claude.py
@@ -85,7 +85,10 @@ class ClaudeBackend:
                  resume_session_id: str | None = None,
                  mcp_servers: dict | None = None,
                  is_orchestrator: bool = False,
-                 scope_mcp_servers: dict | None = None):
+                 scope_mcp_servers: dict | None = None,
+                 config_dir: str = "",
+                 inherit_claude_md: bool = True,
+                 user_mcp_servers: dict | None = None):
         self.model = model
         self.cwd = cwd
         self.system_prompt = system_prompt
@@ -93,6 +96,13 @@ class ClaudeBackend:
         self._mcp_servers = mcp_servers or {}
         self._scope_mcp_servers = scope_mcp_servers or {}
         self._is_orchestrator = is_orchestrator
+        # Профиль Claude (F1/F4 резолвятся против него): пустой → env процесса
+        # orchestra (back-compat, 1:1 upstream).
+        self._config_dir = config_dir
+        # F4: наследовать ли user/project CLAUDE.md + настройки профиля.
+        self._inherit_claude_md = inherit_claude_md
+        # F2: user-MCP из профильного .claude.json (базовый слой merge).
+        self._user_mcp_servers = user_mcp_servers or {}
         self._client: Optional[ClaudeSDKClient] = None
         self._session_id: str | None = resume_session_id
 
@@ -108,6 +118,11 @@ class ClaudeBackend:
         for _k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
             if os.environ.get(_k):
                 env[_k] = os.environ[_k]
+        # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
+        # env как {**os.environ, **options.env}). Пусто → наследуем env процесса
+        # orchestra (back-compat). expanduser — на случай "~" в config_dir.
+        if self._config_dir:
+            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
         options = ClaudeAgentOptions(
             model=self.model, cwd=self.cwd, cli_path=cli,
             permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
@@ -116,13 +131,27 @@ class ClaudeBackend:
             max_buffer_size=50 * 1024 * 1024,
             env=env,
         )
-        options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
         if resume_id:
             options.resume = resume_id
-        merged_mcp = {**self._scope_mcp_servers, **self._mcp_servers}
+        else:
+            options.system_prompt = {"type": "preset", "preset": "claude_code", "append": self.system_prompt}
+        merged_mcp = {
+            **self._user_mcp_servers,
+            **self._scope_mcp_servers,
+            **self._mcp_servers,
+        }
         if merged_mcp:
             options.mcp_servers = merged_mcp
-        options.setting_sources = ["user", "project", "local"]
+        # F4: inherit_claude_md=False → только local-слой (нет user/project
+        # CLAUDE.md и настроек); иначе — полный набор, как в upstream.
+        options.setting_sources = (
+            ["user", "project", "local"] if self._inherit_claude_md else ["local"]
+        )
+        # F1: options.skills НЕ задаём НИКОГДА. Ветка "skills-список → options.skills"
+        # сознательно НЕ реализована (B4: default 1:1 upstream — его роли имеют
+        # skills-списки, но скиллы инъектятся через _inject_skills_to_worktree,
+        # не через options.skills). Единственное действие F1 — gating инъекции
+        # в manager.create_session при skills=="all".
         return ClaudeSDKClient(options=options)
 
     async def _cleanup_failed_client(self) -> None:
diff --git a/app/main.py b/app/main.py
index d4e3609..02e1d11 100644
--- a/app/main.py
+++ b/app/main.py
@@ -21,7 +21,11 @@ from fastapi.staticfiles import StaticFiles
 from fastapi.templating import Jinja2Templates
 from pydantic import BaseModel, field_validator, model_validator
 
-from app.db import init_db, get_logs, get_logs_before, get_all_sessions
+from app.db import (
+    init_db, get_logs, get_logs_before, get_all_sessions,
+    list_profiles, upsert_profile, delete_profile,
+)
+from app.pipeline import list_pipelines
 from app.deps import manager
 from app.models import resolve_model, MODELS
 from app.session import AgentStatus
@@ -106,9 +110,11 @@ class CreateSessionRequest(BaseModel):
     role: str = ""
     task_id: str = ""
     description: str = ""
-    base_branch: str = "main"
+    base_branch: str = ""
     parent_name: str = ""
     mcp_servers: dict = {}
+    pipeline: str = ""
+    profile: str = ""
     owned_dirs: list[str] = []
     tg_topic: bool = False
 
@@ -141,6 +147,12 @@ class CreateSessionRequest(BaseModel):
         return self
 
 
+class ProfileRequest(BaseModel):
+    """Тело запроса для создания/обновления профиля Claude."""
+    name: str
+    config_dir: str = ""
+
+
 class SendRequest(BaseModel):
     message: str
     scope: str
@@ -410,6 +422,8 @@ async def create_session(req: CreateSessionRequest):
             base_branch=req.base_branch,
             parent_name=req.parent_name,
             mcp_servers=req.mcp_servers,
+            pipeline=req.pipeline,
+            profile=req.profile,
             owned_dirs=req.owned_dirs,
             tg_topic=req.tg_topic,
         )
@@ -427,6 +441,58 @@ async def create_session(req: CreateSessionRequest):
         return JSONResponse({"error": str(e)}, status_code=500)
 
 
+@app.get("/api/pipelines")
+async def get_pipelines():
+    """Только валидные пайплайны для UI-дропдаунa: ``[{name, description, roles}]``."""
+    return [
+        {"name": p["name"], "description": p["description"], "roles": p["roles"]}
+        for p in list_pipelines()
+        if p["valid"]
+    ]
+
+
+@app.get("/api/profiles")
+async def get_profiles():
+    """Все профили Claude: ``[{name, config_dir}]``."""
+    return list_profiles()
+
+
+@app.post("/api/profiles")
+async def create_profile(req: ProfileRequest):
+    """Создать или обновить профиль. Имя валидируется тем же regex, что у сессий.
+
+    Валидация ``config_dir`` — **мягкая**: если путь непустой и не указывает на
+    существующую директорию, профиль всё равно сохраняется, но в ответ
+    добавляется ``warning``. Это не блокирует пользователя (папку может создать
+    CLI или она появится позже), но предупреждает об опечатке заранее, а не
+    при первом запуске агента. Формат ответа: ``{profiles, warning}``.
+    """
+    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", req.name):
+        return JSONResponse(
+            {"error": "name must be alphanumeric with ._- allowed, 1-50 chars"},
+            status_code=400,
+        )
+    warning = None
+    config_dir = req.config_dir
+    if config_dir and not Path(os.path.expanduser(config_dir)).is_dir():
+        warning = (
+            f"config_dir '{config_dir}' не существует — будет создан CLI "
+            "или приведёт к ошибке при запуске"
+        )
+    upsert_profile(req.name, config_dir)
+    return {"profiles": list_profiles(), "warning": warning}
+
+
+@app.delete("/api/profiles/{name}")
+async def remove_profile(name: str):
+    """Удалить профиль. Сид-профиль ``personal`` защищён → 409."""
+    try:
+        delete_profile(name)
+    except ValueError as e:
+        return JSONResponse({"error": str(e)}, status_code=409)
+    return list_profiles()
+
+
 @app.get("/api/sessions/{name}")
 async def get_session(name: str, scope: str):
     found = manager.get_by_name(name, scope)
diff --git a/app/manager.py b/app/manager.py
index cbb4e32..1d7a9da 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -21,6 +21,17 @@ from app.prompting import (
 _TASK_BRANCH_RE = re.compile(r"^(?:task-|[A-Z]{2,5}-)(\d+)/")
 from app.workspace import create_worktree, remove_worktree, parse_owned_dirs, dirs_overlap
 from app.models import resolve_model, backend_for_model
+from app.pipeline import (
+    DEFAULT_PIPELINE,
+    build_system_prompt,
+    get_active_pipeline,
+    get_role,
+    get_worktree_config,
+    load_pipeline,
+    resolve_role,
+    template_path,
+    validate_spawn,
+)
 from app.db import (
     save_session, get_session_by_name, get_all_sessions,
     delete_session, archive_session, get_stats,
@@ -42,11 +53,14 @@ COLOR_PALETTE = [
 ]
 
 
+def get_active_profile(scope: str = "", parent_profile: str = "") -> str:
+    return parent_profile or ""
+
 
 def _other_orchestrators_block(exclude_scope: str = "") -> str:
     try:
         orchs = [s for s in get_all_sessions()
-                 if is_orchestrator_role(s.get("role", "worker")) and s.get("scope") != exclude_scope]
+                 if bool(s.get("is_orchestrator")) and s.get("scope") != exclude_scope]
         if not orchs:
             return ""
         lines = ["## Other orchestrators", "You can message other orchestrators via `send_message(to=\"Name\", message=\"...\")`:"]
@@ -67,7 +81,7 @@ def _other_orchestrators_block(exclude_scope: str = "") -> str:
 def _workers_block(scope: str, orchestrator_name: str = "") -> str:
     try:
         workers = [s for s in get_all_sessions()
-                   if not is_orchestrator_role(s.get("role", "worker")) and s.get("scope") == scope]
+                   if not bool(s.get("is_orchestrator")) and s.get("scope") == scope]
         if not workers:
             return ""
 
@@ -106,7 +120,7 @@ def _workers_block(scope: str, orchestrator_name: str = "") -> str:
         return ""
 
 
-def ROLE_SYSTEM_PROMPT(role: str, scope: str = "", name: str = "") -> str:
+def _UPSTREAM_ROLE_SYSTEM_PROMPT(role: str, scope: str = "", name: str = "") -> str:
     base = f"{read_prompt('base.md')}\n\n{role_prompt_file(role)}"
     if is_orchestrator_role(role):
         catalog = roles_catalog()
@@ -124,16 +138,128 @@ def ROLE_SYSTEM_PROMPT(role: str, scope: str = "", name: str = "") -> str:
     return base
 
 
-def ORCHESTRATOR_SYSTEM_PROMPT(scope: str = "") -> str:
-    return ROLE_SYSTEM_PROMPT("orchestrator", scope)
+def _fmt_role_catalog_entry(rr) -> str:
+    """Форматировать одну запись каталога ролей из :class:`ResolvedRole`.
+
+    Совпадает по форме с ``_roles_catalog`` (заголовок ### `name` (label) — model,
+    описание, when/not_for). Источник полей — манифест (ResolvedRole), не frontmatter.
+    """
+    desc = (rr.description or "").strip().replace("\n", " ")
+    entry = f"### `{rr.name}` ({rr.label}) — model: {rr.model}"
+    if desc:
+        entry += f"\n{desc}"
+    if rr.when:
+        entry += f"\n- ✅ **When**: {rr.when.strip()}"
+    if rr.not_for:
+        entry += f"\n- ❌ **Not for**: {rr.not_for.strip()}"
+    skills = rr.skills
+    if isinstance(skills, list) and skills:
+        entry += f"\n- 🔧 **Skills**: {', '.join(skills)}"
+    return entry
+
+
+def _roles_catalog_from_manifest(pipeline: str, parent_role: str) -> str:
+    """Каталог ролей оркестратору из манифеста, отфильтрованный по ``can_spawn``.
+
+    B2: показываем ВСЕ роли из ``can_spawn`` родителя (включая под-оркестраторов).
+    ``can_spawn=['*']`` → все роли пайплайна. Сортировка по ``order``. Закрывает
+    дефект плоского ``_roles_catalog`` (показывал бы запретные роли).
+    """
+    cfg = load_pipeline(pipeline)
+    parent = cfg.roles.get(parent_role)
+    if parent is None:
+        return ""
+    if "*" in parent.can_spawn:
+        # S1: wildcard НЕ включает саму роль-родителя (upstream _roles_catalog
+        # пропускал orchestrator из своего же каталога воркеров).
+        visible = [r for r in cfg.roles if r != parent_role]
+    else:
+        visible = list(parent.can_spawn)
+    visible = [r for r in visible if r in cfg.roles]
+    if not visible:
+        return ""
+    entries = [
+        _fmt_role_catalog_entry(resolve_role(cfg, r))
+        for r in sorted(visible, key=lambda r: cfg.roles[r].order)
+    ]
+    return ('## Available worker roles\nSpawn with `role="<name>"`. '
+            'If no role specified, defaults to `worker`.\n\n' + "\n\n".join(entries))
+
+
+def ROLE_SYSTEM_PROMPT(pipeline: str, role: str, scope: str = "") -> str:
+    """Системный промпт роли: статика слоёв пайплайна + динамика (каталог/блоки).
+
+    Манифест-путь (есть ``pipelines/<pipeline>/``): статика через
+    :func:`build_system_prompt` (ТОЛЬКО ``pipelines/<name>/prompts/`` — изоляция),
+    затем для оркестратора — каталог ролей (фильтр ``can_spawn``) + блоки других
+    оркестраторов/воркеров из БД.
+
+    Fallback (``FileNotFoundError`` — манифеста нет, ИЛИ ``KeyError`` — роли нет
+    в манифесте): делегируем в :func:`_UPSTREAM_ROLE_SYSTEM_PROMPT` (поведение
+    апстрима 1:1, B4 — default/fail-open на worker/orchestrator).
+    """
+    try:
+        base = build_system_prompt(pipeline, role, scope)
+    except (FileNotFoundError, KeyError):
+        # Нет манифеста (FileNotFoundError) ИЛИ роли нет в манифесте (KeyError):
+        # делегируем в upstream-fallback (B4: default/fail-open 1:1 — upstream
+        # допускал произвольную роль воркера с fallback на worker/orchestrator).
+        return _UPSTREAM_ROLE_SYSTEM_PROMPT(role, scope)
+    rr = get_role(pipeline, role)
+    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
+    if is_orch:
+        catalog = _roles_catalog_from_manifest(pipeline, role)
+        if catalog:
+            base += f"\n\n{catalog}"
+        others = _other_orchestrators_block(scope)
+        if others:
+            base += f"\n\n{others}"
+        workers = _workers_block(scope)
+        if workers:
+            base += f"\n\n{workers}"
+    return base
+
 
+def ORCHESTRATOR_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE, scope: str = "") -> str:
+    return ROLE_SYSTEM_PROMPT(pipeline, "orchestrator", scope)
 
-def WORKER_SYSTEM_PROMPT() -> str:
-    return ROLE_SYSTEM_PROMPT("worker")
 
+def WORKER_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE) -> str:
+    return ROLE_SYSTEM_PROMPT(pipeline, "worker")
 
 
 
+def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -> None:
+    try:
+        rr = get_role(pipeline, role)
+    except FileNotFoundError:
+        return
+    if rr is None or not rr.docs_scaffold or rr.docs_dir is None:
+        return
+    dd = rr.docs_dir
+    if dd.requires == "feature" and not feature:
+        return
+    rel = dd.path.replace("{feature}", feature) if feature else dd.path
+    base_docs = (Path(cwd) / "docs_work").resolve()
+    target = (base_docs / rel).resolve()
+    try:
+        target.relative_to(base_docs)
+    except ValueError:
+        logger.warning("scaffold: путь '%s' выходит за docs_work — пропуск", rel)
+        return
+    target.mkdir(parents=True, exist_ok=True)
+    dashboard = target / "dashboard.md"
+    if dashboard.exists() or not dd.template:
+        return
+    tpl = template_path(pipeline, dd.template)
+    if not tpl.is_file():
+        return
+    content = tpl.read_text()
+    if feature:
+        content = content.replace("{feature}", feature)
+    dashboard.write_text(content)
+
+
 def _parse_custom_mcp(raw) -> dict:
     """Sanitize custom MCP servers (from DB JSON string or a dict).
     Returns a dict with the `orchestra` key stripped. Non-dict input -> {}."""
@@ -267,9 +393,11 @@ class SessionManager:
                              system_prompt: str = "", use_worktree: bool = False,
                              repo_path: str | None = None, is_orchestrator: bool = False,
                              role: str = "", task_id: str = "", description: str = "",
-                             base_branch: str = "main",
+                             base_branch: str = "",
                              parent_id: str = "", parent_name: str = "",
                              mcp_servers: dict | None = None,
+                             pipeline: str = "", profile: str = "",
+                             docs_feature: str = "",
                              owned_dirs: list | None = None,
                              tg_topic: bool = False) -> AgentSession:
         scope = scope.rstrip("/")
@@ -283,10 +411,30 @@ class SessionManager:
             ctx = existing.get("context_pct", 0) or 0
             raise ValueError(f"worker '{name}' already exists ({st}, ctx:{ctx}%). Use send_message instead")
 
+        # Явно ли указана роль: генерик-воркер (role не задан) валидируется как
+        # unrouted (child_role="") — им управляет allow_unrouted_workers родителя.
+        explicit_role = bool(role)
         if not role:
             role = "orchestrator" if is_orchestrator else "worker"
-        is_orch = is_orchestrator_role(role)
 
+        # Активный пайплайн: явный аргумент главнее, иначе наследуем от родителя
+        # (или DEFAULT_PIPELINE для корня). parent_name тут — только явно переданный;
+        # для воркеров без parent_name он доразрешается ниже (auto-find).
+        explicit_pipeline = bool(pipeline)
+        parent_pipeline = self._resolve_pipeline(parent_name, scope) if parent_name else ""
+        pipeline = pipeline or get_active_pipeline(scope, parent_pipeline=parent_pipeline)
+
+        # Активный профиль Claude: явный аргумент главнее, иначе наследуем от
+        # родителя (пусто для корня → env процесса). Зеркало логики pipeline.
+        explicit_profile = bool(profile)
+        parent_profile = self._resolve_profile(parent_name, scope) if parent_name else ""
+        profile = profile or get_active_profile(scope, parent_profile=parent_profile)
+
+        # R1: is_orchestrator из манифеста (kind), fallback на frozenset апстрима.
+        is_orch = self._role_is_orchestrator(pipeline, role)
+
+        # Ownership (upstream): нормализуем owned_dirs и предупреждаем о пересечении
+        # с другими живыми воркерами в этом scope (warning, НЕ блок).
         owned_dirs = parse_owned_dirs(owned_dirs)
         if owned_dirs:
             seen_ids: set[str] = set()
@@ -313,21 +461,39 @@ class SessionManager:
                             f"Use different dirs or kill '{row['name']}' first"
                         )
 
+        if not parent_name and not is_orch:
+            parent_name = self._find_orchestrator_name(scope) or ""
+            if parent_name and not explicit_pipeline:
+                # Доразрешили родителя авто-поиском — воркер наследует его пайплайн.
+                parent_pipeline = self._resolve_pipeline(parent_name, scope)
+                pipeline = get_active_pipeline(scope, parent_pipeline=parent_pipeline)
+                is_orch = self._role_is_orchestrator(pipeline, role)
+            if parent_name and not explicit_profile:
+                # Тот же авто-найденный родитель — воркер наследует и его профиль.
+                parent_profile = self._resolve_profile(parent_name, scope)
+                profile = get_active_profile(scope, parent_profile=parent_profile)
+
         if is_orch:
-            prompt = ROLE_SYSTEM_PROMPT(role, scope, name) + ("\n\n" + system_prompt if system_prompt else "")
+            # v2.16: кастомный system_prompt ДОПИСЫВАЕТСЯ к базе роли, а не заменяет
+            # её (раньше было `system_prompt or ROLE_SYSTEM_PROMPT(...)`).
+            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
         else:
-            prompt = ROLE_SYSTEM_PROMPT(role) + ("\n\n" + system_prompt if system_prompt else "")
+            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
+            # Ownership (upstream): для воркера дописываем блок "трогай только это".
             prompt += self._ownership_prompt(owned_dirs)
 
-        if not parent_name and not is_orch:
-            parent_name = self._find_orchestrator_name(scope) or ""
         if not parent_id and parent_name:
             p_session = self.get_by_name(parent_name, scope)
             if p_session:
                 parent_id = p_session.id if isinstance(p_session, AgentSession) else p_session.get("id", "")
 
-        if parent_name:
-            parent_role = self._resolve_role(parent_name, scope)
+        # R2: валидация спавна ДО любых side-effects (worktree/start).
+        # Манифест-путь — validate_spawn (fail-closed/fail-open). Нет манифеста
+        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
+        parent_role = self._resolve_role(parent_name, scope) if parent_name else ""
+        try:
+            validate_spawn(pipeline, parent_role, role if explicit_role else "")
+        except FileNotFoundError:
             if parent_role:
                 whitelist = role_can_spawn(parent_role)
                 if whitelist is not None and role not in whitelist:
@@ -337,6 +503,10 @@ class SessionManager:
                         f"Allowed: {allowed}"
                     )
 
+        # Резолв базовой ветки worktree по стратегии манифеста (DESIGN §10, B3).
+        # Делаем ДО create_worktree, когда pipeline/role/parent_name уже определены.
+        base_branch = self._resolve_base_branch(base_branch, pipeline, role, parent_name, scope)
+
         # Root orchestrators (no parent) always get a TG topic
         if is_orch and not parent_name:
             tg_topic = True
@@ -347,6 +517,7 @@ class SessionManager:
             id=str(uuid.uuid4()), name=name, scope=scope, cwd=cwd, model=model,
             system_prompt=prompt, role=role,
             parent_id=parent_id, parent_name=parent_name,
+            pipeline=pipeline, profile=profile,
             color="" if is_orch else self._pick_color(),
             mcp_servers=_make_mcp_config(name, scope, role, extra=custom_mcp),
             mcp_servers_custom=custom_mcp,
@@ -354,6 +525,7 @@ class SessionManager:
             owned_dirs=owned_dirs,
             tg_topic=tg_topic,
         )
+        session.is_orchestrator = is_orch
         session._template_hash = prompt_template_hash(role)
         session._spawn_warning = ""
         save_session(session._to_db_dict())
@@ -370,11 +542,30 @@ class SessionManager:
                 wip_note = await asyncio.to_thread(self._auto_commit_if_dirty, repo_path)
                 if wip_note:
                     session._spawn_warning = (session._spawn_warning + "; " + wip_note).strip("; ")
-                wt = await asyncio.to_thread(create_worktree, repo_path, name, scope, task_id, base_branch)
+                # Worktree-конфиг из манифеста (симлинки + copies). Нет манифеста
+                # → None → create_worktree использует upstream-fallback (PROJECT_FILES).
+                try:
+                    worktree_cfg = get_worktree_config(pipeline)
codex
I’ll inspect the actual merge diff and the surrounding code paths, then check targeted tests/imports where the risks are concentrated: pipeline resolution, worktree path handling, session persistence, and API expectations.
exec
/usr/bin/zsh -lc "rg -n \"from app\\.manager import|ROLE_SYSTEM_PROMPT|ORCHESTRATOR_SYSTEM_PROMPT|WORKER_SYSTEM_PROMPT|is_orchestrator_role|role_can_spawn|reviewer|watcher|app\\.prompting\" tests app -S" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
tests/test_scaffold.py:14:from app.manager import _scaffold_role_docs
tests/test_default_equals_upstream.py:11:    can_spawn/... + тело). Функции реконструкции: ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``,
tests/test_default_equals_upstream.py:12:    ``_prompting.role_prompt_file``, ``manager._load_modules``, ``_prompting.role_can_spawn``,
tests/test_default_equals_upstream.py:20:  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
tests/test_default_equals_upstream.py:57:    Точная копия первой строки ``manager._UPSTREAM_ROLE_SYSTEM_PROMPT``:
tests/test_default_equals_upstream.py:107:    """Решение upstream по ``_role_can_spawn`` (frontmatter can_spawn).
tests/test_default_equals_upstream.py:109:    Семантика ``_role_can_spawn``:
tests/test_default_equals_upstream.py:115:    wl = _prompting.role_can_spawn(parent)
tests/test_default_equals_upstream.py:135:            assert _prompting.role_can_spawn(parent) is None  # upstream: поля нет
tests/test_default_equals_upstream.py:149:        # orchestrator/sub-orchestrator/full-cycle/reviewer — opus; worker — sonnet/opus
tests/test_default_equals_upstream.py:150:        # → sonnet; watcher — haiku. Defaults манифеста (opus) дают то же для ролей
app/static/js/app.js:1294:let _roleIcons = {'orchestrator':'👑','worker':'⚙️','full-cycle':'🔄','sub-orchestrator':'🎯','reviewer':'🔍','watcher':'👁️'};
tests/test_default_pipeline.py:6:reviewer/watcher), worker на Sonnet, watcher на Haiku, fail-open валидация, сборка
app/manager.py:15:from app.prompting import (
app/manager.py:16:    is_orchestrator_role, safe_format_prompt, read_prompt,
app/manager.py:17:    role_prompt_file, role_can_spawn,
app/manager.py:123:def _UPSTREAM_ROLE_SYSTEM_PROMPT(role: str, scope: str = "", name: str = "") -> str:
app/manager.py:125:    if is_orchestrator_role(role):
app/manager.py:189:def ROLE_SYSTEM_PROMPT(pipeline: str, role: str, scope: str = "") -> str:
app/manager.py:198:    в манифесте): делегируем в :func:`_UPSTREAM_ROLE_SYSTEM_PROMPT` (поведение
app/manager.py:207:        return _UPSTREAM_ROLE_SYSTEM_PROMPT(role, scope)
app/manager.py:209:    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
app/manager.py:223:def ORCHESTRATOR_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE, scope: str = "") -> str:
app/manager.py:224:    return ROLE_SYSTEM_PROMPT(pipeline, "orchestrator", scope)
app/manager.py:227:def WORKER_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE) -> str:
app/manager.py:228:    return ROLE_SYSTEM_PROMPT(pipeline, "worker")
app/manager.py:478:            # её (раньше было `system_prompt or ROLE_SYSTEM_PROMPT(...)`).
app/manager.py:479:            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
app/manager.py:481:            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
app/manager.py:492:        # (FileNotFoundError) → fallback на inline _role_can_spawn (поведение апстрима).
app/manager.py:498:                whitelist = role_can_spawn(parent_role)
app/manager.py:702:            if is_orchestrator_role(row.get("role", "worker")):
app/manager.py:806:        Манифеста нет (FileNotFoundError) или роли нет в нём → ``is_orchestrator_role``.
app/manager.py:814:        return is_orchestrator_role(role)
app/manager.py:843:                is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
app/manager.py:845:            is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
app/manager.py:847:        current_prompt = ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
app/manager.py:909:                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
app/manager.py:1024:        orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
app/manager.py:1025:        workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]
app/tg_bridge.py:1207:        from app.manager import SessionManager
app/deps.py:3:from app.manager import SessionManager
app/skills/codex-review/SKILL.md:159:Ты adversarial code reviewer. В cwd — <проект> (<стек>).
app/skills/codex-review/SKILL.md:191:Ты adversarial code reviewer. В cwd — <проект>.
app/prompts/skills/codex-debate.md:142:Ты adversarial code reviewer. cwd — проект Orchestra (Python, FastAPI, SQLite).
app/prompts/skills/codex-debate.md:304:Ты adversarial code reviewer. cwd — <project_root>.
app/prompts/skills/codex-debate.md:315:Ты adversarial code reviewer. cwd — <project_root>.
app/prompting.py:19:def is_orchestrator_role(role: str) -> bool:
app/prompting.py:72:        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
app/prompting.py:83:def role_can_spawn(role: str):
app/session.py:15:from app.prompting import is_orchestrator_role
app/session.py:179:        return is_orchestrator_role(self.role)
app/session.py:312:                from app.prompting import prompt_template_hash
tests/test_manager.py:25:    from app.manager import SessionManager
tests/test_manager.py:392:        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
tests/test_manager.py:393:        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
tests/test_manager.py:401:    def test_role_can_spawn_absent_is_none(self, roles_dir):
tests/test_manager.py:402:        from app.prompting import role_can_spawn as _role_can_spawn
tests/test_manager.py:404:        assert _role_can_spawn("boss") is None
tests/test_manager.py:406:    def test_role_can_spawn_yaml_null_is_none(self, roles_dir):
tests/test_manager.py:407:        from app.prompting import role_can_spawn as _role_can_spawn
tests/test_manager.py:409:        assert _role_can_spawn("boss") is None
tests/test_manager.py:411:    def test_role_can_spawn_non_list_is_none(self, roles_dir):
tests/test_manager.py:412:        from app.prompting import role_can_spawn as _role_can_spawn
tests/test_manager.py:414:        assert _role_can_spawn("boss") is None
tests/test_manager.py:416:    def test_role_can_spawn_empty_list_is_terminal(self, roles_dir):
tests/test_manager.py:417:        from app.prompting import role_can_spawn as _role_can_spawn
tests/test_manager.py:419:        assert _role_can_spawn("leaf") == []
tests/test_manager.py:421:    def test_role_can_spawn_whitelist(self, roles_dir):
tests/test_manager.py:422:        from app.prompting import role_can_spawn as _role_can_spawn
tests/test_manager.py:423:        self._write_role(roles_dir, "boss", "name: boss\ncan_spawn: [worker, reviewer]")
tests/test_manager.py:424:        assert _role_can_spawn("boss") == ["worker", "reviewer"]
tests/test_manager.py:426:    def test_role_can_spawn_missing_file_is_none(self, roles_dir):
tests/test_manager.py:427:        from app.prompting import role_can_spawn as _role_can_spawn
tests/test_manager.py:428:        assert _role_can_spawn("ghost") is None
tests/test_manager.py:507:        from app.manager import _parse_custom_mcp
tests/test_manager.py:512:        from app.manager import _parse_custom_mcp
tests/test_manager.py:517:        from app.manager import _parse_custom_mcp
tests/test_manager.py:522:        from app.manager import _parse_custom_mcp
tests/test_manager.py:526:        from app.manager import _parse_custom_mcp
tests/test_manager.py:531:        from app.manager import _parse_custom_mcp
tests/test_manager.py:536:        from app.manager import _make_mcp_config
tests/test_manager.py:542:        from app.manager import _make_mcp_config
tests/test_manager.py:657:    """Зафиксировать: при отсутствии манифеста ROLE_SYSTEM_PROMPT(pipeline, role)
tests/test_manager.py:658:    идентичен поведению апстрима (_UPSTREAM_ROLE_SYSTEM_PROMPT)."""
tests/test_manager.py:670:        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
tests/test_manager.py:671:        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
tests/test_manager.py:677:        """_UPSTREAM_ROLE_SYSTEM_PROMPT собирает base.md + тело роли (orchestrator)."""
tests/test_manager.py:678:        from app.manager import _UPSTREAM_ROLE_SYSTEM_PROMPT
tests/test_manager.py:679:        out = _UPSTREAM_ROLE_SYSTEM_PROMPT("orchestrator", "/some/scope")
tests/test_manager.py:684:        from app.manager import _UPSTREAM_ROLE_SYSTEM_PROMPT
tests/test_manager.py:685:        out = _UPSTREAM_ROLE_SYSTEM_PROMPT("worker")
tests/test_manager.py:690:        """Нет манифеста (FileNotFoundError) → ROLE_SYSTEM_PROMPT(pipeline, ...) ==
tests/test_manager.py:691:        _UPSTREAM_ROLE_SYSTEM_PROMPT (fallback идентичен апстриму)."""
tests/test_manager.py:694:        from app.manager import ROLE_SYSTEM_PROMPT, _UPSTREAM_ROLE_SYSTEM_PROMPT
tests/test_manager.py:696:        assert ROLE_SYSTEM_PROMPT("ghost-pipe", "orchestrator", "/s") == \
tests/test_manager.py:697:            _UPSTREAM_ROLE_SYSTEM_PROMPT("orchestrator", "/s")
tests/test_manager.py:698:        assert ROLE_SYSTEM_PROMPT("ghost-pipe", "worker") == \
tests/test_manager.py:699:            _UPSTREAM_ROLE_SYSTEM_PROMPT("worker")
tests/test_manager.py:704:        """ROLE_SYSTEM_PROMPT берёт статику из pipelines/<name>/prompts/ (изоляция)."""
tests/test_manager.py:705:        from app.manager import ROLE_SYSTEM_PROMPT
tests/test_manager.py:706:        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
tests/test_manager.py:713:        from app.manager import ROLE_SYSTEM_PROMPT
tests/test_manager.py:714:        out = ROLE_SYSTEM_PROMPT("testpipe", "secretary")
tests/test_manager.py:721:        from app.manager import ROLE_SYSTEM_PROMPT
tests/test_manager.py:722:        out = ROLE_SYSTEM_PROMPT("testpipe", "pm-glava", "/s")
tests/test_manager.py:736:        ROLE_SYSTEM_PROMPT делегирует в _UPSTREAM_ROLE_SYSTEM_PROMPT.
tests/test_manager.py:744:        monkeypatch.setattr("app.prompting._PROMPTS_DIR", uprompts)
tests/test_manager.py:745:        monkeypatch.setattr("app.prompting._SKILLS_DIR", uprompts / "skills")
tests/test_manager.py:746:        from app.manager import ROLE_SYSTEM_PROMPT, _UPSTREAM_ROLE_SYSTEM_PROMPT
tests/test_manager.py:747:        out = ROLE_SYSTEM_PROMPT("testpipe", "my-custom-worker")
tests/test_manager.py:749:        assert out == _UPSTREAM_ROLE_SYSTEM_PROMPT("my-custom-worker")
tests/test_manager.py:755:        from app.manager import _roles_catalog_from_manifest
tests/test_manager.py:764:        from app.manager import _roles_catalog_from_manifest
tests/test_manager.py:783:        from app.manager import _roles_catalog_from_manifest
tests/test_manager.py:796:        monkeypatch.setattr("app.prompting._PROMPTS_DIR", Path("/nonexistent/app/prompts"))
tests/test_manager.py:797:        from app.manager import ROLE_SYSTEM_PROMPT
tests/test_manager.py:798:        out = ROLE_SYSTEM_PROMPT("testpipe", "coder", "/s")
tests/test_manager.py:867:        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.
tests/test_manager.py:906:        monkeypatch.setattr("app.prompting._PROMPTS_DIR", prompts)
tests/test_manager.py:907:        monkeypatch.setattr("app.prompting._SKILLS_DIR", prompts / "skills")
tests/test_manager.py:947:        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
tests/test_manager.py:1103:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
tests/test_manager.py:1116:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
tests/test_manager.py:1129:        with patch("app.manager.ROLE_SYSTEM_PROMPT", return_value="ROLE_BASE"):
app/main.py:395:    from app.prompting import get_role_icons
app/main.py:508:    from app.prompting import read_prompt as _read_prompt
app/main.py:1238:    from app.prompting import is_orchestrator_role
app/main.py:1241:    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
app/proxy_manager.py:142:        from app.manager import MCP_BASE_ENV

exec
/usr/bin/zsh -lc 'git status --short && git rev-parse --show-toplevel && git log --oneline --decorate -5' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc 'rg -n "def create_worktree|def parse_owned_dirs|class AgentSession|pipeline|profile|is_orchestrator|validate_spawn|template_path|docs_scaffold|scaffold|base_branch|CLAUDE_CONFIG_DIR" app tests pipelines -S' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
?? docs/tasks/pipeline-rebase/codex-review-impl.md
/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
82013ed (HEAD -> feat/mnt-data-projects-python-orchestra/feat-pipeline-rebase) merge PR #2 (feat/pipeline-as-config) onto main v2.18
d8e068f fix: escape single tilde in markdown to prevent false strikethrough
2a33ef3 Revert "fix: disable strikethrough in markdown — tilde in agent text rendered as deleted"
973af6a fix: disable strikethrough in markdown — tilde in agent text rendered as deleted
473acb4 refactor: shared orchestration module for orchestrator + sub-orchestrator

 succeeded in 0ms:
pipelines/tasks-pm/pipeline.yaml:10:    orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
pipelines/tasks-pm/pipeline.yaml:15:  base_branch_strategy: parent
pipelines/tasks-pm/pipeline.yaml:16:  docs_scaffold: true
pipelines/tasks-pm/pipeline.yaml:18:  base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
pipelines/tasks-pm/pipeline.yaml:19:  pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
pipelines/tasks-pm/prompts/roles/coder.md:5:- worktree **от ветки фичи** (`base_branch` от PM), **НЕ от `main`**. Воркеры этапов ответвляются от ветки фичи.
pipelines/tasks-pm/prompts/_pipeline.md:24:- **PM-фичи** утверждает **ветку фичи** (`feature/<id>-<slug>`): создаёт от `main`, подтягивает интеграционную ветку. Передаёт её кодеру как `base_branch`.
pipelines/tasks-pm/prompts/_pipeline.md:25:- **Кодер** создаёт worktree **от ветки фичи** (`base_branch`), НЕ от `main`. Воркеры этапов ответвляются от ветки фичи.
pipelines/tasks-pm/prompts/roles/pm-fichi.md:8:4. **Утверди ветку фичи** (`feature/<id>-<slug>`): создай от `main`, подтяни интеграционную ветку. Передавай кодеру/тестировщику как `base_branch`.
pipelines/tasks-pm/prompts/roles/pm-fichi.md:34:Сформулируй **пакет документов**, который требуешь от аналитика (см. таблицу контрактов в `_pipeline.md`): `SPEC.md`, `TDD_PLAN.md`, `CONTRACTS.md`, **`MANUAL_TESTING.md`**, **`FIXTURES.md`**, чеклист. От кодера — этапные отчёты и `IMPL_REPORT.md`. Без `MANUAL_TESTING.md` / `FIXTURES.md` не принимай анализ — тестер потом будет «вспоминать сам», как сейчас.
pipelines/tasks-pm/prompts/roles/pm-fichi.md:47:1. Собрал достаточно инфы → спавни **аналитика** (is_orchestrator=true, role="analyst"). Требуй git-секцию как обязательную часть отчёта. Не принимай анализ, пока пакет документов не собран и ревью плана не пройдено.
pipelines/tasks-pm/prompts/roles/pm-fichi.md:48:2. Принял анализ → спавни **кодера** (is_orchestrator=true, role="coder"), передай `base_branch` (ветку фичи). **Аналитика НЕ убивай** — оставь idle для вопросов кодера/тестировщика/юзера.
pipelines/tasks-pm/prompts/roles/pm-fichi.md:50:4. **Если юзер просил ручное тестирование** → после кодера спавни **тестировщика** (is_orchestrator=true, role="tester"). Запуск проекта он согласует с тобой, ты — с PM-главой.
pipelines/tasks-pm/prompts/roles/pm-glava.md:25:2. На каждую фичу — положи `docs_work/<feature>/_pm/feature_scope.md` (см. шаблон ниже), и только потом спавни оркестратора `role="pm-fichi"` (is_orchestrator=true). В первом `send_message` сразу укажи: scope, **интеграционная ветка, ветка фичи (создай её сам или поручи), путь к `feature_scope.md`**, критерии приёмки.
pipelines/tasks-pm/prompts/roles/base-orchestrator.md:4:Можешь запустить пайплайн: по просьбе создай ребёнка с ролью `pm-glava` (is_orchestrator=true, role="pm-glava"), передав scope.
pipelines/default/pipeline.yaml:2:description: Upstream pipeline v2.18 (orchestrator / sub-orchestrator / worker / full-cycle). Behaviour 1:1 with mccalpink/orchestra main.
pipelines/default/pipeline.yaml:15:  base_branch_strategy: main
pipelines/default/pipeline.yaml:16:  docs_scaffold: false
pipelines/default/pipeline.yaml:58:      General-purpose worker. Implements tasks directly, no pipeline gates.
pipelines/default/pipeline.yaml:72:      Research → Plan + Codex review → Implement + Codex review. Strict 3-phase pipeline
tests/test_tasks_pm_pipeline.py:9:from app.pipeline import (
tests/test_tasks_pm_pipeline.py:12:    load_pipeline,
tests/test_tasks_pm_pipeline.py:14:    validate_spawn,
tests/test_tasks_pm_pipeline.py:18:    not (PIPELINES_DIR / "tasks-pm" / "pipeline.yaml").is_file(),
tests/test_tasks_pm_pipeline.py:22:_MARKER = "## Пайплайн — сквозные правила"  # характерная строка из prompts/_pipeline.md
tests/test_tasks_pm_pipeline.py:31:    cfg = load_pipeline("tasks-pm")
tests/test_tasks_pm_pipeline.py:38:    cfg = load_pipeline("tasks-pm")
tests/test_tasks_pm_pipeline.py:46:def test_base_branch_strategy():
tests/test_tasks_pm_pipeline.py:47:    cfg = load_pipeline("tasks-pm")
tests/test_tasks_pm_pipeline.py:48:    assert resolve_role(cfg, "base-orchestrator").base_branch_strategy == "main"
tests/test_tasks_pm_pipeline.py:49:    assert resolve_role(cfg, "pm-glava").base_branch_strategy == "main"
tests/test_tasks_pm_pipeline.py:51:        assert resolve_role(cfg, r).base_branch_strategy == "parent", r
tests/test_tasks_pm_pipeline.py:54:def test_is_orchestrator():
tests/test_tasks_pm_pipeline.py:55:    cfg = load_pipeline("tasks-pm")
tests/test_tasks_pm_pipeline.py:57:        assert resolve_role(cfg, r).is_orchestrator is True, r
tests/test_tasks_pm_pipeline.py:59:        assert resolve_role(cfg, r).is_orchestrator is False, r
tests/test_tasks_pm_pipeline.py:62:def test_validate_spawn_fail_closed():
tests/test_tasks_pm_pipeline.py:65:        validate_spawn("tasks-pm", "pm-glava", "analyst")
tests/test_tasks_pm_pipeline.py:67:    validate_spawn("tasks-pm", "pm-glava", "pm-fichi")
tests/test_tasks_pm_pipeline.py:68:    validate_spawn("tasks-pm", "base-orchestrator", "pm-glava")
tests/test_tasks_pm_pipeline.py:73:    assert _MARKER in coder  # слой _pipeline.md (только для оркестраторов)
tests/test_tasks_pm_pipeline.py:84:    assert _MARKER not in secretary  # воркер НЕ получает слой _pipeline.md
tests/test_tasks_pm_pipeline.py:88:    cfg = load_pipeline("tasks-pm")
tests/test_scaffold.py:1:"""Тесты generic-скаффолда doc-папок (app.manager._scaffold_role_docs).
tests/test_scaffold.py:3:Изолированный модуль: фикстура строит синтетический pipelines/<uniq>/ на tmp_path
tests/test_scaffold.py:4:и патчит app.pipeline.PIPELINES_DIR. На приватный tasks-pm НЕ опираемся — тест
tests/test_scaffold.py:13:import app.pipeline as P
tests/test_scaffold.py:14:from app.manager import _scaffold_role_docs
tests/test_scaffold.py:21:#   orch-off   — orchestrator с docs_dir, но docs_scaffold:false (пропуск)
tests/test_scaffold.py:26:  docs_scaffold: true
tests/test_scaffold.py:30:  orch-off:   {kind: orchestrator, label: "Off", docs_scaffold: false, docs_dir: {path: _off, template: plain.md}}
tests/test_scaffold.py:36:def pipelines_root(tmp_path, monkeypatch):
tests/test_scaffold.py:39:    Возвращает кортеж (root, cwd): root — pipelines/, cwd — рабочая папка сессии.
tests/test_scaffold.py:41:    root = tmp_path / "pipelines"
tests/test_scaffold.py:44:    (root / PIPELINE / "pipeline.yaml").write_text(textwrap.dedent(_YAML))
tests/test_scaffold.py:48:    P.load_pipeline.cache_clear()
tests/test_scaffold.py:52:    P.load_pipeline.cache_clear()
tests/test_scaffold.py:55:def test_docs_dir_no_requires_creates_dashboard(pipelines_root):
tests/test_scaffold.py:57:    _root, cwd = pipelines_root
tests/test_scaffold.py:58:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-plain")
tests/test_scaffold.py:64:def test_requires_feature_with_feature(pipelines_root):
tests/test_scaffold.py:66:    _root, cwd = pipelines_root
tests/test_scaffold.py:67:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-feat", feature="login")
tests/test_scaffold.py:75:def test_requires_feature_without_feature_skips(pipelines_root):
tests/test_scaffold.py:77:    _root, cwd = pipelines_root
tests/test_scaffold.py:78:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-feat")
tests/test_scaffold.py:82:def test_no_docs_dir_skips(pipelines_root):
tests/test_scaffold.py:84:    _root, cwd = pipelines_root
tests/test_scaffold.py:85:    _scaffold_role_docs(PIPELINE, str(cwd), "plain-wk")
tests/test_scaffold.py:89:def test_idempotent_no_overwrite(pipelines_root):
tests/test_scaffold.py:91:    _root, cwd = pipelines_root
tests/test_scaffold.py:92:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-plain")
tests/test_scaffold.py:95:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-plain")
tests/test_scaffold.py:99:def test_docs_scaffold_false_skips(pipelines_root):
tests/test_scaffold.py:100:    """(f) docs_scaffold:false на роли → пропуск."""
tests/test_scaffold.py:101:    _root, cwd = pipelines_root
tests/test_scaffold.py:102:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-off")
tests/test_scaffold.py:106:def test_feature_traversal_escape_blocked(pipelines_root):
tests/test_scaffold.py:108:    _root, cwd = pipelines_root
tests/test_scaffold.py:109:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-feat", feature="../../etc")
tests/test_scaffold.py:119:    _scaffold_role_docs(PIPELINE, str(cwd), "orch-feat", feature="login")
tests/test_scaffold.py:123:def test_missing_pipeline_skips(tmp_path, monkeypatch):
tests/test_scaffold.py:126:    P.load_pipeline.cache_clear()
tests/test_scaffold.py:129:    _scaffold_role_docs("nonexistent", str(cwd), "orch-plain")
tests/test_scaffold.py:131:    P.load_pipeline.cache_clear()
tests/test_session.py:173:    s.is_orchestrator = True   # оркестратор отчитывается наверх ТОЛЬКО явным send_message
tests/test_session.py:185:# ── Этап 1: pipeline + is_orchestrator как хранимое поле ──
tests/test_session.py:188:    def test_pipeline_default_empty(self):
tests/test_session.py:191:        assert s.pipeline == ""
tests/test_session.py:193:    def test_pipeline_can_be_set(self):
tests/test_session.py:195:        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", pipeline="tasks-pm")
tests/test_session.py:196:        assert s.pipeline == "tasks-pm"
tests/test_session.py:198:    def test_to_db_dict_includes_pipeline(self):
tests/test_session.py:200:        s = AgentSession(id="i", name="w", scope="/s", cwd="/tmp", pipeline="tasks-pm")
tests/test_session.py:201:        assert s._to_db_dict()["pipeline"] == "tasks-pm"
tests/test_session.py:208:        assert s.is_orchestrator is False        # fallback от role
tests/test_session.py:209:        s.is_orchestrator = True                 # сеттер (раньше падал: no setter)
tests/test_session.py:210:        assert s.is_orchestrator is True
tests/test_session.py:216:        assert orch.is_orchestrator is True       # frozenset fallback
tests/test_session.py:217:        assert wrk.is_orchestrator is False
tests/test_session.py:222:        s.is_orchestrator = False                # явный override (манифест может сказать worker)
tests/test_session.py:223:        assert s.is_orchestrator is False
tests/test_session.py:238:        assert opts.env["CLAUDE_CONFIG_DIR"] == "/tmp/x"
tests/test_session.py:242:        opts = self._opts(config_dir="~/some-profile")
tests/test_session.py:243:        assert opts.env["CLAUDE_CONFIG_DIR"] == os.path.expanduser("~/some-profile")
tests/test_session.py:247:        assert "CLAUDE_CONFIG_DIR" not in opts.env
tests/test_session.py:265:    def test_f1_skills_never_set_with_profile(self):
tests/test_session.py:339:    def test_default_pipeline_no_profile(self, monkeypatch):
tests/test_session.py:341:        s = self._session(monkeypatch, pipeline="default", role="worker")
tests/test_session.py:347:    def test_profile_resolves_config_dir(self, monkeypatch):
tests/test_session.py:351:        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
tests/test_session.py:352:        monkeypatch.setattr("app.db.get_profile",
tests/test_session.py:354:        s = self._session(monkeypatch, pipeline="p", profile="work")
tests/test_session.py:363:        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
tests/test_session.py:364:        monkeypatch.setattr("app.db.get_profile",
tests/test_session.py:369:        s = self._session(monkeypatch, pipeline="p", profile="work")
tests/test_session.py:377:        monkeypatch.setattr("app.pipeline.get_role", _raise)
tests/test_session.py:378:        s = self._session(monkeypatch, pipeline="ghost", role="worker")
tests/test_session.py:384:    def test_profile_not_found_empty_config_dir(self, monkeypatch):
tests/test_session.py:386:        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
tests/test_session.py:387:        monkeypatch.setattr("app.db.get_profile", lambda n: None)
tests/test_session.py:388:        s = self._session(monkeypatch, pipeline="p", profile="ghost")
tests/test_session.py:392:    def test_claude_work_profile_end_to_end_env(self, monkeypatch, tmp_path):
tests/test_session.py:396:        _make_client → ClaudeAgentOptions.env['CLAUDE_CONFIG_DIR'], раскрытый
tests/test_session.py:401:        monkeypatch.setattr("app.pipeline.get_role", lambda p, r: rr)
tests/test_session.py:403:            "app.db.get_profile",
tests/test_session.py:407:        s = self._session(monkeypatch, pipeline="p", profile="work")
tests/test_session.py:412:        assert opts.env["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude-work")
tests/test_default_pipeline.py:1:"""Тесты дефолтного пайплайна ``pipelines/default/`` (Этап 4, обновлён под v2.16).
tests/test_default_pipeline.py:4:манифест + промпты грузятся нашим loader'ом (app/pipeline.py) и воспроизводят
tests/test_default_pipeline.py:7:промпта без слоя ``_pipeline.md``, инлайн ``modules`` (git-workflow/codex-review/
tests/test_default_pipeline.py:10:В отличие от test_pipeline.py (tmp-фикстуры), здесь тесты идут по РЕАЛЬНОМУ
tests/test_default_pipeline.py:11:``pipelines/default/`` на диске — это и есть характеризация 1:1 с апстримом.
tests/test_default_pipeline.py:18:import app.pipeline as P
tests/test_default_pipeline.py:25:    """lru_cache load_pipeline чистится до/после, чтобы реальный default читался
tests/test_default_pipeline.py:27:    P.load_pipeline.cache_clear()
tests/test_default_pipeline.py:29:    P.load_pipeline.cache_clear()
tests/test_default_pipeline.py:35:    def test_load_pipeline_default_is_valid(self):
tests/test_default_pipeline.py:37:        cfg = P.load_pipeline(PIPELINE)
tests/test_default_pipeline.py:43:        cfg = P.load_pipeline(PIPELINE)
tests/test_default_pipeline.py:50:        cfg = P.load_pipeline(PIPELINE)
tests/test_default_pipeline.py:58:        base_branch_strategy main, docs_scaffold off, слои БЕЗ _pipeline.md."""
tests/test_default_pipeline.py:59:        cfg = P.load_pipeline(PIPELINE)
tests/test_default_pipeline.py:64:        assert d.base_branch_strategy == "main"  # все worktree от main
tests/test_default_pipeline.py:65:        assert d.docs_scaffold is False  # апстрим не скаффолдит doc-папки
tests/test_default_pipeline.py:68:    def test_prompt_layers_have_no_pipeline_layer(self):
tests/test_default_pipeline.py:69:        """У апстрима НЕТ _pipeline.md — только base + роль."""
tests/test_default_pipeline.py:70:        cfg = P.load_pipeline(PIPELINE)
tests/test_default_pipeline.py:73:        assert "_pipeline.md" not in cfg.defaults.prompt_layers.orchestrator
tests/test_default_pipeline.py:74:        assert "_pipeline.md" not in cfg.defaults.prompt_layers.worker
tests/test_default_pipeline.py:78:        cfg = P.load_pipeline(PIPELINE)
tests/test_default_pipeline.py:84:        """list_pipelines() видит default и помечает valid=True."""
tests/test_default_pipeline.py:85:        entries = {p["name"]: p for p in P.list_pipelines()}
tests/test_default_pipeline.py:102:    def test_orchestrator_is_orchestrator(self):
tests/test_default_pipeline.py:105:        assert rr.is_orchestrator is True
tests/test_default_pipeline.py:110:        assert P.get_role(PIPELINE, "worker").is_orchestrator is False
tests/test_default_pipeline.py:111:        assert P.get_role(PIPELINE, "full-cycle").is_orchestrator is False
tests/test_default_pipeline.py:118:    def test_sub_orchestrator_is_orchestrator_opus(self):
tests/test_default_pipeline.py:122:        assert rr.is_orchestrator is True
tests/test_default_pipeline.py:148:    def test_orchestrator_layers_substituted_no_pipeline(self):
tests/test_default_pipeline.py:149:        """Резолвнутые слои оркестратора: base + roles/orchestrator.md, БЕЗ _pipeline.md."""
tests/test_default_pipeline.py:158:# ── build_system_prompt: композиция base + роль (без _pipeline.md) ──────────
tests/test_default_pipeline.py:170:    def test_orchestrator_prompt_has_no_pipeline_layer_content(self):
tests/test_default_pipeline.py:171:        """В default НЕТ _pipeline.md — слой не существует и не подмешивается."""
tests/test_default_pipeline.py:173:        assert not P.prompt_path(PIPELINE, "_pipeline.md").is_file()
tests/test_default_pipeline.py:176:        assert "_pipeline" not in out
tests/test_default_pipeline.py:205:    def test_full_cycle_prompt_has_three_phase_pipeline(self):
tests/test_default_pipeline.py:210:        assert "<pipeline>" in out
tests/test_default_pipeline.py:300:# ── validate_spawn: fail-open + can_spawn=['*'] + allow_unrouted_workers ────
tests/test_default_pipeline.py:305:        assert P.validate_spawn(PIPELINE, "orchestrator", "worker") is None
tests/test_default_pipeline.py:308:        assert P.validate_spawn(PIPELINE, "orchestrator", "full-cycle") is None
tests/test_default_pipeline.py:313:            assert P.validate_spawn(PIPELINE, "orchestrator", child) is None
tests/test_default_pipeline.py:317:        assert P.validate_spawn(PIPELINE, "sub-orchestrator", "worker") is None
tests/test_default_pipeline.py:321:        assert P.validate_spawn(PIPELINE, "orchestrator", "") is None
tests/test_default_pipeline.py:325:        assert P.validate_spawn(PIPELINE, "", "orchestrator") is None
tests/test_default_pipeline.py:326:        assert P.validate_spawn(PIPELINE, None, "orchestrator") is None
tests/test_default_pipeline.py:331:        assert P.validate_spawn(PIPELINE, "orchestrator", "nonexistent-role") is None
tests/test_default_pipeline.py:335:        assert P.validate_spawn(PIPELINE, "phantom", "worker") is None
tests/test_mcp_stdio.py:6:async def test_spawn_passes_base_branch(monkeypatch):
tests/test_mcp_stdio.py:17:                             model="claude-sonnet-4-6", base_branch="feature/auth")
tests/test_mcp_stdio.py:18:    assert captured["base_branch"] == "feature/auth"
tests/test_mcp_stdio.py:23:async def test_spawn_base_branch_default_empty(monkeypatch):
tests/test_mcp_stdio.py:36:    assert captured["base_branch"] == ""
tests/test_default_equals_upstream.py:1:"""Characterization-тест: pipeline ``default`` ≡ upstream (frontmatter+glob).
tests/test_default_equals_upstream.py:3:ЦЕЛЬ (ФАЗА B): доказать, что наш манифест-путь (``pipelines/default/``) даёт
tests/test_default_equals_upstream.py:6:``pipelines/default/`` так, что он разойдётся с upstream-источником истины
tests/test_default_equals_upstream.py:14:  * НАШ — ``pipelines/default/pipeline.yaml`` + ``pipelines/default/prompts/``.
tests/test_default_equals_upstream.py:15:    Функции: ``pipeline.build_system_prompt``, ``pipeline.validate_spawn``,
tests/test_default_equals_upstream.py:16:    ``pipeline.resolve_role``.
tests/test_default_equals_upstream.py:20:  2. validate_spawn для ВСЕХ пар (parent, child) совпадает с ``_role_can_spawn``.
tests/test_default_equals_upstream.py:30:import app.pipeline as P
tests/test_default_equals_upstream.py:46:    """Чистим lru_cache load_pipeline до/после — читаем реальный default с диска."""
tests/test_default_equals_upstream.py:47:    P.load_pipeline.cache_clear()
tests/test_default_equals_upstream.py:49:    P.load_pipeline.cache_clear()
tests/test_default_equals_upstream.py:84:        Если тела ``pipelines/default/prompts/roles/*.md`` разойдутся с upstream-телами
tests/test_default_equals_upstream.py:95:# ── B2.2: validate_spawn для всех пар ролей ────────────────────────────────
tests/test_default_equals_upstream.py:98:    """True, если наш ``validate_spawn`` РАЗРЕШАЕТ спавн (не бросает ValueError)."""
tests/test_default_equals_upstream.py:100:        P.validate_spawn(PIPELINE, parent, child)
tests/test_default_equals_upstream.py:188:    ``pipelines/bridge-default/`` (с симлинком на реальные prompts default),
tests/test_default_equals_upstream.py:195:    def bridge_pipeline(self, tmp_path, monkeypatch):
tests/test_default_equals_upstream.py:196:        """Сгенерировать манифест мостом → tmp pipelines/bridge-default/."""
tests/test_default_equals_upstream.py:200:        root = tmp_path / "pipelines"
tests/test_default_equals_upstream.py:204:        (pdir / "pipeline.yaml").write_text(
tests/test_default_equals_upstream.py:210:        P.load_pipeline.cache_clear()
tests/test_default_equals_upstream.py:212:        P.load_pipeline.cache_clear()
tests/test_default_equals_upstream.py:214:    def test_bridge_manifest_self_validates(self, bridge_pipeline):
tests/test_default_equals_upstream.py:216:        cfg = P.load_pipeline(bridge_pipeline)
tests/test_default_equals_upstream.py:220:    def test_bridge_role_model_and_modules(self, bridge_pipeline, role):
tests/test_default_equals_upstream.py:222:        rr = P.get_role(bridge_pipeline, role)
tests/test_default_equals_upstream.py:231:    def test_bridge_spawn_matches_upstream(self, bridge_pipeline, parent, child):
tests/test_default_equals_upstream.py:232:        """validate_spawn на манифесте моста == upstream-логике для всех пар."""
tests/test_default_equals_upstream.py:234:            P.validate_spawn(bridge_pipeline, parent, child)
tests/test_pipeline.py:1:"""Тесты loader'а пайплайнов (app/pipeline.py).
tests/test_pipeline.py:3:Изолированный модуль: фикстуры строят временные pipelines/<name>/pipeline.yaml
tests/test_pipeline.py:4:на tmp_path и патчат app.pipeline.PIPELINES_DIR. На реальные pipelines/ НЕ опираемся.
tests/test_pipeline.py:12:import app.pipeline as P
tests/test_pipeline.py:18:def pipelines_root(tmp_path, monkeypatch):
tests/test_pipeline.py:19:    """Подменяет корень пайплайнов на tmp + чистит lru_cache load_pipeline.
tests/test_pipeline.py:21:    Возвращает Path к временной директории pipelines/.
tests/test_pipeline.py:23:    root = tmp_path / "pipelines"
tests/test_pipeline.py:26:    P.load_pipeline.cache_clear()
tests/test_pipeline.py:28:    P.load_pipeline.cache_clear()
tests/test_pipeline.py:31:def _write_pipeline(root, name: str, yaml_text: str, prompts: dict | None = None):
tests/test_pipeline.py:32:    """Создаёт pipelines/<name>/pipeline.yaml (+ опц. prompts/<rel>=content)."""
tests/test_pipeline.py:35:    (d / "pipeline.yaml").write_text(textwrap.dedent(yaml_text))
tests/test_pipeline.py:46:    description: Test pipeline
tests/test_pipeline.py:66:# ── load_pipeline ────────────────────────────────────────────────────────
tests/test_pipeline.py:69:    def test_loads_valid_manifest(self, pipelines_root):
tests/test_pipeline.py:70:        _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
tests/test_pipeline.py:71:        cfg = P.load_pipeline("demo")
tests/test_pipeline.py:73:        assert cfg.description == "Test pipeline"
tests/test_pipeline.py:79:    def test_missing_file_raises_filenotfound(self, pipelines_root):
tests/test_pipeline.py:81:            P.load_pipeline("nope")
tests/test_pipeline.py:83:    def test_name_mismatch_raises(self, pipelines_root):
tests/test_pipeline.py:84:        _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="other"))
tests/test_pipeline.py:86:            P.load_pipeline("demo")
tests/test_pipeline.py:88:    def test_is_cached(self, pipelines_root):
tests/test_pipeline.py:89:        d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
tests/test_pipeline.py:90:        first = P.load_pipeline("demo")
tests/test_pipeline.py:92:        (d / "pipeline.yaml").write_text("garbage: [")
tests/test_pipeline.py:93:        second = P.load_pipeline("demo")
tests/test_pipeline.py:100:    def test_extra_field_top_level_rejected(self, pipelines_root):
tests/test_pipeline.py:101:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:108:            P.load_pipeline("demo")
tests/test_pipeline.py:110:    def test_extra_field_in_role_rejected(self, pipelines_root):
tests/test_pipeline.py:111:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:117:            P.load_pipeline("demo")
tests/test_pipeline.py:119:    def test_invalid_kind_rejected(self, pipelines_root):
tests/test_pipeline.py:120:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:126:            P.load_pipeline("demo")
tests/test_pipeline.py:128:    def test_invalid_validation_mode_rejected(self, pipelines_root):
tests/test_pipeline.py:129:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:136:            P.load_pipeline("demo")
tests/test_pipeline.py:138:    def test_invalid_model_in_defaults_rejected(self, pipelines_root):
tests/test_pipeline.py:139:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:146:            P.load_pipeline("demo")
tests/test_pipeline.py:148:    def test_invalid_model_in_role_rejected(self, pipelines_root):
tests/test_pipeline.py:149:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:155:            P.load_pipeline("demo")
tests/test_pipeline.py:157:    def test_full_model_id_accepted(self, pipelines_root):
tests/test_pipeline.py:158:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:164:        cfg = P.load_pipeline("demo")
tests/test_pipeline.py:168:    def test_can_spawn_unknown_role_rejected(self, pipelines_root):
tests/test_pipeline.py:169:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:176:            P.load_pipeline("demo")
tests/test_pipeline.py:178:    def test_can_spawn_wildcard_allowed(self, pipelines_root):
tests/test_pipeline.py:179:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:185:        cfg = P.load_pipeline("demo")
tests/test_pipeline.py:200:    def test_prompt_layers_traversal_rejected(self, pipelines_root):
tests/test_pipeline.py:202:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:212:            P.load_pipeline("demo")
tests/test_pipeline.py:214:    def test_prompt_layers_absolute_rejected(self, pipelines_root):
tests/test_pipeline.py:216:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:226:            P.load_pipeline("demo")
tests/test_pipeline.py:228:    def test_docs_dir_absolute_path_rejected(self, pipelines_root):
tests/test_pipeline.py:230:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:236:            P.load_pipeline("demo")
tests/test_pipeline.py:238:    def test_docs_dir_traversal_template_rejected(self, pipelines_root):
tests/test_pipeline.py:240:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:246:            P.load_pipeline("demo")
tests/test_pipeline.py:248:    def test_safe_manifest_paths_accepted(self, pipelines_root):
tests/test_pipeline.py:250:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:254:                orchestrator: ["base.md", "roles/{role}.md", "_pipeline.md"]
tests/test_pipeline.py:259:        cfg = P.load_pipeline("demo")
tests/test_pipeline.py:262:    def test_skills_all_and_list_both_valid(self, pipelines_root):
tests/test_pipeline.py:263:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:269:        cfg = P.load_pipeline("demo")
tests/test_pipeline.py:277:    def test_symlink_source_traversal_rejected(self, pipelines_root):
tests/test_pipeline.py:279:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:288:            P.load_pipeline("demo")
tests/test_pipeline.py:290:    def test_symlink_source_absolute_rejected(self, pipelines_root):
tests/test_pipeline.py:292:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:301:            P.load_pipeline("demo")
tests/test_pipeline.py:303:    def test_symlink_target_traversal_rejected(self, pipelines_root):
tests/test_pipeline.py:305:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:314:            P.load_pipeline("demo")
tests/test_pipeline.py:316:    def test_symlink_safe_paths_accepted(self, pipelines_root):
tests/test_pipeline.py:318:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:327:        cfg = P.load_pipeline("demo")
tests/test_pipeline.py:331:    def test_copies_traversal_rejected(self, pipelines_root):
tests/test_pipeline.py:333:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:342:            P.load_pipeline("demo")
tests/test_pipeline.py:344:    def test_copies_absolute_rejected(self, pipelines_root):
tests/test_pipeline.py:346:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:355:            P.load_pipeline("demo")
tests/test_pipeline.py:361:    def test_returns_worktree_with_copies(self, pipelines_root):
tests/test_pipeline.py:363:        _write_pipeline(pipelines_root, "demo", """\
tests/test_pipeline.py:377:    def test_missing_pipeline_raises_filenotfound(self, pipelines_root):
tests/test_pipeline.py:394:      base_branch_strategy: parent
tests/test_pipeline.py:395:      docs_scaffold: true
tests/test_pipeline.py:397:        orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
tests/test_pipeline.py:404:        base_branch_strategy: main
tests/test_pipeline.py:425:        _write_pipeline(root, "inh", _INHERIT)
tests/test_pipeline.py:426:        return P.load_pipeline("inh")
tests/test_pipeline.py:428:    def test_scalar_inherited_when_role_omits(self, pipelines_root):
tests/test_pipeline.py:429:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:434:        assert rr.docs_scaffold is True
tests/test_pipeline.py:435:        assert rr.base_branch_strategy == "parent"
tests/test_pipeline.py:437:    def test_scalar_overridden_by_role(self, pipelines_root):
tests/test_pipeline.py:438:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:442:        assert rr_lead.base_branch_strategy == "main"  # роль переопределила parent→main
tests/test_pipeline.py:444:    def test_list_union(self, pipelines_root):
tests/test_pipeline.py:445:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:450:    def test_list_all_absorbs(self, pipelines_root):
tests/test_pipeline.py:451:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:456:    def test_list_inherited_when_role_omits(self, pipelines_root):
tests/test_pipeline.py:457:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:463:    def test_prompt_layers_orchestrator_with_role_substituted(self, pipelines_root):
tests/test_pipeline.py:464:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:466:        assert rr.prompt_layers == ["base.md", "roles/coder.md", "_pipeline.md"]
tests/test_pipeline.py:468:    def test_prompt_layers_worker_no_pipeline_layer(self, pipelines_root):
tests/test_pipeline.py:469:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:473:    def test_role_specific_fields_passthrough(self, pipelines_root):
tests/test_pipeline.py:474:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:480:        assert rr.name == "coder" and rr.pipeline == "inh"
tests/test_pipeline.py:482:    def test_is_orchestrator_property(self, pipelines_root):
tests/test_pipeline.py:483:        cfg = self._cfg(pipelines_root)
tests/test_pipeline.py:484:        assert P.resolve_role(cfg, "coder").is_orchestrator is True
tests/test_pipeline.py:485:        assert P.resolve_role(cfg, "secretary").is_orchestrator is False
tests/test_pipeline.py:487:    def test_all_union_all_stays_all(self, pipelines_root):
tests/test_pipeline.py:489:        _write_pipeline(pipelines_root, "aa", """\
tests/test_pipeline.py:495:        cfg = P.load_pipeline("aa")
tests/test_pipeline.py:502:    def test_orchestrator_concatenates_three_layers(self, pipelines_root):
tests/test_pipeline.py:503:        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
tests/test_pipeline.py:506:            "_pipeline.md": "PIPE",
tests/test_pipeline.py:511:    def test_worker_two_layers_no_pipeline(self, pipelines_root):
tests/test_pipeline.py:512:        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
tests/test_pipeline.py:515:            "_pipeline.md": "SHOULD-NOT-APPEAR",  # воркер не берёт _pipeline.md
tests/test_pipeline.py:521:    def test_missing_layer_skipped(self, pipelines_root):
tests/test_pipeline.py:522:        # есть base.md, нет roles/lead.md и _pipeline.md → только base
tests/test_pipeline.py:523:        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
tests/test_pipeline.py:529:    def test_all_layers_missing_returns_empty(self, pipelines_root):
tests/test_pipeline.py:530:        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"))  # без prompts
tests/test_pipeline.py:533:    def test_isolation_does_not_read_app_prompts(self, pipelines_root, monkeypatch, tmp_path):
tests/test_pipeline.py:535:        и наоборот: слой из app/prompts/ в итог НЕ попадает (читаем только pipelines/)."""
tests/test_pipeline.py:539:        _write_pipeline(pipelines_root, "p", _MINIMAL.format(name="p"), prompts={
tests/test_pipeline.py:542:            "_pipeline.md": "ISO-PIPE",
tests/test_pipeline.py:552:    def test_prompt_path_always_inside_pipelines_dir(self, pipelines_root):
tests/test_pipeline.py:554:        assert str(p).startswith(str(pipelines_root))
tests/test_pipeline.py:555:        assert p == pipelines_root / "p" / "prompts" / "roles" / "lead.md"
tests/test_pipeline.py:557:    def test_template_path_inside_pipelines_dir(self, pipelines_root):
tests/test_pipeline.py:558:        t = P.template_path("p", "impl.md")
tests/test_pipeline.py:559:        assert t == pipelines_root / "p" / "templates" / "impl.md"
tests/test_pipeline.py:561:    def test_build_raises_filenotfound_for_missing_pipeline(self, pipelines_root):
tests/test_pipeline.py:567:# ── list_pipelines: скан + устойчивость к битым манифестам ─────────────────
tests/test_pipeline.py:570:    def test_lists_valid_pipelines(self, pipelines_root):
tests/test_pipeline.py:571:        _write_pipeline(pipelines_root, "alpha", _MINIMAL.format(name="alpha"))
tests/test_pipeline.py:572:        _write_pipeline(pipelines_root, "beta", _MINIMAL.format(name="beta"))
tests/test_pipeline.py:573:        out = P.list_pipelines()
tests/test_pipeline.py:578:        assert alpha["description"] == "Test pipeline"
tests/test_pipeline.py:580:    def test_empty_root_returns_empty_list(self, pipelines_root):
tests/test_pipeline.py:581:        assert P.list_pipelines() == []
tests/test_pipeline.py:585:        P.load_pipeline.cache_clear()
tests/test_pipeline.py:586:        assert P.list_pipelines() == []
tests/test_pipeline.py:588:    def test_broken_manifest_marked_invalid_not_raised(self, pipelines_root):
tests/test_pipeline.py:589:        _write_pipeline(pipelines_root, "good", _MINIMAL.format(name="good"))
tests/test_pipeline.py:591:        _write_pipeline(pipelines_root, "bad", """\
tests/test_pipeline.py:596:        out = P.list_pipelines()
tests/test_pipeline.py:601:    def test_dir_without_yaml_skipped(self, pipelines_root):
tests/test_pipeline.py:602:        (pipelines_root / "not_a_pipeline").mkdir()  # папка без pipeline.yaml
tests/test_pipeline.py:603:        _write_pipeline(pipelines_root, "real", _MINIMAL.format(name="real"))
tests/test_pipeline.py:604:        out = P.list_pipelines()
tests/test_pipeline.py:608:# ── validate_spawn: fail-closed/open, whitelist, unrouted, корень ──────────
tests/test_pipeline.py:631:        _write_pipeline(root, "closed", _SPAWN_CLOSED)
tests/test_pipeline.py:634:        _write_pipeline(root, "opened", _SPAWN_OPEN)
tests/test_pipeline.py:636:    def test_allowed_child_passes(self, pipelines_root):
tests/test_pipeline.py:637:        self._closed(pipelines_root)
tests/test_pipeline.py:638:        assert P.validate_spawn("closed", "lead", "coder") is None  # в whitelist
tests/test_pipeline.py:640:    def test_forbidden_child_raises_fail_closed(self, pipelines_root):
tests/test_pipeline.py:641:        self._closed(pipelines_root)
tests/test_pipeline.py:644:            P.validate_spawn("closed", "coder", "coder")
tests/test_pipeline.py:646:    def test_terminal_role_cannot_spawn(self, pipelines_root):
tests/test_pipeline.py:647:        self._closed(pipelines_root)
tests/test_pipeline.py:649:            P.validate_spawn("closed", "secretary", "coder")
tests/test_pipeline.py:651:    def test_root_empty_parent_allowed(self, pipelines_root):
tests/test_pipeline.py:652:        self._closed(pipelines_root)
tests/test_pipeline.py:654:        assert P.validate_spawn("closed", "", "lead") is None
tests/test_pipeline.py:655:        assert P.validate_spawn("closed", None, "lead") is None
tests/test_pipeline.py:657:    def test_unrouted_worker_blocked_when_not_allowed(self, pipelines_root):
tests/test_pipeline.py:658:        self._closed(pipelines_root)
tests/test_pipeline.py:661:            P.validate_spawn("closed", "lead", "")
tests/test_pipeline.py:663:    def test_unrouted_worker_allowed_when_flag_set(self, pipelines_root):
tests/test_pipeline.py:664:        self._closed(pipelines_root)
tests/test_pipeline.py:666:        assert P.validate_spawn("closed", "coder", "") is None
tests/test_pipeline.py:668:    def test_unknown_child_fail_closed_raises(self, pipelines_root):
tests/test_pipeline.py:669:        self._closed(pipelines_root)
tests/test_pipeline.py:671:            P.validate_spawn("closed", "lead", "ghost")
tests/test_pipeline.py:673:    def test_unknown_parent_fail_closed_raises(self, pipelines_root):
tests/test_pipeline.py:674:        self._closed(pipelines_root)
tests/test_pipeline.py:676:            P.validate_spawn("closed", "phantom", "coder")
tests/test_pipeline.py:679:    def test_fail_open_forbidden_child_still_raises(self, pipelines_root):
tests/test_pipeline.py:682:        self._open(pipelines_root)
tests/test_pipeline.py:684:            P.validate_spawn("opened", "coder", "lead")
tests/test_pipeline.py:686:    def test_fail_open_unknown_parent_passes(self, pipelines_root):
tests/test_pipeline.py:687:        self._open(pipelines_root)
tests/test_pipeline.py:688:        assert P.validate_spawn("opened", "phantom", "coder") is None
tests/test_pipeline.py:690:    def test_fail_open_unknown_child_passes(self, pipelines_root):
tests/test_pipeline.py:691:        self._open(pipelines_root)
tests/test_pipeline.py:692:        assert P.validate_spawn("opened", "lead", "mystery") is None
tests/test_pipeline.py:694:    def test_wildcard_can_spawn_allows_any(self, pipelines_root):
tests/test_pipeline.py:695:        _write_pipeline(pipelines_root, "wild", """\
tests/test_pipeline.py:702:        assert P.validate_spawn("wild", "boss", "w") is None
tests/test_pipeline.py:705:# ── get_active_pipeline: наследование от родителя / дефолт ─────────────────
tests/test_pipeline.py:708:    def test_inherits_parent_pipeline(self):
tests/test_pipeline.py:709:        assert P.get_active_pipeline(parent_pipeline="tasks-pm") == "tasks-pm"
tests/test_pipeline.py:712:        assert P.get_active_pipeline() == P.DEFAULT_PIPELINE
tests/test_pipeline.py:713:        assert P.get_active_pipeline(scope="/some/proj") == P.DEFAULT_PIPELINE
tests/test_pipeline.py:716:        assert P.get_active_pipeline(scope="/x", parent_pipeline="custom") == "custom"
tests/test_pipeline.py:732:        orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
tests/test_pipeline.py:737:      base_branch_strategy: parent
tests/test_pipeline.py:738:      docs_scaffold: true
tests/test_pipeline.py:740:      base-orchestrator: {kind: orchestrator, label: Хаб, order: 0, base_branch_strategy: main, can_spawn: [pm-glava, secretary], allow_unrouted_workers: true, tg: {emoji: "🧭", topic: "{project}"}}
tests/test_pipeline.py:741:      pm-glava: {kind: orchestrator, label: ПМ Глава, order: 1, base_branch_strategy: main, can_spawn: [pm-fichi, secretary], allow_unrouted_workers: false, docs_dir: {path: "_sprint", template: sprint.md}, tg: {emoji: "🎯", topic: "{project} · спринт"}}
tests/test_pipeline.py:752:    def test_loads_clean(self, pipelines_root):
tests/test_pipeline.py:753:        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
tests/test_pipeline.py:754:        cfg = P.load_pipeline("tasks-pm")
tests/test_pipeline.py:760:    def test_secretary_inherits_opus_not_sonnet(self, pipelines_root):
tests/test_pipeline.py:761:        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
tests/test_pipeline.py:762:        cfg = P.load_pipeline("tasks-pm")
tests/test_pipeline.py:768:    def test_pm_glava_branch_strategy_main(self, pipelines_root):
tests/test_pipeline.py:769:        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
tests/test_pipeline.py:770:        cfg = P.load_pipeline("tasks-pm")
tests/test_pipeline.py:771:        assert P.resolve_role(cfg, "pm-glava").base_branch_strategy == "main"
tests/test_pipeline.py:772:        assert P.resolve_role(cfg, "coder").base_branch_strategy == "parent"  # из defaults
tests/test_pipeline.py:774:    def test_orchestrators_get_pipeline_layer(self, pipelines_root):
tests/test_pipeline.py:775:        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
tests/test_pipeline.py:776:        cfg = P.load_pipeline("tasks-pm")
tests/test_pipeline.py:777:        # 6 оркестраторов → _pipeline.md; secretary/worker (kind:worker) → нет
tests/test_pipeline.py:778:        assert "_pipeline.md" in P.resolve_role(cfg, "pm-fichi").prompt_layers
tests/test_pipeline.py:779:        assert "_pipeline.md" not in P.resolve_role(cfg, "secretary").prompt_layers
tests/test_pipeline.py:781:    def test_spawn_graph_enforced(self, pipelines_root):
tests/test_pipeline.py:782:        _write_pipeline(pipelines_root, "tasks-pm", _TASKS_PM)
tests/test_pipeline.py:784:        assert P.validate_spawn("tasks-pm", "pm-glava", "pm-fichi") is None
tests/test_pipeline.py:786:            P.validate_spawn("tasks-pm", "pm-glava", "coder")
tests/test_api.py:205:def test_create_request_accepts_base_branch():
tests/test_api.py:209:                               base_branch="feature/auth")
tests/test_api.py:210:    assert req.base_branch == "feature/auth"
tests/test_api.py:213:def test_create_request_base_branch_default_empty():
tests/test_api.py:218:    assert req.base_branch == ""
tests/test_api.py:248:        r = client.get("/api/pipelines")
tests/test_api.py:259:        monkeypatch.setattr(mainmod, "list_pipelines", lambda: [
tests/test_api.py:263:        r = client.get("/api/pipelines")
tests/test_api.py:271:        r = client.get("/api/profiles")
tests/test_api.py:277:        r = client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/x"})
tests/test_api.py:279:        g = client.get("/api/profiles").json()
tests/test_api.py:285:        r2 = client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/y"})
tests/test_api.py:287:        g2 = client.get("/api/profiles").json()
tests/test_api.py:293:        r = client.post("/api/profiles", json={"name": "a b!", "config_dir": "/tmp/x"})
tests/test_api.py:296:    def test_delete_profile(self, client):
tests/test_api.py:297:        client.post("/api/profiles", json={"name": "work", "config_dir": "/tmp/x"})
tests/test_api.py:298:        r = client.delete("/api/profiles/work")
tests/test_api.py:300:        names = [p["name"] for p in client.get("/api/profiles").json()]
tests/test_api.py:304:        r = client.delete("/api/profiles/personal")
tests/test_api.py:306:        names = [p["name"] for p in client.get("/api/profiles").json()]
tests/test_api.py:315:        r = client.post("/api/profiles", json={"name": "work", "config_dir": str(cfg)})
tests/test_api.py:320:        g = client.get("/api/profiles").json()
tests/test_api.py:326:        r = client.post("/api/profiles", json={"name": "work", "config_dir": str(missing)})
tests/test_api.py:332:        g = client.get("/api/profiles").json()
tests/test_api.py:335:        assert any(p["name"] == "work" for p in body["profiles"])
tests/test_api.py:339:        r = client.post("/api/profiles", json={"name": "noenv", "config_dir": ""})
tests/test_api.py:352:        r = client.post("/api/profiles", json={"name": "work", "config_dir": "~/.claude-work"})
tests/test_api.py:359:        r = client.post("/api/profiles", json={"name": "work", "config_dir": "~/.claude-work"})
tests/test_api.py:364:        g = client.get("/api/profiles").json()
tests/test_api.py:369:async def test_create_session_passes_pipeline_and_profile(monkeypatch):
tests/test_api.py:386:        pipeline="default", profile="work",
tests/test_api.py:389:    assert captured["pipeline"] == "default"
tests/test_api.py:390:    assert captured["profile"] == "work"
pipelines/default/prompts/roles/full-cycle.md:5:You follow a STRICT pipeline with gates. Do NOT skip phases. Do NOT freestyle.
pipelines/default/prompts/roles/full-cycle.md:8:<pipeline>
pipelines/default/prompts/roles/full-cycle.md:53:</pipeline>
app/session.py:15:from app.prompting import is_orchestrator_role
app/session.py:103:class AgentSession:
app/session.py:120:    pipeline: str = ""
app/session.py:121:    profile: str = ""
app/session.py:122:    _is_orchestrator: bool | None = field(default=None, repr=False)
app/session.py:176:    def is_orchestrator(self) -> bool:
app/session.py:177:        if self._is_orchestrator is not None:
app/session.py:178:            return self._is_orchestrator
app/session.py:179:        return is_orchestrator_role(self.role)
app/session.py:181:    @is_orchestrator.setter
app/session.py:182:    def is_orchestrator(self, value: bool) -> None:
app/session.py:183:        self._is_orchestrator = value
app/session.py:198:            from app.pipeline import get_role
app/session.py:199:            from app.db import get_profile
app/session.py:203:                rr = get_role(self.pipeline, self.role)
app/session.py:208:            if self.profile:
app/session.py:209:                p = get_profile(self.profile)
app/session.py:221:                is_orchestrator=self.is_orchestrator,
app/session.py:511:        if self.is_orchestrator or not self.on_idle or self._did_report:
app/session.py:607:        if live_pct > 90 and not self.is_orchestrator and not self._compacting:
app/session.py:663:        timeout = IDLE_TIMEOUT_ORCHESTRATOR if self.is_orchestrator else IDLE_TIMEOUT_WORKER
app/session.py:866:            if self.is_orchestrator:
app/session.py:871:                    if s.is_orchestrator and s.scope == self.scope:
app/session.py:1002:            "branch": self.branch, "is_orchestrator": self.is_orchestrator,
app/session.py:1004:            "pipeline": self.pipeline,
app/session.py:1005:            "profile": self.profile,
app/session.py:1035:            "is_orchestrator": self.is_orchestrator,
app/mcp_stdio.py:63:                       base_branch: str = "",
app/mcp_stdio.py:69:    base_branch — от какой ветки ответвить worktree воркера. Пусто ("") = авто по стратегии пайплайна (parent → от ветки родителя, иначе main); явно указанная ветка переопределяет стратегию.
app/mcp_stdio.py:80:        "base_branch": base_branch,
tests/test_db.py:33:        "is_orchestrator": False,
tests/test_db.py:433:# ── Этап 1: pipeline-колонка + round-trip ──
tests/test_db.py:436:    def test_migrate_adds_pipeline_column(self, db):
tests/test_db.py:440:        assert "pipeline" in cols
tests/test_db.py:442:    def test_save_and_load_pipeline(self, db, sample_session):
tests/test_db.py:444:        sample_session["pipeline"] = "tasks-pm"
tests/test_db.py:447:        assert row["pipeline"] == "tasks-pm"
tests/test_db.py:449:    def test_save_without_pipeline_defaults_empty(self, db, sample_session):
tests/test_db.py:451:        sample_session.pop("pipeline", None)
tests/test_db.py:454:        assert row["pipeline"] == ""
tests/test_db.py:457:# ── Этап 6, чанк 1: профили Claude (таблица profiles + sessions.profile) ──
tests/test_db.py:460:    def test_profiles_table_exists(self, db):
tests/test_db.py:466:        assert "profiles" in tables
tests/test_db.py:470:        from app.db import get_profile
tests/test_db.py:471:        p = get_profile("personal")
tests/test_db.py:476:    def test_sessions_profile_column_exists(self, db):
tests/test_db.py:480:        assert "profile" in cols
tests/test_db.py:489:                "SELECT COUNT(*) FROM profiles WHERE name='personal'"
tests/test_db.py:495:    def test_save_and_load_profile(self, db, sample_session):
tests/test_db.py:497:        sample_session["profile"] = "work"
tests/test_db.py:500:        assert row["profile"] == "work"
tests/test_db.py:502:    def test_save_without_profile_defaults_empty(self, db, sample_session):
tests/test_db.py:504:        sample_session.pop("profile", None)
tests/test_db.py:507:        assert row["profile"] == ""
tests/test_db.py:512:        from app.db import upsert_profile, list_profiles
tests/test_db.py:513:        upsert_profile("work", "/home/user/.claude-work")
tests/test_db.py:514:        names = {p["name"] for p in list_profiles()}
tests/test_db.py:519:        from app.db import upsert_profile, list_profiles
tests/test_db.py:520:        upsert_profile("zeta", "/z")
tests/test_db.py:521:        upsert_profile("alpha", "/a")
tests/test_db.py:522:        names = [p["name"] for p in list_profiles()]
tests/test_db.py:525:    def test_get_profile(self, db):
tests/test_db.py:526:        from app.db import upsert_profile, get_profile
tests/test_db.py:527:        upsert_profile("work", "/home/user/.claude-work")
tests/test_db.py:528:        p = get_profile("work")
tests/test_db.py:531:    def test_get_nonexistent_profile(self, db):
tests/test_db.py:532:        from app.db import get_profile
tests/test_db.py:533:        assert get_profile("ghost") is None
tests/test_db.py:536:        from app.db import upsert_profile, get_profile, list_profiles
tests/test_db.py:537:        upsert_profile("work", "/old/path")
tests/test_db.py:538:        before = len(list_profiles())
tests/test_db.py:539:        upsert_profile("work", "/new/path")
tests/test_db.py:540:        after = len(list_profiles())
tests/test_db.py:542:        assert get_profile("work")["config_dir"] == "/new/path"
tests/test_db.py:544:    def test_delete_profile(self, db):
tests/test_db.py:545:        from app.db import upsert_profile, delete_profile, get_profile
tests/test_db.py:546:        upsert_profile("work", "/x")
tests/test_db.py:547:        delete_profile("work")
tests/test_db.py:548:        assert get_profile("work") is None
tests/test_db.py:551:        from app.db import delete_profile, get_profile
tests/test_db.py:553:            delete_profile("personal")
tests/test_db.py:555:        assert get_profile("personal") is not None
tests/test_db.py:562:            "worktree_path": None, "branch": None, "is_orchestrator": True,
app/db.py:53:                is_orchestrator INTEGER DEFAULT 0,
app/db.py:56:                profile TEXT DEFAULT '',
app/db.py:61:            CREATE TABLE IF NOT EXISTS profiles (
app/db.py:74:            CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);
app/db.py:384:        c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
app/db.py:389:    if "pipeline" not in cols:
app/db.py:390:        c.execute("ALTER TABLE sessions ADD COLUMN pipeline TEXT DEFAULT ''")
app/db.py:391:        c.execute("UPDATE sessions SET is_orchestrator = 1 WHERE role IN ('orchestrator', 'sub-orchestrator')")
app/db.py:392:    if "profile" not in cols:
app/db.py:393:        c.execute("ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT ''")
app/db.py:400:    c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
app/db.py:420:    s.setdefault("pipeline", "")
app/db.py:421:    s.setdefault("profile", "")
app/db.py:428:                status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
app/db.py:433:                template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
app/db.py:434:                profile, owned_dirs, tg_topic)
app/db.py:436:                :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
app/db.py:441:                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
app/db.py:442:                :profile, :owned_dirs, :tg_topic)
app/db.py:471:                pipeline=excluded.pipeline,
app/db.py:472:                profile=excluded.profile,
app/db.py:541:# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──
app/db.py:543:def list_profiles() -> list[dict]:
app/db.py:547:            "SELECT name, config_dir FROM profiles ORDER BY name"
app/db.py:552:def get_profile(name: str) -> dict | None:
app/db.py:556:            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
app/db.py:561:def upsert_profile(name: str, config_dir: str) -> None:
app/db.py:565:            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
app/db.py:571:def delete_profile(name: str) -> None:
app/db.py:576:        c.execute("DELETE FROM profiles WHERE name = ?", (name,))
app/prompting.py:19:def is_orchestrator_role(role: str) -> bool:
app/prompting.py:72:        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
app/prompting.py:159:    Accepts role string or legacy bool (is_orchestrator)."""
app/templates/dashboard.html:41:                <button id="profiles-btn" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors text-slate-400" title="Profiles">🗂</button>
app/templates/dashboard.html:42:                <div id="profiles-dropdown" class="absolute right-0 top-full mt-1 w-[320px] glass glow rounded-xl p-3 z-50 hidden">
app/templates/dashboard.html:46:                    <div id="profiles-list" class="space-y-1.5 mb-2"></div>
app/templates/dashboard.html:48:                        <input id="profile-new-name" type="text" placeholder="name" class="w-full px-2 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs focus:border-indigo-500 focus:outline-none">
app/templates/dashboard.html:49:                        <input id="profile-new-dir" type="text" placeholder="config dir (пусто = ~/.claude)" class="w-full px-2 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs focus:border-indigo-500 focus:outline-none">
app/templates/dashboard.html:50:                        <button id="profile-add-btn" class="w-full py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-xs font-medium transition-colors">Add</button>
app/templates/dashboard.html:51:                        <div id="profile-error" class="text-[10px] text-red-400 hidden"></div>
app/templates/dashboard.html:88:                    <select id="orch-profile" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
app/templates/dashboard.html:93:                    <select id="orch-pipeline" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
app/manager.py:16:    is_orchestrator_role, safe_format_prompt, read_prompt,
app/manager.py:24:from app.pipeline import (
app/manager.py:27:    get_active_pipeline,
app/manager.py:30:    load_pipeline,
app/manager.py:32:    template_path,
app/manager.py:33:    validate_spawn,
app/manager.py:56:def get_active_profile(scope: str = "", parent_profile: str = "") -> str:
app/manager.py:57:    return parent_profile or ""
app/manager.py:63:                 if bool(s.get("is_orchestrator")) and s.get("scope") != exclude_scope]
app/manager.py:84:                   if not bool(s.get("is_orchestrator")) and s.get("scope") == scope]
app/manager.py:125:    if is_orchestrator_role(role):
app/manager.py:161:def _roles_catalog_from_manifest(pipeline: str, parent_role: str) -> str:
app/manager.py:168:    cfg = load_pipeline(pipeline)
app/manager.py:189:def ROLE_SYSTEM_PROMPT(pipeline: str, role: str, scope: str = "") -> str:
app/manager.py:192:    Манифест-путь (есть ``pipelines/<pipeline>/``): статика через
app/manager.py:193:    :func:`build_system_prompt` (ТОЛЬКО ``pipelines/<name>/prompts/`` — изоляция),
app/manager.py:202:        base = build_system_prompt(pipeline, role, scope)
app/manager.py:208:    rr = get_role(pipeline, role)
app/manager.py:209:    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
app/manager.py:211:        catalog = _roles_catalog_from_manifest(pipeline, role)
app/manager.py:223:def ORCHESTRATOR_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE, scope: str = "") -> str:
app/manager.py:224:    return ROLE_SYSTEM_PROMPT(pipeline, "orchestrator", scope)
app/manager.py:227:def WORKER_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE) -> str:
app/manager.py:228:    return ROLE_SYSTEM_PROMPT(pipeline, "worker")
app/manager.py:232:def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -> None:
app/manager.py:234:        rr = get_role(pipeline, role)
app/manager.py:237:    if rr is None or not rr.docs_scaffold or rr.docs_dir is None:
app/manager.py:248:        logger.warning("scaffold: путь '%s' выходит за docs_work — пропуск", rel)
app/manager.py:254:    tpl = template_path(pipeline, dd.template)
app/manager.py:394:                             repo_path: str | None = None, is_orchestrator: bool = False,
app/manager.py:396:                             base_branch: str = "",
app/manager.py:399:                             pipeline: str = "", profile: str = "",
app/manager.py:418:            role = "orchestrator" if is_orchestrator else "worker"
app/manager.py:423:        explicit_pipeline = bool(pipeline)
app/manager.py:424:        parent_pipeline = self._resolve_pipeline(parent_name, scope) if parent_name else ""
app/manager.py:425:        pipeline = pipeline or get_active_pipeline(scope, parent_pipeline=parent_pipeline)
app/manager.py:428:        # родителя (пусто для корня → env процесса). Зеркало логики pipeline.
app/manager.py:429:        explicit_profile = bool(profile)
app/manager.py:430:        parent_profile = self._resolve_profile(parent_name, scope) if parent_name else ""
app/manager.py:431:        profile = profile or get_active_profile(scope, parent_profile=parent_profile)
app/manager.py:433:        # R1: is_orchestrator из манифеста (kind), fallback на frozenset апстрима.
app/manager.py:434:        is_orch = self._role_is_orchestrator(pipeline, role)
app/manager.py:466:            if parent_name and not explicit_pipeline:
app/manager.py:468:                parent_pipeline = self._resolve_pipeline(parent_name, scope)
app/manager.py:469:                pipeline = get_active_pipeline(scope, parent_pipeline=parent_pipeline)
app/manager.py:470:                is_orch = self._role_is_orchestrator(pipeline, role)
app/manager.py:471:            if parent_name and not explicit_profile:
app/manager.py:473:                parent_profile = self._resolve_profile(parent_name, scope)
app/manager.py:474:                profile = get_active_profile(scope, parent_profile=parent_profile)
app/manager.py:479:            prompt = ROLE_SYSTEM_PROMPT(pipeline, role, scope) + ("\n\n" + system_prompt if system_prompt else "")
app/manager.py:481:            prompt = ROLE_SYSTEM_PROMPT(pipeline, role) + ("\n\n" + system_prompt if system_prompt else "")
app/manager.py:491:        # Манифест-путь — validate_spawn (fail-closed/fail-open). Нет манифеста
app/manager.py:495:            validate_spawn(pipeline, parent_role, role if explicit_role else "")
app/manager.py:507:        # Делаем ДО create_worktree, когда pipeline/role/parent_name уже определены.
app/manager.py:508:        base_branch = self._resolve_base_branch(base_branch, pipeline, role, parent_name, scope)
app/manager.py:520:            pipeline=pipeline, profile=profile,
app/manager.py:528:        session.is_orchestrator = is_orch
app/manager.py:548:                    worktree_cfg = get_worktree_config(pipeline)
app/manager.py:552:                    create_worktree, repo_path, name, scope, task_id, base_branch, worktree_cfg)
app/manager.py:557:                    _rr = get_role(pipeline, role)
app/manager.py:566:                    _scaffold_role_docs, pipeline, session.cwd, role, docs_feature)
app/manager.py:568:                logger.warning("docs scaffold failed for role '%s'", role)
app/manager.py:641:        if not session.is_orchestrator:
app/manager.py:696:            if s.scope == scope and not s.is_orchestrator and s.status.value in active:
app/manager.py:702:            if is_orchestrator_role(row.get("role", "worker")):
app/manager.py:711:            if s.scope == scope and s.is_orchestrator and s.name not in orch_names:
app/manager.py:714:            if bool(row.get("is_orchestrator")) and row["name"] not in orch_names:
app/manager.py:749:    def _resolve_pipeline(self, name: str, scope: str) -> str:
app/manager.py:753:                return s.pipeline or ""
app/manager.py:755:        return (row.get("pipeline") or "") if row else ""
app/manager.py:757:    def _resolve_profile(self, name: str, scope: str) -> str:
app/manager.py:761:                return s.profile or ""
app/manager.py:763:        return (row.get("profile") or "") if row else ""
app/manager.py:765:    def _resolve_base_branch(self, base_branch: str, pipeline: str, role: str,
app/manager.py:770:        - явно переданная ``base_branch`` важнее стратегии манифеста (B3);
app/manager.py:776:        if base_branch:
app/manager.py:777:            return base_branch
app/manager.py:779:            rr = get_role(pipeline, role)
app/manager.py:783:        if rr is None or rr.base_branch_strategy == "main":
app/manager.py:797:                "base_branch_strategy=parent, но у родителя '%s' нет ветки — fallback на main",
app/manager.py:803:    def _role_is_orchestrator(pipeline: str, role: str) -> bool:
app/manager.py:804:        """R1: is_orchestrator из kind манифеста; fallback на frozenset апстрима.
app/manager.py:806:        Манифеста нет (FileNotFoundError) или роли нет в нём → ``is_orchestrator_role``.
app/manager.py:809:            rr = get_role(pipeline, role)
app/manager.py:813:            return rr.is_orchestrator
app/manager.py:814:        return is_orchestrator_role(role)
app/manager.py:836:        role = db_row.get("role") or ("orchestrator" if db_row.get("is_orchestrator") else "worker")
app/manager.py:837:        pipeline = db_row.get("pipeline", "") or ""
app/manager.py:839:        # колонка is_orchestrator (денормализована при спавне); иначе frozenset.
app/manager.py:840:        is_orch = self._role_is_orchestrator(pipeline, role)
app/manager.py:842:            if get_role(pipeline, role) is None:
app/manager.py:843:                is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
app/manager.py:845:            is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
app/manager.py:847:        current_prompt = ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
app/manager.py:883:            pipeline=db_row.get("pipeline", ""),
app/manager.py:884:            profile=db_row.get("profile", ""),
app/manager.py:893:        session.is_orchestrator = is_orch  # R1: восстановить денормализованное поле
app/manager.py:909:                ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
app/manager.py:926:            if s.is_orchestrator and s.scope == scope:
app/manager.py:980:            if s.name == name and not s.is_orchestrator and (scope is None or s.scope == scope):
app/manager.py:1022:        # R1: используем денормализованную колонку is_orchestrator (наши PM-роли
app/manager.py:1024:        orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
app/manager.py:1025:        workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]
tests/test_workspace.py:126:    def test_base_branch_param(self, git_repo, wt_root):
tests/test_workspace.py:129:        wt = create_worktree(str(git_repo), "worker-1", "/scope", base_branch="feature/auth")
tests/test_workspace.py:143:        from app.pipeline import Symlink, Worktree
tests/test_workspace.py:157:        from app.pipeline import Worktree
tests/test_workspace.py:180:        from app.pipeline import Symlink, Worktree
tests/test_workspace.py:194:        from app.pipeline import Symlink, Worktree
tests/test_workspace.py:218:        from app.pipeline import Symlink, Worktree
tests/test_workspace.py:264:        wt = create_worktree(str(git_repo), "worker-1", "/scope", base_branch="feature/auth")
tests/test_workspace.py:277:        wt = create_worktree(str(git_repo), name, "/scope", base_branch=base)
app/main.py:26:    list_profiles, upsert_profile, delete_profile,
app/main.py:28:from app.pipeline import list_pipelines
app/main.py:109:    is_orchestrator: bool = False
app/main.py:113:    base_branch: str = ""
app/main.py:116:    pipeline: str = ""
app/main.py:117:    profile: str = ""
app/main.py:418:            is_orchestrator=req.is_orchestrator,
app/main.py:422:            base_branch=req.base_branch,
app/main.py:425:            pipeline=req.pipeline,
app/main.py:426:            profile=req.profile,
app/main.py:444:@app.get("/api/pipelines")
app/main.py:445:async def get_pipelines():
app/main.py:449:        for p in list_pipelines()
app/main.py:454:@app.get("/api/profiles")
app/main.py:455:async def get_profiles():
app/main.py:457:    return list_profiles()
app/main.py:460:@app.post("/api/profiles")
app/main.py:461:async def create_profile(req: ProfileRequest):
app/main.py:468:    при первом запуске агента. Формат ответа: ``{profiles, warning}``.
app/main.py:482:    upsert_profile(req.name, config_dir)
app/main.py:483:    return {"profiles": list_profiles(), "warning": warning}
app/main.py:486:@app.delete("/api/profiles/{name}")
app/main.py:487:async def remove_profile(name: str):
app/main.py:490:        delete_profile(name)
app/main.py:493:    return list_profiles()
app/main.py:513:    is_orch = (found.get("is_orchestrator") if isinstance(found, dict) else found.is_orchestrator) or False
app/main.py:794:    is_orch = (session.is_orchestrator if session else
app/main.py:795:               (found.get("is_orchestrator") if isinstance(found, dict) else False))
app/main.py:1238:    from app.prompting import is_orchestrator_role
app/main.py:1239:    active = [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]
app/main.py:1241:    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
app/static/js/app.js:140:    $('#orch-pipeline').addEventListener('change', populateRoleDropdown);
app/static/js/app.js:324:let _pipelineRoles = {};  // карта pipeline-name → [roles]
app/static/js/app.js:328:        const profiles = await api('/api/profiles');
app/static/js/app.js:329:        const select = $('#orch-profile');
app/static/js/app.js:331:        for (const p of profiles) {
app/static/js/app.js:339:        const def = profiles.find(p => p.name === 'personal') || profiles[0];
app/static/js/app.js:346:        const pipelines = await api('/api/pipelines');
app/static/js/app.js:347:        const select = $('#orch-pipeline');
app/static/js/app.js:349:        _pipelineRoles = {};
app/static/js/app.js:350:        for (const p of pipelines) {
app/static/js/app.js:351:            _pipelineRoles[p.name] = p.roles || [];
app/static/js/app.js:364:    const roles = _pipelineRoles[$('#orch-pipeline').value] || [];
app/static/js/app.js:631:    const profile = $('#orch-profile').value;
app/static/js/app.js:632:    const pipeline = $('#orch-pipeline').value;
app/static/js/app.js:639:        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
app/static/js/app.js:1310:    const roleKey = s.role || (s.is_orchestrator ? 'orchestrator' : 'worker');
app/static/js/app.js:3047:                    _row('Role', parsed.is_orchestrator ? '🎯 orchestrator' : '⚙️ worker');
app/static/js/app.js:5201:let _profilesDropdownOpen = false;
app/static/js/app.js:5204:    const btn = $('#profiles-btn');
app/static/js/app.js:5205:    const dropdown = $('#profiles-dropdown');
app/static/js/app.js:5209:        _profilesDropdownOpen = !_profilesDropdownOpen;
app/static/js/app.js:5210:        dropdown.classList.toggle('hidden', !_profilesDropdownOpen);
app/static/js/app.js:5211:        if (_profilesDropdownOpen) loadProfilesList();
app/static/js/app.js:5214:        if (_profilesDropdownOpen && !dropdown.contains(e.target) && e.target !== btn) {
app/static/js/app.js:5215:            _profilesDropdownOpen = false;
app/static/js/app.js:5219:    $('#profile-add-btn')?.addEventListener('click', async (e) => {
app/static/js/app.js:5221:        const name = $('#profile-new-name').value.trim();
app/static/js/app.js:5222:        const config_dir = $('#profile-new-dir').value.trim();
app/static/js/app.js:5223:        const errEl = $('#profile-error');
app/static/js/app.js:5227:            const res = await api('/api/profiles', { method: 'POST', body: JSON.stringify({ name, config_dir }) });
app/static/js/app.js:5228:            $('#profile-new-name').value = '';
app/static/js/app.js:5229:            $('#profile-new-dir').value = '';
app/static/js/app.js:5245:        const profiles = await api('/api/profiles');
app/static/js/app.js:5246:        const list = $('#profiles-list');
app/static/js/app.js:5249:        if (!profiles.length) {
app/static/js/app.js:5250:            list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No profiles.</div>';
app/static/js/app.js:5253:        for (const p of profiles) {
app/static/js/app.js:5262:                ${isPersonal ? '' : `<button class="profile-del-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-red-900/60 rounded text-slate-400 hover:text-red-400 shrink-0" data-name="${escHtml(p.name)}" title="Delete">✕</button>`}
app/static/js/app.js:5266:        list.querySelectorAll('.profile-del-btn').forEach(b => {
app/static/js/app.js:5269:                const errEl = $('#profile-error');
app/static/js/app.js:5273:                    await api(`/api/profiles/${encodeURIComponent(b.dataset.name)}`, { method: 'DELETE' });
tests/test_manager.py:30:def _isolate_pipelines_dir(tmp_path, monkeypatch):
tests/test_manager.py:33:    Делает модуль детерминированным независимо от реального ``pipelines/``
tests/test_manager.py:34:    (Stage 4 параллельно создаёт ``pipelines/default/``). Тесты, которым нужен
tests/test_manager.py:35:    манифест, переопределяют PIPELINES_DIR своей фикстурой (``pipeline_dir``/
tests/test_manager.py:38:    import app.pipeline as pl
tests/test_manager.py:39:    empty = tmp_path / "_no_pipelines_default"
tests/test_manager.py:42:    pl.load_pipeline.cache_clear()
tests/test_manager.py:44:    pl.load_pipeline.cache_clear()
tests/test_manager.py:137:                use_worktree=True, repo_path=str(repo), base_branch="feature/auth",
tests/test_manager.py:179:        rr = MagicMock(skills="all", is_orchestrator=False)
tests/test_manager.py:185:        rr = MagicMock(skills=["foo", "bar"], is_orchestrator=False)
tests/test_manager.py:198:    """DESIGN §10: резолв base_branch по стратегии манифеста (B3).
tests/test_manager.py:200:    Тестируем ``_resolve_base_branch`` напрямую на инстансе manager, мокая
tests/test_manager.py:214:        rr = MagicMock(base_branch_strategy="main")
tests/test_manager.py:216:            out = mgr._resolve_base_branch("", "default", "pm-glava", "", "/s")
tests/test_manager.py:220:        rr = MagicMock(base_branch_strategy="parent")
tests/test_manager.py:223:            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
tests/test_manager.py:228:        rr = MagicMock(base_branch_strategy="parent")
tests/test_manager.py:231:            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
tests/test_manager.py:237:        rr = MagicMock(base_branch_strategy="parent")
tests/test_manager.py:240:            out = mgr._resolve_base_branch("dev", "tasks-pm", "coder", "pm", "/s")
tests/test_manager.py:247:            out = mgr._resolve_base_branch("", "nope", "coder", "pm", "/s")
tests/test_manager.py:318:            "is_orchestrator": True, "color": "#818cf8",
tests/test_manager.py:344:            "is_orchestrator": True, "color": "#818cf8",
tests/test_manager.py:372:            "is_orchestrator": True, "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
tests/test_manager.py:394:        import app.pipeline as pl
tests/test_manager.py:395:        empty_pipelines = tmp_path / "no_pipelines"
tests/test_manager.py:396:        empty_pipelines.mkdir()
tests/test_manager.py:397:        monkeypatch.setattr(pl, "PIPELINES_DIR", empty_pipelines)
tests/test_manager.py:398:        pl.load_pipeline.cache_clear()
tests/test_manager.py:440:            "is_orchestrator": False, "color": "#fff",
tests/test_manager.py:461:            "is_orchestrator": False, "color": "#fff",
tests/test_manager.py:482:            "is_orchestrator": False, "color": "#fff",
tests/test_manager.py:583:            "is_orchestrator": False, "color": "#fff",
tests/test_manager.py:595:# ── Stage 3: loader integration (pipeline manifest) ─────────────────────────
tests/test_manager.py:600:description: Test pipeline
tests/test_manager.py:607:    orchestrator: [base.md, "roles/{role}.md", _pipeline.md]
tests/test_manager.py:618:def _write_pipeline(root, name, manifest_text, prompts=None):
tests/test_manager.py:619:    """Создать pipelines/<name>/ с pipeline.yaml + prompts/* в tmp-корне root."""
tests/test_manager.py:622:    (pdir / "pipeline.yaml").write_text(manifest_text)
tests/test_manager.py:632:def pipeline_dir(tmp_path, monkeypatch):
tests/test_manager.py:633:    """tmp pipelines/ с манифестом testpipe + базовыми слоями промптов.
tests/test_manager.py:635:    Монкипатчит ``app.pipeline.PIPELINES_DIR`` и чистит lru_cache загрузчика,
tests/test_manager.py:638:    import app.pipeline as pl
tests/test_manager.py:639:    root = tmp_path / "pipelines"
tests/test_manager.py:641:    _write_pipeline(root, "testpipe", _MINI_MANIFEST, prompts={
tests/test_manager.py:648:        "_pipeline.md": "PIPELINE-LAYER",
tests/test_manager.py:651:    pl.load_pipeline.cache_clear()
tests/test_manager.py:653:    pl.load_pipeline.cache_clear()
tests/test_manager.py:657:    """Зафиксировать: при отсутствии манифеста ROLE_SYSTEM_PROMPT(pipeline, role)
tests/test_manager.py:690:        """Нет манифеста (FileNotFoundError) → ROLE_SYSTEM_PROMPT(pipeline, ...) ==
tests/test_manager.py:692:        import app.pipeline as pl
tests/test_manager.py:693:        pl.load_pipeline.cache_clear()
tests/test_manager.py:703:    def test_static_layers_from_manifest(self, pipeline_dir, db):
tests/test_manager.py:704:        """ROLE_SYSTEM_PROMPT берёт статику из pipelines/<name>/prompts/ (изоляция)."""
tests/test_manager.py:709:        assert "PIPELINE-LAYER" in out  # coder — orchestrator → _pipeline.md есть
tests/test_manager.py:711:    def test_worker_role_no_pipeline_layer(self, pipeline_dir, db):
tests/test_manager.py:712:        """Воркер (kind:worker) НЕ получает _pipeline.md."""
tests/test_manager.py:719:    def test_orchestrator_gets_filtered_catalog(self, pipeline_dir, db):
tests/test_manager.py:730:    def test_unknown_role_falls_back_to_upstream(self, pipeline_dir, tmp_path,
tests/test_manager.py:754:    def test_pm_glava_shows_only_pm_fichi_and_secretary(self, pipeline_dir):
tests/test_manager.py:762:    def test_sorted_by_order(self, pipeline_dir):
tests/test_manager.py:770:        import app.pipeline as pl
tests/test_manager.py:771:        root = tmp_path / "pipelines"
tests/test_manager.py:780:        _write_pipeline(root, "starpipe", manifest, prompts={"base.md": "B"})
tests/test_manager.py:782:        pl.load_pipeline.cache_clear()
tests/test_manager.py:785:        pl.load_pipeline.cache_clear()
tests/test_manager.py:793:    def test_app_prompts_not_read_in_manifest_path(self, pipeline_dir, db, monkeypatch):
tests/test_manager.py:799:        assert "BASE-LAYER" in out  # из pipelines/testpipe/prompts/, не из app/prompts/
tests/test_manager.py:805:    async def test_forbidden_spawn_blocked_before_side_effect(self, mgr, pipeline_dir, tmp_path):
tests/test_manager.py:824:            "is_orchestrator": True, "color": "",
tests/test_manager.py:826:            "role": "pm-glava", "pipeline": "testpipe",
tests/test_manager.py:841:                        use_worktree=True, repo_path=str(repo), pipeline="testpipe",
tests/test_manager.py:846:    async def test_allowed_spawn_passes(self, mgr, pipeline_dir):
tests/test_manager.py:854:            "is_orchestrator": True, "color": "",
tests/test_manager.py:856:            "role": "pm-glava", "pipeline": "testpipe",
tests/test_manager.py:861:                role="secretary", parent_name="glava", pipeline="testpipe",
tests/test_manager.py:867:        """Нет манифеста → validate_spawn кидает FileNotFoundError → fallback _role_can_spawn.
tests/test_manager.py:873:        import app.pipeline as pl
tests/test_manager.py:875:        # создать pipelines/default/) → load_pipeline FileNotFoundError → fallback.
tests/test_manager.py:877:        empty = Path(tempfile.mkdtemp()) / "no_pipelines"
tests/test_manager.py:880:        pl.load_pipeline.cache_clear()
tests/test_manager.py:886:            "is_orchestrator": False, "color": "#fff",
tests/test_manager.py:892:        pl.load_pipeline.cache_clear()
tests/test_manager.py:913:    async def test_is_orch_from_manifest_kind(self, mgr, pipeline_dir):
tests/test_manager.py:914:        """coder (kind:orchestrator в манифесте) → session.is_orchestrator=True,
tests/test_manager.py:920:                role="coder", is_orchestrator=True, pipeline="testpipe",
tests/test_manager.py:922:        assert session.is_orchestrator is True
tests/test_manager.py:923:        assert session.pipeline == "testpipe"
tests/test_manager.py:926:    async def test_worker_kind_is_not_orchestrator(self, mgr, pipeline_dir):
tests/test_manager.py:927:        """secretary (kind:worker) → is_orchestrator=False даже при is_orchestrator=True arg."""
tests/test_manager.py:934:            "is_orchestrator": True, "color": "",
tests/test_manager.py:936:            "role": "pm-glava", "pipeline": "testpipe",
tests/test_manager.py:941:                role="secretary", parent_name="glava", pipeline="testpipe",
tests/test_manager.py:943:        assert session.is_orchestrator is False
tests/test_manager.py:947:        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
tests/test_manager.py:952:                role="orchestrator", is_orchestrator=True,
tests/test_manager.py:954:        assert session.is_orchestrator is True
tests/test_manager.py:959:    async def test_child_inherits_parent_pipeline(self, mgr, pipeline_dir):
tests/test_manager.py:960:        """Воркер без явного pipeline наследует пайплайн родителя."""
tests/test_manager.py:967:            "is_orchestrator": True, "color": "",
tests/test_manager.py:969:            "role": "coder", "pipeline": "testpipe",
tests/test_manager.py:978:        assert session.pipeline == "testpipe"
tests/test_manager.py:981:    async def test_root_defaults_to_default_pipeline(self, mgr, monkeypatch):
tests/test_manager.py:982:        """Корневой оркестратор без parent и без pipeline → DEFAULT_PIPELINE."""
tests/test_manager.py:984:        from app.pipeline import DEFAULT_PIPELINE
tests/test_manager.py:988:                role="orchestrator", is_orchestrator=True,
tests/test_manager.py:990:        assert session.pipeline == DEFAULT_PIPELINE
tests/test_manager.py:993:    async def test_auto_found_parent_pipeline_inherited(self, mgr, pipeline_dir):
tests/test_manager.py:998:            # активный оркестратор coder в scope с pipeline=testpipe
tests/test_manager.py:1001:                role="coder", is_orchestrator=True, pipeline="testpipe",
tests/test_manager.py:1007:        assert worker.pipeline == "testpipe"
tests/test_manager.py:1019:    async def test_root_with_profile_persists(self, mgr):
tests/test_manager.py:1020:        """Корневой оркестратор с явным profile → session.profile и персист в БД."""
tests/test_manager.py:1026:                role="orchestrator", is_orchestrator=True, profile="work",
tests/test_manager.py:1028:        assert session.profile == "work"
tests/test_manager.py:1031:        assert row["profile"] == "work"
tests/test_manager.py:1034:    async def test_child_inherits_parent_profile(self, mgr):
tests/test_manager.py:1035:        """Ребёнок без явного profile наследует профиль родителя."""
tests/test_manager.py:1042:            "is_orchestrator": True, "color": "",
tests/test_manager.py:1044:            "role": "orchestrator", "pipeline": "", "profile": "work",
tests/test_manager.py:1051:        assert session.profile == "work"
tests/test_manager.py:1054:    async def test_explicit_profile_overrides_inheritance(self, mgr):
tests/test_manager.py:1055:        """Явный profile у ребёнка переопределяет наследование от родителя."""
tests/test_manager.py:1062:            "is_orchestrator": True, "color": "",
tests/test_manager.py:1064:            "role": "orchestrator", "pipeline": "", "profile": "work",
tests/test_manager.py:1069:                parent_name="boss2", profile="personal",
tests/test_manager.py:1071:        assert session.profile == "personal"
tests/test_manager.py:1074:    async def test_no_profile_anywhere_is_empty(self, mgr):
tests/test_manager.py:1075:        """Профиля нет ни явно, ни у родителя → session.profile == '' (env процесса)."""
tests/test_manager.py:1080:                role="orchestrator", is_orchestrator=True,
tests/test_manager.py:1082:        assert session.profile == ""
tests/test_manager.py:1085:    async def test_auto_found_parent_profile_inherited(self, mgr):
tests/test_manager.py:1092:                role="orchestrator", is_orchestrator=True, profile="work",
tests/test_manager.py:1097:        assert worker.profile == "work"
tests/test_manager.py:1144:                is_orchestrator=True,
tests/test_manager.py:1272:                model="claude-opus-4-8", is_orchestrator=True,
tests/test_manager.py:1281:            "worktree_path": None, "branch": None, "is_orchestrator": False,
tests/test_manager.py:1299:                model="claude-opus-4-8", is_orchestrator=True,
tests/test_manager.py:1307:            "worktree_path": None, "branch": None, "is_orchestrator": False,
app/backend_claude.py:42:def _make_auto_approve(is_orchestrator: bool = False):
app/backend_claude.py:43:    blocked = _ORCH_BLOCKED_TOOLS if is_orchestrator else _BLOCKED_TOOLS
app/backend_claude.py:54:def _disallowed_tools(is_orchestrator: bool) -> list[str]:
app/backend_claude.py:60:    if is_orchestrator:
app/backend_claude.py:87:                 is_orchestrator: bool = False,
app/backend_claude.py:98:        self._is_orchestrator = is_orchestrator
app/backend_claude.py:121:        # Профиль: переопределяем CLAUDE_CONFIG_DIR подпроцесса (SDK строит
app/backend_claude.py:125:            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)
app/backend_claude.py:128:            permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
app/backend_claude.py:129:            disallowed_tools=_disallowed_tools(self._is_orchestrator),
app/skills/orchestra/SKILL.md:78:- `is_orchestrator` — true/false
app/skills/orchestra/SKILL.md:122:- `is_orchestrator` — является ли оркестратором (default: false)
app/prompts/roles/worker.md:10:  General-purpose worker. Implements tasks directly, no pipeline gates.
app/pipeline.py:3:Источник истины о ролях — единый манифест ``pipelines/<name>/pipeline.yaml``
app/pipeline.py:5:``pipelines/<name>/`` — ``app/prompts/`` игнорируется (полная изоляция промптов).
app/pipeline.py:8:загрузке: ``load_pipeline`` валидирует и кэширует сырой манифест, ``resolve_role``
app/pipeline.py:25:# Корень с пайплайнами: <repo>/pipelines/. default и tasks-pm — оба в гите.
app/pipeline.py:26:PIPELINES_DIR = Path(__file__).parent.parent / "pipelines"
app/pipeline.py:45:    Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
app/pipeline.py:103:        # B2: путь/шаблон не должны выходить за pipelines/<name>/ (abs или '..').
app/pipeline.py:120:    Пути относительны ``pipelines/<name>/prompts/``.
app/pipeline.py:124:        default_factory=lambda: ["base.md", "roles/{role}.md", "_pipeline.md"])
app/pipeline.py:131:        # B2: слои не должны выходить за pipelines/<name>/prompts/. Плейсхолдер
app/pipeline.py:148:    base_branch_strategy: BranchStrategy = "parent"
app/pipeline.py:149:    docs_scaffold: bool = True
app/pipeline.py:177:    base_branch_strategy: BranchStrategy | None = None
app/pipeline.py:179:    docs_scaffold: bool | None = None
app/pipeline.py:222:                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
app/pipeline.py:234:    pipeline: str
app/pipeline.py:244:    base_branch_strategy: BranchStrategy
app/pipeline.py:246:    docs_scaffold: bool
app/pipeline.py:255:    def is_orchestrator(self) -> bool:
app/pipeline.py:262:def load_pipeline(name: str) -> PipelineConfig:
app/pipeline.py:263:    """Прочитать ``pipelines/<name>/pipeline.yaml``, провалидировать, кэшировать.
app/pipeline.py:270:    path = PIPELINES_DIR / name / "pipeline.yaml"
app/pipeline.py:272:        raise FileNotFoundError(f"pipeline '{name}' not found at {path}")
app/pipeline.py:276:        raise ValueError(f"pipeline name '{cfg.name}' != dir '{name}'")
app/pipeline.py:280:def get_worktree_config(pipeline_name: str) -> Worktree:
app/pipeline.py:283:    Это pipeline-level настройка (симлинки + copies), общая для всех ролей —
app/pipeline.py:289:    return load_pipeline(pipeline_name).defaults.worktree
app/pipeline.py:292:def list_pipelines() -> list[dict]:
app/pipeline.py:293:    """Скан ``pipelines/`` (включая gitignored). Для UI-дропдауна.
app/pipeline.py:302:        if not d.is_dir() or not (d / "pipeline.yaml").is_file():
app/pipeline.py:305:            cfg = load_pipeline(d.name)
app/pipeline.py:330:def resolve_role(pipeline: PipelineConfig, role: str) -> ResolvedRole:
app/pipeline.py:337:    :raises KeyError: если ``role`` нет в ``pipeline.roles`` (ловит вызывающий).
app/pipeline.py:339:    spec = pipeline.roles[role]
app/pipeline.py:340:    d = pipeline.defaults
app/pipeline.py:344:        name=role, pipeline=pipeline.name, kind=spec.kind, label=spec.label,
app/pipeline.py:351:        base_branch_strategy=_merge_scalar(d.base_branch_strategy, spec.base_branch_strategy),
app/pipeline.py:353:        docs_scaffold=_merge_scalar(d.docs_scaffold, spec.docs_scaffold),
app/pipeline.py:360:def get_role(pipeline_name: str, role: str) -> ResolvedRole | None:
app/pipeline.py:362:    cfg = load_pipeline(pipeline_name)
app/pipeline.py:366:def known_roles(pipeline_name: str) -> list[str]:
app/pipeline.py:368:    return sorted(load_pipeline(pipeline_name).roles)
app/pipeline.py:371:# ── Резолв путей промпта (полная изоляция: только pipelines/<name>/prompts/) ─
app/pipeline.py:373:def prompt_path(pipeline_name: str, rel: str) -> Path:
app/pipeline.py:374:    """Путь к слою промпта. ВСЕГДА внутри ``pipelines/<name>/prompts/``.
app/pipeline.py:376:    ``rel`` — элемент prompt_layers (``base.md``, ``roles/coder.md``, ``_pipeline.md``).
app/pipeline.py:379:    return PIPELINES_DIR / pipeline_name / "prompts" / rel
app/pipeline.py:382:def template_path(pipeline_name: str, template: str) -> Path:
app/pipeline.py:383:    """Путь к шаблону doc-папки внутри ``pipelines/<name>/templates/``."""
app/pipeline.py:384:    return PIPELINES_DIR / pipeline_name / "templates" / template
app/pipeline.py:387:def build_system_prompt(pipeline_name: str, role: str, scope: str = "") -> str:
app/pipeline.py:390:    Каждый слой читается из ``pipelines/<name>/prompts/<layer>`` через
app/pipeline.py:403:    rr = resolve_role(load_pipeline(pipeline_name), role)
app/pipeline.py:406:        p = prompt_path(pipeline_name, layer)
app/pipeline.py:410:        mp = prompt_path(pipeline_name, f"modules/{m}.md")
app/pipeline.py:418:                "pipeline '%s' role '%s': module '%s' not found at %s — skipped",
app/pipeline.py:419:                pipeline_name, role, m, mp)
app/pipeline.py:425:def get_active_pipeline(scope: str = "", parent_pipeline: str = "") -> str:
app/pipeline.py:428:    1) ``parent_pipeline`` (от родителя при спавне) — главный источник: дети
app/pipeline.py:433:    логика (чтение колонки sessions.pipeline) — Этап 7; здесь зафиксирована
app/pipeline.py:436:    if parent_pipeline:
app/pipeline.py:437:        return parent_pipeline
app/pipeline.py:443:def validate_spawn(pipeline_name: str, parent_role: str | None, child_role: str) -> None:
app/pipeline.py:458:    cfg = load_pipeline(pipeline_name)
app/pipeline.py:467:                f"unknown parent role '{parent_role}' in pipeline '{pipeline_name}'. "
app/pipeline.py:468:                f"known={known_roles(pipeline_name)}")
app/pipeline.py:479:                f"unknown role '{child_role}' in pipeline '{pipeline_name}'. "
app/pipeline.py:480:                f"known={known_roles(pipeline_name)}")
app/prompts/roles/full-cycle.md:11:  Strict 3-phase pipeline with 2 orchestrator approval gates.
app/prompts/roles/full-cycle.md:19:You follow a STRICT pipeline with gates. Do NOT skip phases. Do NOT freestyle.
app/prompts/roles/full-cycle.md:22:<pipeline>
app/prompts/roles/full-cycle.md:67:</pipeline>
app/workspace.py:19:    # циклической зависимости (pipeline ← workspace).
app/workspace.py:20:    from app.pipeline import Symlink, Worktree as WorktreeCfg
app/workspace.py:108:def create_worktree(repo_path: str, name: str, scope: str, task_id: str = "",
app/workspace.py:109:                    base_branch: str = "main",
app/workspace.py:112:    if not base_branch:
app/workspace.py:113:        base_branch = "main"
app/workspace.py:156:            ["git", "worktree", "add", str(wt_path), "-b", branch, base_branch],
app/workspace.py:735:def parse_owned_dirs(raw) -> list[str]:
app/static/css/vendor/purify.min.js:2:!function(e,t){"object"==typeof exports&&"undefined"!=typeof module?module.exports=t():"function"==typeof define&&define.amd?define(t):(e="undefined"!=typeof globalThis?globalThis:e||self).DOMPurify=t()}(this,function(){"use strict";const{entries:e,setPrototypeOf:t,isFrozen:n,getPrototypeOf:o,getOwnPropertyDescriptor:r}=Object;let{freeze:i,seal:a,create:l}=Object,{apply:c,construct:s}="undefined"!=typeof Reflect&&Reflect;i||(i=function(e){return e}),a||(a=function(e){return e}),c||(c=function(e,t){for(var n=arguments.length,o=new Array(n>2?n-2:0),r=2;r<n;r++)o[r-2]=arguments[r];return e.apply(t,o)}),s||(s=function(e){for(var t=arguments.length,n=new Array(t>1?t-1:0),o=1;o<t;o++)n[o-1]=arguments[o];return new e(...n)});const u=L(Array.prototype.forEach),m=L(Array.prototype.lastIndexOf),f=L(Array.prototype.pop),p=L(Array.prototype.push),d=L(Array.prototype.splice),h=Array.isArray,T=L(String.prototype.toLowerCase),g=L(String.prototype.toString),y=L(String.prototype.match),A=L(String.prototype.replace),E=L(String.prototype.indexOf),_=L(String.prototype.trim),S=L(Number.prototype.toString),b=L(Boolean.prototype.toString),N="undefined"==typeof BigInt?null:L(BigInt.prototype.toString),R="undefined"==typeof Symbol?null:L(Symbol.prototype.toString),D=L(Object.prototype.hasOwnProperty),O=L(Object.prototype.toString),I=L(RegExp.prototype.test),w=(C=TypeError,function(){for(var e=arguments.length,t=new Array(e),n=0;n<e;n++)t[n]=arguments[n];return s(C,t)});var C;function L(e){return function(t){t instanceof RegExp&&(t.lastIndex=0);for(var n=arguments.length,o=new Array(n>1?n-1:0),r=1;r<n;r++)o[r-1]=arguments[r];return c(e,t,o)}}function k(e,o){let r=arguments.length>2&&void 0!==arguments[2]?arguments[2]:T;if(t&&t(e,null),!h(o))return e;let i=o.length;for(;i--;){let t=o[i];if("string"==typeof t){const e=r(t);e!==t&&(n(o)||(o[i]=e),t=e)}e[t]=!0}return e}function x(e){for(let t=0;t<e.length;t++){D(e,t)||(e[t]=null)}return e}function v(t){const n=l(null);for(const[o,r]of e(t)){D(t,o)&&(h(r)?n[o]=x(r):r&&"object"==typeof r&&r.constructor===Object?n[o]=v(r):n[o]=r)}return n}function M(e,t){for(;null!==e;){const n=r(e,t);if(n){if(n.get)return L(n.get);if("function"==typeof n.value)return L(n.value)}e=o(e)}return function(){return null}}const P=i(["a","abbr","acronym","address","area","article","aside","audio","b","bdi","bdo","big","blink","blockquote","body","br","button","canvas","caption","center","cite","code","col","colgroup","content","data","datalist","dd","decorator","del","details","dfn","dialog","dir","div","dl","dt","element","em","fieldset","figcaption","figure","font","footer","form","h1","h2","h3","h4","h5","h6","head","header","hgroup","hr","html","i","img","input","ins","kbd","label","legend","li","main","map","mark","marquee","menu","menuitem","meter","nav","nobr","ol","optgroup","option","output","p","picture","pre","progress","q","rp","rt","ruby","s","samp","search","section","select","shadow","slot","small","source","spacer","span","strike","strong","style","sub","summary","sup","table","tbody","td","template","textarea","tfoot","th","thead","time","tr","track","tt","u","ul","var","video","wbr"]),U=i(["svg","a","altglyph","altglyphdef","altglyphitem","animatecolor","animatemotion","animatetransform","circle","clippath","defs","desc","ellipse","enterkeyhint","exportparts","filter","font","g","glyph","glyphref","hkern","image","inputmode","line","lineargradient","marker","mask","metadata","mpath","part","path","pattern","polygon","polyline","radialgradient","rect","stop","style","switch","symbol","text","textpath","title","tref","tspan","view","vkern"]),z=i(["feBlend","feColorMatrix","feComponentTransfer","feComposite","feConvolveMatrix","feDiffuseLighting","feDisplacementMap","feDistantLight","feDropShadow","feFlood","feFuncA","feFuncB","feFuncG","feFuncR","feGaussianBlur","feImage","feMerge","feMergeNode","feMorphology","feOffset","fePointLight","feSpecularLighting","feSpotLight","feTile","feTurbulence"]),F=i(["animate","color-profile","cursor","discard","font-face","font-face-format","font-face-name","font-face-src","font-face-uri","foreignobject","hatch","hatchpath","mesh","meshgradient","meshpatch","meshrow","missing-glyph","script","set","solidcolor","unknown","use"]),H=i(["math","menclose","merror","mfenced","mfrac","mglyph","mi","mlabeledtr","mmultiscripts","mn","mo","mover","mpadded","mphantom","mroot","mrow","ms","mspace","msqrt","mstyle","msub","msup","msubsup","mtable","mtd","mtext","mtr","munder","munderover","mprescripts"]),B=i(["maction","maligngroup","malignmark","mlongdiv","mscarries","mscarry","msgroup","mstack","msline","msrow","semantics","annotation","annotation-xml","mprescripts","none"]),G=i(["#text"]),W=i(["accept","action","align","alt","autocapitalize","autocomplete","autopictureinpicture","autoplay","background","bgcolor","border","capture","cellpadding","cellspacing","checked","cite","class","clear","color","cols","colspan","controls","controlslist","coords","crossorigin","datetime","decoding","default","dir","disabled","disablepictureinpicture","disableremoteplayback","download","draggable","enctype","enterkeyhint","exportparts","face","for","headers","height","hidden","high","href","hreflang","id","inert","inputmode","integrity","ismap","kind","label","lang","list","loading","loop","low","max","maxlength","media","method","min","minlength","multiple","muted","name","nonce","noshade","novalidate","nowrap","open","optimum","part","pattern","placeholder","playsinline","popover","popovertarget","popovertargetaction","poster","preload","pubdate","radiogroup","readonly","rel","required","rev","reversed","role","rows","rowspan","spellcheck","scope","selected","shape","size","sizes","slot","span","srclang","start","src","srcset","step","style","summary","tabindex","title","translate","type","usemap","valign","value","width","wrap","xmlns"]),j=i(["accent-height","accumulate","additive","alignment-baseline","amplitude","ascent","attributename","attributetype","azimuth","basefrequency","baseline-shift","begin","bias","by","class","clip","clippathunits","clip-path","clip-rule","color","color-interpolation","color-interpolation-filters","color-profile","color-rendering","cx","cy","d","dx","dy","diffuseconstant","direction","display","divisor","dur","edgemode","elevation","end","exponent","fill","fill-opacity","fill-rule","filter","filterunits","flood-color","flood-opacity","font-family","font-size","font-size-adjust","font-stretch","font-style","font-variant","font-weight","fx","fy","g1","g2","glyph-name","glyphref","gradientunits","gradienttransform","height","href","id","image-rendering","in","in2","intercept","k","k1","k2","k3","k4","kerning","keypoints","keysplines","keytimes","lang","lengthadjust","letter-spacing","kernelmatrix","kernelunitlength","lighting-color","local","marker-end","marker-mid","marker-start","markerheight","markerunits","markerwidth","maskcontentunits","maskunits","max","mask","mask-type","media","method","mode","min","name","numoctaves","offset","operator","opacity","order","orient","orientation","origin","overflow","paint-order","path","pathlength","patterncontentunits","patterntransform","patternunits","points","preservealpha","preserveaspectratio","primitiveunits","r","rx","ry","radius","refx","refy","repeatcount","repeatdur","restart","result","rotate","scale","seed","shape-rendering","slope","specularconstant","specularexponent","spreadmethod","startoffset","stddeviation","stitchtiles","stop-color","stop-opacity","stroke-dasharray","stroke-dashoffset","stroke-linecap","stroke-linejoin","stroke-miterlimit","stroke-opacity","stroke","stroke-width","style","surfacescale","systemlanguage","tabindex","tablevalues","targetx","targety","transform","transform-origin","text-anchor","text-decoration","text-rendering","textlength","type","u1","u2","unicode","values","viewbox","visibility","version","vert-adv-y","vert-origin-x","vert-origin-y","width","word-spacing","wrap","writing-mode","xchannelselector","ychannelselector","x","x1","x2","xmlns","y","y1","y2","z","zoomandpan"]),Y=i(["accent","accentunder","align","bevelled","close","columnalign","columnlines","columnspacing","columnspan","denomalign","depth","dir","display","displaystyle","encoding","fence","frame","height","href","id","largeop","length","linethickness","lquote","lspace","mathbackground","mathcolor","mathsize","mathvariant","maxsize","minsize","movablelimits","notation","numalign","open","rowalign","rowlines","rowspacing","rowspan","rspace","rquote","scriptlevel","scriptminsize","scriptsizemultiplier","selection","separator","separators","stretchy","subscriptshift","supscriptshift","symmetric","voffset","width","xmlns"]),X=i(["xlink:href","xml:id","xlink:title","xml:space","xmlns:xlink"]),q=a(/\{\{[\w\W]*|[\w\W]*\}\}/gm),$=a(/<%[\w\W]*|[\w\W]*%>/gm),K=a(/\$\{[\w\W]*/gm),V=a(/^data-[\-\w.\u00B7-\uFFFF]+$/),Z=a(/^aria-[\-\w]+$/),J=a(/^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|matrix):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i),Q=a(/^(?:\w+script|data):/i),ee=a(/[\u0000-\u0020\u00A0\u1680\u180E\u2000-\u2029\u205F\u3000]/g),te=a(/^html$/i),ne=a(/^[a-z][.\w]*(-[.\w]+)+$/i);var oe=Object.freeze({__proto__:null,ARIA_ATTR:Z,ATTR_WHITESPACE:ee,CUSTOM_ELEMENT:ne,DATA_ATTR:V,DOCTYPE_NAME:te,ERB_EXPR:$,IS_ALLOWED_URI:J,IS_SCRIPT_OR_DATA:Q,MUSTACHE_EXPR:q,TMPLIT_EXPR:K});const re=1,ie=3,ae=7,le=8,ce=9,se=function(){return"undefined"==typeof window?null:window};var ue=function t(){let n=arguments.length>0&&void 0!==arguments[0]?arguments[0]:se();const o=e=>t(e);if(o.version="3.4.2",o.removed=[],!n||!n.document||n.document.nodeType!==ce||!n.Element)return o.isSupported=!1,o;let{document:r}=n;const a=r,c=a.currentScript,{DocumentFragment:s,HTMLTemplateElement:C,Node:L,Element:x,NodeFilter:q,NamedNodeMap:$=n.NamedNodeMap||n.MozNamedAttrMap,HTMLFormElement:K,DOMParser:V,trustedTypes:Z}=n,Q=x.prototype,ee=M(Q,"cloneNode"),ne=M(Q,"remove"),ue=M(Q,"nextSibling"),me=M(Q,"childNodes"),fe=M(Q,"parentNode");if("function"==typeof C){const e=r.createElement("template");e.content&&e.content.ownerDocument&&(r=e.content.ownerDocument)}let pe,de="";const{implementation:he,createNodeIterator:Te,createDocumentFragment:ge,getElementsByTagName:ye}=r,{importNode:Ae}=a;let Ee={afterSanitizeAttributes:[],afterSanitizeElements:[],afterSanitizeShadowDOM:[],beforeSanitizeAttributes:[],beforeSanitizeElements:[],beforeSanitizeShadowDOM:[],uponSanitizeAttribute:[],uponSanitizeElement:[],uponSanitizeShadowNode:[]};o.isSupported="function"==typeof e&&"function"==typeof fe&&he&&void 0!==he.createHTMLDocument;const{MUSTACHE_EXPR:_e,ERB_EXPR:Se,TMPLIT_EXPR:be,DATA_ATTR:Ne,ARIA_ATTR:Re,IS_SCRIPT_OR_DATA:De,ATTR_WHITESPACE:Oe,CUSTOM_ELEMENT:Ie}=oe;let{IS_ALLOWED_URI:we}=oe,Ce=null;const Le=k({},[...P,...U,...z,...H,...G]);let ke=null;const xe=k({},[...W,...j,...Y,...X]);let ve=Object.seal(l(null,{tagNameCheck:{writable:!0,configurable:!1,enumerable:!0,value:null},attributeNameCheck:{writable:!0,configurable:!1,enumerable:!0,value:null},allowCustomizedBuiltInElements:{writable:!0,configurable:!1,enumerable:!0,value:!1}})),Me=null,Pe=null;const Ue=Object.seal(l(null,{tagCheck:{writable:!0,configurable:!1,enumerable:!0,value:null},attributeCheck:{writable:!0,configurable:!1,enumerable:!0,value:null}}));let ze=!0,Fe=!0,He=!1,Be=!0,Ge=!1,We=!0,je=!1,Ye=!1,Xe=!1,qe=!1,$e=!1,Ke=!1,Ve=!0,Ze=!1;const Je="user-content-";let Qe=!0,et=!1,tt={},nt=null;const ot=k({},["annotation-xml","audio","colgroup","desc","foreignobject","head","iframe","math","mi","mn","mo","ms","mtext","noembed","noframes","noscript","plaintext","script","style","svg","template","thead","title","video","xmp"]);let rt=null;const it=k({},["audio","video","img","source","image","track"]);let at=null;const lt=k({},["alt","class","for","id","label","name","pattern","placeholder","role","summary","title","value","style","xmlns"]),ct="http://www.w3.org/1998/Math/MathML",st="http://www.w3.org/2000/svg",ut="http://www.w3.org/1999/xhtml";let mt=ut,ft=!1,pt=null;const dt=k({},[ct,st,ut],g);let ht=k({},["mi","mo","mn","ms","mtext"]),Tt=k({},["annotation-xml"]);const gt=k({},["title","style","font","a","script"]);let yt=null;const At=["application/xhtml+xml","text/html"];let Et=null,_t=null;const St=r.createElement("form"),bt=function(e){return e instanceof RegExp||e instanceof Function},Nt=function(){let e=arguments.length>0&&void 0!==arguments[0]?arguments[0]:{};if(_t&&_t===e)return;e&&"object"==typeof e||(e={}),e=v(e),yt=-1===At.indexOf(e.PARSER_MEDIA_TYPE)?"text/html":e.PARSER_MEDIA_TYPE,Et="application/xhtml+xml"===yt?g:T,Ce=D(e,"ALLOWED_TAGS")&&h(e.ALLOWED_TAGS)?k({},e.ALLOWED_TAGS,Et):Le,ke=D(e,"ALLOWED_ATTR")&&h(e.ALLOWED_ATTR)?k({},e.ALLOWED_ATTR,Et):xe,pt=D(e,"ALLOWED_NAMESPACES")&&h(e.ALLOWED_NAMESPACES)?k({},e.ALLOWED_NAMESPACES,g):dt,at=D(e,"ADD_URI_SAFE_ATTR")&&h(e.ADD_URI_SAFE_ATTR)?k(v(lt),e.ADD_URI_SAFE_ATTR,Et):lt,rt=D(e,"ADD_DATA_URI_TAGS")&&h(e.ADD_DATA_URI_TAGS)?k(v(it),e.ADD_DATA_URI_TAGS,Et):it,nt=D(e,"FORBID_CONTENTS")&&h(e.FORBID_CONTENTS)?k({},e.FORBID_CONTENTS,Et):ot,Me=D(e,"FORBID_TAGS")&&h(e.FORBID_TAGS)?k({},e.FORBID_TAGS,Et):v({}),Pe=D(e,"FORBID_ATTR")&&h(e.FORBID_ATTR)?k({},e.FORBID_ATTR,Et):v({}),tt=!!D(e,"USE_PROFILES")&&(e.USE_PROFILES&&"object"==typeof e.USE_PROFILES?v(e.USE_PROFILES):e.USE_PROFILES),ze=!1!==e.ALLOW_ARIA_ATTR,Fe=!1!==e.ALLOW_DATA_ATTR,He=e.ALLOW_UNKNOWN_PROTOCOLS||!1,Be=!1!==e.ALLOW_SELF_CLOSE_IN_ATTR,Ge=e.SAFE_FOR_TEMPLATES||!1,We=!1!==e.SAFE_FOR_XML,je=e.WHOLE_DOCUMENT||!1,qe=e.RETURN_DOM||!1,$e=e.RETURN_DOM_FRAGMENT||!1,Ke=e.RETURN_TRUSTED_TYPE||!1,Xe=e.FORCE_BODY||!1,Ve=!1!==e.SANITIZE_DOM,Ze=e.SANITIZE_NAMED_PROPS||!1,Qe=!1!==e.KEEP_CONTENT,et=e.IN_PLACE||!1,we=function(e){try{return I(e,""),!0}catch(e){return!1}}(e.ALLOWED_URI_REGEXP)?e.ALLOWED_URI_REGEXP:J,mt="string"==typeof e.NAMESPACE?e.NAMESPACE:ut,ht=D(e,"MATHML_TEXT_INTEGRATION_POINTS")&&e.MATHML_TEXT_INTEGRATION_POINTS&&"object"==typeof e.MATHML_TEXT_INTEGRATION_POINTS?v(e.MATHML_TEXT_INTEGRATION_POINTS):k({},["mi","mo","mn","ms","mtext"]),Tt=D(e,"HTML_INTEGRATION_POINTS")&&e.HTML_INTEGRATION_POINTS&&"object"==typeof e.HTML_INTEGRATION_POINTS?v(e.HTML_INTEGRATION_POINTS):k({},["annotation-xml"]);const t=D(e,"CUSTOM_ELEMENT_HANDLING")&&e.CUSTOM_ELEMENT_HANDLING&&"object"==typeof e.CUSTOM_ELEMENT_HANDLING?v(e.CUSTOM_ELEMENT_HANDLING):l(null);if(ve=l(null),D(t,"tagNameCheck")&&bt(t.tagNameCheck)&&(ve.tagNameCheck=t.tagNameCheck),D(t,"attributeNameCheck")&&bt(t.attributeNameCheck)&&(ve.attributeNameCheck=t.attributeNameCheck),D(t,"allowCustomizedBuiltInElements")&&"boolean"==typeof t.allowCustomizedBuiltInElements&&(ve.allowCustomizedBuiltInElements=t.allowCustomizedBuiltInElements),Ge&&(Fe=!1),$e&&(qe=!0),tt&&(Ce=k({},G),ke=l(null),!0===tt.html&&(k(Ce,P),k(ke,W)),!0===tt.svg&&(k(Ce,U),k(ke,j),k(ke,X)),!0===tt.svgFilters&&(k(Ce,z),k(ke,j),k(ke,X)),!0===tt.mathMl&&(k(Ce,H),k(ke,Y),k(ke,X))),Ue.tagCheck=null,Ue.attributeCheck=null,D(e,"ADD_TAGS")&&("function"==typeof e.ADD_TAGS?Ue.tagCheck=e.ADD_TAGS:h(e.ADD_TAGS)&&(Ce===Le&&(Ce=v(Ce)),k(Ce,e.ADD_TAGS,Et))),D(e,"ADD_ATTR")&&("function"==typeof e.ADD_ATTR?Ue.attributeCheck=e.ADD_ATTR:h(e.ADD_ATTR)&&(ke===xe&&(ke=v(ke)),k(ke,e.ADD_ATTR,Et))),D(e,"ADD_URI_SAFE_ATTR")&&h(e.ADD_URI_SAFE_ATTR)&&k(at,e.ADD_URI_SAFE_ATTR,Et),D(e,"FORBID_CONTENTS")&&h(e.FORBID_CONTENTS)&&(nt===ot&&(nt=v(nt)),k(nt,e.FORBID_CONTENTS,Et)),D(e,"ADD_FORBID_CONTENTS")&&h(e.ADD_FORBID_CONTENTS)&&(nt===ot&&(nt=v(nt)),k(nt,e.ADD_FORBID_CONTENTS,Et)),Qe&&(Ce["#text"]=!0),je&&k(Ce,["html","head","body"]),Ce.table&&(k(Ce,["tbody"]),delete Me.tbody),e.TRUSTED_TYPES_POLICY){if("function"!=typeof e.TRUSTED_TYPES_POLICY.createHTML)throw w('TRUSTED_TYPES_POLICY configuration option must provide a "createHTML" hook.');if("function"!=typeof e.TRUSTED_TYPES_POLICY.createScriptURL)throw w('TRUSTED_TYPES_POLICY configuration option must provide a "createScriptURL" hook.');pe=e.TRUSTED_TYPES_POLICY,de=pe.createHTML("")}else void 0===pe&&(pe=function(e,t){if("object"!=typeof e||"function"!=typeof e.createPolicy)return null;let n=null;const o="data-tt-policy-suffix";t&&t.hasAttribute(o)&&(n=t.getAttribute(o));const r="dompurify"+(n?"#"+n:"");try{return e.createPolicy(r,{createHTML:e=>e,createScriptURL:e=>e})}catch(e){return console.warn("TrustedTypes policy "+r+" could not be created."),null}}(Z,c)),null!==pe&&"string"==typeof de&&(de=pe.createHTML(""));i&&i(e),_t=e},Rt=k({},[...U,...z,...F]),Dt=k({},[...H,...B]),Ot=function(e){p(o.removed,{element:e});try{fe(e).removeChild(e)}catch(t){ne(e)}},It=function(e,t){try{p(o.removed,{attribute:t.getAttributeNode(e),from:t})}catch(e){p(o.removed,{attribute:null,from:t})}if(t.removeAttribute(e),"is"===e)if(qe||$e)try{Ot(t)}catch(e){}else try{t.setAttribute(e,"")}catch(e){}},wt=function(e){let t=null,n=null;if(Xe)e="<remove></remove>"+e;else{const t=y(e,/^[\r\n\t ]+/);n=t&&t[0]}"application/xhtml+xml"===yt&&mt===ut&&(e='<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body>'+e+"</body></html>");const o=pe?pe.createHTML(e):e;if(mt===ut)try{t=(new V).parseFromString(o,yt)}catch(e){}if(!t||!t.documentElement){t=he.createDocument(mt,"template",null);try{t.documentElement.innerHTML=ft?de:o}catch(e){}}const i=t.body||t.documentElement;return e&&n&&i.insertBefore(r.createTextNode(n),i.childNodes[0]||null),mt===ut?ye.call(t,je?"html":"body")[0]:je?t.documentElement:i},Ct=function(e){return Te.call(e.ownerDocument||e,e,q.SHOW_ELEMENT|q.SHOW_COMMENT|q.SHOW_TEXT|q.SHOW_PROCESSING_INSTRUCTION|q.SHOW_CDATA_SECTION,null)},Lt=function(e){return e instanceof K&&("string"!=typeof e.nodeName||"string"!=typeof e.textContent||"function"!=typeof e.removeChild||!(e.attributes instanceof $)||"function"!=typeof e.removeAttribute||"function"!=typeof e.setAttribute||"string"!=typeof e.namespaceURI||"function"!=typeof e.insertBefore||"function"!=typeof e.hasChildNodes)},kt=function(e){return"function"==typeof L&&e instanceof L};function xt(e,t,n){u(e,e=>{e.call(o,t,n,_t)})}const vt=function(e){let t=null;if(xt(Ee.beforeSanitizeElements,e,null),Lt(e))return Ot(e),!0;const n=Et(e.nodeName);if(xt(Ee.uponSanitizeElement,e,{tagName:n,allowedTags:Ce}),We&&e.hasChildNodes()&&!kt(e.firstElementChild)&&I(/<[/\w!]/g,e.innerHTML)&&I(/<[/\w!]/g,e.textContent))return Ot(e),!0;if(We&&e.namespaceURI===ut&&"style"===n&&kt(e.firstElementChild))return Ot(e),!0;if(e.nodeType===ae)return Ot(e),!0;if(We&&e.nodeType===le&&I(/<[/\w]/g,e.data))return Ot(e),!0;if(Me[n]||!(Ue.tagCheck instanceof Function&&Ue.tagCheck(n))&&!Ce[n]){if(!Me[n]&&Ut(n)){if(ve.tagNameCheck instanceof RegExp&&I(ve.tagNameCheck,n))return!1;if(ve.tagNameCheck instanceof Function&&ve.tagNameCheck(n))return!1}if(Qe&&!nt[n]){const t=fe(e)||e.parentNode,n=me(e)||e.childNodes;if(n&&t){for(let o=n.length-1;o>=0;--o){const r=ee(n[o],!0);t.insertBefore(r,ue(e))}}}return Ot(e),!0}return e instanceof x&&!function(e){let t=fe(e);t&&t.tagName||(t={namespaceURI:mt,tagName:"template"});const n=T(e.tagName),o=T(t.tagName);return!!pt[e.namespaceURI]&&(e.namespaceURI===st?t.namespaceURI===ut?"svg"===n:t.namespaceURI===ct?"svg"===n&&("annotation-xml"===o||ht[o]):Boolean(Rt[n]):e.namespaceURI===ct?t.namespaceURI===ut?"math"===n:t.namespaceURI===st?"math"===n&&Tt[o]:Boolean(Dt[n]):e.namespaceURI===ut?!(t.namespaceURI===st&&!Tt[o])&&!(t.namespaceURI===ct&&!ht[o])&&!Dt[n]&&(gt[n]||!Rt[n]):!("application/xhtml+xml"!==yt||!pt[e.namespaceURI]))}(e)?(Ot(e),!0):"noscript"!==n&&"noembed"!==n&&"noframes"!==n||!I(/<\/no(script|embed|frames)/i,e.innerHTML)?(Ge&&e.nodeType===ie&&(t=e.textContent,u([_e,Se,be],e=>{t=A(t,e," ")}),e.textContent!==t&&(p(o.removed,{element:e.cloneNode()}),e.textContent=t)),xt(Ee.afterSanitizeElements,e,null),!1):(Ot(e),!0)},Mt=function(e,t,n){if(Pe[t])return!1;if(Ve&&("id"===t||"name"===t)&&(n in r||n in St))return!1;const o=ke[t]||Ue.attributeCheck instanceof Function&&Ue.attributeCheck(t,e);if(Fe&&!Pe[t]&&I(Ne,t));else if(ze&&I(Re,t));else if(!o||Pe[t]){if(!(Ut(e)&&(ve.tagNameCheck instanceof RegExp&&I(ve.tagNameCheck,e)||ve.tagNameCheck instanceof Function&&ve.tagNameCheck(e))&&(ve.attributeNameCheck instanceof RegExp&&I(ve.attributeNameCheck,t)||ve.attributeNameCheck instanceof Function&&ve.attributeNameCheck(t,e))||"is"===t&&ve.allowCustomizedBuiltInElements&&(ve.tagNameCheck instanceof RegExp&&I(ve.tagNameCheck,n)||ve.tagNameCheck instanceof Function&&ve.tagNameCheck(n))))return!1}else if(at[t]);else if(I(we,A(n,Oe,"")));else if("src"!==t&&"xlink:href"!==t&&"href"!==t||"script"===e||0!==E(n,"data:")||!rt[e]){if(He&&!I(De,A(n,Oe,"")));else if(n)return!1}else;return!0},Pt=k({},["annotation-xml","color-profile","font-face","font-face-format","font-face-name","font-face-src","font-face-uri","missing-glyph"]),Ut=function(e){return!Pt[T(e)]&&I(Ie,e)},zt=function(e){xt(Ee.beforeSanitizeAttributes,e,null);const{attributes:t}=e;if(!t||Lt(e))return;const n={attrName:"",attrValue:"",keepAttr:!0,allowedAttributes:ke,forceKeepAttr:void 0};let r=t.length;for(;r--;){const i=t[r],{name:a,namespaceURI:l,value:c}=i,s=Et(a),m=c;let p="value"===a?m:_(m);if(n.attrName=s,n.attrValue=p,n.keepAttr=!0,n.forceKeepAttr=void 0,xt(Ee.uponSanitizeAttribute,e,n),p=n.attrValue,!Ze||"id"!==s&&"name"!==s||0===E(p,Je)||(It(a,e),p=Je+p),We&&I(/((--!?|])>)|<\/(style|script|title|xmp|textarea|noscript|iframe|noembed|noframes)/i,p)){It(a,e);continue}if("attributename"===s&&y(p,"href")){It(a,e);continue}if(n.forceKeepAttr)continue;if(!n.keepAttr){It(a,e);continue}if(!Be&&I(/\/>/i,p)){It(a,e);continue}Ge&&u([_e,Se,be],e=>{p=A(p,e," ")});const d=Et(e.nodeName);if(Mt(d,s,p)){if(pe&&"object"==typeof Z&&"function"==typeof Z.getAttributeType)if(l);else switch(Z.getAttributeType(d,s)){case"TrustedHTML":p=pe.createHTML(p);break;case"TrustedScriptURL":p=pe.createScriptURL(p)}if(p!==m)try{l?e.setAttributeNS(l,a,p):e.setAttribute(a,p),Lt(e)?Ot(e):f(o.removed)}catch(t){It(a,e)}}else It(a,e)}xt(Ee.afterSanitizeAttributes,e,null)},Ft=function(e){let t=null;const n=Ct(e);for(xt(Ee.beforeSanitizeShadowDOM,e,null);t=n.nextNode();)xt(Ee.uponSanitizeShadowNode,t,null),vt(t),zt(t),t.content instanceof s&&Ft(t.content);xt(Ee.afterSanitizeShadowDOM,e,null)};return o.sanitize=function(e){let t=arguments.length>1&&void 0!==arguments[1]?arguments[1]:{},n=null,r=null,i=null,l=null;if(ft=!e,ft&&(e="\x3c!--\x3e"),"string"!=typeof e&&!kt(e)&&"string"!=typeof(e=function(e){switch(typeof e){case"string":return e;case"number":return S(e);case"boolean":return b(e);case"bigint":return N?N(e):"0";case"symbol":return R?R(e):"Symbol()";case"undefined":default:return O(e);case"function":case"object":{if(null===e)return O(e);const t=e,n=M(t,"toString");if("function"==typeof n){const e=n(t);return"string"==typeof e?e:O(e)}return O(e)}}}(e)))throw w("dirty is not a string, aborting");if(!o.isSupported)return e;if(Ye||Nt(t),o.removed=[],"string"==typeof e&&(et=!1),et){const t=e.nodeName;if("string"==typeof t){const e=Et(t);if(!Ce[e]||Me[e])throw w("root node is forbidden and cannot be sanitized in-place")}}else if(e instanceof L)n=wt("\x3c!----\x3e"),r=n.ownerDocument.importNode(e,!0),r.nodeType===re&&"BODY"===r.nodeName||"HTML"===r.nodeName?n=r:n.appendChild(r);else{if(!qe&&!Ge&&!je&&-1===e.indexOf("<"))return pe&&Ke?pe.createHTML(e):e;if(n=wt(e),!n)return qe?null:Ke?de:""}n&&Xe&&Ot(n.firstChild);const c=Ct(et?e:n);for(;i=c.nextNode();)vt(i),zt(i),i.content instanceof s&&Ft(i.content);if(et)return e;if(qe){if(Ge){n.normalize();let e=n.innerHTML;u([_e,Se,be],t=>{e=A(e,t," ")}),n.innerHTML=e}if($e)for(l=ge.call(n.ownerDocument);n.firstChild;)l.appendChild(n.firstChild);else l=n;return(ke.shadowroot||ke.shadowrootmode)&&(l=Ae.call(a,l,!0)),l}let m=je?n.outerHTML:n.innerHTML;return je&&Ce["!doctype"]&&n.ownerDocument&&n.ownerDocument.doctype&&n.ownerDocument.doctype.name&&I(te,n.ownerDocument.doctype.name)&&(m="<!DOCTYPE "+n.ownerDocument.doctype.name+">\n"+m),Ge&&u([_e,Se,be],e=>{m=A(m,e," ")}),pe&&Ke?pe.createHTML(m):m},o.setConfig=function(){Nt(arguments.length>0&&void 0!==arguments[0]?arguments[0]:{}),Ye=!0},o.clearConfig=function(){_t=null,Ye=!1},o.isValidAttribute=function(e,t,n){_t||Nt({});const o=Et(e),r=Et(t);return Mt(o,r,n)},o.addHook=function(e,t){"function"==typeof t&&p(Ee[e],t)},o.removeHook=function(e,t){if(void 0!==t){const n=m(Ee[e],t);return-1===n?void 0:d(Ee[e],n,1)[0]}return f(Ee[e])},o.removeHooks=function(e){Ee[e]=[]},o.removeAllHooks=function(){Ee={afterSanitizeAttributes:[],afterSanitizeElements:[],afterSanitizeShadowDOM:[],beforeSanitizeAttributes:[],beforeSanitizeElements:[],beforeSanitizeShadowDOM:[],uponSanitizeAttribute:[],uponSanitizeElement:[],uponSanitizeShadowNode:[]}},o}();return ue});
app/static/css/vendor/highlight.min.js:316:}),ae=["a","abbr","address","article","aside","audio","b","blockquote","body","button","canvas","caption","cite","code","dd","del","details","dfn","div","dl","dt","em","fieldset","figcaption","figure","footer","form","h1","h2","h3","h4","h5","h6","header","hgroup","html","i","iframe","img","input","ins","kbd","label","legend","li","main","mark","menu","nav","object","ol","optgroup","option","p","picture","q","quote","samp","section","select","source","span","strong","summary","sup","table","tbody","td","textarea","tfoot","th","thead","time","tr","ul","var","video","defs","g","marker","mask","pattern","svg","switch","symbol","feBlend","feColorMatrix","feComponentTransfer","feComposite","feConvolveMatrix","feDiffuseLighting","feDisplacementMap","feFlood","feGaussianBlur","feImage","feMerge","feMorphology","feOffset","feSpecularLighting","feTile","feTurbulence","linearGradient","radialGradient","stop","circle","ellipse","image","line","path","polygon","polyline","rect","text","use","textPath","tspan","foreignObject","clipPath"],ie=["any-hover","any-pointer","aspect-ratio","color","color-gamut","color-index","device-aspect-ratio","device-height","device-width","display-mode","forced-colors","grid","height","hover","inverted-colors","monochrome","orientation","overflow-block","overflow-inline","pointer","prefers-color-scheme","prefers-contrast","prefers-reduced-motion","prefers-reduced-transparency","resolution","scan","scripting","update","width","min-width","max-width","min-height","max-height"].sort().reverse(),re=["active","any-link","blank","checked","current","default","defined","dir","disabled","drop","empty","enabled","first","first-child","first-of-type","fullscreen","future","focus","focus-visible","focus-within","has","host","host-context","hover","indeterminate","in-range","invalid","is","lang","last-child","last-of-type","left","link","local-link","not","nth-child","nth-col","nth-last-child","nth-last-col","nth-last-of-type","nth-of-type","only-child","only-of-type","optional","out-of-range","past","placeholder-shown","read-only","read-write","required","right","root","scope","target","target-within","user-invalid","valid","visited","where"].sort().reverse(),se=["after","backdrop","before","cue","cue-region","first-letter","first-line","grammar-error","marker","part","placeholder","selection","slotted","spelling-error"].sort().reverse(),oe=["accent-color","align-content","align-items","align-self","alignment-baseline","all","anchor-name","animation","animation-composition","animation-delay","animation-direction","animation-duration","animation-fill-mode","animation-iteration-count","animation-name","animation-play-state","animation-range","animation-range-end","animation-range-start","animation-timeline","animation-timing-function","appearance","aspect-ratio","backdrop-filter","backface-visibility","background","background-attachment","background-blend-mode","background-clip","background-color","background-image","background-origin","background-position","background-position-x","background-position-y","background-repeat","background-size","baseline-shift","block-size","border","border-block","border-block-color","border-block-end","border-block-end-color","border-block-end-style","border-block-end-width","border-block-start","border-block-start-color","border-block-start-style","border-block-start-width","border-block-style","border-block-width","border-bottom","border-bottom-color","border-bottom-left-radius","border-bottom-right-radius","border-bottom-style","border-bottom-width","border-collapse","border-color","border-end-end-radius","border-end-start-radius","border-image","border-image-outset","border-image-repeat","border-image-slice","border-image-source","border-image-width","border-inline","border-inline-color","border-inline-end","border-inline-end-color","border-inline-end-style","border-inline-end-width","border-inline-start","border-inline-start-color","border-inline-start-style","border-inline-start-width","border-inline-style","border-inline-width","border-left","border-left-color","border-left-style","border-left-width","border-radius","border-right","border-right-color","border-right-style","border-right-width","border-spacing","border-start-end-radius","border-start-start-radius","border-style","border-top","border-top-color","border-top-left-radius","border-top-right-radius","border-top-style","border-top-width","border-width","bottom","box-align","box-decoration-break","box-direction","box-flex","box-flex-group","box-lines","box-ordinal-group","box-orient","box-pack","box-shadow","box-sizing","break-after","break-before","break-inside","caption-side","caret-color","clear","clip","clip-path","clip-rule","color","color-interpolation","color-interpolation-filters","color-profile","color-rendering","color-scheme","column-count","column-fill","column-gap","column-rule","column-rule-color","column-rule-style","column-rule-width","column-span","column-width","columns","contain","contain-intrinsic-block-size","contain-intrinsic-height","contain-intrinsic-inline-size","contain-intrinsic-size","contain-intrinsic-width","container","container-name","container-type","content","content-visibility","counter-increment","counter-reset","counter-set","cue","cue-after","cue-before","cursor","cx","cy","direction","display","dominant-baseline","empty-cells","enable-background","field-sizing","fill","fill-opacity","fill-rule","filter","flex","flex-basis","flex-direction","flex-flow","flex-grow","flex-shrink","flex-wrap","float","flood-color","flood-opacity","flow","font","font-display","font-family","font-feature-settings","font-kerning","font-language-override","font-optical-sizing","font-palette","font-size","font-size-adjust","font-smooth","font-smoothing","font-stretch","font-style","font-synthesis","font-synthesis-position","font-synthesis-small-caps","font-synthesis-style","font-synthesis-weight","font-variant","font-variant-alternates","font-variant-caps","font-variant-east-asian","font-variant-emoji","font-variant-ligatures","font-variant-numeric","font-variant-position","font-variation-settings","font-weight","forced-color-adjust","gap","glyph-orientation-horizontal","glyph-orientation-vertical","grid","grid-area","grid-auto-columns","grid-auto-flow","grid-auto-rows","grid-column","grid-column-end","grid-column-start","grid-gap","grid-row","grid-row-end","grid-row-start","grid-template","grid-template-areas","grid-template-columns","grid-template-rows","hanging-punctuation","height","hyphenate-character","hyphenate-limit-chars","hyphens","icon","image-orientation","image-rendering","image-resolution","ime-mode","initial-letter","initial-letter-align","inline-size","inset","inset-area","inset-block","inset-block-end","inset-block-start","inset-inline","inset-inline-end","inset-inline-start","isolation","justify-content","justify-items","justify-self","kerning","left","letter-spacing","lighting-color","line-break","line-height","line-height-step","list-style","list-style-image","list-style-position","list-style-type","margin","margin-block","margin-block-end","margin-block-start","margin-bottom","margin-inline","margin-inline-end","margin-inline-start","margin-left","margin-right","margin-top","margin-trim","marker","marker-end","marker-mid","marker-start","marks","mask","mask-border","mask-border-mode","mask-border-outset","mask-border-repeat","mask-border-slice","mask-border-source","mask-border-width","mask-clip","mask-composite","mask-image","mask-mode","mask-origin","mask-position","mask-repeat","mask-size","mask-type","masonry-auto-flow","math-depth","math-shift","math-style","max-block-size","max-height","max-inline-size","max-width","min-block-size","min-height","min-inline-size","min-width","mix-blend-mode","nav-down","nav-index","nav-left","nav-right","nav-up","none","normal","object-fit","object-position","offset","offset-anchor","offset-distance","offset-path","offset-position","offset-rotate","opacity","order","orphans","outline","outline-color","outline-offset","outline-style","outline-width","overflow","overflow-anchor","overflow-block","overflow-clip-margin","overflow-inline","overflow-wrap","overflow-x","overflow-y","overlay","overscroll-behavior","overscroll-behavior-block","overscroll-behavior-inline","overscroll-behavior-x","overscroll-behavior-y","padding","padding-block","padding-block-end","padding-block-start","padding-bottom","padding-inline","padding-inline-end","padding-inline-start","padding-left","padding-right","padding-top","page","page-break-after","page-break-before","page-break-inside","paint-order","pause","pause-after","pause-before","perspective","perspective-origin","place-content","place-items","place-self","pointer-events","position","position-anchor","position-visibility","print-color-adjust","quotes","r","resize","rest","rest-after","rest-before","right","rotate","row-gap","ruby-align","ruby-position","scale","scroll-behavior","scroll-margin","scroll-margin-block","scroll-margin-block-end","scroll-margin-block-start","scroll-margin-bottom","scroll-margin-inline","scroll-margin-inline-end","scroll-margin-inline-start","scroll-margin-left","scroll-margin-right","scroll-margin-top","scroll-padding","scroll-padding-block","scroll-padding-block-end","scroll-padding-block-start","scroll-padding-bottom","scroll-padding-inline","scroll-padding-inline-end","scroll-padding-inline-start","scroll-padding-left","scroll-padding-right","scroll-padding-top","scroll-snap-align","scroll-snap-stop","scroll-snap-type","scroll-timeline","scroll-timeline-axis","scroll-timeline-name","scrollbar-color","scrollbar-gutter","scrollbar-width","shape-image-threshold","shape-margin","shape-outside","shape-rendering","speak","speak-as","src","stop-color","stop-opacity","stroke","stroke-dasharray","stroke-dashoffset","stroke-linecap","stroke-linejoin","stroke-miterlimit","stroke-opacity","stroke-width","tab-size","table-layout","text-align","text-align-all","text-align-last","text-anchor","text-combine-upright","text-decoration","text-decoration-color","text-decoration-line","text-decoration-skip","text-decoration-skip-ink","text-decoration-style","text-decoration-thickness","text-emphasis","text-emphasis-color","text-emphasis-position","text-emphasis-style","text-indent","text-justify","text-orientation","text-overflow","text-rendering","text-shadow","text-size-adjust","text-transform","text-underline-offset","text-underline-position","text-wrap","text-wrap-mode","text-wrap-style","timeline-scope","top","touch-action","transform","transform-box","transform-origin","transform-style","transition","transition-behavior","transition-delay","transition-duration","transition-property","transition-timing-function","translate","unicode-bidi","user-modify","user-select","vector-effect","vertical-align","view-timeline","view-timeline-axis","view-timeline-inset","view-timeline-name","view-transition-name","visibility","voice-balance","voice-duration","voice-family","voice-pitch","voice-range","voice-rate","voice-stress","voice-volume","white-space","white-space-collapse","widows","width","will-change","word-break","word-spacing","word-wrap","writing-mode","x","y","z-index","zoom"].sort().reverse(),le=re.concat(se).sort().reverse()

codex
The merge commit is at `82013ed`; I’m going to compare it against both parents, not just main, so lost behavior from either side is visible. The first quick scan already shows the hot spots are `SessionManager.create_session`, `AgentSession.start`, pipeline path resolution, and frontend/API field alignment.
exec
/usr/bin/zsh -lc 'git show --pretty=raw --no-patch HEAD' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
commit 82013edce1dba5d57497edf0a3ad2acfbdadbd57
tree a1138530fdc4cb47bc0489a3879e1e0178900caf
parent d8e068f497d60340e739ca3d9fdcabec9a6183ac
parent b1d6f905237bf5ae78424bc715a09e1cc740a02a
author Maxim <65215214+DrSeedon@users.noreply.github.com> 1780548019 +0200
committer Maxim <65215214+DrSeedon@users.noreply.github.com> 1780548019 +0200

    merge PR #2 (feat/pipeline-as-config) onto main v2.18
    
    Vadim's pipeline-as-config PR (16 commits from v2.16 base) merged onto
    current main (v2.18+, ~30 commits ahead). Manual conflict resolution
    in 4 files: backend_claude.py, main.py, manager.py, test_manager.py.
    
    Key decisions:
    - Keep main's architecture: prompting.py, deps.py, split routes, guards
    - Add PR's pipeline features: YAML manifests, profiles, pipeline-aware prompts
    - Deduplicate: PR's inlined prompt functions removed, use prompting.py
    - Sync default pipeline with v2.18 upstream (removed reviewer/watcher roles,
      added orchestration module, codex-debate skill)
    - base_branch="" preserved for pipeline branch strategy
    - owned_dirs: keep main's BLOCK behavior (not PR's warning)
    - is_orchestrator: denormalized to session (PR) + static fallback (main)
    
    486 tests pass, 5 skipped.

exec
/usr/bin/zsh -lc "sed -n '260,620p' app/pipeline.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:

@lru_cache(maxsize=None)
def load_pipeline(name: str) -> PipelineConfig:
    """Прочитать ``pipelines/<name>/pipeline.yaml``, провалидировать, кэшировать.

    :raises FileNotFoundError: если папки/файла нет.
    :raises pydantic.ValidationError: если схема битая (extra-поле, неверный kind/model).
    :raises ValueError: если ``name`` в файле не совпадает с именем папки, либо битый
        граф can_spawn.
    """
    path = PIPELINES_DIR / name / "pipeline.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"pipeline '{name}' not found at {path}")
    data = yaml.safe_load(path.read_text()) or {}
    cfg = PipelineConfig(**data)  # pydantic: схема + граф can_spawn
    if cfg.name != name:
        raise ValueError(f"pipeline name '{cfg.name}' != dir '{name}'")
    return cfg


def get_worktree_config(pipeline_name: str) -> Worktree:
    """Вернуть worktree-конфиг пайплайна (``defaults.worktree``).

    Это pipeline-level настройка (симлинки + copies), общая для всех ролей —
    в :class:`ResolvedRole` её нет.

    :raises FileNotFoundError: если манифест отсутствует (пробрасываем, чтобы
        вызывающий в manager сделал fallback на upstream-поведение).
    """
    return load_pipeline(pipeline_name).defaults.worktree


def list_pipelines() -> list[dict]:
    """Скан ``pipelines/`` (включая gitignored). Для UI-дропдауна.

    Возвращает ``[{name, description, roles:[...], valid:bool, error:str|None}]``.
    Битый манифест НЕ роняет список — помечается ``valid=False`` с текстом ошибки.
    """
    out: list[dict] = []
    if not PIPELINES_DIR.is_dir():
        return out
    for d in sorted(PIPELINES_DIR.iterdir()):
        if not d.is_dir() or not (d / "pipeline.yaml").is_file():
            continue
        try:
            cfg = load_pipeline(d.name)
            out.append({"name": cfg.name, "description": cfg.description,
                        "roles": sorted(cfg.roles), "valid": True, "error": None})
        except Exception as e:  # noqa: BLE001 — намеренно глотаем, чтобы список не падал
            out.append({"name": d.name, "description": "", "roles": [],
                        "valid": False, "error": str(e)})
    return out


# ── Резолв роли: наследование defaults→roles ──────────────────────────────

def _merge_scalar(default_val, role_val):
    """Скаляр: роль переопределяет, если задала (не None); иначе наследуем."""
    return default_val if role_val is None else role_val


def _merge_list(default_val: AllOrList, role_val: AllOrList | None) -> AllOrList:
    """Список: union(defaults ∪ role). ``"all"`` в любом из двух → ``"all"`` (поглощает)."""
    if role_val is None:
        return default_val
    if default_val == "all" or role_val == "all":
        return "all"
    return sorted(set(default_val) | set(role_val))


def resolve_role(pipeline: PipelineConfig, role: str) -> ResolvedRole:
    """Слить роль с defaults в :class:`ResolvedRole` (все поля заполнены).

    Скаляр — роль переопределяет если задан, иначе defaults. Список (skills/
    mcp_servers) — union с поглощением ``"all"``. ``prompt_layers`` — по kind роли
    с подстановкой ``{role}``.

    :raises KeyError: если ``role`` нет в ``pipeline.roles`` (ловит вызывающий).
    """
    spec = pipeline.roles[role]
    d = pipeline.defaults
    layers_tmpl = (d.prompt_layers.orchestrator if spec.kind == "orchestrator"
                   else d.prompt_layers.worker)
    return ResolvedRole(
        name=role, pipeline=pipeline.name, kind=spec.kind, label=spec.label,
        order=spec.order, can_spawn=spec.can_spawn,
        allow_unrouted_workers=spec.allow_unrouted_workers,
        modules=spec.modules,
        model=_merge_scalar(d.model, spec.model),
        skills=_merge_list(d.skills, spec.skills),
        mcp_servers=_merge_list(d.mcp_servers, spec.mcp_servers),
        base_branch_strategy=_merge_scalar(d.base_branch_strategy, spec.base_branch_strategy),
        inherit_claude_md=_merge_scalar(d.inherit_claude_md, spec.inherit_claude_md),
        docs_scaffold=_merge_scalar(d.docs_scaffold, spec.docs_scaffold),
        docs_dir=spec.docs_dir, tg=spec.tg,
        when=spec.when, not_for=spec.not_for, description=spec.description,
        prompt_layers=[p.replace("{role}", role) for p in layers_tmpl],
    )


def get_role(pipeline_name: str, role: str) -> ResolvedRole | None:
    """Загрузить пайплайн и резолвнуть роль. None, если роли нет в манифесте."""
    cfg = load_pipeline(pipeline_name)
    return resolve_role(cfg, role) if role in cfg.roles else None


def known_roles(pipeline_name: str) -> list[str]:
    """Отсортированный список имён ролей пайплайна."""
    return sorted(load_pipeline(pipeline_name).roles)


# ── Резолв путей промпта (полная изоляция: только pipelines/<name>/prompts/) ─

def prompt_path(pipeline_name: str, rel: str) -> Path:
    """Путь к слою промпта. ВСЕГДА внутри ``pipelines/<name>/prompts/``.

    ``rel`` — элемент prompt_layers (``base.md``, ``roles/coder.md``, ``_pipeline.md``).
    ``app/prompts/`` НЕ участвует — гарантия изоляции.
    """
    return PIPELINES_DIR / pipeline_name / "prompts" / rel


def template_path(pipeline_name: str, template: str) -> Path:
    """Путь к шаблону doc-папки внутри ``pipelines/<name>/templates/``."""
    return PIPELINES_DIR / pipeline_name / "templates" / template


def build_system_prompt(pipeline_name: str, role: str, scope: str = "") -> str:
    """Собрать system_prompt из prompt_layers резолвнутой роли.

    Каждый слой читается из ``pipelines/<name>/prompts/<layer>`` через
    :func:`prompt_path` (ПОЛНАЯ изоляция — ``app/prompts/`` не читается). Отсутствующий
    слой-файл пропускается. Конкатенация через ``\\n\\n``. Динамика (каталог ролей,
    блоки других оркестраторов/воркеров) добавляется вызывающим в manager — здесь
    только статика из файлов.

    После слоёв роли инлайнятся ``modules`` — переиспользуемые блоки промпта из
    ``prompts/modules/{m}.md`` (та же изоляция). Отсутствующий модуль пропускается с
    warning (роль не должна падать из-за недостающего блока).

    :raises FileNotFoundError: если манифест пайплайна отсутствует (на Этапе 3 manager
        ловит и делегирует в legacy-путь апстрима).
    """
    rr = resolve_role(load_pipeline(pipeline_name), role)
    parts: list[str] = []
    for layer in rr.prompt_layers:
        p = prompt_path(pipeline_name, layer)
        if p.is_file():
            parts.append(p.read_text())
    for m in rr.modules:
        mp = prompt_path(pipeline_name, f"modules/{m}.md")
        if mp.is_file():
            # ``.strip()`` — точное соответствие upstream ``_load_modules`` (manager.py):
            # модули инлайнятся обрезанными, разделитель между ними ровно ``\n\n``.
            # Без strip хвостовые ``\n`` в файле дают ``\n\n\n`` и расхождение с upstream.
            parts.append(mp.read_text().strip())
        else:
            logger.warning(
                "pipeline '%s' role '%s': module '%s' not found at %s — skipped",
                pipeline_name, role, m, mp)
    return "\n\n".join(parts)


# ── Активный пайплайн ──────────────────────────────────────────────────────

def get_active_pipeline(scope: str = "", parent_pipeline: str = "") -> str:
    """Определить активный пайплайн для НОВОЙ сессии.

    1) ``parent_pipeline`` (от родителя при спавне) — главный источник: дети
       наследуют пайплайн родителя.
    2) пусто/корневой оркестратор → :data:`DEFAULT_PIPELINE`.

    Один пайплайн на дерево агентов — в середине цепочки сменить нельзя. Полная
    логика (чтение колонки sessions.pipeline) — Этап 7; здесь зафиксирована
    сигнатура и базовое поведение наследования.
    """
    if parent_pipeline:
        return parent_pipeline
    return DEFAULT_PIPELINE


# ── Валидация спавна (fail-closed / fail-open) ────────────────────────────

def validate_spawn(pipeline_name: str, parent_role: str | None, child_role: str) -> None:
    """Проверить допустимость спавна ``child_role`` родителем ``parent_role``.

    Режим из ``PipelineConfig.validation``:

    * **fail-closed** (наш дефолт) — неизвестный parent/child → ValueError.
    * **fail-open** (дух апстрима) — неизвестные роли пропускаются; но явный
      ``can_spawn``-whitelist при ИЗВЕСТНЫХ ролях действует в обоих режимах.

    Корень (parent пуст/None) — спавн от юзера/UI, всегда разрешён. Пустой
    ``child_role`` (генерик-воркер) разрешён только если ``allow_unrouted_workers``.

    :raises ValueError: при запрещённом спавне.
    :raises FileNotFoundError: если манифест отсутствует (manager ловит → fallback).
    """
    cfg = load_pipeline(pipeline_name)
    fail_closed = cfg.validation == "fail-closed"

    if not parent_role:  # корень — спавн от юзера/UI
        return
    parent = cfg.roles.get(parent_role)
    if parent is None:
        if fail_closed:
            raise ValueError(
                f"unknown parent role '{parent_role}' in pipeline '{pipeline_name}'. "
                f"known={known_roles(pipeline_name)}")
        return  # fail-open: неизвестный parent → пропуск
    if not child_role:  # генерик-воркер (роль не указана)
        if not parent.allow_unrouted_workers:
            raise ValueError(
                f"role '{parent_role}' must specify child role. "
                f"allowed: {parent.can_spawn or '(none)'}")
        return
    if child_role not in cfg.roles:
        if fail_closed:
            raise ValueError(
                f"unknown role '{child_role}' in pipeline '{pipeline_name}'. "
                f"known={known_roles(pipeline_name)}")
        return  # fail-open: неизвестный child → пропуск
    if "*" in parent.can_spawn:
        return
    if child_role not in parent.can_spawn:
        raise ValueError(
            f"role '{parent_role}' cannot spawn '{child_role}'. "
            f"allowed: {parent.can_spawn or '(none — terminal)'}")

exec
/usr/bin/zsh -lc "sed -n '1,260p' app/pipeline.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Loader пайплайнов: схема манифеста (pydantic) + резолв ролей/промптов/спавна.

Источник истины о ролях — единый манифест ``pipelines/<name>/pipeline.yaml``
(вместо frontmatter+glob апстрима). При активном пайплайне ВСЁ берётся только из
``pipelines/<name>/`` — ``app/prompts/`` игнорируется (полная изоляция промптов).

Наследование defaults→roles выполняется на РЕЗОЛВЕ (:func:`resolve_role`), не на
загрузке: ``load_pipeline`` валидирует и кэширует сырой манифест, ``resolve_role``
сливает роль с defaults в :class:`ResolvedRole`.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ALIASES, MODELS

logger = logging.getLogger(__name__)

# Корень с пайплайнами: <repo>/pipelines/. default и tasks-pm — оба в гите.
PIPELINES_DIR = Path(__file__).parent.parent / "pipelines"
DEFAULT_PIPELINE = "default"

# Спецзначение "all" для skills/mcp_servers (строка) vs явный список.
AllOrList = Union[Literal["all"], list[str]]

Kind = Literal["orchestrator", "worker"]
ValidationMode = Literal["fail-closed", "fail-open"]
BranchStrategy = Literal["parent", "main"]


def _model_is_known(model: str) -> bool:
    """Модель валидна, если это alias (lowercase) ИЛИ полный id из app.models."""
    return model.lower() in ALIASES or model in MODELS


def _is_safe_rel(p: str) -> bool:
    """True если ``p`` — безопасный относительный путь (без абсолютного и '..').

    Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
    """
    from pathlib import PurePosixPath
    if not p or p.startswith("/"):
        return False
    return ".." not in PurePosixPath(p).parts


# ── Pydantic-схема манифеста ───────────────────────────────────────────────

class Symlink(BaseModel):
    """Симлинк в worktree: source (относительно repo) → target (внутри worktree)."""
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str

    @field_validator("source", "target")
    @classmethod
    def _safe_rel(cls, v: str) -> str:
        # B2: source резолвится от repo, target — внутри worktree; ни один не должен
        # выходить за свою границу (abs или '..'). Та же защита, что у docs_dir.
        if not _is_safe_rel(v):
            raise ValueError(f"unsafe symlink path '{v}' (abs или '..')")
        return v


class Worktree(BaseModel):
    """Настройка worktree роли: симлинки и копируемые файлы (= PROJECT_FILES)."""
    model_config = ConfigDict(extra="forbid")
    symlinks: list[Symlink] = Field(default_factory=list)
    copies: list[str] = Field(default_factory=list)

    @field_validator("copies")
    @classmethod
    def _safe_copies(cls, v: list[str]) -> list[str]:
        # B2: copies резолвятся как repo/<name> и пишутся как wt_path/<name>;
        # abs или '..' позволили бы чтение/запись вне repo/worktree. Та же защита,
        # что у symlinks (симметрично — иначе copies остаётся дырой).
        for name in v:
            if not _is_safe_rel(name):
                raise ValueError(f"unsafe copy path '{name}' (abs или '..')")
        return v


class DocsDir(BaseModel):
    """Скаффолдинг doc-папки роли в docs_work/.

    ``requires='feature'`` → плейсхолдер ``{feature}`` обязателен в path; если фича
    не передана при спавне — скаффолд пропускается.
    """
    model_config = ConfigDict(extra="forbid")
    path: str
    template: str | None = None
    requires: Literal["feature"] | None = None

    @field_validator("path", "template")
    @classmethod
    def _safe_rel(cls, v: str | None) -> str | None:
        # B2: путь/шаблон не должны выходить за pipelines/<name>/ (abs или '..').
        # {feature} подставляется в рантайме — containment проверяет B3.
        if v is not None and not _is_safe_rel(v):
            raise ValueError(f"unsafe docs_dir path '{v}' (abs или '..')")
        return v


class Tg(BaseModel):
    """Параметры Telegram-топика роли (emoji + шаблон topic)."""
    model_config = ConfigDict(extra="forbid")
    emoji: str = ""
    topic: str = ""


class PromptLayers(BaseModel):
    """Порядок слоёв промпта по kind. ``{role}`` подставляется на резолве.

    Пути относительны ``pipelines/<name>/prompts/``.
    """
    model_config = ConfigDict(extra="forbid")
    orchestrator: list[str] = Field(
        default_factory=lambda: ["base.md", "roles/{role}.md", "_pipeline.md"])
    worker: list[str] = Field(
        default_factory=lambda: ["base.md", "roles/{role}.md"])

    @field_validator("orchestrator", "worker")
    @classmethod
    def _safe_layers(cls, v: list[str]) -> list[str]:
        # B2: слои не должны выходить за pipelines/<name>/prompts/. Плейсхолдер
        # {role} безопасен (_is_safe_rel("roles/{role}.md") True).
        for layer in v:
            if not _is_safe_rel(layer):
                raise ValueError(f"unsafe prompt layer '{layer}' (abs или '..')")
        return v


class Defaults(BaseModel):
    """Дефолты пайплайна. Роль переопределяет: скаляр — replace, список — union."""
    model_config = ConfigDict(extra="forbid")
    model: str = "opus"
    skills: AllOrList = "all"
    mcp_servers: AllOrList = "all"
    inherit_claude_md: bool = True
    prompt_layers: PromptLayers = Field(default_factory=PromptLayers)
    worktree: Worktree = Field(default_factory=Worktree)
    base_branch_strategy: BranchStrategy = "parent"
    docs_scaffold: bool = True

    @field_validator("model")
    @classmethod
    def _model_known(cls, v: str) -> str:
        if not _model_is_known(v):
            raise ValueError(
                f"unknown model '{v}'. aliases={sorted(ALIASES)} ids={sorted(MODELS)}")
        return v


class RoleSpec(BaseModel):
    """Сырая роль из манифеста. Опциональные поля (model/skills/...) = None →
    наследуются из defaults на резолве. kind/label — обязательны для контракта.
    """
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    label: str
    order: int = 100
    can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
    allow_unrouted_workers: bool = False
    # Модули — переиспользуемые блоки промпта (prompts/modules/{m}.md), инлайнятся
    # в system_prompt после слоёв роли. Пусто → ничего не добавляется.
    modules: list[str] = Field(default_factory=list)
    # Переопределения defaults (None → наследуем):
    model: str | None = None
    skills: AllOrList | None = None
    mcp_servers: AllOrList | None = None
    base_branch_strategy: BranchStrategy | None = None
    inherit_claude_md: bool | None = None
    docs_scaffold: bool | None = None
    # Роле-специфика:
    docs_dir: DocsDir | None = None
    tg: Tg | None = None
    when: str | None = None
    not_for: str | None = None
    description: str | None = None

    @field_validator("model")
    @classmethod
    def _model_known(cls, v: str | None) -> str | None:
        if v is not None and not _model_is_known(v):
            raise ValueError(f"unknown model '{v}'")
        return v

    @field_validator("modules")
    @classmethod
    def _safe_modules(cls, v: list[str]) -> list[str]:
        # B2: имя модуля → prompts/modules/{m}.md; не должно выходить за изоляцию
        # (abs или '..'). Та же защита, что у docs_dir/prompt_layers.
        for m in v:
            if not _is_safe_rel(m):
                raise ValueError(f"unsafe module name '{m}' (abs или '..')")
        return v


class PipelineConfig(BaseModel):
    """Сырой манифест пайплайна (роли с None-полями, до наследования)."""
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    validation: ValidationMode = "fail-closed"
    defaults: Defaults = Field(default_factory=Defaults)
    roles: dict[str, RoleSpec]

    @model_validator(mode="after")
    def _check_graph(self) -> "PipelineConfig":
        """can_spawn ⊆ roles (кроме '*'): ссылка на несуществующую роль → ошибка."""
        known = set(self.roles)
        for rname, r in self.roles.items():
            for child in r.can_spawn:
                if child != "*" and child not in known:
                    raise ValueError(
                        f"pipeline '{self.name}': role '{rname}' can_spawn references "
                        f"unknown role '{child}'. known={sorted(known)}")
        return self


class ResolvedRole(BaseModel):
    """RoleSpec после слияния defaults→role. Все поля заполнены, None нет.

    То, что отдаётся наружу (manager/workspace/tg).
    """
    model_config = ConfigDict(extra="forbid")
    name: str
    pipeline: str
    kind: Kind
    label: str
    order: int
    can_spawn: list[str]
    allow_unrouted_workers: bool
    modules: list[str]
    model: str
    skills: AllOrList
    mcp_servers: AllOrList
    base_branch_strategy: BranchStrategy
    inherit_claude_md: bool
    docs_scaffold: bool
    docs_dir: DocsDir | None
    tg: Tg | None
    when: str | None
    not_for: str | None
    description: str | None
    prompt_layers: list[str]  # выбранный (orchestrator|worker) список с подставленным {role}

    @property
    def is_orchestrator(self) -> bool:
        return self.kind == "orchestrator"


# ── Загрузка манифеста ─────────────────────────────────────────────────────


exec
/usr/bin/zsh -lc "sed -n '1,260p' app/workspace.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Worktree management — create and remove git worktrees for agent sessions."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Только для аннотаций (строковые аннотации + from __future__ import annotations):
    # рантайм-импорт не нужен, объекты приходят готовыми от вызывающего. Так избегаем
    # циклической зависимости (pipeline ← workspace).
    from app.pipeline import Symlink, Worktree as WorktreeCfg

logger = logging.getLogger(__name__)

WORKTREE_ROOT = Path(__file__).parent.parent / "worktrees"
PROJECT_FILES = ("CLAUDE.md", ".worktreeinclude", ".mcp.json", ".env")


@dataclass
class Worktree:
    path: str
    branch: str


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "-", s).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug.lower()[:80]


_TASK_ID_RE = re.compile(r"^([A-Z]{2,5})-(\d+)$", re.IGNORECASE)
_TASK_ID_BARE = re.compile(r"^(\d+)$")


def _normalize_task_id(task_id: str) -> str:
    tid = task_id.strip().lstrip("#")
    m = _TASK_ID_RE.match(tid)
    if m:
        n = int(m.group(2))
        if n < 1:
            raise ValueError(f"Invalid task_id '{task_id}': number must be >= 1")
        return str(n)
    m = _TASK_ID_BARE.match(tid)
    if m:
        n = int(m.group(1))
        if n < 1:
            raise ValueError(f"Invalid task_id '{task_id}': number must be >= 1")
        return str(n)
    raise ValueError(f"Invalid task_id '{task_id}': expected number, #N, or PREFIX-N (legacy)")


def _within(child: Path, *roots: Path) -> bool:
    """True, если резолвнутый ``child`` лежит внутри одного из ``roots`` (или равен).

    Защита от symlink-побега: строковый валидатор (:class:`Symlink`/``copies``) ловит
    abs/``..`` в спеке, но если сам ``repo/docs_work`` — симлинк наружу, путь после
    ``resolve()`` уйдёт за границу. Здесь проверяем уже резолвнутый реальный путь.
    """
    rc = child.resolve()
    for root in roots:
        rr = root.resolve()
        if rc == rr or rr in rc.parents:
            return True
    return False


def _resolve_src(repo: Path, rel: str) -> Path | None:
    """Резолв source: ``repo/rel`` → fallback ``repo.parent/rel``. None если нет/побег.

    Возвращает существующий путь, лежащий внутри ``repo`` или ``repo.parent``.
    Симлинк, уводящий за обе границы, отбрасывается (containment по resolve()).
    """
    for base in (repo, repo.parent):
        cand = base / rel
        if cand.exists() and _within(cand, repo, repo.parent):
            return cand
    return None


def _apply_symlink(repo: Path, wt_path: Path, sl: "Symlink") -> None:
    """Создать симлинк ``wt_path/sl.target`` → source внутри/рядом с repo.

    source резолвится как ``repo/sl.source`` с fallback ``repo.parent/sl.source``
    (та же логика, что у copies: docs_work лежит в основном репо, gitignored).
    Несуществующий source → warning + пропуск (worktree не падает, как у copies).
    Пути sl.source/sl.target уже провалидированы pydantic (:class:`Symlink`);
    дополнительно проверяем resolved-containment (symlink-побег).
    """
    src = _resolve_src(repo, sl.source)
    if src is None:
        logger.warning("symlink source '%s' not found/escapes (repo=%s) — skipped", sl.source, repo)
        return
    target = wt_path / sl.target
    if not _within(target.parent, wt_path):
        raise ValueError(f"symlink target '{sl.target}' escapes worktree")
    os.symlink(str(src), str(target))


def create_worktree(repo_path: str, name: str, scope: str, task_id: str = "",
                    base_branch: str = "main",
                    worktree_cfg: "WorktreeCfg | None" = None) -> Worktree:
    # Защитный дефолт: пустая строка (sentinel из manager) → main, чтобы git не упал.
    if not base_branch:
        base_branch = "main"
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise ValueError(f"repo_path does not exist: {repo_path}")

    scope_slug = _slugify(scope)
    wt_dir = WORKTREE_ROOT / scope_slug
    wt_dir.mkdir(parents=True, exist_ok=True)
    wt_path = wt_dir / name

    if task_id:
        par = _normalize_task_id(task_id)
        branch = f"task-{par}/{name}"
    else:
        branch = f"feat/{scope_slug}/{name}"

    if wt_path.exists():
        raise ValueError(f"worktree already exists: {wt_path}. Remove session first.")

    ref_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo), capture_output=True, text=True,
    )

    fmt_check = subprocess.run(
        ["git", "check-ref-format", "--branch", branch],
        cwd=str(repo), capture_output=True, text=True,
    )
    if fmt_check.returncode != 0:
        raise ValueError(f"Invalid branch name '{branch}': {fmt_check.stderr.strip()}")

    if ref_check.returncode == 0:
        # ветка уже существует — допустимо только если не занята другим worktree
        if _is_branch_checked_out_elsewhere(str(repo), branch, wt_path):
            raise ValueError(f"Branch '{branch}' is checked out in another worktree.")
        # reuse: git worktree add <path> <branch> (без -b)
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch],
            cwd=str(repo), capture_output=True, text=True,
        )
    else:
        # ветка новая — создаём через -b
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch, base_branch],
            cwd=str(repo), capture_output=True, text=True,
        )
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

    # worktree_cfg задан → правила манифеста (copies + symlinks) и ТОЛЬКО они.
    # None → upstream-fallback: хардкод PROJECT_FILES, симлинков нет.
    copies = worktree_cfg.copies if worktree_cfg is not None else list(PROJECT_FILES)
    try:
        for fname in copies:
            src = _resolve_src(repo, fname)
            if src is None:
                continue
            dst = wt_path / fname
            if not _within(dst.parent, wt_path):
                raise ValueError(f"copy target '{fname}' escapes worktree")
            shutil.copy2(str(src), str(dst))
        if worktree_cfg is not None:
            for sl in worktree_cfg.symlinks:
                _apply_symlink(repo, wt_path, sl)
    except Exception:
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            cwd=str(repo), capture_output=True, text=True,
        )
        raise

    return Worktree(path=str(wt_path), branch=branch)


def _resolve_repo(worktree_path: str, fallback_repo: str) -> Path:
    wt = Path(worktree_path).resolve()
    git_common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if git_common.returncode == 0:
        git_dir = Path(git_common.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (wt / git_dir).resolve()
        return git_dir.parent
    return Path(fallback_repo).resolve()


def _ensure_repo_on_branch(repo: str, target_branch: str = "main") -> tuple[str | None, bool]:
    """Returns (error_or_None, did_stash).

    Выполняет stash (если репо грязный) и checkout target_branch.
    НЕ делает stash pop — это обязанность вызывающего кода в блоке finally.
    """
    did_stash = False
    repo_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    )
    if repo_status.stdout.strip():
        stash = subprocess.run(
            ["git", "stash", "--include-untracked"], cwd=repo, capture_output=True, text=True,
        )
        if stash.returncode != 0:
            return f"main repo dirty and stash failed: {stash.stderr.strip()}", False
        did_stash = True
        logger.info(f"Auto-stashed dirty repo: {repo}")
    head = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, text=True,
    )
    if head.returncode != 0 or head.stdout.strip() != target_branch:
        checkout = subprocess.run(
            ["git", "checkout", target_branch], cwd=repo, capture_output=True, text=True,
        )
        if checkout.returncode != 0:
            # НЕ делаем stash pop здесь — did_stash=True сигнализирует finally в вызывающем коде
            return f"cannot checkout {target_branch} in repo: {checkout.stderr.strip()}", did_stash
    return None, did_stash


def _get_commit_messages(repo: str, branch: str, base: str) -> list[str]:
    """Return subject lines of commits in branch not in base."""
    log = subprocess.run(
        ["git", "log", f"{base}..{branch}", "--format=%s", "--reverse"],
        cwd=repo, capture_output=True, text=True,
    )
    if log.returncode != 0 or not log.stdout.strip():
        return []
    return [line for line in log.stdout.strip().splitlines() if line.strip()]


def _build_squash_message(branch: str, messages: list[str]) -> str:
    """Build squash commit message with task refs prefix and message list."""
    all_refs: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        for m in _TASK_REF_RE.finditer(msg):
            if m.group(3):
                ref = f"#{m.group(3)}"
            else:
                ref = f"#{m.group(2)}"
            if ref not in seen:
                seen.add(ref)
                all_refs.append(ref)

    if messages:
        summary = messages[-1] if len(messages) == 1 else messages[0]
    else:
        summary = f"merge {branch}"

exec
/usr/bin/zsh -lc "sed -n '360,580p' app/manager.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
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
                whitelist = role_can_spawn(parent_role)
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
        session.is_orchestrator = is_orch
        session._template_hash = prompt_template_hash(role)
        session._spawn_warning = ""
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
                try:
                    _rr = get_role(pipeline, role)
                    _skills = _rr.skills if _rr else None
                except FileNotFoundError:
                    _skills = None
                if _skills != "all":
                    await asyncio.to_thread(inject_skills_to_worktree, role, wt.path)

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

exec
/usr/bin/zsh -lc "sed -n '580,940p' app/manager.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
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
        async def _on_worker_idle(worker_name: str, worker_scope: str, last_texts: list[str], stop_reason: str = ""):

exec
/usr/bin/zsh -lc "sed -n '1,380p' app/session.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""AgentSession — backend-agnostic wrapper with persistent event loop."""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.events import AgentEvent
from app.prompting import is_orchestrator_role

if TYPE_CHECKING:
    from app.backend_protocol import BackendLike
from app.db import save_session, add_log

logger = logging.getLogger(__name__)

import concurrent.futures
_DB_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _db_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Dedicated pool for DB writes so logs/persists don't contend with git ops
    on the default executor (used by asyncio.to_thread)."""
    global _DB_EXECUTOR
    if _DB_EXECUTOR is None:
        _DB_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _DB_EXECUTOR


IDLE_TIMEOUT_WORKER = 300
IDLE_TIMEOUT_ORCHESTRATOR = 600



def _load_scope_mcp_servers(scope: str) -> dict:
    servers = {}
    for name in ("settings.json", "settings.local.json"):
        path = Path(scope) / ".claude" / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse MCP servers from {path}: {e}")
    mcp_json = Path(scope) / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text())
            for k, v in data.get("mcpServers", {}).items():
                if k != "orchestra":
                    servers[k] = v
        except Exception as e:
            logger.warning(f"Failed to parse .mcp.json from {mcp_json}: {e}")
    return servers


def _load_user_mcp_servers(config_dir: str) -> dict:
    """F2: user-MCP из top-level ``.claude.json`` профиля.

    ``config_dir`` непуст → ``<config_dir>/.claude.json``; пуст → ``~/.claude.json``
    (env процесса orchestra). Берёт ключ ``mcpServers``, пропуская ``orchestra``
    (серверный MCP подмешивается отдельно и не должен подменяться профилем).
    Зеркалит стиль ``_load_scope_mcp_servers``: ошибки парсинга — warning, не падаем.

    ВНИМАНИЕ: личный профиль CLI хранит ``.claude.json`` в HOME root
    (``~/.claude.json``), а НЕ внутри ``~/.claude/``. Поэтому для личного профиля
    держим ``config_dir=""`` (сид-профиль ``personal`` так и сидится). Если задать
    ``config_dir="~/.claude"`` — функция пойдёт в ``~/.claude/.claude.json``,
    которого нет, и вернёт пусто. Рабочий профиль (``~/.claude-work``) хранит
    ``.claude.json`` ВНУТРИ config dir — для него путь верный.
    """
    servers: dict = {}
    base = Path(os.path.expanduser(config_dir)) if config_dir else Path.home()
    path = base / ".claude.json"
    if not path.is_file():
        return servers
    try:
        data = json.loads(path.read_text())
        for k, v in data.get("mcpServers", {}).items():
            if k != "orchestra":
                servers[k] = v
    except Exception as e:
        logger.warning(f"Failed to parse user MCP servers from {path}: {e}")
    return servers


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"


@dataclass
class AgentSession:
    id: str
    name: str
    scope: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    system_prompt: str = ""
    status: AgentStatus = AgentStatus.IDLE
    session_id: str | None = None
    cost_usd: float = 0.0
    cost_usd_cached: float = 0.0
    worktree_path: str | None = None
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    role: str = "worker"
    parent_id: str = ""
    parent_name: str = ""
    pipeline: str = ""
    profile: str = ""
    _is_orchestrator: bool | None = field(default=None, repr=False)
    color: str = ""
    mcp_servers: dict = field(default_factory=dict, repr=False)
    mcp_servers_custom: dict = field(default_factory=dict, repr=False)
    on_error: Optional[callable] = field(default=None, repr=False)
    backend_type: str = "claude"
    task_id: str = ""
    description: str = ""
    owned_dirs: list = field(default_factory=list, repr=False)
    tg_topic: bool = False

    needs_switch: bool = False

    progress_pct: int = 0
    progress_status: str = ""

    total_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    _backend: Optional["BackendLike"] = field(default=None, repr=False)
    _listen_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _background_tasks: set = field(default_factory=set, repr=False)
    _last_context: dict = field(default_factory=lambda: {"percentage": 0, "total_tokens": 0, "max_tokens": 0}, repr=False)
    _did_report: bool = field(default=False, repr=False)
    _turn_logs: list = field(default_factory=list, repr=False)
    _prompt_injected: bool = field(default=False, repr=False)
    _current_prompt: str = field(default="", repr=False)
    _template_hash: str = field(default="", repr=False)
    _turn_start: float = field(default=0.0, repr=False)
    _last_msg_time: float = field(default=0.0, repr=False)
    _pending_messages: list = field(default_factory=list, repr=False)
    on_idle: Optional[callable] = field(default=None, repr=False)
    _hibernate_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _hibernated: bool = field(default=False, repr=False)
    _compacting: bool = field(default=False, repr=False)
    _compact_ack_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _compact_ack_gen: int = field(default=-1, repr=False)
    _last_cost: float = field(default=0.0, repr=False)
    _last_cost_cached: float = field(default=0.0, repr=False)
    _last_turn_ok: bool = field(default=True, repr=False)
    _last_stop_reason: str = field(default="", repr=False)
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _persist_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _persist_dirty: bool = field(default=False, repr=False)
    _turn_gen: int = field(default=0, repr=False)
    _auto_report_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _spawn_warning: str = field(default="", repr=False)

    TURN_TIMEOUT = 600

    @property
    def is_orchestrator(self) -> bool:
        if self._is_orchestrator is not None:
            return self._is_orchestrator
        return is_orchestrator_role(self.role)

    @is_orchestrator.setter
    def is_orchestrator(self, value: bool) -> None:
        self._is_orchestrator = value

    def _make_backend(self, force_fresh: bool = False):
        resume = None if force_fresh else self.session_id
        if self.backend_type == "codex":
            from app.backend_codex import CodexBackend
            return CodexBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_thread_id=resume,
                mcp_env=self._build_codex_mcp_env(),
                reasoning_effort=self._codex_reasoning_effort(),
            )
        else:
            from app.backend_claude import ClaudeBackend
            from app.pipeline import get_role
            from app.db import get_profile
            # Резолв роли: нет манифеста → чистый upstream-fallback
            # (inherit=True, config_dir по профилю, user_mcp пуст — как сегодня).
            try:
                rr = get_role(self.pipeline, self.role)
            except FileNotFoundError:
                rr = None
            inherit = rr.inherit_claude_md if rr else True
            config_dir = ""
            if self.profile:
                p = get_profile(self.profile)
                config_dir = p["config_dir"] if p else ""
            # F2: user-MCP подмешиваем ТОЛЬКО при mcp_servers=="all" (tasks-pm);
            # default/список — без user-MCP (1:1 upstream).
            user_mcp: dict = {}
            if rr is not None and rr.mcp_servers == "all":
                user_mcp = _load_user_mcp_servers(config_dir)
            return ClaudeBackend(
                model=self.model, cwd=self.cwd,
                system_prompt=self.system_prompt,
                resume_session_id=resume,
                mcp_servers=self.mcp_servers,
                is_orchestrator=self.is_orchestrator,
                scope_mcp_servers=_load_scope_mcp_servers(self.scope),
                config_dir=config_dir,
                inherit_claude_md=inherit,
                user_mcp_servers=user_mcp,
            )

    def _codex_reasoning_effort(self) -> str:
        return "high"

    def _spawn_bg(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        def _on_done(t):
            self._background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    logger.warning(f"[{self.name}] background task failed: {exc}")
        task.add_done_callback(_on_done)
        return task

    def _build_codex_mcp_env(self) -> dict[str, str]:
        env = {}
        for _name, cfg in self.mcp_servers.items():
            for k, v in cfg.get("env", {}).items():
                env[k] = str(v)
        return env

    async def start(self, initial_message: str | None = None) -> None:
        if initial_message:
            await self.send(initial_message)
        else:
            self.status = AgentStatus.IDLE
            self._persist()

    async def send(self, message: str) -> None:
        if self._compacting:
            self._pending_messages.append(message)
            self._log("user_message", message)
            self._log("status", f"message queued (compact in progress, {len(self._pending_messages)} pending)")
            return

        if self.status == AgentStatus.RUNNING:
            if self.backend_type == "codex":
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued ({len(self._pending_messages)} pending)")
                return
            self._log("user_message", message)
            try:
                backend = await self._ensure_backend()
                await backend.send(message)
                return
            except Exception as e:
                logger.warning(f"[{self.name}] mid-turn inject failed, queueing: {e}")
                self._pending_messages.append(message)
                self._log("status", f"inject failed, queued ({len(self._pending_messages)} pending)")
                return

        async with self._lifecycle_lock:
            if self.status == AgentStatus.RUNNING:
                if self.backend_type != "codex":
                    self._log("user_message", message)
                    try:
                        backend = await self._ensure_backend()
                        await backend.send(message)
                        return
                    except Exception as e:
                        logger.warning(f"[{self.name}] mid-turn inject failed in lock, queueing: {e}")
                self._pending_messages.append(message)
                self._log("user_message", message)
                self._log("status", f"message queued (race, {len(self._pending_messages)} pending)")
                return

            if self._hibernate_task and not self._hibernate_task.done():
                self._hibernate_task.cancel()
                self._hibernate_task = None

            if self._hibernated:
                logger.info(f"[{self.name}] waking from hibernate")
                self._hibernated = False

            self.progress_pct = 0
            self.progress_status = ""
            self._log("user_message", message)

            did_inject = False
            pending_th = ""
            templates_changed = False
            if self.session_id and self._current_prompt and not self._prompt_injected:
                from app.prompting import prompt_template_hash
                current_th = prompt_template_hash(self.role)
                old_th = self._template_hash or current_th
                templates_changed = old_th != current_th
                pending_th = current_th
                message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                did_inject = True

            if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
                self._did_report = False
                self._bump_turn_gen()
                self._turn_logs = []
                self._turn_start = asyncio.get_event_loop().time()
                self._last_msg_time = self._turn_start
                self.status = AgentStatus.RUNNING
                self._persist()

            try:
                backend = await self._ensure_backend()
            except Exception:
                self.status = AgentStatus.IDLE
                self._persist()
                raise

            await backend.send(message)

            if did_inject:
                if templates_changed:
                    self._log("status", f"prompt updated → {pending_th}")
                self._template_hash = pending_th
                self._prompt_injected = True
                self.system_prompt = self._current_prompt

            if self.backend_type == "codex":
                self._listen_task = asyncio.create_task(self._codex_turn_loop())

    async def _ensure_backend(self, force_fresh: bool = False):
        if self._backend is not None:
            if not force_fresh:
                return self._backend
            await self._disconnect_backend()
        self._backend = self._make_backend(force_fresh=force_fresh)
        try:
            await self._backend.connect()
        except Exception as e:
            logger.error(f"[{self.name}] backend connect failed: {e}")
            self._log("error", f"connect failed: {e}")
            self._backend = None
            raise
        if self.backend_type != "codex":
            self._listen_task = asyncio.create_task(self._claude_event_loop())
            self._listen_task.add_done_callback(self._on_task_done)
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return self._backend

    # ── Event loops ──

    MAX_CONSECUTIVE_FAILURES = 5

    async def _claude_event_loop(self) -> None:
        logger.info(f"[{self.name}] claude event loop started")
        consecutive_failures = 0
        while True:
            try:
                if self._backend is None:
                    logger.warning(f"[{self.name}] event loop: backend is None, exiting")
                    return
                async for event in self._backend.events():

exec
/usr/bin/zsh -lc "sed -n '1,240p' app/db.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""SQLite storage for sessions and logs."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"


def _resolve_db_path() -> Path:
    """Путь к БД: ORCHESTRA_DB_PATH из env (если задан) или дефолт data/orchestra.db.

    Позволяет разным worktree/веткам и тестам держать свою БД, не блокируя
    друг друга через SQLite-лок при параллельной работе.
    """
    override = os.getenv("ORCHESTRA_DB_PATH", "").strip()
    if not override:
        return _DEFAULT_DB_PATH
    p = Path(override)
    return p if p.is_absolute() else (Path(__file__).parent.parent / p)


DB_PATH = _resolve_db_path()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                cwd TEXT NOT NULL,
                model TEXT NOT NULL,
                system_prompt TEXT DEFAULT '',
                status TEXT DEFAULT 'starting',
                session_id TEXT,
                cost_usd REAL DEFAULT 0.0,
                worktree_path TEXT,
                branch TEXT,
                is_orchestrator INTEGER DEFAULT 0,
                color TEXT DEFAULT '',
                mcp_servers_custom TEXT DEFAULT '',
                profile TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(name, scope)
            );
            CREATE TABLE IF NOT EXISTS profiles (
                name TEXT PRIMARY KEY,
                config_dir TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);

            CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_inbox_session ON inbox(session_id, status);

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS test_lock (
                scope TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                reason TEXT DEFAULT '',
                acquired_at TEXT NOT NULL
            );
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS tm_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prefix TEXT NOT NULL DEFAULT 'TASK',
                scope TEXT UNIQUE,
                yougile_project_id TEXT,
                yougile_board_id TEXT,
                yougile_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(prefix)
            );
            CREATE TABLE IF NOT EXISTS tm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                par_number INTEGER NOT NULL,
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
                paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
                status TEXT NOT NULL DEFAULT 'backlog',
                assignee TEXT NOT NULL DEFAULT '',
                yougile_task_id TEXT UNIQUE,
                sync_revision INTEGER NOT NULL DEFAULT 0,
                worker_session_id TEXT,
                git_commits TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                paid_at TEXT,
                CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
            );
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id);
            CREATE TABLE IF NOT EXISTS tm_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                balance_rub INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL REFERENCES tm_clients(id),
                amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                date TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_payment_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL REFERENCES tm_payments(id),
                task_id INTEGER NOT NULL REFERENCES tm_tasks(id),
                amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tm_alloc_payment ON tm_payment_allocations(payment_id);
            CREATE INDEX IF NOT EXISTS idx_tm_alloc_task ON tm_payment_allocations(task_id);
            CREATE TABLE IF NOT EXISTS tm_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tm_tasks(id),
                direction TEXT NOT NULL DEFAULT 'push',
                action TEXT NOT NULL,
                sync_revision INTEGER,
                payload TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tm_sync_task ON tm_sync_log(task_id);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status);
            CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                five_hour_pct REAL DEFAULT 0,
                seven_day_pct REAL DEFAULT 0,
                five_hour_resets_at TEXT,
                seven_day_resets_at TEXT,
                total_cost_usd REAL DEFAULT 0,
                active_agents INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_snapshots(ts);
        """)
        _migrate(c)


def _reconstruct_costs(c) -> None:
    import re as _re
    sessions = c.execute("SELECT id FROM sessions").fetchall()
    for s in sessions:
        logs = c.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='status' "
            "AND (content LIKE 'turn ended%$%' OR content LIKE 'turn done%$%') ORDER BY id ASC",
            (s["id"],),
        ).fetchall()
        prev = 0.0
        real_cost = 0.0
        for l in logs:
            m = _re.search(r'\$(\d+\.?\d*)', l["content"])
            if not m:
                continue
            val = float(m.group(1))
            if val == 0:
                continue
            if val < prev:
                real_cost += prev
            prev = val
        real_cost += prev
        c.execute("UPDATE sessions SET cost_usd=?, cost_usd_cached=0, cost_reset_v1=1 WHERE id=?",
                  (round(real_cost, 4), s["id"]))


codex
I found one likely merge artifact already: some code paths now trust the denormalized `is_orchestrator` column, while others still use the old static role set. That can matter for manifest-defined orchestrator roles like `pm-glava` and `coder`, so I’m checking all active-worker/orchestrator filters before calling it.
exec
/usr/bin/zsh -lc "sed -n '1,180p' app/mcp_stdio.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc "sed -n '1160,1270p' app/main.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
    return {
        "anthropic": anthropic_data,
        "orchestra": _get_agents_cost(),
    }


SNAPSHOT_INTERVAL = 300


async def _usage_snapshot_loop():
    from app.db import usage_save_snapshot, usage_cleanup_old
    await asyncio.sleep(10)
    while True:
        try:
            token, refresh_token, _tier = _read_oauth_credentials()
            if token:
                try:
                    data = await _fetch_anthropic_usage(token)
                except PermissionError:
                    if refresh_token:
                        new_token = await _refresh_oauth_token(refresh_token)
                        if new_token:
                            data = await _fetch_anthropic_usage(new_token)
                        else:
                            data = None
                    else:
                        data = None
                except Exception:
                    data = None

                if data:
                    fh = data.get("five_hour") or {}
                    sd = data.get("seven_day") or {}
                    cost = sum(s.cost_usd for s in manager.sessions.values())
                    active = sum(1 for s in manager.sessions.values() if s.status.value == "running")
                    usage_save_snapshot(
                        fh.get("utilization", 0), sd.get("utilization", 0),
                        fh.get("resets_at", ""), sd.get("resets_at", ""),
                        round(cost, 4), active,
                    )
                    _usage_cache["data"] = data
                    _usage_cache["ts"] = time.time()
                    _save_usage_cache()
            usage_cleanup_old(30)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logging.getLogger(__name__).error(f"usage snapshot error: {e}")
        await asyncio.sleep(SNAPSHOT_INTERVAL)


@app.get("/api/usage/history")
async def usage_history(hours: int = 24):
    from app.db import usage_get_history
    return usage_get_history(hours)


@app.post("/api/report_bug")
async def report_bug_endpoint(req: Request):
    data = await req.json()
    title = data.get("title", "Untitled")
    description = data.get("description", "")
    reporter = data.get("reporter", "unknown")
    scope = data.get("scope", "")
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## [{ts}] {title}\n- **Reporter:** {reporter}\n- **Scope:** {scope}\n{description}\n"
    bugs_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "BUGS.md")
    try:
        with open(bugs_path, "a") as f:
            f.write(entry)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"result": f"Bug reported: {title}"}


@app.get("/api/orchestrators")
async def list_orchestrators():
    from app.prompting import is_orchestrator_role
    active = [s.to_dict() for s in manager.sessions.values() if s.is_orchestrator]
    active_ids = {s["id"] for s in active}
    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
    result = active + db_orchs
    running_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "running"}
    waiting_scopes = {s.scope for s in manager.sessions.values() if s.status.value == "waiting"}
    for o in result:
        o["any_running"] = o.get("scope", "") in running_scopes
        o["any_waiting"] = o.get("scope", "") in waiting_scopes
    return result


@app.delete("/api/orchestrators/{name}")
async def delete_orchestrator(name: str, scope: str, delete_tg_topics: bool = False):
    result = await manager.remove_scope(scope, delete_tg_topics=delete_tg_topics)
    return {"ok": True, **result}


@app.post("/api/orchestrators/{name}/change-scope")
async def change_orchestrator_scope_endpoint(name: str, req: ChangeScopeRequest):
    new_scope = req.new_scope.rstrip("/")
    new_cwd = (req.new_cwd or req.new_scope).rstrip("/")
    if not _is_safe_path(new_scope) or not _is_safe_path(new_cwd):
        return JSONResponse({"error": "path not in allowed roots"}, status_code=403)
    result = await manager.change_orchestrator_scope(
        name, req.old_scope.rstrip("/"), new_scope, new_cwd)
    if result.get("error"):
        return JSONResponse(result, status_code=409)
    return result


@app.get("/api/test-lock")

 succeeded in 0ms:
"""External stdio MCP server for Orchestra.

Runs as a separate process, communicates with Orchestra via HTTP API.
Avoids the in-process SDK control_request deadlock (issue #425/#701).

Usage: python -m app.mcp_stdio
"""

import json
import logging
import os
import sys

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("orchestra-mcp")

ORCHESTRA_URL = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888")
SCOPE = os.environ.get("ORCHESTRA_SCOPE", "")
ROLE = os.environ.get("ORCHESTRA_ROLE", "orchestrator")
WORKER_NAME = os.environ.get("WORKER_NAME", "worker")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

mcp = FastMCP("orchestra")


def _auth_headers() -> dict:
    if _INTERNAL_TOKEN:
        return {"Authorization": f"Bearer {_INTERNAL_TOKEN}"}
    return {}


async def _api(method: str, path: str, **kwargs) -> dict | list | None:
    t = kwargs.pop("timeout", 30)
    headers = _auth_headers()
    async with httpx.AsyncClient(base_url=ORCHESTRA_URL, timeout=t, headers=headers) as client:
        if method == "GET":
            r = await client.get(path, params=kwargs.get("params"))
        elif method == "POST":
            r = await client.post(path, json=kwargs.get("json"))
        elif method == "PUT":
            r = await client.put(path, json=kwargs.get("json"), params=kwargs.get("params"))
        elif method == "DELETE":
            r = await client.delete(path, params=kwargs.get("params"))
        else:
            return None
        if r.status_code >= 400:
            return {"error": r.text}
        try:
            return r.json()
        except Exception as e:
            return {"error": f"invalid JSON response (status={r.status_code}): {r.text[:200]}"}


@mcp.tool()
async def spawn_worker(name: str, task: str, repo_path: str,
                       model: str = "",
                       system_prompt: str = "",
                       task_id: str = "",
                       description: str = "",
                       base_branch: str = "",
                       role: str = "worker",
                       mcp_servers: str = "",
                       owned_dirs: str = "",
                       tg_topic: bool = False) -> str:
    """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose explicitly: claude-opus-4-8[1m] for research/planning/long-lived, claude-sonnet-4-6 for implementation from spec, gpt-5.5 for Codex.
    base_branch — от какой ветки ответвить worktree воркера. Пусто ("") = авто по стратегии пайплайна (parent → от ветки родителя, иначе main); явно указанная ветка переопределяет стратегию.
    mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
    tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
    if not model:
        return "Error: model is required. Choose: claude-opus-4-8[1m] (think), claude-sonnet-4-6 (type), gpt-5.5 (codex)"
    scope = SCOPE or repo_path
    body = {
        "name": name, "scope": scope, "cwd": repo_path,
        "model": model, "system_prompt": system_prompt,
        "use_worktree": True, "repo_path": repo_path,
        "base_branch": base_branch,
        "role": role,
        "parent_name": WORKER_NAME,
    }
    if mcp_servers:
        import json
        try:
            parsed = json.loads(mcp_servers)
            if isinstance(parsed, dict):
                body["mcp_servers"] = parsed
            else:
                return "Error: mcp_servers must be a JSON object, e.g. {\"playwright\": {\"command\": \"npx\", \"args\": [...]}}"
        except json.JSONDecodeError as e:
            return f"Error: mcp_servers is not valid JSON: {e}"
    if owned_dirs:
        import json
        try:
            parsed = json.loads(owned_dirs)
            if isinstance(parsed, list):
                body["owned_dirs"] = parsed
            else:
                return "Error: owned_dirs must be a JSON array, e.g. [\"app/api/\", \"app/models/\"]"
        except json.JSONDecodeError as e:
            return f"Error: owned_dirs is not valid JSON: {e}"
    if task_id:
        body["task_id"] = task_id
    if description:
        body["description"] = description
    if tg_topic:
        body["tg_topic"] = True
    result = await _api("POST", "/api/sessions", json=body)
    if isinstance(result, dict) and result.get("error"):
        return f"Spawn failed: {result['error']}"
    await _api("POST", f"/api/sessions/{name}/send", json={
        "message": task, "scope": scope,
    })
    out = f"Worker '{name}' spawned. Model: {model}. Task sent."
    if isinstance(result, dict) and result.get("spawn_warning"):
        out += f"\n⚠️ {result['spawn_warning']}"
    return out


@mcp.tool()
async def acquire_test_lock(reason: str = "") -> str:
    """Захватить ГЛОБАЛЬНЫЙ эксклюзивный лок на ПОЛНЫЙ прогон тестов (фулл-сьют) для проекта.
    Бери его ТОЛЬКО перед полным прогоном и ТОЛЬКО с согласия PM. Узкие тесты этапа лока НЕ требуют.
    Занято другим агентом → вернётся отказ с именем держателя — НЕ запускай фулл-сьют, жди и попробуй позже.
    Всегда вызывай release_test_lock() после прогона."""
    result = await _api("POST", "/api/test-lock/acquire", json={
        "scope": SCOPE, "holder": WORKER_NAME, "reason": reason,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Lock error: {result['error']}"
    if result.get("acquired"):
        return f"Test lock ACQUIRED for '{WORKER_NAME}' (reason: {reason or 'n/a'}). Release it when done."
    return (f"Test lock BUSY — held by '{result.get('holder')}'. "
            f"Do NOT run the full suite. Wait and retry, or coordinate via PM.")


@mcp.tool()
async def release_test_lock() -> str:
    """Освободить глобальный тест-лок (если ты его держишь). Вызывай сразу после полного прогона."""
    result = await _api("POST", "/api/test-lock/release", json={
        "scope": SCOPE, "holder": WORKER_NAME,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Lock error: {result['error']}"
    if result.get("released"):
        return "Test lock released."
    return "Test lock was not held by you (nothing to release)."


@mcp.tool()
async def test_lock_status() -> str:
    """Кто сейчас держит глобальный тест-лок проекта (или свободен)."""
    result = await _api("GET", "/api/test-lock", params={"scope": SCOPE})
    if isinstance(result, dict) and result.get("error"):
        return f"Lock error: {result['error']}"
    if not result.get("held"):
        return "Test lock is FREE."
    return (f"Test lock HELD by '{result.get('holder')}' "
            f"(reason: {result.get('reason') or 'n/a'}, since {result.get('acquired_at')}).")


@mcp.tool()
async def send_message(to: str, message: str) -> str:
    """Send a message to any agent by name. Triggers a new turn."""
    result = await _api("POST", f"/api/sessions/{to}/send", json={
        "message": message, "sender": WORKER_NAME or ROLE, "scope": SCOPE,
    })
    if isinstance(result, dict) and result.get("error"):
        return f"Send failed: {result['error']}"
    parent = result.get("parent_name", "") if isinstance(result, dict) else ""
    if parent and parent != WORKER_NAME:
        return f"Message sent to '{to}'\n⚠️ This worker belongs to '{parent}'. Consider messaging '{parent}' instead."
    return f"Message sent to '{to}'"


_ORCH_ROLES = frozenset({"orchestrator", "sub-orchestrator"})



exec
/usr/bin/zsh -lc "sed -n '240,560p' app/db.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:


def _migrate(c) -> None:
    cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
    if "color" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
    if "context_pct" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
    if "context_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
    if "progress_pct" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN progress_pct INTEGER DEFAULT 0")
    if "progress_status" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN progress_status TEXT DEFAULT ''")
    if "backend_type" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN backend_type TEXT DEFAULT 'claude'")
    if "task_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN task_id TEXT DEFAULT ''")
    if "description" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN description TEXT DEFAULT ''")
    if "cost_usd_cached" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_usd_cached REAL DEFAULT 0.0")
    if "cost_reset_v1" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_reset_v1 INTEGER DEFAULT 0")
        _reconstruct_costs(c)
    proj_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_projects)").fetchall()}
    if proj_cols and "yougile_enabled" not in proj_cols:
        c.execute("ALTER TABLE tm_projects ADD COLUMN yougile_enabled INTEGER NOT NULL DEFAULT 0")
        c.execute("UPDATE tm_projects SET yougile_enabled = 1 WHERE id = 'parsing-hub'")
    if proj_cols and "prefix" not in proj_cols:
        c.execute("ALTER TABLE tm_projects ADD COLUMN prefix TEXT NOT NULL DEFAULT 'TASK'")
        c.execute("UPDATE tm_projects SET prefix = 'PAR' WHERE id = 'parsing-hub'")
        c.execute("UPDATE tm_projects SET prefix = 'ORC' WHERE id = 'orchestra'")
    if "total_turns" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_turns INTEGER DEFAULT 0")
    if "total_input_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_input_tokens INTEGER DEFAULT 0")
    if "total_output_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_output_tokens INTEGER DEFAULT 0")
    if "total_tool_calls" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_tool_calls INTEGER DEFAULT 0")
    if "template_hash" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN template_hash TEXT DEFAULT ''")
    if "mcp_servers_custom" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN mcp_servers_custom TEXT DEFAULT ''")
    bg_ddl = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bg_jobs'"
    ).fetchone()
    if bg_ddl and "type IN ('timer'" in bg_ddl[0]:
        _bg_cols = ("id", "type", "config", "message", "target_session_id", "target_name",
                    "target_scope", "created_by_name", "status", "error", "expires_at",
                    "trigger_at", "created_at", "triggered_at", "last_output")
        _bg_col_list = ", ".join(_bg_cols)
        c.execute("ALTER TABLE bg_jobs RENAME TO bg_jobs_old")
        c.execute("""
            CREATE TABLE bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            )
        """)
        c.execute(f"INSERT INTO bg_jobs ({_bg_col_list}) SELECT {_bg_col_list} FROM bg_jobs_old")
        c.execute("DROP TABLE bg_jobs_old")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status)")
    try:
        c.execute("DROP TABLE IF EXISTS tm_par_sequence")
    except Exception:
        pass
    for old_name in ("_tm_tasks_old", "tm_tasks_old"):
        old_exists = c.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{old_name}'").fetchone()
        if old_exists:
            c.execute("DROP TABLE IF EXISTS tm_tasks")
            c.execute(f"ALTER TABLE {old_name} RENAME TO tm_tasks")
            break
    try:
        auto_idx = [r[1] for r in c.execute("PRAGMA index_list(tm_tasks)").fetchall()
                    if r[1].startswith("sqlite_autoindex")]
    except Exception:
        auto_idx = []
    needs_recreate = False
    for idx in auto_idx:
        try:
            info = c.execute(f"PRAGMA index_info({idx})").fetchall()
            if [r[2] for r in info] == ["par_number"]:
                needs_recreate = True
                break
        except Exception:
            pass
    if needs_recreate:
        c.execute("ALTER TABLE tm_tasks RENAME TO _tm_tasks_old")
        c.execute("""CREATE TABLE tm_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            par_number INTEGER NOT NULL,
            project_id TEXT NOT NULL REFERENCES tm_projects(id),
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
            paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
            status TEXT NOT NULL DEFAULT 'backlog', assignee TEXT NOT NULL DEFAULT '',
            yougile_task_id TEXT UNIQUE, sync_revision INTEGER NOT NULL DEFAULT 0,
            worker_session_id TEXT, git_commits TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            completed_at TEXT, paid_at TEXT,
            CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
        )""")
        c.execute("INSERT INTO tm_tasks SELECT * FROM _tm_tasks_old")
        c.execute("DROP TABLE _tm_tasks_old")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status)")
    for tbl in ("tm_payment_allocations", "tm_sync_log"):
        try:
            schema = c.execute(f"SELECT sql FROM sqlite_master WHERE name='{tbl}' AND type='table'").fetchone()
            if schema and "tm_tasks_old" in schema[0]:
                old_name = f"_{tbl}_fix"
                c.execute(f"ALTER TABLE {tbl} RENAME TO {old_name}")
                create_sql = schema[0].replace('"tm_tasks_old"', 'tm_tasks').replace("tm_tasks_old", "tm_tasks")
                c.execute(create_sql)
                c.execute(f"INSERT INTO {tbl} SELECT * FROM {old_name}")
                c.execute(f"DROP TABLE {old_name}")
        except Exception:
            pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
    task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
    if task_cols and "priority" not in task_cols:
        c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
    client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
    if client_cols and "journal_yougile_id" not in client_cols:
        c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
    if "role" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
        c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
    if "parent_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT DEFAULT ''")
    if "parent_name" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN parent_name TEXT DEFAULT ''")
    if "pipeline" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN pipeline TEXT DEFAULT ''")
        c.execute("UPDATE sessions SET is_orchestrator = 1 WHERE role IN ('orchestrator', 'sub-orchestrator')")
    if "profile" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT ''")
    if "owned_dirs" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
    if "tg_topic" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN tg_topic INTEGER DEFAULT 0")
    # Идемпотентный сид профиля 'personal' (config_dir="" → env процесса, как сегодня).
    # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
    c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")


def save_session(s: dict) -> None:
    s.setdefault("context_pct", 0)
    s.setdefault("context_tokens", 0)
    s.setdefault("progress_pct", 0)
    s.setdefault("progress_status", "")
    s.setdefault("backend_type", "claude")
    s.setdefault("task_id", "")
    s.setdefault("description", "")
    s.setdefault("cost_usd_cached", 0.0)
    s.setdefault("total_turns", 0)
    s.setdefault("total_input_tokens", 0)
    s.setdefault("total_output_tokens", 0)
    s.setdefault("total_tool_calls", 0)
    s.setdefault("template_hash", "")
    s.setdefault("role", "worker")
    s.setdefault("parent_id", "")
    s.setdefault("parent_name", "")
    s.setdefault("pipeline", "")
    s.setdefault("profile", "")
    s.setdefault("mcp_servers_custom", "")
    s.setdefault("owned_dirs", "")
    s.setdefault("tg_topic", 0)
    with _conn() as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
                status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
                color, created_at, finished_at, context_pct, context_tokens,
                progress_pct, progress_status, backend_type, task_id, description,
                cost_usd_cached,
                total_turns, total_input_tokens, total_output_tokens, total_tool_calls,
                template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
                profile, owned_dirs, tg_topic)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
                :color, :created_at, :finished_at, :context_pct, :context_tokens,
                :progress_pct, :progress_status, :backend_type, :task_id, :description,
                :cost_usd_cached,
                :total_turns, :total_input_tokens, :total_output_tokens, :total_tool_calls,
                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
                :profile, :owned_dirs, :tg_topic)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                system_prompt=excluded.system_prompt,
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                cost_usd_cached=excluded.cost_usd_cached,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
                cwd=excluded.cwd,
                color=excluded.color,
                finished_at=excluded.finished_at,
                context_pct=excluded.context_pct,
                context_tokens=excluded.context_tokens,
                progress_pct=excluded.progress_pct,
                progress_status=excluded.progress_status,
                backend_type=excluded.backend_type,
                task_id=excluded.task_id,
                description=excluded.description,
                total_turns=excluded.total_turns,
                total_input_tokens=excluded.total_input_tokens,
                total_output_tokens=excluded.total_output_tokens,
                total_tool_calls=excluded.total_tool_calls,
                template_hash=excluded.template_hash,
                role=excluded.role,
                parent_id=excluded.parent_id,
                parent_name=excluded.parent_name,
                mcp_servers_custom=excluded.mcp_servers_custom,
                pipeline=excluded.pipeline,
                profile=excluded.profile,
                owned_dirs=excluded.owned_dirs,
                tg_topic=excluded.tg_topic
        """, s)


def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
    """Move an orchestrator's session to a new scope in one transaction.

    Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
    bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
    session_id (Claude resume token) is left intact — context survives.

    Rejected if another session with the same name already lives in new_scope
    (UNIQUE(name, scope)). tm_projects/test_lock migration is skipped on UNIQUE
    collision (target already taken) but the session move still succeeds.
    """
    with _conn() as c:
        row = c.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return {"error": f"session not found: {session_id}"}
        name = row["name"]
        clash = c.execute(
            "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
            (name, new_scope, session_id),
        ).fetchone()
        if clash:
            return {"error": f"session '{name}' already exists in scope '{new_scope}'"}

        cur = c.execute(
            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
            (new_scope, new_cwd, session_id, old_scope),
        )
        if cur.rowcount == 0:
            return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}

        tm_migrated = False
        target_taken = c.execute("SELECT 1 FROM tm_projects WHERE scope=?", (new_scope,)).fetchone()
        if not target_taken:
            cur = c.execute("UPDATE tm_projects SET scope=? WHERE scope=?", (new_scope, old_scope))
            tm_migrated = cur.rowcount > 0

        c.execute(
            "UPDATE bg_jobs SET target_scope=? WHERE target_scope=? AND status IN ('active','triggering')",
            (new_scope, old_scope),
        )

        lock_target_taken = c.execute("SELECT 1 FROM test_lock WHERE scope=?", (new_scope,)).fetchone()
        if not lock_target_taken:
            c.execute("UPDATE test_lock SET scope=? WHERE scope=?", (new_scope, old_scope))

        return {"ok": True, "scope": new_scope, "cwd": new_cwd, "tm_project_migrated": tm_migrated}


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_by_name(name: str, scope: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE name = ? AND scope = ? AND status != 'archived'",
            (name, scope),
        ).fetchone()
        return dict(row) if row else None


# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──

def list_profiles() -> list[dict]:
    """Все профили, отсортированы по имени: ``[{"name":..., "config_dir":...}]``."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name, config_dir FROM profiles ORDER BY name"
        ).fetchall()
        return [{"name": r["name"], "config_dir": r["config_dir"]} for r in rows]


def get_profile(name: str) -> dict | None:
    """Один профиль по имени или ``None``, если не найден."""
    with _conn() as c:
        row = c.execute(
            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        return {"name": row["name"], "config_dir": row["config_dir"]} if row else None



exec
/usr/bin/zsh -lc 'git diff --name-status HEAD''^1 HEAD && git diff --name-status HEAD''^2 HEAD' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
M	app/backend_claude.py
M	app/db.py
M	app/main.py
M	app/manager.py
M	app/mcp_stdio.py
A	app/pipeline.py
M	app/session.py
M	app/static/js/app.js
M	app/templates/dashboard.html
M	app/workspace.py
A	docs/tasks/pipeline-rebase/codex-review-plan.md
A	docs/tasks/pipeline-rebase/plan.md
A	docs/tasks/pipeline-rebase/research.md
A	pipelines/default/pipeline.yaml
A	pipelines/default/prompts/base.md
A	pipelines/default/prompts/modules/git-workflow.md
A	pipelines/default/prompts/modules/orchestration.md
A	pipelines/default/prompts/modules/report-format.md
A	pipelines/default/prompts/roles/full-cycle.md
A	pipelines/default/prompts/roles/orchestrator.md
A	pipelines/default/prompts/roles/sub-orchestrator.md
A	pipelines/default/prompts/roles/worker.md
A	pipelines/default/prompts/skills/codex-debate.md
A	pipelines/default/prompts/skills/html-artifacts.md
A	pipelines/default/prompts/skills/vps-deploy.md
A	pipelines/tasks-pm/pipeline.yaml
A	pipelines/tasks-pm/prompts/_pipeline.md
A	pipelines/tasks-pm/prompts/base.md
A	pipelines/tasks-pm/prompts/roles/analyst.md
A	pipelines/tasks-pm/prompts/roles/base-orchestrator.md
A	pipelines/tasks-pm/prompts/roles/coder.md
A	pipelines/tasks-pm/prompts/roles/pm-fichi.md
A	pipelines/tasks-pm/prompts/roles/pm-glava.md
A	pipelines/tasks-pm/prompts/roles/secretary.md
A	pipelines/tasks-pm/prompts/roles/tester.md
A	pipelines/tasks-pm/prompts/roles/worker.md
A	pipelines/tasks-pm/templates/analysis.md
A	pipelines/tasks-pm/templates/impl.md
A	pipelines/tasks-pm/templates/pm.md
A	pipelines/tasks-pm/templates/sprint.md
A	pipelines/tasks-pm/templates/testing.md
M	pyproject.toml
A	scripts/extract-manifest.py
M	tests/test_api.py
M	tests/test_db.py
A	tests/test_default_equals_upstream.py
A	tests/test_default_pipeline.py
M	tests/test_manager.py
M	tests/test_mcp_stdio.py
A	tests/test_pipeline.py
A	tests/test_scaffold.py
M	tests/test_session.py
A	tests/test_tasks_pm_pipeline.py
M	tests/test_workspace.py
M	uv.lock
M	CHANGELOG.md
M	TODO.md
M	app/auth.py
M	app/backend_claude.py
A	app/backend_protocol.py
M	app/bg_jobs.py
A	app/deps.py
M	app/main.py
M	app/manager.py
M	app/mcp_stdio.py
A	app/prompting.py
D	app/prompts/modules/codex-review.md
A	app/prompts/modules/orchestration.md
M	app/prompts/roles/full-cycle.md
M	app/prompts/roles/orchestrator.md
D	app/prompts/roles/reviewer.md
M	app/prompts/roles/sub-orchestrator.md
D	app/prompts/roles/watcher.md
M	app/prompts/roles/worker.md
A	app/prompts/skills/codex-debate.md
A	app/routes/__init__.py
A	app/routes/bg.py
A	app/routes/proxy.py
A	app/routes/tm.py
M	app/session.py
M	app/static/css/style.css
M	app/static/js/app.js
M	app/tg_bridge.py
M	app/tm.py
D	app/tools.py
M	app/workspace.py
A	docs/codex-full-review.md
A	docs/fork-analysis.md
A	docs/tasks/45/codex-review-impl.md
A	docs/tasks/45/codex-review-plan.md
A	docs/tasks/45/plan.md
A	docs/tasks/45/report.md
A	docs/tasks/45/research.md
A	docs/tasks/46/analysis.md
A	docs/tasks/debate-test/codex_architecture.md
A	docs/tasks/debate-test/codex_plan-review.md
A	docs/tasks/debate-test/codex_sessions.json
A	docs/tasks/debate-test/debate-report.md
A	docs/tasks/debate-test/plan.md
A	docs/tasks/guards/codex-review-impl.md
A	docs/tasks/guards/plan.md
A	docs/tasks/guards/report.md
A	docs/tasks/guards/research.md
A	docs/tasks/pipeline-rebase/codex-review-plan.md
A	docs/tasks/pipeline-rebase/plan.md
A	docs/tasks/pipeline-rebase/research.md
A	docs/tasks/visibility/plan.md
A	docs/tasks/visibility/report.md
A	docs/tasks/visibility/research.md
A	docs/tasks/wt-cleanup/plan.md
A	docs/tasks/wt-cleanup/report.md
A	docs/tasks/wt-cleanup/research.md
M	pipelines/default/pipeline.yaml
D	pipelines/default/prompts/modules/codex-review.md
A	pipelines/default/prompts/modules/orchestration.md
M	pipelines/default/prompts/roles/full-cycle.md
M	pipelines/default/prompts/roles/orchestrator.md
D	pipelines/default/prompts/roles/reviewer.md
M	pipelines/default/prompts/roles/sub-orchestrator.md
D	pipelines/default/prompts/roles/watcher.md
A	pipelines/default/prompts/skills/codex-debate.md
M	tests/test_default_equals_upstream.py
M	tests/test_default_pipeline.py
M	tests/test_manager.py
M	tests/test_workspace.py
M	uv.lock

exec
/usr/bin/zsh -lc "sed -n '70,170p' app/main.py && sed -n '390,450p' app/main.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{tb}")
    return JSONResponse({"error": f"Internal: {exc}"}, status_code=500)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        if check_internal_token(request.headers.get("authorization", "")):
            return await call_next(request)
        if not is_auth_enabled():
            return await call_next(request)
        if not requires_auth(path, method):
            return await call_next(request)
        token = request.cookies.get("session")
        if token and validate_session(token):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)


app.add_middleware(AuthMiddleware)


class CreateSessionRequest(BaseModel):
    name: str
    cwd: str
    model: str = "claude-sonnet-4-6"
    scope: Optional[str] = None
    system_prompt: str = ""
    use_worktree: bool = False
    repo_path: Optional[str] = None
    is_orchestrator: bool = False
    role: str = ""
    task_id: str = ""
    description: str = ""
    base_branch: str = ""
    parent_name: str = ""
    mcp_servers: dict = {}
    pipeline: str = ""
    profile: str = ""
    owned_dirs: list[str] = []
    tg_topic: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,49}$", v):
            raise ValueError("name must be alphanumeric with ._- allowed, 1-50 chars")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v):
        resolved = resolve_model(v)
        if resolved not in MODELS:
            raise ValueError(f"unknown model '{v}'. Available: {', '.join(MODELS.keys())}")
        return resolved

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, v):
        if not Path(v).is_dir():
            raise ValueError(f"cwd does not exist: {v}")
        return v

    @model_validator(mode="after")
    def validate_worktree(self):
        if self.use_worktree and not self.repo_path:
            raise ValueError("repo_path required when use_worktree=True")
        return self


class ProfileRequest(BaseModel):
    """Тело запроса для создания/обновления профиля Claude."""
    name: str
    config_dir: str = ""


class SendRequest(BaseModel):
    message: str
    scope: str
    sender: str | None = None


class ScopeRequest(BaseModel):
    scope: str


class TestLockRequest(BaseModel):
    scope: str
    holder: str
    reason: str = ""

    return items


@app.get("/api/role-icons")
async def role_icons():
    from app.prompting import get_role_icons
    return get_role_icons()


@app.get("/api/sessions")
async def list_sessions(scope: Optional[str] = None):
    return manager.list_sessions(scope)


@app.post("/api/sessions", status_code=201)
async def create_session(req: CreateSessionRequest):
    if not _is_safe_path(req.cwd):
        return JSONResponse({"error": f"cwd not in allowed paths: {req.cwd}"}, status_code=403)
    scope = req.scope or req.cwd
    try:
        session = await manager.create_session(
            name=req.name,
            scope=scope,
            cwd=req.cwd,
            model=req.model,
            system_prompt=req.system_prompt,
            use_worktree=req.use_worktree,
            repo_path=req.repo_path,
            is_orchestrator=req.is_orchestrator,
            role=req.role,
            task_id=req.task_id,
            description=req.description,
            base_branch=req.base_branch,
            parent_name=req.parent_name,
            mcp_servers=req.mcp_servers,
            pipeline=req.pipeline,
            profile=req.profile,
            owned_dirs=req.owned_dirs,
            tg_topic=req.tg_topic,
        )
        d = session.to_dict()
        if session._spawn_warning:
            d["spawn_warning"] = session._spawn_warning
        return d
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except sqlite3.IntegrityError:
        return JSONResponse({"error": f"session '{req.name}' already exists"}, status_code=409)
    except Exception as e:
        import traceback
        logging.getLogger(__name__).error(f"spawn failed: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/pipelines")
async def get_pipelines():
    """Только валидные пайплайны для UI-дропдаунa: ``[{name, description, roles}]``."""
    return [
        {"name": p["name"], "description": p["description"], "roles": p["roles"]}
        for p in list_pipelines()
        if p["valid"]

exec
/usr/bin/zsh -lc 'rg -n "pipeline|profile|is_orchestrator|base_branch|docs_feature|docsFeature|profiles|pipelines" app/static/js/app.js app/templates/dashboard.html -S' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
app/templates/dashboard.html:41:                <button id="profiles-btn" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors text-slate-400" title="Profiles">🗂</button>
app/templates/dashboard.html:42:                <div id="profiles-dropdown" class="absolute right-0 top-full mt-1 w-[320px] glass glow rounded-xl p-3 z-50 hidden">
app/templates/dashboard.html:46:                    <div id="profiles-list" class="space-y-1.5 mb-2"></div>
app/templates/dashboard.html:48:                        <input id="profile-new-name" type="text" placeholder="name" class="w-full px-2 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs focus:border-indigo-500 focus:outline-none">
app/templates/dashboard.html:49:                        <input id="profile-new-dir" type="text" placeholder="config dir (пусто = ~/.claude)" class="w-full px-2 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs focus:border-indigo-500 focus:outline-none">
app/templates/dashboard.html:50:                        <button id="profile-add-btn" class="w-full py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-xs font-medium transition-colors">Add</button>
app/templates/dashboard.html:51:                        <div id="profile-error" class="text-[10px] text-red-400 hidden"></div>
app/templates/dashboard.html:88:                    <select id="orch-profile" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
app/templates/dashboard.html:93:                    <select id="orch-pipeline" class="w-full px-3 py-2 bg-slate-900 border border-slate-800 rounded-lg text-sm focus:border-indigo-500 focus:outline-none">
app/static/js/app.js:140:    $('#orch-pipeline').addEventListener('change', populateRoleDropdown);
app/static/js/app.js:324:let _pipelineRoles = {};  // карта pipeline-name → [roles]
app/static/js/app.js:328:        const profiles = await api('/api/profiles');
app/static/js/app.js:329:        const select = $('#orch-profile');
app/static/js/app.js:331:        for (const p of profiles) {
app/static/js/app.js:339:        const def = profiles.find(p => p.name === 'personal') || profiles[0];
app/static/js/app.js:346:        const pipelines = await api('/api/pipelines');
app/static/js/app.js:347:        const select = $('#orch-pipeline');
app/static/js/app.js:349:        _pipelineRoles = {};
app/static/js/app.js:350:        for (const p of pipelines) {
app/static/js/app.js:351:            _pipelineRoles[p.name] = p.roles || [];
app/static/js/app.js:364:    const roles = _pipelineRoles[$('#orch-pipeline').value] || [];
app/static/js/app.js:631:    const profile = $('#orch-profile').value;
app/static/js/app.js:632:    const pipeline = $('#orch-pipeline').value;
app/static/js/app.js:639:        await api('/api/sessions', { method: 'POST', body: JSON.stringify({ name, cwd, model, profile, pipeline, role, is_orchestrator: true }) });
app/static/js/app.js:1310:    const roleKey = s.role || (s.is_orchestrator ? 'orchestrator' : 'worker');
app/static/js/app.js:3047:                    _row('Role', parsed.is_orchestrator ? '🎯 orchestrator' : '⚙️ worker');
app/static/js/app.js:5201:let _profilesDropdownOpen = false;
app/static/js/app.js:5204:    const btn = $('#profiles-btn');
app/static/js/app.js:5205:    const dropdown = $('#profiles-dropdown');
app/static/js/app.js:5209:        _profilesDropdownOpen = !_profilesDropdownOpen;
app/static/js/app.js:5210:        dropdown.classList.toggle('hidden', !_profilesDropdownOpen);
app/static/js/app.js:5211:        if (_profilesDropdownOpen) loadProfilesList();
app/static/js/app.js:5214:        if (_profilesDropdownOpen && !dropdown.contains(e.target) && e.target !== btn) {
app/static/js/app.js:5215:            _profilesDropdownOpen = false;
app/static/js/app.js:5219:    $('#profile-add-btn')?.addEventListener('click', async (e) => {
app/static/js/app.js:5221:        const name = $('#profile-new-name').value.trim();
app/static/js/app.js:5222:        const config_dir = $('#profile-new-dir').value.trim();
app/static/js/app.js:5223:        const errEl = $('#profile-error');
app/static/js/app.js:5227:            const res = await api('/api/profiles', { method: 'POST', body: JSON.stringify({ name, config_dir }) });
app/static/js/app.js:5228:            $('#profile-new-name').value = '';
app/static/js/app.js:5229:            $('#profile-new-dir').value = '';
app/static/js/app.js:5245:        const profiles = await api('/api/profiles');
app/static/js/app.js:5246:        const list = $('#profiles-list');
app/static/js/app.js:5249:        if (!profiles.length) {
app/static/js/app.js:5250:            list.innerHTML = '<div class="text-[10px] text-slate-500 text-center py-2">No profiles.</div>';
app/static/js/app.js:5253:        for (const p of profiles) {
app/static/js/app.js:5262:                ${isPersonal ? '' : `<button class="profile-del-btn text-[10px] px-1.5 py-0.5 bg-slate-700 hover:bg-red-900/60 rounded text-slate-400 hover:text-red-400 shrink-0" data-name="${escHtml(p.name)}" title="Delete">✕</button>`}
app/static/js/app.js:5266:        list.querySelectorAll('.profile-del-btn').forEach(b => {
app/static/js/app.js:5269:                const errEl = $('#profile-error');
app/static/js/app.js:5273:                    await api(`/api/profiles/${encodeURIComponent(b.dataset.name)}`, { method: 'DELETE' });

exec
/usr/bin/zsh -lc "rg -n \"get_all_sessions\\(|is_orchestrator_role\\(|is_orchestrator\\)\" app tests -S" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
tests/test_db.py:156:        parsing = get_all_sessions(scope=sample_session["scope"])
tests/test_db.py:170:        all_sessions = get_all_sessions()
app/db.py:579:def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
tests/test_manager.py:947:        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
app/prompting.py:19:def is_orchestrator_role(role: str) -> bool:
app/prompting.py:72:        fallback = _PROMPTS_DIR / "roles" / ("orchestrator.md" if is_orchestrator_role(role) else "worker.md")
app/prompting.py:159:    Accepts role string or legacy bool (is_orchestrator)."""
app/main.py:513:    is_orch = (found.get("is_orchestrator") if isinstance(found, dict) else found.is_orchestrator) or False
app/main.py:601:            for row in get_all_sessions():
app/main.py:1241:    db_orchs = [s for s in get_all_sessions() if is_orchestrator_role(s.get("role", "worker")) and s["id"] not in active_ids]
app/backend_claude.py:128:            permission_mode="default", can_use_tool=_make_auto_approve(self._is_orchestrator),
app/backend_claude.py:129:            disallowed_tools=_disallowed_tools(self._is_orchestrator),
app/tg_bridge.py:653:    for s in get_all_sessions():
app/tg_bridge.py:810:    orchs = [s for s in get_all_sessions() if s.get("tg_topic") or s.get("role", "worker") in ("orchestrator", "sub-orchestrator")]
app/tg_bridge.py:850:    for s in get_all_sessions():
app/manager.py:62:        orchs = [s for s in get_all_sessions()
app/manager.py:83:        workers = [s for s in get_all_sessions()
app/manager.py:125:    if is_orchestrator_role(role):
app/manager.py:209:    is_orch = rr.is_orchestrator if rr is not None else is_orchestrator_role(role)
app/manager.py:450:            for row in get_all_sessions(scope):
app/manager.py:699:        for row in get_all_sessions(scope):
app/manager.py:702:            if is_orchestrator_role(row.get("role", "worker")):
app/manager.py:713:        for row in get_all_sessions(scope):
app/manager.py:720:        for row in get_all_sessions(scope):
app/manager.py:814:        return is_orchestrator_role(role)
app/manager.py:830:        for row in get_all_sessions():
app/manager.py:843:                is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
app/manager.py:845:            is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
app/manager.py:966:        for row in get_all_sessions(scope):
app/manager.py:988:        for row in get_all_sessions(scope):
app/manager.py:1024:        orchs = [r for r in resumable if bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker"))]
app/manager.py:1025:        workers = [r for r in resumable if not (bool(r.get("is_orchestrator")) or is_orchestrator_role(r.get("role", "worker")))]
app/workspace.py:683:    for s in get_all_sessions():
app/session.py:179:        return is_orchestrator_role(self.role)

codex
The path traversal guards in `pipeline.py` and `workspace.py` are mostly real checks, including resolved-path containment after symlinks. I’m now looking for places where user-supplied pipeline/profile/worktree parameters bypass validation or where DB-loaded sessions are treated differently from live sessions.
exec
/usr/bin/zsh -lc "sed -n '560,640p' app/db.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:

def upsert_profile(name: str, config_dir: str) -> None:
    """Создать профиль или обновить его ``config_dir`` (по конфликту имени)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET config_dir = excluded.config_dir",
            (name, config_dir),
        )


def delete_profile(name: str) -> None:
    """Удалить профиль. Сид-профиль ``personal`` удалять запрещено."""
    if name == "personal":
        raise ValueError("Профиль 'personal' является сид-профилем и не может быть удалён")
    with _conn() as c:
        c.execute("DELETE FROM profiles WHERE name = ?", (name,))


def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
    with _conn() as c:
        archived_filter = "" if include_archived else " AND status != 'archived'"
        if scope:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE scope = ?{archived_filter} ORDER BY created_at DESC", (scope,)
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE 1=1{archived_filter} ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def rename_session(session_id: str, new_name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def archive_session(session_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )


def add_log(session_id: str, ts: datetime, type: str, content: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO logs (session_id, ts, type, content) VALUES (?, ?, ?, ?)",
            (session_id, ts.isoformat(), type, content),
        )
        return cur.lastrowid


def get_logs(session_id: str, after_id: int = 0, limit: int = 5000, conn=None) -> list[dict]:
    c = conn or _conn()
    try:
        if after_id > 0:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (session_id, after_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        else:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
    finally:
        if conn is None:
            c.close()


def get_logs_before(session_id: str, before_id: int, limit: int = 500) -> list[dict]:

exec
/usr/bin/zsh -lc "sed -n '940,1045p' app/manager.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
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

exec
/usr/bin/zsh -lc "sed -n '1120,1220p' app/tg_bridge.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc "sed -n '620,870p' app/tg_bridge.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
        try:
            await ensure_topics()
        except Exception as e:
            logger.error(f"Topic sync error: {e}")


async def start_bridge(manager):
    global bot, _manager, DEEPGRAM_API_KEY
    from dotenv import load_dotenv
    load_dotenv()

    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

    load_config()
    token = os.getenv("TG_BRIDGE_TOKEN", "")
    group = int(os.getenv("TG_BRIDGE_GROUP", config.get("group_id", 0)))

    if not token or not group:
        logger.info("TG Bridge disabled (no TG_BRIDGE_TOKEN/TG_BRIDGE_GROUP)")
        return

    _manager = manager
    config["group_id"] = group
    save_config()

    local_api = os.getenv("TG_LOCAL_API_URL", "")
    if local_api:
        import aiohttp as _aio
        for _attempt in range(10):
            try:
                async with _aio.ClientSession() as _s:
                    async with _s.get(local_api, timeout=_aio.ClientTimeout(total=2)):
                        pass
                break
            except Exception:
                logger.info(f"Waiting for Local Bot API ({_attempt+1}/10)...")
                await asyncio.sleep(2)
        from aiogram.client.telegram import TelegramAPIServer
        server = TelegramAPIServer(base=f"{local_api}/bot{{token}}/{{method}}", file=f"{local_api}/file/bot{{token}}/{{path}}")
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(api=server)
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None), session=session)
        logger.info(f"TG Bot using LOCAL API: {local_api}")
    else:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))

    _tasks.append(asyncio.create_task(_safe_polling()))
    _tasks.append(asyncio.create_task(_deferred_startup()))
    logger.info(f"TG Bridge started (polling immediate, topics deferred) | group={group}")


async def _deferred_startup():
    try:
        await ensure_topics()
        await _sync_all_topic_statuses()
        for name, thread_id in config["topics"].items():
            _tasks.append(asyncio.create_task(stream_logs(name, thread_id)))
        _tasks.append(asyncio.create_task(topic_sync_loop()))
        logger.info(f"TG deferred startup done | topics={len(config['topics'])}")
    except Exception as e:
        logger.error(f"TG deferred startup failed: {e}")


async def _safe_polling():
    while True:
        try:
            logger.info("TG polling started")
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"TG polling crashed: {e}, restarting in 10s")
            await asyncio.sleep(10)
        else:
            logger.warning("TG polling exited cleanly, restarting in 5s")
            await asyncio.sleep(5)


async def stop_bridge():
    for t in _tasks:
        t.cancel()
    _tasks.clear()
    if bot:
        await bot.session.close()


if __name__ == "__main__":
    import sys
    async def _main():
        from app.manager import SessionManager
        m = SessionManager()
        from app.db import init_db
        init_db()
        if len(sys.argv) > 1:
            os.environ["TG_BRIDGE_TOKEN"] = sys.argv[1]
        if len(sys.argv) > 2:
            os.environ["TG_BRIDGE_GROUP"] = sys.argv[2]
        await start_bridge(m)
        await asyncio.Event().wait()
    asyncio.run(_main())

 succeeded in 0ms:
    thread_id = config.get("topics", {}).pop(old_name, None)
    if thread_id is None:
        return {"error": f"no topic for '{old_name}'"}
    config["topics"][new_name] = thread_id
    topic_names = config.get("topic_names", {})
    old_display = topic_names.pop(old_name, None)
    new_display = _short_name(new_name)
    topic_names[new_name] = new_display
    config["topic_names"] = topic_names
    mirrors = config.get("mirrors", {})
    if old_name in mirrors:
        mirrors[new_name] = mirrors.pop(old_name)
        config["mirrors"] = mirrors
    if old_name in _topic_status:
        _topic_status[new_name] = _topic_status.pop(old_name)
    save_config()
    if bot:
        try:
            await bot.edit_forum_topic(
                chat_id=config["group_id"],
                message_thread_id=thread_id,
                name=new_display,
            )
        except Exception as e:
            logger.warning(f"Failed to rename TG topic {old_name} → {new_name}: {e}")
    return {"ok": True, "old_name": old_name, "new_name": new_name, "display": new_display, "thread_id": thread_id}


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _find_orch_for_scope(scope: str) -> str | None:
    from app.db import get_all_sessions
    for s in get_all_sessions():
        if s.get("role", "worker") in ("orchestrator", "sub-orchestrator") and s.get("scope", "").rstrip("/") == scope.rstrip("/"):
            return s["name"]
    return None


def _find_thread_for_scope(scope: str) -> int | None:
    orch_name = _find_orch_for_scope(scope)
    if orch_name:
        return config["topics"].get(orch_name)
    return None


async def _mirror_send_file(orch_name: str, tg_file, caption: str, is_photo: bool):
    mirror = config.get("mirrors", {}).get(orch_name)
    if not mirror or not bot:
        return
    chat_id = mirror.get("chat_id")
    topic_id = mirror.get("topic_id")
    if not chat_id:
        return
    try:
        if is_photo:
            await bot.send_photo(chat_id, tg_file, caption=caption, message_thread_id=topic_id)
        else:
            await bot.send_document(chat_id, tg_file, caption=caption, message_thread_id=topic_id)
    except Exception as e:
        logger.warning(f"Mirror file send failed for {orch_name}: {e}")


async def send_file_to_tg(path: str, caption: str, scope: str, sender: str, as_document: bool = False) -> dict:
    if not bot or not config["group_id"]:
        return {"error": "TG bridge not active"}
    from pathlib import Path as P
    fp = P(path)
    if not fp.exists():
        return {"error": f"file not found: {path}"}
    file_size = fp.stat().st_size
    if file_size == 0:
        return {"error": f"file is empty (0 bytes): {path}"}
    if file_size > 50 * 1024 * 1024:
        return {"error": "file too large (max 50MB)"}
    orch_name = _find_orch_for_scope(scope)
    thread_id = config["topics"].get(orch_name) if orch_name else None
    logger.info(f"send_file: path={path} size={file_size} scope={scope!r} orch={orch_name!r} group_id={config['group_id']} thread_id={thread_id}")
    if not thread_id:
        return {"error": f"no TG topic for scope: {scope}"}
    label = f"📎 {sender}: {caption}" if caption else f"📎 {sender}: {fp.name}"
    label = label[:1024]
    try:
        from aiogram.types import FSInputFile
        tg_file = FSInputFile(path, filename=fp.name)
        is_photo = not as_document and fp.suffix.lower() in _IMAGE_EXTS
        if is_photo:
            msg = await bot.send_photo(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
        else:
            msg = await bot.send_document(config["group_id"], tg_file, caption=label, message_thread_id=thread_id)
        logger.info(f"send_file: delivered msg_id={msg.message_id} chat_id={msg.chat.id} thread={getattr(msg, 'message_thread_id', None)}")
        if orch_name:
            mirror_file = FSInputFile(path, filename=fp.name)
            await _mirror_send_file(orch_name, mirror_file, label, is_photo)
        return {"ok": True, "message_id": msg.message_id, "chat_id": msg.chat.id}
    except TelegramRetryAfter as e:
        logger.warning(f"send_file flood: retry after {e.retry_after}s")
        await asyncio.sleep(e.retry_after + 0.5)
        try:
            tg_file2 = FSInputFile(path, filename=fp.name)
            if is_photo:
                msg2 = await bot.send_photo(config["group_id"], tg_file2, caption=label, message_thread_id=thread_id)
            else:
                msg2 = await bot.send_document(config["group_id"], tg_file2, caption=label, message_thread_id=thread_id)
            logger.info(f"send_file retry: delivered msg_id={msg2.message_id} chat_id={msg2.chat.id}")
            return {"ok": True, "message_id": msg2.message_id, "chat_id": msg2.chat.id}
        except Exception as e2:
            logger.error(f"send_file retry failed: {e2}")
            return {"error": f"Send failed after flood retry: {e2}"}
    except Exception as e:
        logger.error(f"send_file exception: type={type(e).__name__} err={e}")
        return {"error": str(e)}


_topic_status = {}


def _any_running_in_scope(scope: str) -> bool:
    if not _manager or not scope:
        return False
    for s in _manager.sessions.values():
        if s.scope == scope and s.status.value == "running":
            return True
    return False


async def check_scope_idle(orch_name: str, scope: str):
    if not _any_running_in_scope(scope):
        await _update_topic_status(orch_name, False)


async def _sync_all_topic_statuses():
    if not _manager or not bot:
        return
    for s in _manager.sessions.values():
        if s.role not in ("orchestrator", "sub-orchestrator"):
            continue
        name = s.name
        if name not in config["topics"]:
            continue
        is_running = _any_running_in_scope(s.scope)
        _topic_status.pop(name, None)
        await _update_topic_status(name, is_running)


_ICON_RUNNING = "5312016608254762256"
_ICON_IDLE = "5350392020785437399"


async def _update_topic_status(orch_name: str, is_running: bool):
    if _topic_status.get(orch_name) == is_running:
        return
    _topic_status[orch_name] = is_running
    short = (config.get("topic_names") or {}).get(orch_name) or _short_name(orch_name)
    icon_id = _ICON_RUNNING if is_running else _ICON_IDLE
    thread_id = config["topics"].get(orch_name)
    if thread_id and bot:
        try:
            await bot.edit_forum_topic(chat_id=config["group_id"], message_thread_id=thread_id,
                                       name=short, icon_custom_emoji_id=icon_id)
        except Exception as e:
            logger.debug(f"Topic status update failed: {e}")
    mirror = config.get("mirrors", {}).get(orch_name)
    if mirror and mirror.get("chat_id") and mirror.get("topic_id") and bot:
        try:
            await bot.edit_forum_topic(chat_id=mirror["chat_id"], message_thread_id=mirror["topic_id"],
                                       name=short, icon_custom_emoji_id=icon_id)
        except Exception as e:
            logger.debug(f"Mirror topic status update failed: {e}")


async def _mirror_send(orch_name: str, text: str, entities=None):
    mirrors = config.get("mirrors", {})
    mirror = mirrors.get(orch_name)
    if not mirror or not bot:
        return
    chat_id = mirror.get("chat_id")
    topic_id = mirror.get("topic_id")
    if not chat_id:
        return
    try:
        await bot.send_message(chat_id, text, message_thread_id=topic_id, entities=entities)
    except Exception as e:
        logger.warning(f"Mirror send failed for {orch_name}: {e}")


async def ensure_topics():
    if not bot or not config["group_id"] or not _manager:
        return
    from app.db import get_all_sessions
    orchs = [s for s in get_all_sessions() if s.get("tg_topic") or s.get("role", "worker") in ("orchestrator", "sub-orchestrator")]
    if not orchs:
        return

    for o in orchs:
        name = o["name"]
        if name in config["topics"]:
            continue
        try:
            chosen = _pick_unique_topic_name(name)
            result = await bot.create_forum_topic(chat_id=config["group_id"], name=chosen, icon_custom_emoji_id=_ICON_IDLE)
            config["topics"][name] = result.message_thread_id
            config.setdefault("topic_names", {})[name] = chosen
            save_config()
            logger.info(f"Created topic for {name} as '{chosen}': {result.message_thread_id}")
            asyncio.create_task(stream_logs(name, result.message_thread_id))
        except Exception as e:
            logger.error(f"Failed to create topic for {name}: {e}")

    mirrors = config.get("mirrors", {})
    for name, mirror in mirrors.items():
        if mirror.get("topic_id") is not None:
            continue
        chat_id = mirror.get("chat_id")
        if not chat_id:
            continue
        try:
            short = _short_name(name)
            result = await bot.create_forum_topic(chat_id=chat_id, name=short, icon_custom_emoji_id=_ICON_IDLE)
            mirror["topic_id"] = result.message_thread_id
            save_config()
            logger.info(f"Created mirror topic for {name}: {result.message_thread_id}")
        except Exception as e:
            logger.warning(f"Mirror topic creation failed for {name}: {e}")


async def stream_logs(orch_name: str, thread_id: int):
    from app.db import get_logs, get_session_by_name, get_all_sessions

    scope = None
    for s in get_all_sessions():
        if s["name"] == orch_name:
            scope = s.get("scope", "")
            break
    if not scope:
        return

    session_id = None
    row = get_session_by_name(orch_name, scope)
    if row:
        session_id = row["id"]
    if not session_id:
        return

    from app.db import _conn
    _poll_conn = _conn()
    logs = get_logs(session_id, after_id=0, conn=_poll_conn)
    last_id = logs[-1]["id"] if logs else 0
    _last_tool_msg = None
    _last_tool_text = ""
    _idle_ticks = 0

exec
/usr/bin/zsh -lc "sed -n '1,45p' app/main.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
"""Orchestra — AI Agent Orchestrator API."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator, model_validator

from app.db import (
    init_db, get_logs, get_logs_before, get_all_sessions,
    list_profiles, upsert_profile, delete_profile,
)
from app.pipeline import list_pipelines
from app.deps import manager
from app.models import resolve_model, MODELS
from app.session import AgentStatus
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    init_db()
    await manager.auto_resume_all()
    manager.start_background_tasks()
    from app.bg_jobs import bg_manager
    bg_manager.set_session_manager(manager)
    await bg_manager.restore_from_db()
    from app.tg_bridge import start_bridge, stop_bridge

exec
/usr/bin/zsh -lc 'rg -n "import sqlite3|sqlite3" app/main.py' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc 'rg -n "async def spawn_worker|async def spawn_sub|is_orchestrator|pipeline|profile|docs_feature|role:" app/mcp_stdio.py' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
10:import sqlite3
282:_DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}
436:    except sqlite3.IntegrityError:
757:    import sqlite3
775:        except sqlite3.IntegrityError:

 succeeded in 0ms:
58:async def spawn_worker(name: str, task: str, repo_path: str,
64:                       role: str = "worker",

codex
The import surface looks clean at module import level so far; `sqlite3` is present and the new `app.deps` split is used consistently. I’m checking behavioral regressions now by running a few focused tests and lightweight repro snippets rather than a full suite.
exec
/usr/bin/zsh -lc "sed -n '250,330p' app/main.py && sed -n '330,390p' app/main.py" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
        real_path = path_map.get(entry.name)
        if not real_path or not Path(real_path).is_dir():
            continue
        if real_path == str(Path.home()):
            continue
        folder = real_path.rstrip("/").split("/")[-1]
        results.append({"path": real_path, "name": folder})
    return results


_ALLOWED_ROOTS: list[str] = []


def _get_allowed_roots() -> list[str]:
    if _ALLOWED_ROOTS:
        return _ALLOWED_ROOTS
    extra = os.environ.get("ALLOWED_ROOTS", "")
    if extra:
        for p in extra.split(":"):
            if p and Path(p).is_dir():
                _ALLOWED_ROOTS.append(p)
    for root in ["/mnt/data", "/opt", "/tmp", str(Path.home())]:
        if Path(root).is_dir():
            _ALLOWED_ROOTS.append(root)
    uploads = str(Path(__file__).parent.parent / "data" / "uploads")
    _ALLOWED_ROOTS.append(uploads)
    return _ALLOWED_ROOTS


_DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws",
                 ".npmrc", ".pypirc", ".netrc", ".docker", ".kube"}
_DENIED_HOME_PARTS = {".claude", ".config"}
_DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}


def _is_safe_path(path: str) -> bool:
    try:
        p = Path(path).resolve()
        resolved = str(p)
    except (ValueError, OSError):
        return False
    def _within(root: str) -> bool:
        try:
            return os.path.commonpath([os.path.realpath(root), resolved]) == os.path.realpath(root)
        except (ValueError, OSError):
            return False
    if not any(_within(root) for root in _get_allowed_roots()):
        return False
    home = str(Path.home())
    for part in p.parts:
        if part in _DENIED_PARTS or part.startswith(".env"):
            return False
    if resolved.startswith(home):
        for part in _DENIED_HOME_PARTS:
            if f"{home}/{part}" in resolved:
                return False
    if p.suffix in _DENIED_EXTENSIONS:
        return False
    return True


BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
                     '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z',
                     '.exe', '.bin', '.so', '.whl', '.dll', '.dylib', '.pyc',
                     '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.mp3', '.mp4',
                     '.wav', '.avi', '.mov', '.ttf', '.otf', '.woff', '.woff2'}

@app.get("/api/files/raw")
async def get_file_raw(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    from starlette.responses import FileResponse
    target = Path(path)
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(target))


@app.get("/api/files/content")
async def get_file_content(path: str):
    if not _is_safe_path(path):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    target = Path(path)
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    if not target.is_file():
        return JSONResponse({"error": "not a file"}, status_code=400)
    size = target.stat().st_size
    if target.suffix.lower() in BINARY_EXTENSIONS:
        return JSONResponse({"error": "binary file", "size": size})
    if size > 500 * 1024:
        return JSONResponse({"error": "too large", "size": size})
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "size": size, "name": str(target)}


@app.post("/api/open-folder")
async def open_folder(req: dict):
    if not os.environ.get("ALLOW_OPEN_FOLDER"):
        return JSONResponse({"error": "disabled on this server"}, status_code=403)
    import subprocess
    path = req.get("path", "")
    if not Path(path).is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    env = {**os.environ, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.Popen(["xdg-open", path], env=env)
    return {"ok": True}


@app.get("/api/open-file")
async def open_file(path: str):
    if not os.environ.get("ALLOW_OPEN_FOLDER"):
        return JSONResponse({"error": "disabled on this server"}, status_code=403)
    import subprocess
    p = Path(path)
    if not p.exists():
        return JSONResponse({"error": "file not found"}, status_code=404)
    env = {**os.environ, "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    subprocess.Popen(["xdg-open", str(p)], env=env)
    return {"ok": True}


@app.get("/api/files")
async def list_files(path: str):
    if not _is_safe_path(path):
        return JSONResponse({"error": "access denied"}, status_code=403)
    target = Path(path)
    if not target.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            items.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            })
    except PermissionError:
        pass
    return items

exec
/usr/bin/zsh -lc 'rg -n "class TestPipelineSpawnValidation|PipelineSpawn|base_branch|is_orchestrator|pipeline inheritance|parent" tests/test_manager.py -S' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
137:                use_worktree=True, repo_path=str(repo), base_branch="feature/auth",
179:        rr = MagicMock(skills="all", is_orchestrator=False)
185:        rr = MagicMock(skills=["foo", "bar"], is_orchestrator=False)
198:    """DESIGN §10: резолв base_branch по стратегии манифеста (B3).
200:    Тестируем ``_resolve_base_branch`` напрямую на инстансе manager, мокая
205:    def _put_parent(self, mgr, name, scope, branch):
207:        parent = MagicMock()
208:        parent.name = name
209:        parent.scope = scope
210:        parent.branch = branch
211:        mgr.sessions[name] = parent
214:        rr = MagicMock(base_branch_strategy="main")
216:            out = mgr._resolve_base_branch("", "default", "pm-glava", "", "/s")
219:    def test_strategy_parent_uses_parent_branch(self, mgr):
220:        rr = MagicMock(base_branch_strategy="parent")
221:        self._put_parent(mgr, "pm", "/s", "feature/x")
223:            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
226:    def test_strategy_parent_no_branch_falls_back_to_main(self, mgr, caplog):
228:        rr = MagicMock(base_branch_strategy="parent")
229:        self._put_parent(mgr, "pm", "/s", "")  # у родителя нет ветки
231:            out = mgr._resolve_base_branch("", "tasks-pm", "coder", "pm", "/s")
236:        # B3: явная ветка важнее strategy="parent" — get_role даже не зовётся.
237:        rr = MagicMock(base_branch_strategy="parent")
238:        self._put_parent(mgr, "pm", "/s", "feature/x")
240:            out = mgr._resolve_base_branch("dev", "tasks-pm", "coder", "pm", "/s")
247:            out = mgr._resolve_base_branch("", "nope", "coder", "pm", "/s")
318:            "is_orchestrator": True, "color": "#818cf8",
344:            "is_orchestrator": True, "color": "#818cf8",
372:            "is_orchestrator": True, "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
390:        rdir.mkdir(parents=True)
437:            "id": "p-1", "name": "parent", "scope": "/s", "cwd": "/tmp",
440:            "is_orchestrator": False, "color": "#fff",
447:                role="worker", parent_name="parent",
458:            "id": "p-2", "name": "parent", "scope": "/s", "cwd": "/tmp",
461:            "is_orchestrator": False, "color": "#fff",
469:                    role="full-cycle", parent_name="parent",
479:            "id": "p-3", "name": "parent", "scope": "/s", "cwd": "/tmp",
482:            "is_orchestrator": False, "color": "#fff",
490:                    role="worker", parent_name="parent",
494:    async def test_unknown_parent_fails_open(self, mgr, roles_dir):
500:                role="worker", parent_name="ghost-parent",
583:            "is_orchestrator": False, "color": "#fff",
621:    (pdir / "prompts" / "roles").mkdir(parents=True)
626:        target.parent.mkdir(parents=True, exist_ok=True)
668:        rdir.mkdir(parents=True)
740:        (uprompts / "roles").mkdir(parents=True)
824:            "is_orchestrator": True, "color": "",
840:                        role="coder", parent_name="glava",
854:            "is_orchestrator": True, "color": "",
861:                role="secretary", parent_name="glava", pipeline="testpipe",
886:            "is_orchestrator": False, "color": "#fff",
897:                    role="full-cycle", parent_name="boss",
904:        (prompts / "roles").mkdir(parents=True)
914:        """coder (kind:orchestrator в манифесте) → session.is_orchestrator=True,
920:                role="coder", is_orchestrator=True, pipeline="testpipe",
922:        assert session.is_orchestrator is True
927:        """secretary (kind:worker) → is_orchestrator=False даже при is_orchestrator=True arg."""
934:            "is_orchestrator": True, "color": "",
941:                role="secretary", parent_name="glava", pipeline="testpipe",
943:        assert session.is_orchestrator is False
947:        """Нет манифеста → is_orch из is_orchestrator_role(role) (frozenset)."""
952:                role="orchestrator", is_orchestrator=True,
954:        assert session.is_orchestrator is True
959:    async def test_child_inherits_parent_pipeline(self, mgr, pipeline_dir):
967:            "is_orchestrator": True, "color": "",
976:                parent_name="coderboss",
982:        """Корневой оркестратор без parent и без pipeline → DEFAULT_PIPELINE."""
988:                role="orchestrator", is_orchestrator=True,
993:    async def test_auto_found_parent_pipeline_inherited(self, mgr, pipeline_dir):
994:        """Воркер без явного parent_name авто-находит оркестратора в scope и
1001:                role="coder", is_orchestrator=True, pipeline="testpipe",
1003:            # generic worker без parent_name → авто-находит coderboss2 → testpipe
1008:        assert worker.parent_name == "coderboss2"
1026:                role="orchestrator", is_orchestrator=True, profile="work",
1034:    async def test_child_inherits_parent_profile(self, mgr):
1042:            "is_orchestrator": True, "color": "",
1049:                parent_name="boss",
1062:            "is_orchestrator": True, "color": "",
1069:                parent_name="boss2", profile="personal",
1080:                role="orchestrator", is_orchestrator=True,
1085:    async def test_auto_found_parent_profile_inherited(self, mgr):
1086:        """Воркер без явного parent_name авто-находит оркестратора в scope и
1092:                role="orchestrator", is_orchestrator=True, profile="work",
1098:        assert worker.parent_name == "orch-prof"
1144:                is_orchestrator=True,
1272:                model="claude-opus-4-8", is_orchestrator=True,
1281:            "worktree_path": None, "branch": None, "is_orchestrator": False,
1299:                model="claude-opus-4-8", is_orchestrator=True,
1307:            "worktree_path": None, "branch": None, "is_orchestrator": False,

codex
There is a clear import-time failure in `app/main.py`: a duplicated guard line leaves an `if` with no body in `get_file_content`. I’m confirming it with `py_compile` and collecting exact line references for the review.
exec
/usr/bin/zsh -lc "nl -ba app/main.py | sed -n '304,322p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
   304	            if f"{home}/{part}" in resolved:
   305	                return False
   306	    if p.suffix in _DENIED_EXTENSIONS:
   307	        return False
   308	    return True
   309	
   310	
   311	BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.bmp', '.webp',
   312	                     '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z',
   313	                     '.exe', '.bin', '.so', '.whl', '.dll', '.dylib', '.pyc',
   314	                     '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.mp3', '.mp4',
   315	                     '.wav', '.avi', '.mov', '.ttf', '.otf', '.woff', '.woff2'}
   316	
   317	@app.get("/api/files/raw")
   318	async def get_file_raw(path: str):
   319	    if not _is_safe_path(path):
   320	        return JSONResponse({"error": "access denied"}, status_code=403)
   321	    from starlette.responses import FileResponse
   322	    target = Path(path)

exec
/usr/bin/zsh -lc 'python -m py_compile app/main.py app/manager.py app/pipeline.py app/workspace.py app/session.py app/backend_claude.py' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
exec
/usr/bin/zsh -lc 'UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_pipeline.py tests/test_workspace.py' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 105ms:
 succeeded in 3642ms:
........................................................................ [ 68%]
.................................                                        [100%]
105 passed in 2.98s

codex
The suspected syntax issue did not reproduce under `py_compile`; the earlier read showed a duplicated line artifact, but the file compiles. I’ll keep it out of findings unless another read confirms it. Targeted pipeline/workspace tests pass with a writable uv cache.
exec
/usr/bin/zsh -lc "nl -ba app/main.py | sed -n '322,350p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
   322	    target = Path(path)
   323	    if not target.is_file():
   324	        return JSONResponse({"error": "not found"}, status_code=404)
   325	    return FileResponse(str(target))
   326	
   327	
   328	@app.get("/api/files/content")
   329	async def get_file_content(path: str):
   330	    if not _is_safe_path(path):
   331	        return JSONResponse({"error": "access denied"}, status_code=403)
   332	    target = Path(path)
   333	    if not target.exists():
   334	        return JSONResponse({"error": "not found"}, status_code=404)
   335	    if not target.is_file():
   336	        return JSONResponse({"error": "not a file"}, status_code=400)
   337	    size = target.stat().st_size
   338	    if target.suffix.lower() in BINARY_EXTENSIONS:
   339	        return JSONResponse({"error": "binary file", "size": size})
   340	    if size > 500 * 1024:
   341	        return JSONResponse({"error": "too large", "size": size})
   342	    content = target.read_text(encoding="utf-8", errors="replace")
   343	    return {"content": content, "size": size, "name": str(target)}
   344	
   345	
   346	@app.post("/api/open-folder")
   347	async def open_folder(req: dict):
   348	    if not os.environ.get("ALLOW_OPEN_FOLDER"):
   349	        return JSONResponse({"error": "disabled on this server"}, status_code=403)
   350	    import subprocess

exec
/usr/bin/zsh -lc 'git diff HEAD''^2 HEAD -- app/manager.py app/main.py app/session.py app/workspace.py app/mcp_stdio.py | sed -n '"'1,260p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
diff --git a/app/main.py b/app/main.py
index 507c49b..02e1d11 100644
--- a/app/main.py
+++ b/app/main.py
@@ -22,15 +22,13 @@ from fastapi.templating import Jinja2Templates
 from pydantic import BaseModel, field_validator, model_validator
 
 from app.db import (
-    init_db, get_logs, get_logs_before,
+    init_db, get_logs, get_logs_before, get_all_sessions,
     list_profiles, upsert_profile, delete_profile,
 )
 from app.pipeline import list_pipelines
-from app.manager import SessionManager
+from app.deps import manager
 from app.models import resolve_model, MODELS
 from app.session import AgentStatus
-
-manager = SessionManager()
 templates = Jinja2Templates(directory="app/templates")
 
 
@@ -60,6 +58,13 @@ async def lifespan(app: FastAPI):
 app = FastAPI(title="Orchestra", lifespan=lifespan)
 app.mount("/static", StaticFiles(directory="app/static"), name="static")
 
+from app.routes.tm import router as tm_router
+from app.routes.bg import router as bg_router
+from app.routes.proxy import router as proxy_router
+app.include_router(tm_router)
+app.include_router(bg_router)
+app.include_router(proxy_router)
+
 
 from app.auth import is_auth_enabled, validate_session, requires_auth, check_internal_token
 
@@ -271,7 +276,8 @@ def _get_allowed_roots() -> list[str]:
     return _ALLOWED_ROOTS
 
 
-_DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws"}
+_DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws",
+                 ".npmrc", ".pypirc", ".netrc", ".docker", ".kube"}
 _DENIED_HOME_PARTS = {".claude", ".config"}
 _DENIED_EXTENSIONS = {".db", ".db-shm", ".db-wal", ".db-journal", ".sqlite", ".sqlite3", ".key", ".pem", ".p12", ".pfx"}
 
@@ -386,7 +392,7 @@ async def list_files(path: str):
 
 @app.get("/api/role-icons")
 async def role_icons():
-    from app.manager import get_role_icons
+    from app.prompting import get_role_icons
     return get_role_icons()
 
 
@@ -499,7 +505,7 @@ async def get_session(name: str, scope: str):
 
 @app.get("/api/sessions/{name}/prompt")
 async def get_session_prompt(name: str, scope: str):
-    from app.manager import _read_prompt
+    from app.prompting import read_prompt as _read_prompt
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
@@ -591,7 +597,15 @@ async def send_message(name: str, req: SendRequest):
         if not session:
             session = await manager.ensure_loaded_any(name)
         if not session:
-            return JSONResponse({"error": "not found"}, status_code=404)
+            all_names = [s.name for s in manager.sessions.values()]
+            for row in get_all_sessions():
+                if row["name"] not in all_names:
+                    all_names.append(row["name"])
+            similar = [n for n in all_names if name.lower() in n.lower() or n.lower() in name.lower()]
+            hint = f" Similar: {', '.join(similar[:5])}" if similar else f" Available: {', '.join(all_names[:10])}"
+            return JSONResponse({"error": f"agent '{name}' not found.{hint}"}, status_code=404)
+        if hasattr(session, 'needs_switch') and session.needs_switch:
+            return JSONResponse({"error": "worker was merged — call switch_worker_branch first"}, status_code=400)
         msg = f"[from:{req.sender}] {req.message}" if req.sender else req.message
         if req.sender:
             msg += manager._context_warning(req.sender)
@@ -601,7 +615,8 @@ async def send_message(name: str, req: SendRequest):
             now = datetime.now(local_tz).strftime("%H:%M")
             msg = f"[{now}] {msg}"
         await manager.send(session.id, msg)
-        return {"ok": True}
+        pn = getattr(session, "parent_name", "") or (session.get("parent_name", "") if isinstance(session, dict) else "")
+        return {"ok": True, "parent_name": pn}
     except (RuntimeError, KeyError) as e:
         return JSONResponse({"error": str(e)}, status_code=400)
     except Exception as e:
@@ -612,8 +627,6 @@ async def send_message(name: str, req: SendRequest):
 @app.post("/api/sessions/{name}/compact")
 async def compact_session(name: str, req: ScopeRequest):
     session = await manager.ensure_loaded(name, req.scope)
-    if not session:
-        session = await manager.ensure_loaded_any(name)
     if not session:
         return JSONResponse({"error": "not found"}, status_code=404)
     if session.status.value == "running":
@@ -625,8 +638,6 @@ async def compact_session(name: str, req: ScopeRequest):
 @app.post("/api/sessions/{name}/restart-cli")
 async def restart_cli(name: str, req: ScopeRequest):
     session = await manager.ensure_loaded(name, req.scope)
-    if not session:
-        session = await manager.ensure_loaded_any(name)
     if not session:
         return JSONResponse({"error": "not found"}, status_code=404)
     await session._disconnect_backend()
@@ -743,36 +754,33 @@ async def rename_session(name: str, req: dict):
     session = manager.sessions.get(sid)
     old_branch = None
     new_branch = None
-    if session:
-        session.name = new_name
-        if session.system_prompt:
-            session.system_prompt = session.system_prompt.replace(
+    import sqlite3
+    from app.db import _conn
+    with _conn() as c:
+        row = c.execute("SELECT branch, system_prompt FROM sessions WHERE id=?", (sid,)).fetchone()
+        updates = {"name": new_name}
+        if row and row["system_prompt"]:
+            updates["system_prompt"] = row["system_prompt"].replace(
                 f"Worker name: {name}", f"Worker name: {new_name}"
             ).replace(
                 f"Orchestrator: {name}", f"Orchestrator: {new_name}"
             )
-        if session.branch and session.branch.endswith(f"/{name}"):
-            old_branch = session.branch
-            new_branch = session.branch[: -len(name)] + new_name
+        if row and row["branch"] and row["branch"].endswith(f"/{name}"):
+            old_branch = row["branch"]
+            new_branch = row["branch"][: -len(name)] + new_name
+            updates["branch"] = new_branch
+        sets = ", ".join(f"{k}=?" for k in updates)
+        try:
+            c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*updates.values(), sid))
+        except sqlite3.IntegrityError:
+            return JSONResponse({"error": "name already taken"}, status_code=409)
+    if session:
+        session.name = new_name
+        if updates.get("system_prompt"):
+            session.system_prompt = updates["system_prompt"]
+        if new_branch:
             session.branch = new_branch
         session._persist()
-    else:
-        from app.db import _conn
-        with _conn() as c:
-            row = c.execute("SELECT branch, system_prompt FROM sessions WHERE id=?", (sid,)).fetchone()
-            updates = {"name": new_name}
-            if row and row["system_prompt"]:
-                updates["system_prompt"] = row["system_prompt"].replace(
-                    f"Worker name: {name}", f"Worker name: {new_name}"
-                ).replace(
-                    f"Orchestrator: {name}", f"Orchestrator: {new_name}"
-                )
-            if row and row["branch"] and row["branch"].endswith(f"/{name}"):
-                old_branch = row["branch"]
-                new_branch = row["branch"][: -len(name)] + new_name
-                updates["branch"] = new_branch
-            sets = ", ".join(f"{k}=?" for k in updates)
-            c.execute(f"UPDATE sessions SET {sets} WHERE id=?", (*updates.values(), sid))
     if old_branch and new_branch:
         wt_path = (session.worktree_path if session else None) or (
             found.get("worktree_path") if isinstance(found, dict) else getattr(found, "worktree_path", None)
@@ -796,11 +804,46 @@ async def rename_session(name: str, req: dict):
 
 
 @app.delete("/api/sessions/{name}")
-async def delete_session(name: str, scope: str):
+async def delete_session(name: str, scope: str, force: bool = False):
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
     sid = found["id"] if isinstance(found, dict) else found.id
+    if not force:
+        if not isinstance(found, dict) and found.status.value == "running":
+            return JSONResponse({"error": "worker is running — stop first (or force=true)"}, status_code=400)
+        wt = found.get("worktree_path") if isinstance(found, dict) else found.worktree_path
+        if wt and Path(wt).is_dir():
+            status_proc = await asyncio.create_subprocess_exec(
+                "git", "status", "--porcelain", cwd=wt,
+                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
+            )
+            try:
+                stdout, stderr = await asyncio.wait_for(status_proc.communicate(), timeout=5)
+            except asyncio.TimeoutError:
+                status_proc.kill()
+                return JSONResponse({"error": "git status timed out in worktree. Use force=true if certain"}, status_code=400)
+            if status_proc.returncode != 0:
+                return JSONResponse({"error": f"git status failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
+            dirty = stdout.decode().strip()
+            if dirty:
+                files = [l[3:] for l in dirty.splitlines()[:10]]
+                return JSONResponse({"error": f"worker has uncommitted changes: {', '.join(files)}. Commit or discard first (or force=true)"}, status_code=400)
+            ahead_proc = await asyncio.create_subprocess_exec(
+                "git", "rev-list", "main..HEAD", "--count", cwd=wt,
+                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
+            )
+            try:
+                stdout, stderr = await asyncio.wait_for(ahead_proc.communicate(), timeout=5)
+            except asyncio.TimeoutError:
+                ahead_proc.kill()
+                return JSONResponse({"error": "git rev-list timed out. Use force=true if certain"}, status_code=400)
+            ahead = stdout.decode().strip()
+            if ahead_proc.returncode != 0 or not ahead.isdigit():
+                return JSONResponse({"error": f"git rev-list failed: {stderr.decode().strip()}. Use force=true if certain"}, status_code=400)
+            n = int(ahead)
+            if n > 0:
+                return JSONResponse({"error": f"worker has {n} unmerged commit(s). merge_worker first (or force=true)"}, status_code=400)
     await manager.remove(sid)
     return {"ok": True}
 
@@ -810,6 +853,7 @@ async def merge_session(name: str, req: dict):
     from app.workspace import merge_worktree_to_main
     scope = req.get("scope", "")
     target = req.get("target", "main")
+    next_task_id = req.get("next_task_id", "")
     found = manager.get_by_name(name, scope)
     if not found:
         return JSONResponse({"error": "not found"}, status_code=404)
@@ -837,6 +881,27 @@ async def merge_session(name: str, req: dict):
                         link_results[task_ref] = {"ok": False, "error": str(link_err)}
                 if link_results:
                     result["linked_tasks"] = link_results
+                if not isinstance(found, dict):
+                    found.branch = target
+                    found.task_id = ""
+                    found.needs_switch = True
+                    found._persist()
+                if next_task_id and not isinstance(found, dict):
+                    from app.workspace import switch_worktree_branch, _normalize_task_id
+                    par = _normalize_task_id(next_task_id)
+                    new_branch = f"task-{par}/{name}"
+                    switch_result = await asyncio.to_thread(
+                        switch_worktree_branch, worktree_path, new_branch, f"refs/heads/{target}")
+                    if switch_result.get("ok"):
+                        found.branch = switch_result.get("branch", new_branch)
+                        found.task_id = par
+                        found.needs_switch = False
+                        found._persist()
+                        try:
+                            _tm.api_update_task(par, status="in_progress")
+                        except Exception:
+                            pass
+                    result["switch"] = switch_result
             return result
         except Exception as e:
             return JSONResponse({"error": str(e)}, status_code=500)
@@ -872,6 +937,7 @@ async def switch_branch(name: str, req: dict):
                 if result.get("ok") or result.get("branch"):
                     found.branch = result.get("branch", new_branch)
                     found.task_id = par
+                    found.needs_switch = False
                     found._persist()
             try:
                 _tm.api_update_task(par, status="in_progress")
@@ -1169,8 +1235,7 @@ async def report_bug_endpoint(req: Request):

exec
/usr/bin/zsh -lc 'UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_manager.py tests/test_session.py tests/test_api.py tests/test_mcp_stdio.py' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
codex
Focused `pipeline.py` and `workspace.py` tests passed: 105 tests. The broader manager/session/API batch is still running; while it runs, I’m comparing the merge against the PR parent to spot functionality dropped from Vadim’s side.
codex
The broader test batch has not produced output after about a minute, so I’m going to give it a bit longer and then stop it if it’s hung. The review findings should not depend on waiting for a long-running batch.
codex
That focused batch appears hung rather than simply slow. I’m stopping it and will report that the smaller targeted tests passed while the combined manager/session/API run did not complete.
2026-06-04T04:45:07.686341Z ERROR codex_core::tools::router: error=write_stdin failed: stdin is closed for this session; rerun exec_command with tty=true to keep stdin open
codex
The exec session does not accept stdin, so I’m identifying the pytest process directly and terminating only that command.
exec
/usr/bin/zsh -lc 'ps -eo pid,ppid,stat,cmd | rg "uv run pytest|pytest -q tests/test_manager|session.py tests/test_api|test_mcp_stdio"' in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
      1       0 Ss   bwrap --new-session --die-with-parent --ro-bind / / --dev /dev --bind /tmp /tmp --bind /tmp/claude-1000 /tmp/claude-1000 --bind /home/maxim/.codex/memories /home/maxim/.codex/memories --bind /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase --ro-bind /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase/.git /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase/.git --ro-bind /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase/.codex /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase/.codex --unshare-user --unshare-pid --unshare-net --proc /proc --argv0 codex-linux-sandbox -- /home/maxim/.npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/codex/codex --sandbox-policy-cwd /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase --command-cwd /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase --sandbox-policy {"type":"workspace-write","writable_roots":["/home/maxim/.codex/memories"],"network_access":false,"exclude_tmpdir_env_var":false,"exclude_slash_tmp":false} --file-system-sandbox-policy {"kind":"restricted","entries":[{"path":{"type":"special","value":{"kind":"root"}},"access":"read"},{"path":{"type":"special","value":{"kind":"current_working_directory"}},"access":"write"},{"path":{"type":"special","value":{"kind":"slash_tmp"}},"access":"write"},{"path":{"type":"special","value":{"kind":"tmpdir"}},"access":"write"},{"path":{"type":"path","path":"/home/maxim/.codex/memories"},"access":"write"},{"path":{"type":"path","path":"/mnt/data/Projects/Python/orchestra/.git/worktrees/feat-pipeline-rebase"},"access":"read"},{"path":{"type":"path","path":"/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase/.git"},"access":"read"},{"path":{"type":"path","path":"/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase/.codex"},"access":"read"}]} --network-sandbox-policy "restricted" --apply-seccomp-then-exec -- /usr/bin/zsh -c __CODEX_SNAPSHOT_OVERRIDE_SET_0="${CODEX_THREAD_ID+x}" __CODEX_SNAPSHOT_OVERRIDE_0="${CODEX_THREAD_ID-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_0="${ALL_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_0="${ALL_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_1="${BUNDLE_HTTPS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_1="${BUNDLE_HTTPS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_2="${BUNDLE_HTTP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_2="${BUNDLE_HTTP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_3="${BUNDLE_NO_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_3="${BUNDLE_NO_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_4="${CODEX_NETWORK_ALLOW_LOCAL_BINDING+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_4="${CODEX_NETWORK_ALLOW_LOCAL_BINDING-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_5="${CODEX_NETWORK_PROXY_ACTIVE+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_5="${CODEX_NETWORK_PROXY_ACTIVE-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_6="${DOCKER_HTTPS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_6="${DOCKER_HTTPS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_7="${DOCKER_HTTP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_7="${DOCKER_HTTP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_8="${ELECTRON_GET_USE_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_8="${ELECTRON_GET_USE_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_9="${FTP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_9="${FTP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_10="${HTTPS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_10="${HTTPS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_11="${HTTP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_11="${HTTP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_12="${NO_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_12="${NO_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_13="${NPM_CONFIG_HTTPS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_13="${NPM_CONFIG_HTTPS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_14="${NPM_CONFIG_HTTP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_14="${NPM_CONFIG_HTTP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_15="${NPM_CONFIG_NOPROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_15="${NPM_CONFIG_NOPROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_16="${NPM_CONFIG_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_16="${NPM_CONFIG_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_17="${PIP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_17="${PIP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_18="${WSS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_18="${WSS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_19="${WS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_19="${WS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_20="${YARN_HTTPS_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_20="${YARN_HTTPS_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_21="${YARN_HTTP_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_21="${YARN_HTTP_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_22="${YARN_NO_PROXY+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_22="${YARN_NO_PROXY-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_23="${all_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_23="${all_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_24="${ftp_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_24="${ftp_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_25="${http_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_25="${http_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_26="${https_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_26="${https_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_27="${no_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_27="${no_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_28="${npm_config_http_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_28="${npm_config_http_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_29="${npm_config_https_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_29="${npm_config_https_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_30="${npm_config_noproxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_30="${npm_config_noproxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_31="${npm_config_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_31="${npm_config_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_32="${ws_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_32="${ws_proxy-}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_33="${wss_proxy+x}" __CODEX_SNAPSHOT_PROXY_OVERRIDE_33="${wss_proxy-}" __CODEX_SNAPSHOT_PROXY_ENV_SET="${CODEX_NETWORK_PROXY_ACTIVE+x}"  if . '/home/maxim/.codex/shell_snapshots/019e90ee-e6f5-7cc2-a913-3d1b9eacdc86.1780548036358972187.sh' >/dev/null 2>&1; then :; fi  if [ -n "${__CODEX_SNAPSHOT_OVERRIDE_SET_0}" ]; then export CODEX_THREAD_ID="${__CODEX_SNAPSHOT_OVERRIDE_0}"; else unset CODEX_THREAD_ID; fi if [ -n "$__CODEX_SNAPSHOT_PROXY_ENV_SET" ] || [ -n "${CODEX_NETWORK_PROXY_ACTIVE+x}" ]; then if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_0}" ]; then export ALL_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_0}"; else unset ALL_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_1}" ]; then export BUNDLE_HTTPS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_1}"; else unset BUNDLE_HTTPS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_2}" ]; then export BUNDLE_HTTP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_2}"; else unset BUNDLE_HTTP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_3}" ]; then export BUNDLE_NO_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_3}"; else unset BUNDLE_NO_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_4}" ]; then export CODEX_NETWORK_ALLOW_LOCAL_BINDING="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_4}"; else unset CODEX_NETWORK_ALLOW_LOCAL_BINDING; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_5}" ]; then export CODEX_NETWORK_PROXY_ACTIVE="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_5}"; else unset CODEX_NETWORK_PROXY_ACTIVE; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_6}" ]; then export DOCKER_HTTPS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_6}"; else unset DOCKER_HTTPS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_7}" ]; then export DOCKER_HTTP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_7}"; else unset DOCKER_HTTP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_8}" ]; then export ELECTRON_GET_USE_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_8}"; else unset ELECTRON_GET_USE_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_9}" ]; then export FTP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_9}"; else unset FTP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_10}" ]; then export HTTPS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_10}"; else unset HTTPS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_11}" ]; then export HTTP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_11}"; else unset HTTP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_12}" ]; then export NO_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_12}"; else unset NO_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_13}" ]; then export NPM_CONFIG_HTTPS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_13}"; else unset NPM_CONFIG_HTTPS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_14}" ]; then export NPM_CONFIG_HTTP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_14}"; else unset NPM_CONFIG_HTTP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_15}" ]; then export NPM_CONFIG_NOPROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_15}"; else unset NPM_CONFIG_NOPROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_16}" ]; then export NPM_CONFIG_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_16}"; else unset NPM_CONFIG_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_17}" ]; then export PIP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_17}"; else unset PIP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_18}" ]; then export WSS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_18}"; else unset WSS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_19}" ]; then export WS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_19}"; else unset WS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_20}" ]; then export YARN_HTTPS_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_20}"; else unset YARN_HTTPS_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_21}" ]; then export YARN_HTTP_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_21}"; else unset YARN_HTTP_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_22}" ]; then export YARN_NO_PROXY="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_22}"; else unset YARN_NO_PROXY; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_23}" ]; then export all_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_23}"; else unset all_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_24}" ]; then export ftp_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_24}"; else unset ftp_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_25}" ]; then export http_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_25}"; else unset http_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_26}" ]; then export https_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_26}"; else unset https_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_27}" ]; then export no_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_27}"; else unset no_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_28}" ]; then export npm_config_http_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_28}"; else unset npm_config_http_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_29}" ]; then export npm_config_https_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_29}"; else unset npm_config_https_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_30}" ]; then export npm_config_noproxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_30}"; else unset npm_config_noproxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_31}" ]; then export npm_config_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_31}"; else unset npm_config_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_32}" ]; then export ws_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_32}"; else unset ws_proxy; fi if [ -n "${__CODEX_SNAPSHOT_PROXY_OVERRIDE_SET_33}" ]; then export wss_proxy="${__CODEX_SNAPSHOT_PROXY_OVERRIDE_33}"; else unset wss_proxy; fi fi  exec '/usr/bin/zsh' -c 'ps -eo pid,ppid,stat,cmd | rg "uv run pytest|pytest -q tests/test_manager|session.py tests/test_api|test_mcp_stdio"'
      2       1 S    /usr/bin/zsh -c ps -eo pid,ppid,stat,cmd | rg "uv run pytest|pytest -q tests/test_manager|session.py tests/test_api|test_mcp_stdio"
      4       2 R    rg uv run pytest|pytest -q tests/test_manager|session.py tests/test_api|test_mcp_stdio

exec
/usr/bin/zsh -lc 'git diff HEAD''^2 HEAD -- app/manager.py app/session.py app/workspace.py app/mcp_stdio.py | sed -n '"'260,620p'" in /mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-pipeline-rebase
 succeeded in 0ms:
         if others:
             base += f"\n\n{others}"
-        workers = _workers_block(scope)
+        workers = _workers_block(scope, name)
         if workers:
             base += f"\n\n{workers}"
     return base
@@ -367,25 +228,8 @@ def WORKER_SYSTEM_PROMPT(pipeline: str = DEFAULT_PIPELINE) -> str:
     return ROLE_SYSTEM_PROMPT(pipeline, "worker")
 
 
-def _prompt_template_hash(role_or_orch) -> str:
-    """Hash only the static template files (base.md + role.md + skills).
-    Accepts role string or legacy bool (is_orchestrator)."""
-    import hashlib
-    if isinstance(role_or_orch, bool):
-        role = "orchestrator" if role_or_orch else "worker"
-    else:
-        role = role_or_orch
-    content = _read_prompt("base.md") + _role_prompt_file(role)
-    return hashlib.md5(content.encode()).hexdigest()[:8]
-
 
 def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -> None:
-    """Идемпотентно скаффолдит doc-папку роли в docs_work/ по манифесту.
-
-    Источник пути/шаблона — resolve_role(...).docs_dir (не хардкод). Если у роли
-    нет docs_dir, docs_scaffold выключен, или requires=='feature' без feature —
-    скаффолд пропускается. Манифеста нет (FileNotFoundError) → пропуск.
-    """
     try:
         rr = get_role(pipeline, role)
     except FileNotFoundError:
@@ -396,8 +240,6 @@ def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -
     if dd.requires == "feature" and not feature:
         return
     rel = dd.path.replace("{feature}", feature) if feature else dd.path
-    # B3: feature приходит из рантайм-ввода (API/MCP docs_feature) — может
-    # содержать '../'. Проверяем containment в docs_work ПЕРЕД mkdir/write.
     base_docs = (Path(cwd) / "docs_work").resolve()
     target = (base_docs / rel).resolve()
     try:
@@ -418,28 +260,6 @@ def _scaffold_role_docs(pipeline: str, cwd: str, role: str, feature: str = "") -
     dashboard.write_text(content)
 
 
-def _inject_skills_to_worktree(role: str, worktree_path: str) -> None:
-    """Copy role skills into worktree/.claude/skills/ as native Claude CLI skills."""
-    role_path = _PROMPTS_DIR / "roles" / f"{role}.md"
-    if not role_path.exists():
-        return
-    meta, _ = _parse_role_frontmatter(role_path.read_text())
-    skill_names = meta.get("skills", [])
-    if not skill_names or not _SKILLS_DIR.is_dir():
-        return
-    wt = Path(worktree_path)
-    for sname in skill_names:
-        skill_src = _SKILLS_DIR / f"{sname}.md"
-        if not skill_src.exists():
-            logger.warning(f"Skill '{sname}' not found in {_SKILLS_DIR}")
-            continue
-        skill_dir = wt / ".claude" / "skills" / sname
-        skill_dir.mkdir(parents=True, exist_ok=True)
-        import shutil
-        shutil.copy2(skill_src, skill_dir / "SKILL.md")
-    logger.info(f"Injected {len(skill_names)} skills into {worktree_path}/.claude/skills/")
-
-
 def _parse_custom_mcp(raw) -> dict:
     """Sanitize custom MCP servers (from DB JSON string or a dict).
     Returns a dict with the `orchestra` key stripped. Non-dict input -> {}."""
@@ -493,6 +313,8 @@ class SessionManager:
             self._spawn_task = asyncio.create_task(self._spawn_worker_loop())
         if not getattr(self, '_cleanup_task', None) or self._cleanup_task.done():
             self._cleanup_task = asyncio.create_task(self._periodic_db_cleanup())
+        if not getattr(self, '_wt_cleanup_task', None) or self._wt_cleanup_task.done():
+            self._wt_cleanup_task = asyncio.create_task(self._periodic_worktree_cleanup())
 
     async def enqueue_worker_spawn(self, **job) -> None:
         await self._spawn_queue.put(job)
@@ -583,8 +405,11 @@ class SessionManager:
         model = resolve_model(model)
         if not Path(cwd).is_dir():
             raise ValueError(f"cwd does not exist: {cwd}")
-        if get_session_by_name(name, scope):
-            raise ValueError(f"session '{name}' already exists in scope '{scope}'")
+        existing = get_session_by_name(name, scope)
+        if existing:
+            st = existing.get("status", "?")
+            ctx = existing.get("context_pct", 0) or 0
+            raise ValueError(f"worker '{name}' already exists ({st}, ctx:{ctx}%). Use send_message instead")
 
         # Явно ли указана роль: генерик-воркер (role не задан) валидируется как
         # unrouted (child_role="") — им управляет allow_unrouted_workers родителя.
@@ -611,17 +436,30 @@ class SessionManager:
         # Ownership (upstream): нормализуем owned_dirs и предупреждаем о пересечении
         # с другими живыми воркерами в этом scope (warning, НЕ блок).
         owned_dirs = parse_owned_dirs(owned_dirs)
-        ownership_warning = ""
         if owned_dirs:
-            conflicts = []
+            seen_ids: set[str] = set()
             for s in self.sessions.values():
-                if s.scope == scope and s.status.value in ("idle", "running") and s.owned_dirs:
+                if s.scope == scope and s.status.value in ("idle", "running", "waiting") and s.owned_dirs:
+                    seen_ids.add(s.id)
                     ov = dirs_overlap(owned_dirs, s.owned_dirs)
                     if ov:
-                        conflicts.append((s.name, ov))
-            if conflicts:
-                ownership_warning = "; ".join(f"{n} owns {ov}" for n, ov in conflicts)
-                logger.warning(f"owned_dirs overlap for new worker '{name}': {ownership_warning}")
+                        raise ValueError(
+                            f"owned_dirs overlap with '{s.name}': {', '.join(ov)}. "
+                            f"Use different dirs or kill '{s.name}' first"
+                        )
+            for row in get_all_sessions(scope):
+                if row["id"] in seen_ids:
+                    continue
+                if (row.get("status") or "") not in ("idle", "running", "waiting"):
+                    continue
+                row_dirs = parse_owned_dirs(row.get("owned_dirs"))
+                if row_dirs:
+                    ov = dirs_overlap(owned_dirs, row_dirs)
+                    if ov:
+                        raise ValueError(
+                            f"owned_dirs overlap with '{row['name']}': {', '.join(ov)}. "
+                            f"Use different dirs or kill '{row['name']}' first"
+                        )
 
         if not parent_name and not is_orch:
             parent_name = self._find_orchestrator_name(scope) or ""
@@ -657,7 +495,7 @@ class SessionManager:
             validate_spawn(pipeline, parent_role, role if explicit_role else "")
         except FileNotFoundError:
             if parent_role:
-                whitelist = _role_can_spawn(parent_role)
+                whitelist = role_can_spawn(parent_role)
                 if whitelist is not None and role not in whitelist:
                     allowed = ", ".join(whitelist) if whitelist else "(none — terminal role)"
                     raise ValueError(
@@ -687,10 +525,9 @@ class SessionManager:
             owned_dirs=owned_dirs,
             tg_topic=tg_topic,
         )
-        # R1: денормализуем is_orchestrator (kind манифеста / fallback) в хранимое поле.
         session.is_orchestrator = is_orch
-        session._template_hash = _prompt_template_hash(role)
-        session._spawn_warning = ownership_warning
+        session._template_hash = prompt_template_hash(role)
+        session._spawn_warning = ""
         save_session(session._to_db_dict())
 
         if task_id and not is_orch:
@@ -716,29 +553,23 @@ class SessionManager:
                 session.cwd = wt.path
                 session.worktree_path = wt.path
                 session.branch = wt.branch
-                # F1: при skills=="all" (tasks-pm) скиллы приходят через профиль
-                # (CLAUDE_CONFIG_DIR + setting_sources), native-инъекция не нужна.
-                # default/список/нет манифеста → инъекция как в upstream.
                 try:
                     _rr = get_role(pipeline, role)
                     _skills = _rr.skills if _rr else None
                 except FileNotFoundError:
                     _skills = None
                 if _skills != "all":
-                    await asyncio.to_thread(_inject_skills_to_worktree, role, wt.path)
+                    await asyncio.to_thread(inject_skills_to_worktree, role, wt.path)
 
-            # Best-effort скаффолд doc-папки роли по манифесту (фильтрация внутри
-            # функции: docs_scaffold/docs_dir/requires). cwd = итоговый (worktree
-            # если создан, иначе исходный). Не должен валить create_session.
             try:
                 await asyncio.to_thread(
                     _scaffold_role_docs, pipeline, session.cwd, role, docs_feature)
-            except Exception as e:  # noqa: BLE001 — best-effort, как другие шаги
-                logger.warning("docs scaffold failed for role '%s': %s", role, e)
+            except Exception:
+                logger.warning("docs scaffold failed for role '%s'", role)
 
             if not is_orch:
                 orch_name = parent_name or self._find_orchestrator_name(scope)
-                session.system_prompt = _safe_format_prompt(
+                session.system_prompt = safe_format_prompt(
                     session.system_prompt,
                     worker_name=name, orchestrator_name=orch_name or "orchestrator",
                     scope=scope, branch=session.branch or "main",
@@ -1068,13 +899,13 @@ class SessionManager:
             session._last_context = {"percentage": pct, "total_tokens": tokens, "max_tokens": max_t}
         orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
         if not is_orch:
-            current_prompt = _safe_format_prompt(
+            current_prompt = safe_format_prompt(
                 current_prompt,
                 worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                 scope=db_row["scope"], branch=db_row.get("branch") or "main",
             )
         if old_prompt and old_prompt != current_prompt:
-            formatted_base = _safe_format_prompt(
+            formatted_base = safe_format_prompt(
                 ROLE_SYSTEM_PROMPT(pipeline, role, db_row["scope"]) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role),
                 worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
                 scope=db_row["scope"], branch=db_row.get("branch") or "main",
@@ -1083,7 +914,7 @@ class SessionManager:
                 custom_part = old_prompt[len(formatted_base):]
                 current_prompt = current_prompt + custom_part
         session._current_prompt = current_prompt
-        session._template_hash = db_row.get("template_hash") or _prompt_template_hash(role)
+        session._template_hash = db_row.get("template_hash") or prompt_template_hash(role)
         if not is_orch:
             session.on_idle = self._make_idle_callback(db_row["scope"])
         await session.start()
@@ -1255,9 +1086,32 @@ class SessionManager:
             except Exception as e:
                 logger.warning(f"DB cleanup failed: {e}")
 
+    async def _periodic_worktree_cleanup(self) -> None:
+        WT_CLEANUP_INTERVAL = 24 * 3600
+        try:
+            from app.workspace import cleanup_stale_worktrees
+            removed = await asyncio.to_thread(cleanup_stale_worktrees)
+            if removed:
+                logger.info(f"Startup worktree cleanup: removed {len(removed)} stale worktree(s)")
+        except Exception as e:
+            logger.warning(f"Startup worktree cleanup failed: {e}")
+        while True:
+            try:
+                await asyncio.sleep(WT_CLEANUP_INTERVAL)
+                from app.workspace import cleanup_stale_worktrees
+                removed = await asyncio.to_thread(cleanup_stale_worktrees)
+                if removed:
+                    logger.info(f"Periodic worktree cleanup: removed {len(removed)} stale worktree(s)")
+            except asyncio.CancelledError:
+                return
+            except Exception as e:
+                logger.warning(f"Periodic worktree cleanup failed: {e}")
+
     async def shutdown_all(self) -> None:
         if getattr(self, '_cleanup_task', None) and not self._cleanup_task.done():
             self._cleanup_task.cancel()
+        if getattr(self, '_wt_cleanup_task', None) and not self._wt_cleanup_task.done():
+            self._wt_cleanup_task.cancel()
         for session in list(self.sessions.values()):
             try:
                 await session.stop()
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index d11a437..c7da908 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -68,7 +68,7 @@ async def spawn_worker(name: str, task: str, repo_path: str,
     """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose explicitly: claude-opus-4-8[1m] for research/planning/long-lived, claude-sonnet-4-6 for implementation from spec, gpt-5.5 for Codex.
     base_branch — от какой ветки ответвить worktree воркера. Пусто ("") = авто по стратегии пайплайна (parent → от ветки родителя, иначе main); явно указанная ветка переопределяет стратегию.
     mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
-    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → предупреждение (НЕ блок).
+    owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
     tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
     if not model:
         return "Error: model is required. Choose: claude-opus-4-8[1m] (think), claude-sonnet-4-6 (type), gpt-5.5 (codex)"
@@ -169,9 +169,15 @@ async def send_message(to: str, message: str) -> str:
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Send failed: {result['error']}"
+    parent = result.get("parent_name", "") if isinstance(result, dict) else ""
+    if parent and parent != WORKER_NAME:
+        return f"Message sent to '{to}'\n⚠️ This worker belongs to '{parent}'. Consider messaging '{parent}' instead."
     return f"Message sent to '{to}'"
 
 
+_ORCH_ROLES = frozenset({"orchestrator", "sub-orchestrator"})
+
+
 @mcp.tool()
 async def list_agents() -> str:
     """List all agents in your project (orchestrators and workers)."""
@@ -180,10 +186,10 @@ async def list_agents() -> str:
         return f"Error: {sessions}"
     if not sessions:
         return "No agents"
-    lines = []
     icons_data = await _api("GET", "/api/role-icons")
     _icons = icons_data if isinstance(icons_data, dict) else {}
-    for s in sessions:
+
+    def _fmt(s, show_owner=False):
         r = s.get("role", "worker")
         role = _icons.get(r, "⚙️")
         st = "🟢" if s.get("status") in ("running", "idle") else "⚪"
@@ -193,7 +199,32 @@ async def list_agents() -> str:
         task_str = f" | {task}" if task else ""
         desc = s.get('description', '')
         desc_str = f' | "{desc}"' if desc else ""
-        lines.append(f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')}{ctx_str}{task_str}{desc_str}")
+        owner = s.get('parent_name', '')
+        owner_str = f" | owner: {owner}" if show_owner and owner else ""
+        return f"{st} {role} **{s['name']}** | {s.get('status','?')} | {s.get('model','?')}{ctx_str}{task_str}{desc_str}{owner_str}"
+
+    orchestrators, my_workers, other_workers = [], [], []
+    for s in sessions:
+        if s.get("role", "worker") in _ORCH_ROLES:
+            orchestrators.append(s)
+        else:
+            pn = s.get("parent_name", "")
+            if pn == WORKER_NAME or not pn:
+                my_workers.append(s)
+            else:
+                other_workers.append(s)
+
+    lines = []
+    if orchestrators:
+        lines.append("## Orchestrators")
+        lines.extend(_fmt(s) for s in orchestrators)
+    if my_workers:
+        lines.append("## Your workers")
+        lines.extend(_fmt(s) for s in my_workers)
+    if other_workers:
+        lines.append("## Other orchestrators' workers")
+        lines.append("⚠️ These workers belong to other orchestrators. Avoid sending them tasks directly.")
+        lines.extend(_fmt(s, show_owner=True) for s in other_workers)
     return "\n".join(lines)
 
 
@@ -250,9 +281,9 @@ async def compact_worker(name: str) -> str:
 
 
 @mcp.tool()
-async def kill_worker(name: str) -> str:
-    """Stop and archive a worker."""
-    result = await _api("DELETE", f"/api/sessions/{name}", params={"scope": SCOPE})
+async def kill_worker(name: str, force: bool = False) -> str:
+    """Stop and archive a worker. Blocked if worker has uncommitted changes or unmerged commits — pass force=True to override."""
+    result = await _api("DELETE", f"/api/sessions/{name}", params={"scope": SCOPE, "force": str(force).lower()})
     if isinstance(result, dict) and result.get("error"):
         return f"Kill failed: {result['error']}"
     return f"Worker '{name}' stopped and archived."
@@ -331,9 +362,12 @@ async def change_worker_model(name: str, model: str) -> str:
 
 
 @mcp.tool()
-async def merge_worker(name: str, target: str = "main") -> str:
-    """Merge a worker's branch into target branch (default main). Always squash — one clean commit per task. Returns commit count or conflict file list."""
-    result = await _api("POST", f"/api/sessions/{name}/merge", json={"scope": SCOPE, "target": target, "squash": True})
+async def merge_worker(name: str, target: str = "main", next_task_id: str = "") -> str:
+    """Merge a worker's branch into target branch (default main). Always squash — one clean commit per task. Returns commit count or conflict file list. Pass next_task_id to auto-switch to new branch after merge."""
+    body = {"scope": SCOPE, "target": target, "squash": True}
+    if next_task_id:
+        body["next_task_id"] = next_task_id
+    result = await _api("POST", f"/api/sessions/{name}/merge", json=body)
     if isinstance(result, dict) and result.get("error"):
         return f"Merge failed: {result['error']}"
     if isinstance(result, dict) and result.get("ok"):
@@ -345,6 +379,12 @@ async def merge_worker(name: str, target: str = "main") -> str:
                 parts.append(f"  → {par}: {info.get('added', 0)} commits linked")
             elif isinstance(info, dict):
                 parts.append(f"  ⚠️ {par}: FAILED — {info.get('error', 'unknown')}")
+        switch = result.get("switch")
+        if switch:
+            if switch.get("ok"):
+                parts.append(f"  → switched to branch {switch.get('branch', '?')}")
+            else:
+                parts.append(f"  ⚠️ switch failed: {switch.get('error', 'unknown')}")

