# Context for item-35

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/manager.py b/app/manager.py
index 39f64685a..83b47560c 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -30,40 +30,41 @@ from app.workspace import (
     parse_owned_dirs, dirs_overlap,
     validate_repo_root, resolve_base_branch as resolve_git_base_branch,
     repo_root,
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
+    resolve_effort,
     resolve_role,
     template_path,
     validate_spawn,
 )
 from app.db import (
     get_session, get_session_by_name, get_all_sessions, publish_ready_session,
     archive_session, get_stats, update_session_lifecycle,
 )
 from app.errtext import err_text
 from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 _adhoc_serial = itertools.count(1)
 
 # Клиент MCP отваливается по таймауту через 30 с (mcp_stdio.py). Ждём заведомо меньше,
 # чтобы вызывающий получил внятный отказ, а не ReadTimeout, неотличимый от мёртвого сервера.
 LOCK_WAIT_LIMIT_SECONDS = 25.0
 
 
@@ -642,41 +643,41 @@ class SessionManager:
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
-        effort = raw_effort if isinstance(raw_effort, str) and raw_effort else None
+        effort = resolve_effort(raw_effort, model, bt)
         session_id = str(uuid.uuid4())
         session = AgentSession(
             id=session_id, name=name, scope=scope, cwd=cwd, model=model,
             system_prompt=prompt, prompt_overlay=prompt_overlay, role=role,
             parent_id=parent_id, parent_name=parent_name,
             pipeline=pipeline, profile=profile,
             color="" if is_orch else self._pick_color(),
             mcp_servers=_make_mcp_config(name, scope, role, parent_name=parent_name,
                                          extra=custom_mcp, session_id=session_id),
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
diff --git a/app/pipeline.py b/app/pipeline.py
index 34d01e471..538b362ce 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -12,51 +12,72 @@ from __future__ import annotations
 
 import logging
 from functools import lru_cache
 from pathlib import Path
 from typing import Literal, Union
 
 import yaml
 from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
 
 from app.models import ALIASES, MODELS
 
 logger = logging.getLogger(__name__)
 
 # Корень с пайплайнами: <repo>/pipelines/. В гите только default.
 PIPELINES_DIR = Path(__file__).parent.parent / "pipelines"
 DEFAULT_PIPELINE = "default"
 
 # Спецзначение "all" для skills/mcp_servers (строка) vs явный список.
 AllOrList = Union[Literal["all"], list[str]]
 
+# Эффорт роли: скаляр (одно значение на всех) либо карта «ключ → ступень», где ключ —
+# id модели, имя рантайма или "default". Модель, а не рантайм, потому что Sol и Luna
+# живут в одном рантайме codex и требуют разных ступеней (#213).
+EffortSpec = Union[str, dict[str, str]]
+
 Kind = Literal["orchestrator", "worker"]
 ValidationMode = Literal["fail-closed", "fail-open"]
 BranchStrategy = Literal["parent", "main"]
 
 
 def _model_is_known(model: str) -> bool:
     """Модель валидна, если её ID или alias явно присутствует в реестре."""
     normalized = model.lower().strip()
     return normalized in ALIASES or normalized in MODELS
 
 
+def _canon_model(model: str) -> str:
+    """Alias → canonical id. Незнакомое возвращаем как есть (валидация — отдельно)."""
+    key = model.lower().strip()
+    return ALIASES.get(key, key)
+
+
+def _is_runtime(name: str) -> bool:
+    """True, если ``name`` — зарегистрированный рантайм (claude/codex/grok/...)."""
+    from app.runtime_registry import get_runtime  # локально: тяжёлый импорт бэкендов
+    try:
+        get_runtime(name)
+        return True
+    except ValueError:
+        return False
+
+
 def _is_safe_rel(p: str) -> bool:
     """True если ``p`` — безопасный относительный путь (без абсолютного и '..').
 
     Защита изоляции: слои промпта/шаблоны не должны выходить за pipelines/<name>/.
     """
     from pathlib import PurePosixPath
     if not p or p.startswith("/"):
         return False
     return ".." not in PurePosixPath(p).parts
 
 
 def _is_safe_component(value: str) -> bool:
     """True for one portable path component (pipeline/skill identifiers)."""
     return bool(
         value
         and value not in {".", ".."}
         and "/" not in value
         and "\\" not in value
         and "\x00" not in value
     )
@@ -181,60 +202,110 @@ class Defaults(BaseModel):
     @classmethod
     def _safe_skills(cls, v: AllOrList) -> AllOrList:
         return _validate_skill_names(v)
 
 
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
-    effort: str | None = None
+    effort: EffortSpec | None = None
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
 
+    @field_validator("effort")
+    @classmethod
+    def _effort_keys(cls, v: EffortSpec | None) -> EffortSpec | None:
+        """Карта эффорта: нормализовать ключи-модели; неизвестная СТУПЕНЬ — отказ.
+
+        Два разных исхода у двух разных ошибок, и разница не косметическая:
+
+        * **Неизвестная ступень → `ValueError`** (манифест не грузится). Пропуск такой
+          строки не «оставляет как было», а ТИХО МЕНЯЕТ МАРШРУТ: опечатка в ключе Sol
+          роняет его на `default`, то есть с `xhigh` на `high`, — и с перечитыванием на
+          границе хода это уезжает живым агентам само. Список ступеней замкнут и известен
+          на момент загрузки, гонки инициализации здесь нет, поэтому опечатка однозначна.
+          Цена принята осознанно: спавн новых агентов падает, пока не починят; живые при
+          этом работают — `AgentSession._apply_manifest_effort` на сбой резолва оставляет
+          текущее значение и НЕ пересобирает бэкенды.
+        * **Неизвестный ключ модели → warning, ключ сохраняем.** Реестр моделей
+          досоздаётся на старте (`models.fetch_models_from_proxy`), манифест мог быть
+          разобран раньше него — отказ или выброс потеряли бы валидную строку из-за
+          порядка инициализации.
+
+        Скаляр не трогаем вовсе — обратная совместимость.
+        """
+        if not isinstance(v, dict):
+            return v
+        from app.backend_codex import CODEX_REASONING_EFFORTS  # владелец набора ступеней
+        out: dict[str, str] = {}
+        for key, val in v.items():
+            if val not in CODEX_REASONING_EFFORTS:
+                raise ValueError(
+                    f"effort['{key}']: unknown level '{val}'; "
+                    f"known={sorted(CODEX_REASONING_EFFORTS)}")
+            # Порядок проверок: рантайм раньше модели, иначе ключи "codex"/"grok" (они же
+            # алиасы моделей gpt-5.6-sol и grok-4.5) читались бы как модель — и ключ
+            # "codex" не покрывал бы Luna. Имена рантаймов здесь ЗАРЕЗЕРВИРОВАНЫ: выбрать
+            # ими конкретную модель нельзя, для этого есть полный id.
+            if key == "default" or _is_runtime(key):
+                out[key] = val
+            elif _model_is_known(key):
+                out[_canon_model(key)] = val
+            else:
+                # Незнакомый ключ НЕ выбрасываем: реестр моделей досоздаётся на старте
+                # (`fetch_models_from_proxy`), и манифест мог быть разобран раньше него —
+                # выброс сделал бы валидную строку невосстановимо потерянной. Ключ просто
+                # не совпадёт ни с одной моделью, пока она не появится.
+                logger.warning(
+                    f"effort: key '{key}' — не известная модель и не рантайм; "
+                    f"сработает только если такая модель появится в реестре")
+                out[key] = val
+        return out
+
     @field_validator("modules")
     @classmethod
     def _safe_modules(cls, v: list[str]) -> list[str]:
         # B2: имя модуля → prompts/modules/{m}.md; не должно выходить за изоляцию
         # (abs или '..'). Та же защита, что у docs_dir/prompt_layers.
         for m in v:
             if not _is_safe_rel(m):
                 raise ValueError(f"unsafe module name '{m}' (abs или '..')")
         return v
 
     @field_validator("skills")
     @classmethod
     def _safe_skills(cls, v: AllOrList | None) -> AllOrList | None:
         return _validate_skill_names(v)
 
 
 class PipelineConfig(BaseModel):
     """Сырой манифест пайплайна (роли с None-полями, до наследования)."""
     model_config = ConfigDict(extra="forbid")
     name: str
@@ -254,83 +325,126 @@ class PipelineConfig(BaseModel):
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
-    effort: str | None
+    effort: EffortSpec | None
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
 
-@lru_cache(maxsize=None)
+class _ManifestUnstable(OSError):
+    """Файл сменился между stat и чтением — прочитанное невалидно, нужен повтор."""
+
+
+@lru_cache(maxsize=64)
+def _load_pipeline_cached(name: str, path: Path, stamp: tuple[int, int]) -> PipelineConfig:
+    """Разбор манифеста. Ключ кэша включает (mtime_ns, размер) — правка даёт промах.
+
+    Размер в ключе не избыточен: пара «та же секунда + тот же размер» уже давала
+    ложное попадание в кеше байткода CPython, и стоила полутора часов отладки (#214).
+    """
+    text = path.read_text()
+    after = path.stat()
+    if (after.st_mtime_ns, after.st_size) != stamp:
+        # Файл писали, пока мы читали. Проверки схемы тут не защищают: НЕДОПИСАННЫЙ YAML
+        # бывает синтаксически валидным, и роль молча получила бы неполную карту эффорта —
+        # а с #214 такая карта уезжает живым агентам на их следующем ходе.
+        # lru_cache исключения не кеширует, поэтому отравленной записи не остаётся.
+        raise _ManifestUnstable(f"pipeline '{name}' changed while being read")
+    data = yaml.safe_load(text) or {}
+    cfg = PipelineConfig(**data)  # pydantic: схема + граф can_spawn
+    if cfg.name != name:
+        raise ValueError(f"pipeline name '{cfg.name}' != dir '{name}'")
+    return cfg
+
+
 def load_pipeline(name: str) -> PipelineConfig:
     """Прочитать ``pipelines/<name>/pipeline.yaml``, провалидировать, кэшировать.
 
+    Кэш инвалидируется по (mtime_ns, размер): правка манифеста при живом сервере видна
+    сразу, без рестарта (#214 — эффорт перечитывается на границе каждого хода).
+    Один ``stat`` на вызов, разбор — только на изменившемся файле.
+
+    Чтение стабильное: если файл сменился ПОКА мы его читали, разбор отбрасывается и
+    попытка повторяется (до трёх раз). Неатомарная запись извне — редактором, `sed -i`,
+    деплоем — иначе отдала бы недописанный YAML, который бывает синтаксически валидным.
+
     :raises FileNotFoundError: если папки/файла нет.
     :raises pydantic.ValidationError: если схема битая (extra-поле, неверный kind/model).
     :raises ValueError: если ``name`` в файле не совпадает с именем папки, либо битый
         граф can_spawn.
+    :raises OSError: если файл менялся в течение всех трёх попыток чтения.
     """
     # Empty name = legacy/ad-hoc session with no pipeline → treat as "not found"
     # so callers' FileNotFoundError branch handles it (role=None), not a crash.
     if not name:
         raise FileNotFoundError("pipeline name is empty")
     if not _is_safe_component(name):
         raise ValueError(f"unsafe pipeline name '{name}'")
     path = PIPELINES_DIR / name / "pipeline.yaml"
     if not path.is_file():
         raise FileNotFoundError(f"pipeline '{name}' not found at {path}")
-    data = yaml.safe_load(path.read_text()) or {}
-    cfg = PipelineConfig(**data)  # pydantic: схема + граф can_spawn
-    if cfg.name != name:
-        raise ValueError(f"pipeline name '{cfg.name}' != dir '{name}'")
-    return cfg
+    unstable: _ManifestUnstable | None = None
+    for _ in range(3):
+        st = path.stat()
+        try:
+            return _load_pipeline_cached(name, path, (st.st_mtime_ns, st.st_size))
+        except _ManifestUnstable as e:
+            unstable = e
+    raise unstable
+
+
+# Вызывающие (и ~23 теста) чистят кэш через load_pipeline.cache_clear() — адрес
+# сохраняем, чтобы разбиение на «stat + разбор» не расползлось по коду.
+load_pipeline.cache_clear = _load_pipeline_cached.cache_clear
+load_pipeline.cache_info = _load_pipeline_cached.cache_info
 
 
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
@@ -380,40 +494,57 @@ def resolve_role(pipeline: PipelineConfig, role: str) -> ResolvedRole:
     layers_tmpl = (d.prompt_layers.orchestrator if spec.kind == "orchestrator"
                    else d.prompt_layers.worker)
     return ResolvedRole(
         name=role, pipeline=pipeline.name, kind=spec.kind, label=spec.label,
         order=spec.order, can_spawn=spec.can_spawn,
         allow_unrouted_workers=spec.allow_unrouted_workers,
         modules=spec.modules,
         model=_merge_scalar(d.model, spec.model),
         effort=spec.effort,
         skills=_merge_list(d.skills, spec.skills),
         mcp_servers=_merge_list(d.mcp_servers, spec.mcp_servers),
         base_branch_strategy=_merge_scalar(d.base_branch_strategy, spec.base_branch_strategy),
         inherit_claude_md=_merge_scalar(d.inherit_claude_md, spec.inherit_claude_md),
         docs_scaffold=_merge_scalar(d.docs_scaffold, spec.docs_scaffold),
         docs_dir=spec.docs_dir, tg=spec.tg,
         when=spec.when, not_for=spec.not_for, description=spec.description,
         prompt_layers=[p.replace("{role}", role) for p in layers_tmpl],
     )
 
 
+def resolve_effort(effort: EffortSpec | None, model: str, runtime: str) -> str | None:
+    """Ступень эффорта под конкретную модель спавна.
+
+    Скаляр — как раньше. Карта — точный id модели → рантайм → ``default`` → None.
+    ``model`` ожидается уже канонизованным (``resolve_model``), но alias тоже переживёт.
+    """
+    if isinstance(effort, str):
+        return effort or None
+    if not isinstance(effort, dict):
+        return None
+    for key in (_canon_model(model), runtime, "default"):
+        val = effort.get(key)
+        if val:
+            return val
+    return None
+
+
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
     Единственный источник — ``pipelines/<name>/prompts/`` (app/prompts/ удалён).
     """
     return PIPELINES_DIR / pipeline_name / "prompts" / rel
diff --git a/app/session.py b/app/session.py
index 562c8cc2e..7ac155b38 100644
--- a/app/session.py
+++ b/app/session.py
@@ -925,40 +925,41 @@ class AgentSession:
             pending_th = ""
             templates_changed = False
             if self.session_id and self._current_prompt and not self._prompt_injected:
                 # Inject updated system prompt once per session — workers list, role
                 # catalog, and template content drift as other agents spawn/die.
                 # Only on first message after resume; subsequent turns use cached prompt.
                 current_th = prompt_template_hash(self.role)
                 old_th = self._template_hash or current_th
                 templates_changed = old_th != current_th
                 pending_th = current_th
                 # Personal memory is re-read here, not reused from the assembled string:
                 # the prompt is built at spawn / _load_from_db, so anything the agent
                 # wrote to its own memory since then would otherwise wait for a restart.
                 self._current_prompt = refresh_worker_memory(
                     self._current_prompt, self.name, self.role, self.scope
                 )
                 message = f"[Orchestra platform note: {'your role instructions were updated.' if templates_changed else 'refreshed context (worker list, etc.).'} This is from the server, not another agent.]\n{self._current_prompt}\n\n---\n\n{message}"
                 did_inject = True
 
             await self._apply_pending_identity_restart()
+            await self._apply_manifest_effort()
 
             if self.status in (AgentStatus.IDLE, AgentStatus.WAITING):
                 self._manually_interrupted = False
                 self._did_report = False
                 self._turns.bump_turn_gen()
                 self._turn_logs = []
                 self._turn_start = asyncio.get_event_loop().time()
                 self._last_msg_time = self._turn_start
                 self.status = AgentStatus.RUNNING
                 self._persist()
                 asyncio.create_task(self._notify_scope_running())
 
             try:
                 try:
                     backend = await self._ensure_backend(
                         exclude_history_users=(original_user_message,),
                     )
                 except NativeHistoryImportError as error:
                     backend = await self._fallback_db_backed_claude(
                         error,
@@ -1116,40 +1117,75 @@ class AgentSession:
                 f"project-doc:{result.path}:{result.actual_bytes}:{result.budget_bytes}",
                 result.diagnostic,
             )
         if result.instruction:
             self._codex_project_doc_instruction = result.instruction
     async def _apply_pending_identity_restart(self) -> bool:
         """Погасить бэкенд, если имя сменилось, — но только на ГРАНИЦЕ хода.
 
         Дисконнект внутри живого хода оборвал бы его, поэтому в RUNNING только копим
         флаг. Упавший ход флаг не съедает: он доживает до начала следующего, а если
         коннекта не станет вовсе (гибернация, рестарт), новый бэкенд и так строится из
         уже пересобранного `mcp_servers`. Повторный вызов — no-op.
         """
         if not self._identity_stale or self.status == AgentStatus.RUNNING:
             return False
         self._identity_stale = False
         self._log("status", "identity changed — restarting MCP subprocess")
         await self._disconnect_backend()
         return True
 
+    async def _apply_manifest_effort(self) -> bool:
+        """Перечитать эффорт роли из манифеста — на ГРАНИЦЕ хода, как и рестарт identity.
+
+        Эффорт попадает в бэкенд один раз, при сборке (`BackendBuildContext.effort`), и
+        `_ensure_backend` готовый бэкенд не пересобирает. Поэтому новое значение вступает
+        в силу только через дисконнект: текущий ход не трогаем, следующий соберёт бэкенд
+        с новым значением (сессия/контекст сохраняются — `resume` по `session_id`).
+
+        Расхождения нет → ноль действий и ноль дисконнектов. Любой сбой резолва (битый
+        `pipeline.yaml`, нет роли, нет значения для этой модели) → остаёмся на текущем
+        значении: сломанный манифест не должен веером пересобирать бэкенды всем живым
+        агентам. Legacy-сессии без роли/пайплайна живут на значении из БД.
+        """
+        if self.status == AgentStatus.RUNNING or not self.pipeline or not self.role:
+            return False
+        try:
+            from app.pipeline import get_role, resolve_effort
+            rr = get_role(self.pipeline, self.role)
+            desired = resolve_effort(rr.effort, self.model, self.backend_type) if rr else None
+        except Exception as e:
+            logger.warning(f"[{self.name}] manifest effort re-read failed: {err_text(e)}")
+            return False
+        if desired is None or desired == self.effort:
+            return False
+        old = self.effort
+        # Сперва дисконнект, только потом фиксация значения. Обратный порядок делает сбой
+        # дисконнекта НЕВОССТАНОВИМЫМ: значение уже равно манифестному, расхождения на
+        # следующем ходе нет, повтора не будет — и агент навсегда остаётся на бэкенде со
+        # старой ступенью. Здесь падение оставляет расхождение, и следующий ход повторит.
+        await self._disconnect_backend()
+        self.effort = desired
+        self._persist()
+        self._log("status", f"effort {old or '(none)'} → {desired} (pipeline manifest)")
+        return True
+
     async def _build_claude_history_import(
         self,
         target_session_id: str,
         target_model: str,
         exclude_user_messages: tuple[str, ...] = (),
     ):
         if self._log_futures:
             await asyncio.gather(*tuple(self._log_futures), return_exceptions=True)
         loop = asyncio.get_running_loop()
         snapshot_id, rows = await loop.run_in_executor(
             _db_executor(), partial(get_history_logs, self.id)
         )
         return await loop.run_in_executor(
             _db_executor(),
             partial(
                 render_claude_history,
                 rows,
                 snapshot_id=snapshot_id,
                 session_id=target_session_id,
                 cwd=self.cwd,
diff --git a/docs/tasks/214/codex-review-impl-r3.md b/docs/tasks/214/codex-review-impl-r3.md
new file mode 100644
index 000000000..70d97a0e0
--- /dev/null
+++ b/docs/tasks/214/codex-review-impl-r3.md
@@ -0,0 +1,28 @@
+# #214 — Codex review, раунд 3 (свежая сессия)
+
+> ⚠️ **Восстановлено из транскрипта джоба `bg-60d79b6cfb`, а не записано штатно** — тот же сбой
+> `codex_review_artifact.py` (#217). Ревью отработало: 180 976 input / 1 793 output токенов.
+> Ниже — полный `agent_message` из
+> `/tmp/codex_review_impl-effort-model_codex-review-impl-r3.jsonl`, дословно.
+>
+> Раунд пущен СВЕЖЕЙ сессией, не `resume`: на тот момент я считал сломанным именно resume-путь.
+> Контекст раундов 1-2 пересказан ревьюеру в запросе. Это 3-й и последний раунд по потолку
+> `codex-debate` для исполняемого артефакта.
+
+## Summary
+
+The disconnect-order fix is complete for the reviewed lifecycle cases, and all four default roles resolve the same effort map. The focused suite passes: 37 tests.
+
+## Findings (suggestion)
+
+- `app/session.py:1166` — **FIXED (item 1).** Disconnect now precedes the in-memory and persisted effort update. A failed or partially completed disconnect leaves the manifest change pending, so the next turn retries it. A process crash between disconnect and persistence also self-recovers: the backend is rebuilt from the persisted old value, then the manifest is reapplied at the next boundary. Hibernate does not create a permanent disagreement because rebuilding ultimately uses `self.effort`.
+
+- `app/pipeline.py:334` — **STILL BROKEN (item 2).** The reader still performs `stat()` and `read_text()` without checking that the file stayed stable. The absence of an in-process writer does not eliminate non-atomic writes by an administrator, deployment command, or editor. More importantly, partially written YAML can be syntactically valid, so `_apply_manifest_effort()` may accept an intermediate map and rebuild a live backend at the wrong effort. A post-read `stat()` comparison with a bounded retry would close this race.
+
+- `app/pipeline.py:267` — **STILL BROKEN (item 3).** Dropping only an invalid level is inconsistent with the stated last-good policy. For example, a typo in Sol’s exact entry leaves `default: high`, actively changing Sol from `xhigh` to `high`; it does not merely retain stale configuration. Rejecting the manifest makes `_apply_manifest_effort()` keep the already active value, matching its documented handling of other invalid YAML. The warning helps diagnosis but does not prevent the unintended fallback.
+
+- The new YAML is well-formed. `orchestrator`, `sub-orchestrator`, `worker`, and `full-cycle` resolve identically for all tested model/default cases. Scalar compatibility remains directly covered by `TestEffortByModel::test_scalar_applies_to_every_model`.
+
+## Verdict
+
+Changes requested: item 1 is fixed, but items 2 and 3 remain real configuration-safety issues on a hot path. No new blocking bug found.
diff --git a/docs/tasks/214/codex-review-impl.md b/docs/tasks/214/codex-review-impl.md
new file mode 100644
index 000000000..b05cd1141
--- /dev/null
+++ b/docs/tasks/214/codex-review-impl.md
@@ -0,0 +1,64 @@
+## Summary
+
+Core resolution order and scalar backward compatibility work, and the focused tests pass: 24/24. Existing sessions remain unaffected because only the new-session spawn path resolves the manifest map; persisted `sessions.effort` behavior is unchanged.
+
+Pydantic rejects integer and boolean effort values rather than coercing them to strings.
+
+## Findings
+
+- suggestion — `app/pipeline.py:263` — `grok` has the same ambiguity as `codex`: both are runtime IDs and aliases (`grok → grok-4.5`). Runtime-first validation therefore makes `{grok: high}` apply to every future Grok-runtime model, not specifically `grok-4.5`. `claude` and `opencode` are not currently aliases. → Treat runtime names as explicitly reserved keys and document that aliases colliding with them cannot select a model; add a `grok` regression test. Exact `grok-4.5` remains available for model-specific selection.
+
+- suggestion — `app/pipeline.py:265` — Unknown model keys are destructively removed during cached manifest validation. If `load_pipeline()` runs before `fetch_models_from_proxy()` registers a proxy model, that model’s effort entry is permanently absent from the cached `RoleSpec`, even after the registry gains the model. → Preserve unknown string keys for spawn-time exact matching, or clear/reload the pipeline cache after every model-registry refresh. Preserving keys also avoids coupling manifest correctness to startup ordering.
+
+- suggestion — `app/pipeline.py:256` — Dropping misspelled keys or levels and falling through to `default`/`None` hides configuration errors in a shared runtime; warnings may never be noticed, while every subsequent worker silently receives the wrong effort. → Reject invalid entries when loading the manifest, or at minimum mark the pipeline invalid instead of mutating the configured map. If fail-open availability is mandatory, surface the degradation through the pipeline validation result rather than logs alone.
+
+## Verdict
+
+Changes requested before approval. Spawn-time selection and scalar compatibility are correct, but dynamic registry timing can silently discard valid per-model configuration, and ambiguous/runtime or invalid keys need a clearer, observable contract.
+
+
+> ⚠️ **Раунд 2 восстановлен из транскрипта джоба, а не записан штатно.** Обёртка
+> `codex_review_artifact.py` упала с `exit 2` (`the following arguments are required:
+> --usage-event-id, --usage-session-id, --usage-model`) — причина в #217: `d9d770e4`
+> добавил обязательные аргументы, а живой MCP-процесс воркера поднят до мержа и зовёт
+> скрипт по-старому. Само ревью отработало: 572 858 input / 3 700 output токенов.
+> Текст ниже — полный `agent_message` из `/tmp/codex_review_impl-effort-model_codex-review-impl.jsonl`,
+> дословно. Первая ручная реконструкция (по хвосту в 3000 символов) была неполной и заменена этой.
+
+## Round 2
+
+## Summary
+
+Round 1 status:
+
+- Unknown model keys / dynamic registry timing: FIXED.
+- `grok` runtime/alias ambiguity: FIXED and tested.
+- Silent dropping of invalid effort levels: STILL BROKEN.
+- Cache-contract regression: FIXED by deliberately changing and testing the contract.
+
+Focused tests pass.
+
+The running-turn claim is correct: every `RUNNING` branch returns before `_apply_manifest_effort()`. The lifecycle lock serializes session operations, but it does not make concurrent filesystem edits deterministic because manifest writers do not share that lock.
+
+## Findings
+
+- suggestion — `app/session.py:1158` — NEW BUG: `desired is None` is treated as “keep the DB value,” so removing an effort mapping cannot clear an existing effort. This contradicts the stated comparison contract and prevents a bulk manifest edit from changing agents back to backend-default effort. → Distinguish “manifest/role could not be read” from a successfully resolved `None`; after a successful read, apply and persist `None` when it differs. If inheritance of legacy DB values is intentional, restrict it explicitly to legacy sessions rather than all roles without a match.
+
+- suggestion — `app/session.py:1161` — NEW BUG: state is committed before backend disconnection succeeds. If `backend.disconnect()` raises, `self.effort` and potentially the DB contain the new value while `_backend` still references a backend built with the old effort. On later turns `desired == self.effort`, so the disconnect is never retried and the agent can continue indefinitely at the wrong effort. → Disconnect first and commit the new effort only after success, or roll back `self.effort` on failure so the next turn retries.
+
+- suggestion — `app/pipeline.py:386` — NEW BUG: `stat()` and `read_text()` are separate operations with no stable-snapshot check. An in-place bulk edit can therefore expose partial YAML, and the lifecycle lock provides no protection against it. `_apply_manifest_effort()` catches this, but `get_role_icons()` and worktree preparation do not generally catch parse/validation failures, widening a brief edit into unrelated request or spawn failures. → Require atomic replacement for manifest updates, or re-stat after reading and retry when `(mtime_ns, size)` changed during the read.
+
+- suggestion — `app/pipeline.py:256` — STILL BROKEN: an invalid level is deleted, potentially causing fallback to a valid but unintended `default`. The availability argument explains why one bad edit should not replace the last working configuration, but silent mutation is not the only alternative. → Retain the last successfully parsed manifest when a changed file is invalid and expose the validation error; this preserves availability without accepting a typo as different routing.
+
+## Verdict
+
+Changes requested. Running turns are protected and the cache shim is compatible with existing `cache_clear()`/`cache_info()` callers, but clearing effort and disconnect failure currently leave persistent live/backend disagreement. The manifest read also needs an atomic-update contract or stable-read protection.
+
+### Разбор
+
+| находка | решение | что сделано |
+|---|---|---|
+| `NEW BUG`: значение фиксируется до успешного дисконнекта | **ACK, настоящий баг** | Порядок инвертирован: `_disconnect_backend()` ПЕРВЫМ, фиксация после. Сбой оставляет расхождение живым, следующий ход повторит. Тест `test_failed_disconnect_leaves_change_pending`; мутация «вернуть старый порядок» — красная |
+| `NEW BUG`: `stat()`+`read_text()` не атомарны, возможен торн-рид | **ACK по сути, другое лекарство** | Проверено: `pipeline.yaml` в `app/` никем не пишется программно, писателя нет вообще. Требование «писать через `os.replace()`» записано в отчёт §8 и уходит в `CLAUDE.md`. Re-stat с ретраем не делаю: при атомарной записи торн-рида не существует, ретрай — код ради случая, закрываемого дисциплиной писателя |
+| `desired is None` → наследуем значение из БД вместо очистки | **DISAGREE, обосновано** | Это явное требование постановки: «нет значения для этой модели → остаёмся на текущем». Очистка в `None` означала бы, что роль без эффорта СБРАСЫВАЕТ живым агентам ступень на дефолт рантайма — то есть битая/неполная карта тихо понижает всех. Ограничение «только для legacy» не помогает: отличить «роль намеренно без эффорта» от «ключ для этой модели забыли» в манифесте нельзя |
+| `STILL BROKEN`: неизвестный УРОВЕНЬ отбрасывается | **DISAGREE, позиция прежняя** | Предложенное лекарство — «держать последний удачно разобранный манифест» — это второй владелец значения конфига и тихая работа на устаревшей конфигурации; ровно то, от чего отказались, отвергнув отдельный тул. Идея «показывать деградацию в результате валидации» принята как верная и отложена сознательно (отчёт §9) |
diff --git a/docs/tasks/214/report.md b/docs/tasks/214/report.md
new file mode 100644
index 000000000..f33ed52e2
--- /dev/null
+++ b/docs/tasks/214/report.md
@@ -0,0 +1,356 @@
+# #214 — эффорт задаётся по МОДЕЛИ
+
+Коммиты: `af2bccd7` (часть 1 — эффорт по модели), `8b58533a` (часть 2 — живая смена на границе
+хода), `6545350a` (оркестраторы medium→high + порядок дисконнект/фиксация по ревью).
+Файлы: `app/pipeline.py`, `app/manager.py`, `app/session.py`, `pipelines/default/pipeline.yaml`,
+`tests/test_pipeline.py`, `tests/test_default_pipeline.py`, `tests/test_manager.py`,
+`tests/test_session.py`.
+
+Задача выросла по ходу дела дважды: сперва «менять эффорт живым агентам, не прерывая ход» (§4),
+затем «поднять и оркестраторов» (§7). Разделы идут в порядке появления, не переписаны задним
+числом.
+
+## 1. Что сделано
+
+`RoleSpec.effort` / `ResolvedRole.effort` принимают `str | dict[str, str]` (`EffortSpec`).
+Ключ карты — id модели, имя рантайма или `default`. Разрешение — `pipeline.resolve_effort(effort,
+model, runtime)`: точный id модели → рантайм → `default` → `None`. В `manager.create_session`
+(`app/manager.py:663`) данные уже под рукой: `model` канонизован на `:526` (`resolve_model`),
+`bt = backend_for_model(model)` посчитан на `:661`.
+
+**Порядок проверки ключа в валидаторе имеет значение и проверен тестом.** Сперва рантайм, потом
+модель: `codex` — это ОДНОВРЕМЕННО имя рантайма и alias модели `gpt-5.6-sol` (`app/models.py`,
+`ALIASES["codex"]`). При обратном порядке ключ `codex` схлопывался бы в `gpt-5.6-sol` и не покрывал
+бы Luna — то есть ровно ту модель, ради различения которой ключом выбрана модель, а не рантайм.
+Мутация «поменять порядок ветвей» валит `test_runtime_key_covers_whole_runtime` и
+`test_exact_model_beats_runtime_and_default`.
+
+**Две ошибки — два разных исхода, и разница не косметическая** (итоговое поведение, см. §10):
+неизвестная СТУПЕНЬ роняет манифест (`ValueError`, fail-closed), незнакомый КЛЮЧ МОДЕЛИ
+сохраняется с warning и совпадёт, когда такая модель появится в реестре. Причина асимметрии:
+список ступеней замкнут и известен на момент загрузки — опечатка в нём однозначна; реестр моделей
+досоздаётся на старте (`models.fetch_models_from_proxy`), поэтому отказ по ключу зависел бы от
+порядка инициализации и терял бы валидную строку. Скаляр остаётся полностью валидным.
+
+Значения и основания — в комментарии над `roles:` в манифесте: Opus `high` (#208, перегиб на high),
+Sol `xhigh` (#208, перегиба в лестнице нет), Luna `high` (#204, колено на high), `default` `high`.
+Изначально карту получили только `worker` и `full-cycle`; оркестраторские роли подняты с `medium`
+до той же карты позже, отдельным решением — §7.
+
+## 2. Живые сессии: где лежит эффорт и что там сейчас
+
+Поле — `sessions.effort TEXT DEFAULT ''` (`app/db.py:915-916`). Снято с ЖИВОЙ БД через
+`sqlite3.Connection.backup` (не `cp`: при WAL копия файла отдаёт устаревший срез), запрос
+read-only, 12.08.2026:
+
+| модель | роль | effort в БД | статус | n |
+|---|---|---|---|---|
+| `claude-opus-5[1m]` | full-cycle | `xhigh` | idle | 5 |
+| `claude-opus-5[1m]` | full-cycle | `xhigh` | running | 3 |
+| `claude-opus-5[1m]` | worker | `high` | idle / running | 2 / 2 |
+| `claude-opus-5[1m]` | orchestrator | `''` | idle / waiting | 2 / 2 |
+| `claude-opus-5[1m]` | orchestrator / sub-orchestrator | `medium` | idle | 1 / 1 |
+| `gpt-5.6-sol` | worker | `high` | idle / running | 8 / 1 |
+| `gpt-5.6-sol` | full-cycle | `xhigh` | idle / running | 7 / 1 |
+| `gpt-5.6-luna` | worker | `high` | idle | 1 |
+
+Это срез на утро; пересчёт в §4 сделан позже в тот же день и даёт другие числа (сессии рождаются и
+архивируются) — сравнивать надо внутри одного среза, а не между ними.
+
+Читается так: **8 Opus-агентов на роли full-cycle до сих пор держат `xhigh`** — они заспавнены до
+#207, который сменил значение роли на `high`; манифест они не перечитывали. Зеркально **9 Sol-ов на
+роли worker сидят на `high`**, потому что роль была скаляром, — это ровно тот недобор ступени, ради
+которого делалась правка. Четыре оркестратора с `effort=''` заспавнены ещё до появления поля.
+
+## 3. Переживёт ли `UPDATE` работающий сервер — НЕТ
+
+Не переживёт, и это тот же механизм, что уже наблюдался с `sessions.model`.
+`AgentSession._to_db_dict()` кладёт в снимок `"effort": self.effort or ""` (`app/session.py:2835`),
+`save_session` пишет его апсертом с `effort=excluded.effort` (`app/db.py:1118`). Снимок
+отправляется при каждом `_persist()` (`_persist_loop`, `app/session.py:2715-2721`) — то есть на
+любом изменении состояния сессии, включая начало и конец хода. Ручной `UPDATE` живёт до первого
+такого persist'а и затем затирается значением из памяти.
+
+Второй барьер, независимый от первого: даже корректное значение в памяти не долетит до модели без
+пересоздания бэкенда. Эффорт уходит в бэкенд один раз, при сборке
+(`app/session.py:716`, `effort=self.effort` в `BackendBuildContext`) — дальше он живёт внутри
+`ClaudeBackend._effort` / `CodexBackend.reasoning_effort`. `_ensure_backend` возвращает уже
+существующий бэкенд без пересборки (`app/session.py:1191-1193`).
+
+Отсюда безопасный порядок для ручной правки (**выполнение и рестарт — решение юзера, я не
+выполнял**):
+
+```sql
+-- при ОСТАНОВЛЕННОМ сервисе orchestra, иначе значение вернётся из памяти
+UPDATE sessions
+   SET effort = 'high'
+ WHERE finished_at IS NULL
+   AND model = 'claude-opus-5[1m]'
+   AND effort <> 'high';
+```
+
+Проверка до и после (тем же `backup()`-снимком):
+`SELECT model, role, effort, status, COUNT(*) FROM sessions WHERE finished_at IS NULL GROUP BY 1,2,3,4;`
+
+Зеркальный запрос для Sol, если решим доводить и его до манифестного значения:
+`UPDATE sessions SET effort='xhigh' WHERE finished_at IS NULL AND model='gpt-5.6-sol' AND role IN ('worker','full-cycle') AND effort<>'xhigh';`
+
+Оба запроса нарочно с `effort <> ...` в `WHERE`: холостой апдейт не должен трогать строки.
+
+## 4. Часть 2 — живая смена эффорта без прерывания хода
+
+Запрос юзера: «менять эфорты уже текущих айдл и ранинг, не прерывая, а на новом ходу».
+Реализовано **без нового тула, поля и роута**: источником истины остаётся манифест, он
+перечитывается на границе каждого хода.
+
+**Механика.** `AgentSession._apply_manifest_effort()` (`app/session.py:1136`) вызывается в `send()`
+сразу после `_apply_pending_identity_restart()` (`:945`) — на том же семафоре «граница хода»,
+который в проекте уже был для смены identity. Резолв: `get_role(pipeline, role)` →
+`resolve_effort(rr.effort, self.model, self.backend_type)`. Расходится с `self.effort` → пишем
+новое значение, `_persist()`, `_disconnect_backend()`; следующий `_ensure_backend` соберёт бэкенд
+с новым эффортом, `session_id` сохраняется, контекст не теряется.
+
+**Почему именно дисконнект, а не присваивание поля.** Это второй барьер из §3 и он важнее первого:
+эффорт уходит в рантайм ОДИН раз, при сборке бэкенда (`BackendBuildContext.effort`,
+`app/session.py:716` → `ClaudeBackend._effort` / `CodexBackend.reasoning_effort`), а
+`_ensure_backend` готовый бэкенд не пересобирает (`:1191`). Поэтому правка значения в БД не
+сработала бы, даже если бы её никто не перезаписывал: живой процесс модели про неё не узнал бы.
+
+**Ход не прерывается.** `send()` на RUNNING-сессии уходит в ветку mid-turn inject и возвращается
+ДО строки `:945` — до кода смены эффорта живой ход не доходит вовсе. Новое значение вступает в
+силу на следующем ходе. Проверено тестом `test_running_turn_is_not_interrupted`, а не рассуждением.
+
+**Гонка «поменяли ровно в момент старта хода» имеет определённый исход — но не по той причине,
+которую я написал сначала.** Весь `send()` идёт под `self._lifecycle_lock` (взятие — `:840`,
+release — `finally` на `:1046`), и манифест читается ОДИН раз за ход. Отсюда то, что важно на
+практике: внутри хода значение не меняется, состояния «ход стартовал на старом значении, а бэкенд
+собран на новом» не существует, а правка, не попавшая в это чтение, применяется на следующем ходе.
+
+**Чего лок НЕ делает — я это переоценил, поправил ревьюер.** Дословно (раунд 2): «The lifecycle
+lock serializes session operations, but it does not make concurrent filesystem edits deterministic
+because manifest writers do not share that lock». Верно: лок упорядочивает операции СЕССИИ, а не
+запись в файл, и какую из двух версий увидит чтение — решает планировщик, а не лок. Настоящая
+гарантия здесь даётся не локом, а стабильным чтением: увиденная версия всегда ЦЕЛАЯ, и ход целиком
+идёт по ней.
+
+**Стабильное чтение манифеста** (`app/pipeline.py`, `_load_pipeline_cached`): после `read_text()`
+повторно снимается `stat`, и если `(mtime_ns, размер)` изменились — разбор отбрасывается, попытка
+повторяется (до трёх). Защита не от битого YAML (его отвергнет схема), а от **недописанного, но
+синтаксически валидного**: такой прошёл бы валидацию, и роль получила бы неполную карту эффорта,
+которая с частью 2 сразу уехала бы живым агентам. `lru_cache` исключения не кеширует — отравленной
+записи в кеше не остаётся. Тест `test_file_changed_during_read_is_not_cached` дописывает файл ровно
+между чтением и `stat` и проверяет, что наружу ушла дописанная версия, а не обрывок.
+
+**Массовая установка — одна операция.** «Всем Opus поставить `high`» = одна правка
+`pipelines/default/pipeline.yaml`. Чтобы она была видна без рестарта, `load_pipeline` кэшируется по
+`(имя, путь, mtime_ns, размер)` вместо `(имя)` — один `stat` на вызов, разбор только на
+изменившемся файле. Размер в ключе не для красоты: пара «та же секунда + тот же размер» уже давала
+ложное попадание в кеше байткода CPython в этой же задаче (см. §5).
+
+**Отказ тихий и безопасный.** Битый `pipeline.yaml`, отсутствующая роль, нет значения для этой
+модели → остаёмся на текущем значении и НЕ дёргаем `_disconnect_backend()`. Сломанный манифест не
+пересобирает бэкенды веером всем живым агентам. Совпадающее значение → ноль действий и ноль
+дисконнектов (тест `test_unchanged_manifest_rebuilds_nothing` считает пересборки бэкенда: две
+подряд ходки на одном бэкенде).
+
+### Что произойдёт с живыми агентами на их следующем ходе
+
+Посчитано по живой БД (снимок `Connection.backup`) прогоном настоящего `resolve_effort` против
+настоящего манифеста — не по памяти:
+
+```
+живых сессий: 34 | без изменений: 15 | пропущено (нет роли/значения/манифеста): 0
+  gpt-5.6-sol        worker        high  -> xhigh   n=9
+  claude-opus-5[1m]  full-cycle    xhigh -> high    n=6
+  claude-opus-5[1m]  orchestrator  ''    -> medium  n=4
+  итого сменят эффорт: 19
+```
+
+**Залипшие значения чинятся сами, без единого `UPDATE`** — это и есть ответ на запрос «перевести
+всех». 9 Sol-воркеров добирают ступень, 6 Opus full-cycle слезают с унаследованного `xhigh` (#207),
+4 оркестратора с пустым полем получают свой `medium`. `UPDATE` из §3 остаётся невыполненным и
+теперь не нужен.
+
+**Оговорка про legacy.** Сессия без `role` или без `pipeline` (ad-hoc спавн, доманифестные записи)
+манифеста не имеет — живёт на значении из БД, её никто не трогает. В текущем срезе таких нет, но
+ветка есть и закрыта тестом `test_legacy_session_without_role_is_untouched`.
+
+**Известный размен, называю явно.** Инвалидация по mtime сделала манифест ЖИВЫМ для всех своих
+полей, не только для эффорта, и убрала кеш как укрытие от битого файла. Пока `pipeline.yaml`
+недописан, `get_worktree_config` (`app/manager.py:693` ловит только `FileNotFoundError`) и
+`get_role_icons` (`app/prompting.py:165`) упадут — спавн и роут отдадут ошибку вместо тихой работы
+на устаревшем кеше. Это окно длиной в запись файла. Фолбэк «держать последний хороший конфиг» я
+сознательно НЕ делал: он заводит второго владельца значения конфига — ровно то, от чего мы ушли,
+отказавшись от отдельного тула.
+
+## 5. Проверки
+
+Итоговый узкий прогон (без фулл-сьюта, лок не брался):
+`test_pipeline.py + test_session.py + test_default_pipeline.py + test_manager.py` — **536 passed**.
+
+Мутации, каждая с откатом в той же команде:
+
+| мутация | ожидание | факт |
+|---|---|---|
+| в `resolve_effort` убрать ключ модели из порядка поиска | красное | 8 failed |
+| в валидаторе проверять модель раньше рантайма | красное | 2 failed (`codex` схлопнулся в Sol) |
+| составная: ключ Sol удалён у `worker`, но оставлен у `full-cycle` | красное только по `worker` | 3 failed, все по `worker` |
+| убрать вызов `_apply_manifest_effort` с границы хода | красное | 3 failed |
+| снять ранний выход «значение не изменилось» (пересборка всегда) | красное | 2 failed |
+| выкинуть mtime из ключа кэша манифеста | красное | 2 failed |
+| пробрасывать сбой резолва вместо fail-safe | красное | 1 failed (битый манифест) |
+| вернуть старый порядок «фиксация → дисконнект» | красное | 1 failed (сбой дисконнекта съедал смену) |
+| вернуть fail-open на неизвестной СТУПЕНИ | красное | 3 failed, включая живого агента, молча сползшего на `default: high` |
+
+**Грабля, которая едва не испортила вывод (стоила ~20 минут).** После отката мутации №2 тесты
+остались красными на ЧЕСТНОМ коде: откат вернул файл того же РАЗМЕРА в ту же СЕКУНДУ, что и
+мутация (`cp` + `mv` не двигают mtime вперёд), а CPython инвалидирует `__pycache__` по паре
+(mtime, size) — обе совпали, и интерпретатор продолжал исполнять байткод МУТАНТА. Симптом
+выглядел как «мой код не работает», хотя исходник был правильный; выдал себя тем, что вставка
+отладочного `print` (то есть смена размера) «чинила» поведение. Лечение — `touch <файл>` сразу
+после отката, до прогона.
+
+## 6. Codex-ревью
+
+Артефакт: `docs/tasks/214/codex-review-impl.md`.
+
+**Раунд 1 — вердикт дословно:**
+
+> Changes requested before approval. Spawn-time selection and scalar compatibility are correct, but
+> dynamic registry timing can silently discard valid per-model configuration, and ambiguous/runtime
+> or invalid keys need a clearer, observable contract.
+
+Вердикт состоявшийся: ревьюер прогнал тесты и привёл строку результата
+(`FAILED tests/test_pipeline.py::TestLoadPipeline::test_is_cached`), которую я воспроизвёл у себя
+той же командой.
+
+**Главная польза раунда 1 — не находка, а прогон.** Ревью шло по рабочему дереву, в котором уже
+лежала НЕзакоммиченная часть 2, и поймало настоящую регрессию: `test_is_cached` требовал, чтобы
+перезапись файла НЕ была видна («кеш должен вернуть прежний объект») — ровно то поведение, которое
+часть 2 обязана сломать. Тест переписан под новый контракт двумя честными: файл не тронут → тот же
+объект; файл изменён → новый объект с новым значением. Плюс третий, `test_broken_manifest_after_
+edit_fails_loud`, фиксирует обратную сторону размена из §4.
+
+**Разбор находок (все три — `suggestion`, блокеров нет):**
+
+| находка | решение | что сделано |
+|---|---|---|
+| `grok` — тоже и рантайм, и alias модели (`grok-4.5`), как `codex` | ACK | Имена рантаймов задокументированы как ЗАРЕЗЕРВИРОВАННЫЕ ключи (комментарий у валидатора), добавлен `test_grok_key_is_a_runtime_key_not_a_model`: точный `grok-4.5` сильнее ключа `grok` |
+| незнакомые ключи выбрасывались деструктивно; манифест мог быть разобран раньше `fetch_models_from_proxy` → валидная строка терялась навсегда | ACK | Незнакомый ключ больше НЕ выбрасывается: warning + ключ сохраняется, совпадёт когда модель появится в реестре (`test_key_matches_once_model_appears_in_registry`) |
+| fail-open прячет опечатку: воркеры молча получают не тот эффорт | PARTIAL | Ключи теперь сохраняются (см. выше). Неизвестный УРОВЕНЬ (`hgih`) по-прежнему отбрасывается с warning, а не роняет манифест: `load_pipeline` лежит на пути спавна ЛЮБОГО агента и теперь ещё и на границе каждого хода — одна опечатка сделала бы неспавнимыми все роли разом. Это осознанный выбор постановки (#213 §1: «неизвестный ключ — пропуск с warning, validation: fail-open»). Предложение «показывать деградацию через результат валидации, а не только в логах» разумно, но это UI/`list_pipelines` — вне границ #214, отдаю оркестратору отдельной строкой |
+
+## 7. Оркестраторы подняты medium→high: цена вопроса
+
+Указание юзера («опус в бд всех на хайт») распространено и на `orchestrator`/`sub-orchestrator` —
+теперь все четыре роли несут одну и ту же карту. Основание ступени: #208, `medium→high` у Opus
+даёт **+2.9 пункта индекса — самый крупный шаг во всей его лестнице** (дальше `high→xhigh` уже
++1.0 за +47% цены).
+
+**Сколько это стоит.** Считано по `turn_usage` за последние 7 дней, формула цены — единственный
+владелец (`app/backend_claude.py:684`: `cache_read` ×0.1, `cache_create` ×1.25 от input):
+
+| группа | ходов | наш $ за 7 дней | доля Claude | доля ВЫХОДА в их $ |
+|---|---|---|---|---|
+| воркеры | 439 | $1269.83 | 65.6% | 15.5% |
+| оркестраторы | 632 | $666.87 | 34.4% | 7.2% |
+
+Проверка суммы: пересчёт по формуле даёт $1937 против $1868 суммой сохранённых `cost_usd` —
+расхождение 3.7%, то есть считаю тем же, чем считает система.
+
+Эффорт удорожает **выход** (reasoning-токены), а не перечитывание контекста. У оркестраторов выход
+= 7.2% их доллара, поэтому внешние «+69% цены за шаг medium→high» (#208) ложатся только на эту
+седьмую часть:
+
+**≈ +$33 в неделю = +1.7% недельного расхода Claude.** Для сравнения: поднять так же всех воркеров
+стоило бы +8.7%.
+
+**Оговорка, без которой цифра врёт в большую сторону.** #208 прямо показал, что недельный пул
+Claude, возможно, списывается по ТОКЕНАМ, а не по нашему доллару (`cache_create` объясняет расход
+пула лучше: R² 0.912 против 0.867 у `cost_usd`). Выходные токены оркестраторов — **0.20% от всех их
+токенов**, значит на пуле, который считает токены, тот же шаг даёт **+0.14%**, то есть практически
+ноль. Диапазон честного ответа: **от +0.14% до +1.7% недельного потребления**, и узкая граница
+вероятнее.
+
+**Откат — одна строка:** заменить `high` на `medium` в ключе `"claude-opus-5[1m]"` у ролей
+`orchestrator` и `sub-orchestrator`; живые агенты подхватят на следующем ходе, рестарт не нужен.
+
+**Ошибка, которую поймала сверка с известным числом.** Первый прогон дал «оркестраторы = 6.8%
+расхода», что противоречило известным 28.4% из #208. Причина: группировал по флагу
+`sessions.is_orchestrator`, который проставлен всего у 4 записей из 133, — правильный признак
+здесь `sessions.role IN ('orchestrator','sub-orchestrator')`, он даёт 34.4%. Ровно тот случай,
+когда агрегат надо сверять с внешним якорем, а не принимать первый.
+
+## 8. Атомарная запись манифеста
+
+Проверил кодом, а не рассуждением: `pipeline.yaml` в `app/` **нигде не пишется программно** —
+только читается (`app/pipeline.py:385`; ни одного `write_text`/`open(...,'w')` по этому пути).
+Переводить на `os.replace()` нечего.
+
+Требование на будущее (в `CLAUDE.md` его заберёт оркестратор): **любой код, который начнёт писать
+`pipelines/*/pipeline.yaml`, обязан писать во временный файл рядом и делать `os.replace()`.**
+На одной ФС rename атомарен, читатель видит либо старый файл целиком, либо новый целиком.
+Без этого `load_pipeline` может прочитать недописанный YAML: `stat()` и `read_text()` — две
+отдельные операции, между ними файл может смениться. Codex предлагал вместо этого re-stat
+после чтения с ретраем; не делал — при атомарной записи торн-рида не существует вовсе, а ретрай
+добавляет код ради случая, который закрывается дисциплиной писателя.
+
+## 9. Предложено и сознательно отложено
+
+Codex (раунд 2): показывать деградацию манифеста не только в логах, но и в результате валидации —
+`list_pipelines()` уже возвращает `valid`/`error` для дашборда, туда же просится «манифест
+разобран, но N записей эффорта отброшено». Не делаю: `list_pipelines`/UI сейчас никто не смотрит,
+а расход на Claude идёт с темпом ×2.3. Всплывёт, когда будем трогать UI — файл `app/pipeline.py`,
+функция `list_pipelines`.
+
+## 10. Codex, раунд 3 — что закрыто и что осталось открытым
+
+Артефакт: `docs/tasks/214/codex-review-impl-r3.md` (восстановлен из транскрипта джоба, штатная
+запись упала по #217). **Вердикт дословно:**
+
+> Changes requested: item 1 is fixed, but items 2 and 3 remain real configuration-safety issues on
+> a hot path. No new blocking bug found.
+
+Вердикт состоявшийся: ревьюер привёл прогон («The focused suite passes: 37 tests») и разобрал
+конкретные строки изменённых файлов.
+
+**Item 1 — FIXED, подтверждено ревьюером дословно:** «Disconnect now precedes the in-memory and
+persisted effort update. A failed or partially completed disconnect leaves the manifest change
+pending, so the next turn retries it. A process crash between disconnect and persistence also
+self-recovers... Hibernate does not create a permanent disagreement».
+
+**Item 2 — был STILL BROKEN, теперь исправлен (ПОСЛЕ раунда 3, то есть без ревью).** Мой довод
+«писателя в коде нет» ревьюер разбил конкретным механизмом: «The absence of an in-process writer
+does not eliminate non-atomic writes by an administrator, deployment command, or editor. More
+importantly, partially written YAML can be syntactically valid, so `_apply_manifest_effort()` may
+accept an intermediate map and rebuild a live backend at the wrong effort». Второе предложение —
+именно то, чего мой fail-safe не покрывал: недописанный, но валидный YAML не отвергается, он
+ПРИНИМАЕТСЯ. Довод принят, стабильное чтение добавлено (см. §4). Атомарная запись со стороны
+писателя (§8) остаётся в силе как второй эшелон, а не как замена.
+
+**Item 3 — ЗАКРЫТ: fail-closed, по решению оркестратора.** Ревьюер снял посылку, на которой
+держался fail-open. Дословно: «a typo in Sol's exact entry leaves `default: high`, actively
+changing Sol from `xhigh` to `high`; it does not merely retain stale configuration». То есть
+пропуск строки — это не «остались как были», а **тихая смена маршрута**, и с частью 2 она уезжает
+живым агентам сама, без всякого спавна.
+
+Разворот спеки #213 §1 записан явно, чтобы не читался как самоуправство: тот аргумент опирался на
+посылку «худшее при опечатке — остались как были». Посылка ложна → вывод из неё не действует. Это
+пересчёт решения на новых данных, а не его отмена.
+
+Итоговое поведение:
+
+| что не так в манифесте | исход | почему так |
+|---|---|---|
+| неизвестная СТУПЕНЬ (`hgih`) | `ValueError`, манифест не грузится | список замкнут, известен при загрузке, опечатка однозначна; пропуск = тихая смена маршрута |
+| незнакомый КЛЮЧ МОДЕЛИ | warning, ключ сохраняется | реестр досоздаётся на старте — отказ зависел бы от порядка инициализации и терял валидную строку |
+
+**Цена принята осознанно: спавн новых агентов падает, пока опечатку не исправят.** Живые агенты за
+это не платят, и это проверено отдельным тестом именно на ветке `raise`, а не только на warning:
+`test_typo_in_level_keeps_live_agent_on_current_effort` — эффорт остаётся текущим, дисконнектов
+ноль. Мутация «вернуть fail-open» валит три теста, и среди них этот: под fail-open агент молча
+сползает на `default: high` — ровно тот вред, который описал ревьюер.
+
+**Потолок раундов исчерпан (3 из 3 для исполняемого артефакта).** Раунд 3 не перезапускался: он
+состоялся, его текст восстановлен дословно из
+`/tmp/codex_review_impl-effort-model_codex-review-impl-r3.jsonl`. Повторный прогон ради красивого
+артефакта потратил бы четвёртый раунд, что скилл запрещает.
diff --git a/docs/workers/impl-effort-model.md b/docs/workers/impl-effort-model.md
new file mode 100644
index 000000000..f21b11b32
--- /dev/null
+++ b/docs/workers/impl-effort-model.md
@@ -0,0 +1,27 @@
+# impl-effort-model — личная память
+
+## Мутационная проверка: после отката ОБЯЗАТЕЛЬНО `touch` файла
+`cp F F.bak` → мутация → `mv F.bak F` возвращает файл с mtime бэкапа. CPython инвалидирует
+`__pycache__` по паре **(mtime, size)** — если мутация не изменила размер (частый случай:
+переставил две ветки `if`/`elif`) и уложилась в ту же секунду, интерпретатор продолжит
+исполнять байткод МУТАНТА. Симптом: честный код «не работает», тесты красные, а вставка
+отладочного `print` (смена размера) «чинит» его. Стоило ~1.5 часа на #214.
+**Всегда:** `cp F.bak F && touch F` перед прогоном.
+
+## Codex-ревью: текст живёт в `/tmp/codex_review_<агент>_<output>.jsonl`
+Если джоб упал на записи артефакта (`codex_review_artifact.py`, exit 2) — НЕ переспрашивать
+ревьюера и не тратить раунд. Полный `agent_message` лежит в этом jsonl; вытащить
+`json.loads` по строкам, взять последний `item.type == "agent_message"`. Уведомление джоба
+даёт только хвост в 3000 символов, jsonl — всё.
+
+## Проверка «кто оркестратор» в БД: по `role`, НЕ по `is_orchestrator`
+Флаг `sessions.is_orchestrator` проставлен у единиц записей (4 из 133 на 12.08.2026) и
+занижает долю оркестраторов в разы. Правильный признак —
+`role IN ('orchestrator','sub-orchestrator')`. Даёт 34.4% расхода Claude против 6.8% по флагу.
+
+## Цена эффорта считается от доли ВЫХОДА, а не от всего доллара
+Эффорт удорожает выходные (reasoning) токены. У нас выход = 7-15% доллара, остальное
+`cache_read`/`cache_write` (перечитывание контекста). Поэтому «+69% за ступень» из внешнего
+бенча превращается в +1.7% недельного расхода, а не в +69%. Формула цены — единственный
+владелец: `app/backend_claude.py:684` (`cache_read` ×0.1, `cache_write` ×1.25 от input).
+Пересчёт сверять с суммой сохранённых `cost_usd`: сошлось в пределах 3.7% — значит считаю тем же.
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 28fbf8537..cb4472c66 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -1,98 +1,109 @@
 name: default
 description: Upstream-derived v2.18 pipeline with local models and runtime modules.
 validation: fail-open
 defaults:
   model: opus
   skills: []
   mcp_servers: []
   inherit_claude_md: true
   prompt_layers:
     orchestrator: [base.md, "roles/{role}.md"]
     worker:       [base.md, "roles/{role}.md"]
   worktree:
     symlinks: []
     copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
   base_branch_strategy: main
   docs_scaffold: false
-# Про `effort` у РАБОЧИХ ролей (`worker`, `full-cycle`), #213. Оркестраторских `medium` ниже это
-# не касается: их эффорт этой правкой не рассматривался (#208 Q2 — отдельной аномалии у них нет).
-# Поле скалярное, одно на роль, а модель роли переопределяется при спавне — поэтому `high` у
-# рабочих ролей верен для их дефолтного Opus и НЕ подходит остальным. Замер #208: перегиб отдачи
-# у Opus на `high` (дальше +1.0 пункта за +47% цены), у Sol перегиба в пределах лестницы нет
-# (+1.7/+1.7/+1.9) — ему нужен `xhigh`, у Luna хватает `high`. Развести нельзя ни здесь, ни по
-# рантайму: Sol и Luna — оба `codex` (`backend_for_model`), ключом должна быть МОДЕЛЬ.
-# Ждёт правки в коде; до неё Sol-воркеры недополучают ступень. Это запись ограничения, не задание.
+# `effort` у ВСЕХ четырёх ролей задан одной и той же КАРТОЙ модель→ступень (#214): роль одна, а
+# модель выбирается при спавне, и оптимум у моделей разный. Ключом обязана быть МОДЕЛЬ, а не
+# рантайм: Sol и Luna оба `codex` (`backend_for_model`) и требуют разных ступеней.
+# Разрешение (`pipeline.resolve_effort`): точный id модели → рантайм → `default` → нет эффорта.
+# Скаляр остаётся валидным — просто здесь он больше не используется.
+# Оркестраторы подняты с `medium` до `high` по прямому указанию юзера (#214): #208 меряло только
+# рабочие роли, но medium→high — САМЫЙ крупный шаг лестницы Opus (+2.9 пункта), и переносить его
+# на оркестраторов дешевле, чем оставлять их на ступени, выбранной до этого замера. Откат — правка
+# одного ключа `claude-opus-5[1m]` в двух ролях ниже; живые агенты подхватят её на следующем ходе.
+# Основания значений:
+#   claude-opus-5[1m] → high  — #208: перегиб отдачи на `high` (medium→high +2.9, дальше high→xhigh
+#                               всего +1.0 пункта при +47% цены)
+#   gpt-5.6-sol       → xhigh — #208: перегиба в пределах лестницы НЕТ, +1.7/+1.7/+1.9 на каждый шаг;
+#                               дешёвого оптимума у Sol не существует, ступень честно окупается
+#   gpt-5.6-luna      → high  — #204, AA-LCR low 0.653 / medium 0.720 / high 0.740 / xhigh 0.733 /
+#                               max 0.783: `high` и `xhigh` неразличимы, `max` даёт +2 пункта за
+#                               +45% цены. Колено на `high`
+#   default           → high  — остальные модели (Spark, Terra, Grok) не мерились
 roles:
   orchestrator:
     kind: orchestrator
     label: Orchestrator
     order: 0
     model: claude-opus-5[1m]
-    effort: medium
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, vps-deploy, codex-debate, grill-me, orchestra-agents]
     modules: [model-routing, git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "👑"}
     when: Managing a team of workers, decomposing tasks, approving plans
     not_for: Direct implementation — delegate to workers
     description: >
       Manages worker agents. Decomposes tasks, spawns workers, reviews results.
       Available worker roles are injected automatically from roles/ directory.
   sub-orchestrator:
     kind: orchestrator
     label: Sub-Orchestrator
     order: 1
     model: claude-opus-5[1m]
-    effort: medium
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [orchestra-agents]
     modules: [model-routing, git-workflow, orchestration, worker-lifecycle, background-jobs, task-management, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "🎯"}
     when: Managing a sub-team within a larger hierarchy (department lead, tech lead, team lead)
     not_for: Direct implementation — delegate to workers
     description: >
       Manages a subset of workers under a parent orchestrator.
       Reports up to parent, delegates down to workers.
   worker:
     kind: worker
     label: Worker
     order: 2
     model: claude-opus-5[1m]
-    effort: high
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, codex-debate]
     modules: [git-workflow, report-format, self-improvement, memory-search]
     can_spawn: []
     allow_unrouted_workers: false
     tg: {emoji: "⚙️"}
     when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
     not_for: Tasks needing research or unknown scope — use full-cycle
     description: >
       General-purpose worker. Implements tasks directly, no pipeline gates.
       For system workers (permanent, module-scoped) and disposable one-shots.
   full-cycle:
     kind: worker
     label: Full-Cycle
     order: 3
     model: claude-opus-5[1m]
     # xhigh → high (#207). Anthropic для Opus 5 велит начинать с high и НЕ переносить настройки
     # прошлого поколения — унаследованный xhigh оттуда и пришёл; на девяти чужих бенчмарках
     # high→xhigh даёт +47% цены без значимого прироста, наш #199 на Sol — ×2.04 при том же вердикте.
     # НЕ ЗАКРЫТО: вендор оправдывает xhigh длиной горизонта задачи, а все опубликованные замеры
     # короче наших сессий. Правка обратимая и наблюдаемая: пошли разваливающиеся длинные ходы →
-    # вернуть xhigh, и это будет данными, а не спором.
-    effort: high
+    # вернуть xhigh, и это будет данными, а не спором. Относится к ключу Opus; у Sol ступень
+    # своя (#214, основания — в комментарии над `roles:`).
+    effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, codex-debate]
     modules: [model-routing, research-method, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: false
     tg: {emoji: "🔄"}
     when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
     not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
     description: >
       Research+Experiment (truth from sources and/or measurements) → Plan sliced into
       tickets with acceptance criteria → Implement ticket-by-ticket. Strict 3-phase
       pipeline, 2 orchestrator approval gates, Codex review at plan + impl. For a
       research-only task the orchestrator simply stops after Phase 1. All artifacts
       in docs/tasks/<id>/.
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 60ab94a37..5d452247d 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -102,40 +102,59 @@ class TestDefaultRolesResolve:
         """worker И full-cycle — воркеры (оркестратор спавнит их как исполнителей)."""
         assert P.get_role(PIPELINE, "worker").is_orchestrator is False
         assert P.get_role(PIPELINE, "full-cycle").is_orchestrator is False
         assert P.get_role(PIPELINE, "worker").can_spawn == []
         assert P.get_role(PIPELINE, "full-cycle").can_spawn == ["*"]
 
     def test_full_cycle_model_opus5(self):
         rr = P.get_role(PIPELINE, "full-cycle")
         assert rr is not None
         assert rr.model == "claude-opus-5[1m]"
 
     def test_sub_orchestrator_is_orchestrator_opus5(self):
         """sub-orchestrator — kind:orchestrator, Opus 5, can_spawn=['*']."""
         rr = P.get_role(PIPELINE, "sub-orchestrator")
         assert rr is not None
         assert rr.is_orchestrator is True
         assert rr.model == "claude-opus-5[1m]"
         assert rr.can_spawn == ["*"]
         assert rr.allow_unrouted_workers is True
 
+    @pytest.mark.parametrize(
+        "role", ["worker", "full-cycle", "orchestrator", "sub-orchestrator"])
+    @pytest.mark.parametrize("model,runtime,expected", [
+        ("claude-opus-5[1m]", "claude", "high"),    # #208: перегиб отдачи на high
+        ("gpt-5.6-sol", "codex", "xhigh"),          # #208: перегиба в лестнице нет
+        ("gpt-5.6-luna", "codex", "high"),          # #204: колено на high
+        ("gpt-5.3-codex-spark", "codex", "high"),   # не мерился → default
+    ])
+    def test_every_role_resolves_effort_by_model(self, role, model, runtime, expected):
+        """Все четыре роли — одна карта. Оркестраторы подняты medium→high (#214)."""
+        rr = P.get_role(PIPELINE, role)
+        assert P.resolve_effort(rr.effort, model, runtime) == expected
+
+    def test_no_role_is_left_on_a_scalar_effort(self):
+        """Скаляр остаётся ВАЛИДНЫМ (тесты в test_pipeline.py), но в дефолтном
+        манифесте его больше нет — иначе роль снова обслуживала бы одну модель."""
+        for role in P.known_roles(PIPELINE):
+            assert isinstance(P.get_role(PIPELINE, role).effort, dict), role
+
     def test_modules_resolve_from_manifest(self):
         """modules пробрасываются из манифеста в ResolvedRole без слияния с defaults."""
         assert P.get_role(PIPELINE, "orchestrator").modules == [
             "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
             "background-jobs", "task-management", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "sub-orchestrator").modules == [
             "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
             "background-jobs", "task-management", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "worker").modules == [
             "git-workflow", "report-format", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "full-cycle").modules == [
             "model-routing", "research-method", "git-workflow", "worker-lifecycle",
             "report-format", "self-improvement", "memory-search",
         ]
 
     def test_model_routing_reaches_only_spawn_capable_roles(self):
         """Маршрутизация инлайнится ровно тем, кто умеет спавнить, и ровно из модуля (#203).
diff --git a/tests/test_manager.py b/tests/test_manager.py
index 5dd5aecc0..61e16c817 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -168,40 +168,62 @@ class TestCreateSession:
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
             session = await mgr.create_session(
                 name="worker-1",
                 scope="/test/scope",
                 cwd="/tmp",
                 model="claude-sonnet-5[1m]",
             )
         assert session.name == "worker-1"
         assert session.id is not None
         assert len(session.id) > 0
 
     @pytest.mark.asyncio
     async def test_generates_uuid(self, mgr):
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
             s1 = await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
             s2 = await mgr.create_session(name="w2", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
         assert s1.id != s2.id
 
+    @pytest.mark.asyncio
+    @pytest.mark.parametrize("role,model,expected", [
+        # Карта модель→ступень реального манифеста (#214): роль одна, ступень разная.
+        ("worker", "claude-opus-5[1m]", "high"),
+        ("worker", "gpt-5.6-sol", "xhigh"),
+        ("worker", "gpt-5.6-luna", "high"),
+        ("full-cycle", "gpt-5.6-sol", "xhigh"),
+        # alias на входе — модель канонизуется до резолва эффорта
+        ("worker", "gpt5.6sol", "xhigh"),
+        # оркестраторы несут ту же карту (#214: подняты с medium до high на Opus)
+        ("orchestrator", "claude-opus-5[1m]", "high"),
+        ("orchestrator", "gpt-5.6-sol", "xhigh"),
+    ])
+    async def test_spawn_effort_picked_by_model(self, mgr, role, model, expected):
+        from tests.conftest import make_backend_mock
+        with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+            session = await mgr.create_session(
+                name="w-eff", scope="/s", cwd="/tmp", model=model, role=role,
+                is_orchestrator=(role == "orchestrator"), planned_initial_turn=False,
+            )
+        assert session.effort == expected
+
     @pytest.mark.asyncio
     async def test_validates_cwd(self, mgr):
         with pytest.raises(ValueError, match="does not exist"):
             await mgr.create_session(
                 name="w", scope="/s", cwd="/nonexistent/path", model="claude-sonnet-5[1m]"
             )
 
     @pytest.mark.asyncio
     async def test_duplicate_name_scope_raises(self, mgr):
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
             await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
             with pytest.raises(ValueError, match="already exists"):
                 await mgr.create_session(name="w1", scope="/s", cwd="/tmp", model="claude-sonnet-5[1m]")
 
     @pytest.mark.asyncio
     async def test_persists_to_db(self, mgr):
         from app.db import get_session_by_name
         from tests.conftest import make_backend_mock
         with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index 2275dfe36..302b17c49 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -68,47 +68,98 @@ _MINIMAL = """\
 class TestLoadPipeline:
     def test_loads_valid_manifest(self, pipelines_root):
         _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
         cfg = P.load_pipeline("demo")
         assert cfg.name == "demo"
         assert cfg.description == "Test pipeline"
         assert cfg.validation == "fail-closed"
         assert set(cfg.roles) == {"lead", "hand"}
         assert cfg.roles["lead"].kind == "orchestrator"
         assert cfg.roles["hand"].kind == "worker"
 
     def test_missing_file_raises_filenotfound(self, pipelines_root):
         with pytest.raises(FileNotFoundError):
             P.load_pipeline("nope")
 
     def test_name_mismatch_raises(self, pipelines_root):
         _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="other"))
         with pytest.raises(ValueError, match="name"):
             P.load_pipeline("demo")
 
-    def test_is_cached(self, pipelines_root):
+    def test_is_cached_while_file_unchanged(self, pipelines_root):
+        _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
+        first = P.load_pipeline("demo")
+        assert P.load_pipeline("demo") is first  # нетронутый файл не перечитывается
+
+    def test_cache_invalidated_when_file_changes(self, pipelines_root):
+        """#214: правка манифеста при живом сервере видна БЕЗ рестарта.
+
+        Контракт сменился намеренно: раньше кеш держал первый разбор до
+        ``cache_clear()``, теперь ключ включает mtime+размер файла. Это цена за то,
+        чтобы «всем Opus поставить high» делалось одной правкой yaml, а живые агенты
+        подхватывали её на своём следующем ходе (`AgentSession._apply_manifest_effort`).
+        """
         d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
         first = P.load_pipeline("demo")
-        # перезаписываем файл — кеш должен вернуть прежний объект
-        (d / "pipeline.yaml").write_text("garbage: [")
+        assert first.roles["hand"].effort is None
+
+        (d / "pipeline.yaml").write_text(
+            _MINIMAL.format(name="demo").replace(
+                "        can_spawn: []\n", "        can_spawn: []\n        effort: high\n", 1))
         second = P.load_pipeline("demo")
-        assert first is second
+        assert second is not first
+        assert second.roles["hand"].effort == "high"
+
+    def test_file_changed_during_read_is_not_cached(self, pipelines_root, monkeypatch):
+        """Неатомарная запись извне: содержимое не должно попасть в кеш и наружу.
+
+        Опасен не битый YAML (его отвергнет схема), а НЕДОПИСАННЫЙ, но синтаксически
+        валидный: роль получила бы неполную карту эффорта, и та уехала бы живым агентам.
+        """
+        d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
+        target = d / "pipeline.yaml"
+        full = _MINIMAL.format(name="demo").replace(
+            "        can_spawn: []\n", "        can_spawn: []\n        effort: high\n", 1)
+        real_read = P.Path.read_text
+        torn = {"n": 0}
+
+        def read_then_grow(self, *a, **kw):
+            text = real_read(self, *a, **kw)
+            if self == target and torn["n"] == 0:
+                torn["n"] += 1
+                target.write_text(full)  # «дописали» файл ровно между read и stat
+            return text
+
+        monkeypatch.setattr(P.Path, "read_text", read_then_grow)
+        cfg = P.load_pipeline("demo")
+
+        assert torn["n"] == 1                       # торн-рид действительно случился
+        assert cfg.roles["hand"].effort == "high"   # отдана дописанная версия, не обрывок
+        assert P.load_pipeline("demo") is cfg       # в кеше лежит она же
+
+    def test_broken_manifest_after_edit_fails_loud(self, pipelines_root):
+        """Обратная сторона инвалидации: битый файл больше не прячется за кешем."""
+        d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
+        P.load_pipeline("demo")
+        (d / "pipeline.yaml").write_text("garbage: [")
+        with pytest.raises(Exception):
+            P.load_pipeline("demo")
 
 
 # ── Валидация схемы (extra=forbid, kind, model, can_spawn-граф) ─────────────
 
 class TestSchemaValidation:
     def test_extra_field_top_level_rejected(self, pipelines_root):
         _write_pipeline(pipelines_root, "demo", """\
             name: demo
             roles:
               r: {kind: worker, label: R}
             bogus_field: 1
         """)
         with pytest.raises(Exception):  # pydantic.ValidationError (extra=forbid)
             P.load_pipeline("demo")
 
     def test_extra_field_in_role_rejected(self, pipelines_root):
         _write_pipeline(pipelines_root, "demo", """\
             name: demo
             roles:
               r: {kind: worker, label: R, mystery: yes}
@@ -508,40 +559,151 @@ class TestResolveRole:
         assert rr.tg is not None and rr.tg.emoji == "🛠"
         assert rr.name == "coder" and rr.pipeline == "inh"
 
     def test_is_orchestrator_property(self, pipelines_root):
         cfg = self._cfg(pipelines_root)
         assert P.resolve_role(cfg, "coder").is_orchestrator is True
         assert P.resolve_role(cfg, "secretary").is_orchestrator is False
 
     def test_all_union_all_stays_all(self, pipelines_root):
         # оба 'all' → 'all'
         _write_pipeline(pipelines_root, "aa", """\
             name: aa
             defaults: {skills: all}
             roles:
               r: {kind: worker, label: R, skills: all}
         """)
         cfg = P.load_pipeline("aa")
         assert P.resolve_role(cfg, "r").skills == "all"
 
 
+# ── effort: скаляр или карта модель→ступень (#214) ─────────────────────────
+
+class TestEffortByModel:
+    def _role(self, root, effort_yaml: str):
+        _write_pipeline(root, "eff", f"""\
+            name: eff
+            roles:
+              hand: {{kind: worker, label: Hand, effort: {effort_yaml}}}
+        """)
+        return P.resolve_role(P.load_pipeline("eff"), "hand").effort
+
+    def test_scalar_applies_to_every_model(self, pipelines_root):
+        eff = self._role(pipelines_root, "medium")
+        assert eff == "medium"
+        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "medium"
+        assert P.resolve_effort(eff, "gpt-5.6-sol", "codex") == "medium"
+
+    def test_map_resolves_by_exact_model_id(self, pipelines_root):
+        eff = self._role(
+            pipelines_root,
+            '{"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: low}')
+        assert P.resolve_effort(eff, "claude-opus-5[1m]", "claude") == "high"
+        assert P.resolve_effort(eff, "gpt-5.6-sol", "codex") == "xhigh"


## Later history of the touched files on main (after this commit)

194 later commits touch these paths; the first 40 (oldest first):
100cc871b 2026-08-12 #221: #221: add Telegram formatting rules to orchestrator prompt
9442bc38b 2026-08-12 #221: #221: add model routing priority oracle
45d761005 2026-08-12 #223: #223: correct barrier conclusion
bf5de05e2 2026-08-12 #222: #222: add Spark admission delivery oracle
6dac7dcbf 2026-08-12 #220: #220: план фазы 2 — T1 пересборка промпта, T2/T3 дренаж, красные тесты тикетов
6712fdcf4 2026-08-12 #219, #223: #219 T2: контракт делегирования «таблица, а не область» в worker-lifecycle + тесты на происхождение якорей (первая редакция теста была ложно-зелёной на составной мутации)
9b1b48b54 2026-08-12 #219: #219 T1b: красные тесты проводки — два гейта, killed-токен, девять неприкосновенных путей
f5910ff9c 2026-08-12 #224: #224: plan + acceptance tests committed RED (T1-T7)
d986be3c1 2026-08-12 #193: #193: add red subrepo memory regression test
9fc4534e5 2026-08-12 #231: #231: предрегистрация эксперимента (стенд, критерий, все четыре исхода) — ДО спавна плеч
d9733d591 2026-08-12 #224: #224: point TestClaudeBackendProfile F2 tests at the config file (contract moved out of argv)
a01a4b2aa 2026-08-13 #230: #230: план фазы 2 + красные оракулы T1-T5 (заглушки, 8 failed)
000927f30 2026-08-13 #223: #223: research explicit test-layer authorization
7cb9b324e 2026-08-13 #230: #230: три находки независимой проверки — гейт на futures, оракул по leftover, start_time до сброса
5c346ffd5 2026-08-13 #227: #227: enforce worker model policy at spawn
9538e066c 2026-08-13 #243: #243: preserve Codex threads across model switches
6163944bb 2026-08-13 #227: временно отключить worker_model_policy в манифесте — живой процесс со старой схемой роняет загрузку целиком; вернуть при рестарте
59ee1b11c 2026-08-13 #227: #227: gate Opus by Claude weekly pace
d485e1c52 2026-08-13 #258: #258: research safe orphan process identity
017ca19c0 2026-08-13 #237: #237: research seamless active-turn restart
96192b400 2026-08-14 #36: #36: unknown roles fail closed in validate_spawn
01f4794e2 2026-08-14 #200: #200: one CLI path encoder in app.manager.enc_cli_dir
9268255cf 2026-08-14 #277: #277: drop quota percents from the turn-ended TG line
0220d2a2d 2026-08-14 #278: #278: skip unfinished Antigravity RED tests; drop dead can_spawn leftover
077a795c7 2026-08-14 #281: #281: bind orchestrator HTTP privilege to a per-MCP proof
5a11c5a14 2026-08-14 #280: #280: drop vacuum fail-open spawn test; deny unknown parent role
b92be6ec2 2026-08-16 #180: restore Codex project trust and context
3cfeb617a 2026-08-16 #297: #297: suppress silent marker auto-report
0015743d7 2026-08-16 #296: #296: implement risk-based review routing
366367f5d 2026-08-16 Merge origin/main into VPS main
bd4f6e61a 2026-08-16 #304: #304: select codex review model explicitly
b47679c16 2026-08-16 #291: #291: implement T1 quota topology and schema
1e020d60e 2026-08-17 #311: #311: freeze durable delivery RED oracles
9a1e2d108 2026-08-17 #314: #314: freeze enforcement and analytics RED oracles
b604ef449 2026-08-17 #305: #305: serialize managed Codex cold starts
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
1fe3cf1d7 2026-08-18 #329: один владелец логики пулов — квотная арифметика вырезана из манифеста, блок выключен до рестарта
8c5ea3647 2026-08-18 #329: включён worker_model_policy — рестарт 18.08 17:31 UTC загрузил новую схему
b643c67e3 2026-08-19 #230: горячее применение правок и живучесть ходов при рестарте
937950484 2026-08-19 #340: #340: перенос истории запрещать только тому вызову, который может исполняться сейчас

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 100cc871b #221: #221: add Telegram formatting rules to orchestrator prompt

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 5d452247d..1ab4ac075 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -280,10 +280,44 @@ class TestDefaultBuildSystemPrompt:
         out = P.build_system_prompt(PIPELINE, "orchestrator")
         assert "## Role: Worker" not in out
         assert "## Role: Full-Cycle Worker" not in out
 
 
+class TestTelegramFormattingOwnership:
+    """#221: Telegram presentation rules belong only to the user-facing role."""
+
+    OPEN = "<telegram-formatting>"
+    CLOSE = "</telegram-formatting>"
+    USER_ROLE = "orchestrator"
+    OTHER_ROLES = ("sub-orchestrator", "worker", "full-cycle")
+
+    def _source_block(self) -> tuple[str, list[str]]:
+        source = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text(encoding="utf-8")
+        start = source.find(self.OPEN)
+        end = source.find(self.CLOSE, start)
+        assert start != -1 and end != -1, "Telegram formatting section is missing from its owner"
+        block = source[start:end + len(self.CLOSE)]
+        clauses = [line.strip() for line in block.splitlines() if line.strip()]
+        assert len(clauses) >= 10, "Telegram formatting section is unexpectedly short"
+        return block, clauses
+
+    def test_every_source_clause_reaches_the_assembled_user_prompt(self):
+        """The source file, not hand-written test phrases, supplies the delivery anchors."""
+        _block, clauses = self._source_block()
+        assembled = P.build_system_prompt(PIPELINE, self.USER_ROLE)
+        for clause in clauses:
+            assert clause in assembled, f"Telegram formatting clause did not assemble: {clause!r}"
+
+    def test_telegram_formatting_does_not_leak_to_non_user_roles(self):
+        block, _clauses = self._source_block()
+        assert self.OPEN in P.build_system_prompt(PIPELINE, self.USER_ROLE)
+        for role in self.OTHER_ROLES:
+            assembled = P.build_system_prompt(PIPELINE, role)
+            assert self.OPEN not in assembled, f"Telegram rules leaked into {role}"
+            assert block not in assembled, f"Telegram rules leaked into {role}"
+
+
 # ── modules: инлайн переиспользуемых блоков после слоёв роли ────────────────
 
 class TestDefaultModulesInline:
     GIT_MARKER = "Each worker runs in an isolated"
     ORCH_MARKER = "## Role: Orchestrator"
### 9442bc38b #221: #221: add model routing priority oracle

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 1ab4ac075..6fa8aebd8 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -633,5 +633,39 @@ class TestOracleGate:
                 "либо слова посажены в общий слой вместо роли"
             )
             assert self.EXEC_ANCHOR not in out, (
                 f"{role}: контрправило исполнителя протекло в промпт оркестратора"
             )
+
+POOL_PRIORITY_ANCHORS = (
+    "Luna is the DEFAULT",
+    "Sol when the task is complex and Luna will not manage it",
+    "Opus only for special complex tasks",
+    "the Codex pool is meant to be burned",
+    "cost of exhaustion, not the cost of spend",
+)
+OBSOLETE_PRIORITY_ANCHOR = "— DEFAULT worker"
+
+
+def _roles_receiving_model_routing():
+    from app.pipeline import build_system_prompt
+    roles = []
+    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
+        if "model-routing" in build_system_prompt("default", role) or "Spark" in build_system_prompt("default", role):
+            roles.append(role)
+    assert roles, "ни одна роль не получает model-routing — проверка выродилась"
+    return roles
+
+
+def test_pool_priority_rule_reaches_roles_that_receive_model_routing():
+    from app.pipeline import build_system_prompt
+    for role in _roles_receiving_model_routing():
+        out = build_system_prompt("default", role)
+        for anchor in POOL_PRIORITY_ANCHORS:
+            assert anchor in out, f"{role}: нет якоря {anchor!r}"
+
+
+def test_obsolete_priority_formulation_is_gone_everywhere():
+    from app.pipeline import build_system_prompt
+    for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
+        out = build_system_prompt("default", role)
+        assert OBSOLETE_PRIORITY_ANCHOR not in out, f"{role}: осталась старая формулировка приоритета"
### 45d761005 #223: #223: correct barrier conclusion

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 6fa8aebd8..f69034f49 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -634,10 +634,125 @@ class TestOracleGate:
             )
             assert self.EXEC_ANCHOR not in out, (
                 f"{role}: контрправило исполнителя протекло в промпт оркестратора"
             )
 
+class TestTicketDelegationGate:
+    """#223: закрытый тикет уходит исполнителю, а оракул остаётся у full-cycle."""
+
+    IMMUTABLE_ANCHOR = (
+        "The received acceptance test is immutable: NEVER edit, delete, rename, skip, "
+        "xfail, or weaken it."
+    )
+    WORKER_FAILURE_ANCHOR = (
+        "If the command cannot be made green without changing that test, report `WIP/STOP`; "
+        "do not replace it or create a different check."
+    )
+    TEST_INFRA_ANCHOR = (
+        "Do not modify any test, fixture, test helper, `conftest.py`, test configuration, "
+        "marker, or test-selection setting; if the implementation requires one, report "
+        "`WIP/STOP`."
+    )
+    FULL_CYCLE_ANCHORS = (
+        "Only a ticket with a reviewed, committed RED command that just failed for the "
+        "missing behavior is delegable.",
+        "A ticket marked `oracle: none` is NEVER delegated; implement it yourself on the "
+        "expensive side.",
+        "Send `Files`, `Test`, `AC`, `blocked-by`, the RED commit, the exact command, its "
+        "non-zero exit and failing assertion, plus these sentences verbatim:",
+        "The worker sends exactly one message: its terminal `DONE` report, or one terminal "
+        "exception report instead.",
+        "The terminal report contains the executor commit, the exact test command and output, "
+        "and evidence for every remaining AC.",
+        "Before merge, compare every oracle path byte-for-byte with the RED commit.",
+        "Reject any executor diff that changes a test, fixture, test helper, `conftest.py`, "
+        "test configuration, marker, or test-selection setting relative to the RED commit.",
+        "A clarification request, a `WIP/STOP` report, or any oracle mutation is a failed "
+        "executor attempt.",
+        "Luna gets exactly one attempt.",
+        "On failure, send the same unchanged ticket once to a Sol `worker`; do not answer "
+        "Luna's question, rewrite its oracle, or return the ticket to Luna.",
+        "A Sol `worker` gets exactly one attempt.",
+        "If the premise, scope, Test, or AC must change, take it back immediately and re-close "
+        "it before any future delegation.",
+        "A child's green report is evidence, not acceptance. Merge only a clean committed "
+        "result, then rerun the exact command and the ticket's focused regression check "
+        "yourself.",
+        "Independent tickets whose files and lines do not overlap may run concurrently; "
+        "serialize only dependency chains and overlapping changes.",
+        "Never split one implementation ticket across agents.",
+    )
+    ORCHESTRATOR_ROLES = ("orchestrator", "sub-orchestrator")
+
+    def _src(self, role: str) -> str:
+        return P.prompt_path(PIPELINE, f"roles/{role}.md").read_text(encoding="utf-8")
+
+    def test_t1_delegation_full_cycle_source_owns_the_complete_contract(self):
+        src = self._src("full-cycle")
+        missing = [anchor for anchor in self.FULL_CYCLE_ANCHORS if anchor not in src]
+        assert not missing, f"roles/full-cycle.md is missing delegation clauses: {missing}"
+
+    def test_t1_delegation_immutable_rule_is_owned_by_both_sources(self):
+        for role in ("full-cycle", "worker"):
+            assert self.IMMUTABLE_ANCHOR in self._src(role), (
+                f"roles/{role}.md must own the immutable-oracle rule"
+            )
+            assert self.TEST_INFRA_ANCHOR in self._src(role), (
+                f"roles/{role}.md must own the oracle-infrastructure rule"
+            )
+        assert self.WORKER_FAILURE_ANCHOR in self._src("worker"), (
+            "roles/worker.md must turn an oracle-dependent implementation into WIP/STOP"
+        )
+
+    def test_t1_delegation_contract_reaches_working_roles(self):
+        full_cycle = P.build_system_prompt(PIPELINE, "full-cycle")
+        for anchor in (
+            *self.FULL_CYCLE_ANCHORS,
+            self.IMMUTABLE_ANCHOR,
+            self.TEST_INFRA_ANCHOR,
+        ):
+            assert anchor in full_cycle, f"full-cycle prompt lost clause: {anchor!r}"
+        assert self.IMMUTABLE_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
+            "worker prompt lost the immutable-oracle rule"
+        )
+        assert self.WORKER_FAILURE_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
+            "worker prompt lost the WIP/STOP consequence of oracle immutability"
+        )
+        assert self.TEST_INFRA_ANCHOR in P.build_system_prompt(PIPELINE, "worker"), (
+            "worker prompt lost the oracle-infrastructure rule"
+        )
+
+    def test_t1_delegation_does_not_leak_into_orchestrators(self):
+        anchors = (
+            *self.FULL_CYCLE_ANCHORS,
+            self.IMMUTABLE_ANCHOR,
+            self.WORKER_FAILURE_ANCHOR,
+            self.TEST_INFRA_ANCHOR,
+        )
+        for role in self.ORCHESTRATOR_ROLES:
+            out = P.build_system_prompt(PIPELINE, role)
+            leaked = [anchor for anchor in anchors if anchor in out]
+            assert not leaked, f"{role} received executor-only delegation clauses: {leaked}"
+
+    def test_t1_delegation_worker_does_not_receive_parent_policy(self):
+        out = P.build_system_prompt(PIPELINE, "worker")
+        leaked = [anchor for anchor in self.FULL_CYCLE_ANCHORS if anchor in out]
+        assert not leaked, f"worker received parent-only routing policy: {leaked}"
+        assert self.WORKER_FAILURE_ANCHOR not in P.build_system_prompt(
+            PIPELINE, "full-cycle"
+        ), "full-cycle received the worker-only WIP/STOP instruction"
+
+    def test_t1_delegation_gate_precedes_implementation_work(self):
+        out = P.build_system_prompt(PIPELINE, "full-cycle")
+        phase_3 = out.find("### Phase 3: IMPLEMENT")
+        gate = out.find(self.FULL_CYCLE_ANCHORS[0], phase_3)
+        premortem = out.find("**Pre-mortem — what breaks for the next consumer.**", phase_3)
+        assert -1 not in (phase_3, gate, premortem) and phase_3 < gate < premortem, (
+            "the delegation gate must run after Phase 3 starts and before implementation work"
+        )
+
+
 POOL_PRIORITY_ANCHORS = (
     "Luna is the DEFAULT",
     "Sol when the task is complex and Luna will not manage it",
     "Opus only for special complex tasks",
     "the Codex pool is meant to be burned",
### bf5de05e2 #222: #222: add Spark admission delivery oracle

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index f69034f49..5ca7c7204 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -174,10 +174,40 @@ class TestDefaultRolesResolve:
         worker_out = P.build_system_prompt(PIPELINE, "worker")
         assert P.get_role(PIPELINE, "worker").can_spawn == []
         for anchor in ["<model-routing>", *bullets]:
             assert anchor not in worker_out, f"маршрутизация протекла воркеру: {anchor[:40]}"
 
+    def test_t1_spark_admission_rule_is_delivered_without_leaking(self):
+        anchors = (
+            "separate but small quota wallet, not free capacity",
+            "#222 measured only 25 identical benchmark batches per week (250 starts, 200 usage-bearing turns, 125 strict PASS)",
+            "Its dollar price is UNKNOWN (research-preview rates; local price=None), so any money summary that includes Spark is incomplete",
+            "text-only; ≤2 named files",
+            "≤100K total initial context (system prompt + task + supplied files)",
+            "every correctness-critical decision and value is explicit",
+            "an independent pre-existing oracle mechanically covers every correctness-critical criterion",
+            "Spark silently invents missing data: in #222 it did so 2/2 times and missed both future oracles (19/42 and 18/42), while Luna stopped and asked 2/2 times; any missing fact or decision forbids this route",
+            "At ~164K Spark failed loudly before any answer in 2/2 runs, so keep the ≤100K headroom; the measured context failure was not silent corruption",
+            "semantic prose, prompt work without literal anchors, review, research, architecture, vision, and security are forbidden",
+            "After any failed or incomplete Spark attempt, never retry Spark",
+        )
+        module = P.prompt_path(PIPELINE, "modules/model-routing.md").read_text()
+        spark_rules = [line for line in module.splitlines() if line.startswith("- **Spark**")]
+        assert len(spark_rules) == 1, "Spark admission must have exactly one owner rule"
+        spark_rule = spark_rules[0]
+        for anchor in anchors:
+            assert anchor in spark_rule, f"Spark admission rule lacks {anchor!r}"
+
+        for role in ("orchestrator", "sub-orchestrator", "full-cycle"):
+            out = P.build_system_prompt(PIPELINE, role)
+            for anchor in anchors:
+                assert out.count(anchor) == 1, f"{role}: Spark rule is missing or duplicated: {anchor!r}"
+
+        worker_out = P.build_system_prompt(PIPELINE, "worker")
+        for anchor in anchors:
+            assert anchor not in worker_out, f"Spark admission leaked to terminal worker: {anchor!r}"
+
     def test_tg_emoji_for_v216_roles(self):
         assert P.get_role(PIPELINE, "sub-orchestrator").tg.emoji == "🎯"
 
     def test_orchestrator_skills_from_manifest(self):
         rr = P.get_role(PIPELINE, "orchestrator")
### 6dac7dcbf #220: #220: план фазы 2 — T1 пересборка промпта, T2/T3 дренаж, красные тесты тикетов

diff --git a/app/manager.py b/app/manager.py
index 83b47560c..8b18e5dd7 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -435,10 +435,26 @@ class SessionManager:
         self.sessions: dict[str, AgentSession] = {}
         self._session_locks: dict[str, asyncio.Lock] = {}
         self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
         # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
+        # #220 T2: рестарт закрывает приём новых ходов, пока дренажит уже идущие
+        self.draining = False
+
+    def begin_drain(self) -> None:
+        """Закрыть приём новых ходов. СИНХРОННО — в этом весь смысл.
+
+        Ни одного `await` здесь быть не должно: флаг обязан встать раньше, чем цикл
+        событий отдаст управление кому-то ещё. Иначе ход, уже прошедший проверку
+        гейта, успеет присвоить себе RUNNING после того, как дренаж снял снимок
+        живых ходов, и попадёт под сигнал как раз тот, кого дренаж защищал.
+        """
+        self.draining = True
+
+    def end_drain(self) -> None:
+        """Открыть приём обратно. Нужен тестам и отменённому рестарту."""
+        self.draining = False
 
     def get_session_lock(self, session_id: str) -> asyncio.Lock:
         if session_id not in self._session_locks:
             self._session_locks[session_id] = asyncio.Lock()
         return self._session_locks[session_id]
@@ -1415,10 +1431,54 @@ class SessionManager:
         for row in get_all_sessions():
             if row["name"] == name:
                 return await self._load_from_db(row)
         return None
 
+    def assemble_prompt(
+        self, *, pipeline: str, role: str, scope: str, is_orch: bool, name: str,
+        owned_dirs, branch: str, stored_overlay: str | None, old_prompt: str,
+    ) -> tuple[str, str | None]:
+        """Собрать системный промпт из файлов ролей — один владелец на двух вызывающих.
+
+        Зовётся из `_load_from_db` (восстановление сессии при старте) и из переинжекта
+        в `session.py`: без второго вызывающего правка `pipelines/**` доезжала до живого
+        агента только рестартом (#220 T1, медиана задержки выката 3.3 ч).
+
+        Возвращает (собранный промпт, восстановленный overlay). `overlay is None` на
+        выходе означает полную замену промпта оператором — у неё нет границы
+        компонентов, и пересобирать её нельзя.
+        """
+        current_base = ROLE_SYSTEM_PROMPT(
+            pipeline, role, scope
+        ) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
+        if not is_orch:
+            orch_name = self._find_orchestrator_name(scope)
+            current_base = safe_format_prompt(
+                current_base,
+                worker_name=name, orchestrator_name=orch_name or "orchestrator",
+                scope=scope, branch=branch,
+            )
+        if stored_overlay is None:
+            old_without_memory = strip_worker_memory(old_prompt)
+            if not old_without_memory:
+                prompt_overlay = self._ownership_prompt(parse_owned_dirs(owned_dirs))
+                prompt_without_memory = current_base + prompt_overlay
+            elif old_without_memory.startswith(current_base):
+                prompt_overlay = old_without_memory[len(current_base):]
+                prompt_without_memory = current_base + prompt_overlay
+            else:
+                # A legacy/full-prompt override has no component boundary to recover.
+                # Preserve it byte-for-byte instead of guessing and dropping authority.
+                prompt_overlay = None
+                prompt_without_memory = old_without_memory
+        else:
+            prompt_overlay = strip_worker_memory(stored_overlay)
+            prompt_without_memory = current_base + prompt_overlay
+        return refresh_worker_memory(
+            prompt_without_memory, name, role, scope,
+        ), prompt_overlay
+
     async def _load_from_db(self, db_row: dict) -> AgentSession:
         role = db_row.get("role") or ("orchestrator" if db_row.get("is_orchestrator") else "worker")
         # Old rows (migrated) store pipeline='' → normalize to DEFAULT_PIPELINE.
         # Without this, ROLE_SYSTEM_PROMPT('') now fails loud (legacy fallback removed)
         # and resume/load of pre-pipeline sessions would break.
@@ -1434,13 +1494,10 @@ class SessionManager:
             if get_role(pipeline, role) is None:
                 is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
         except FileNotFoundError:
             is_orch = bool(db_row.get("is_orchestrator")) or is_orchestrator_role(role)
         old_prompt = db_row.get("system_prompt", "")
-        current_base = ROLE_SYSTEM_PROMPT(
-            pipeline, role, db_row["scope"]
-        ) if is_orch else ROLE_SYSTEM_PROMPT(pipeline, role)
         cwd = db_row.get("cwd") or db_row["scope"]
         if not Path(cwd).is_dir():
             cwd = db_row["scope"]
         expected_bt = backend_for_model(db_row["model"])
         stored_bt = db_row.get("backend_type") or expected_bt
@@ -1461,40 +1518,15 @@ class SessionManager:
                 if actual_branch != db_branch:
                     db_branch = actual_branch
                     m = _TASK_BRANCH_RE.match(actual_branch)
                     db_task_id = m.group(1) if m else ""
 
-        orch_name = self._find_orchestrator_name(db_row["scope"]) if not is_orch else None
-        if not is_orch:
-            current_base = safe_format_prompt(
-                current_base,
-                worker_name=db_row["name"], orchestrator_name=orch_name or "orchestrator",
-                scope=db_row["scope"],
-                branch=db_row.get("branch") or db_row.get("base_branch") or "",
-            )
-        stored_overlay = db_row.get("prompt_overlay")
-        if stored_overlay is None:
-            old_without_memory = strip_worker_memory(old_prompt)
-            if not old_without_memory:
-                prompt_overlay = self._ownership_prompt(
-                    parse_owned_dirs(db_row.get("owned_dirs"))
-                )
-                prompt_without_memory = current_base + prompt_overlay
-            elif old_without_memory.startswith(current_base):
-                prompt_overlay = old_without_memory[len(current_base):]
-                prompt_without_memory = current_base + prompt_overlay
-            else:
-                # A legacy/full-prompt override has no component boundary to recover.
-                # Preserve it byte-for-byte instead of guessing and dropping authority.
-                prompt_overlay = None
-                prompt_without_memory = old_without_memory
-        else:
-            prompt_overlay = strip_worker_memory(stored_overlay)
-            prompt_without_memory = current_base + prompt_overlay
-        current_prompt = refresh_worker_memory(
-            prompt_without_memory,
-            db_row["name"], role, db_row["scope"],
+        current_prompt, prompt_overlay = self.assemble_prompt(
+            pipeline=pipeline, role=role, scope=db_row["scope"], is_orch=is_orch,
+            name=db_row["name"], owned_dirs=db_row.get("owned_dirs"),
+            branch=db_row.get("branch") or db_row.get("base_branch") or "",
+            stored_overlay=db_row.get("prompt_overlay"), old_prompt=old_prompt,
         )
 
         custom_mcp = _parse_custom_mcp(db_row.get("mcp_servers_custom"))
         session = AgentSession(
             id=db_row["id"], name=db_row["name"], scope=db_row["scope"], cwd=cwd,
diff --git a/app/session.py b/app/session.py
index 7ac155b38..c1d415572 100644
### 6712fdcf4 #219, #223: #219 T2: контракт делегирования «таблица, а не область» в worker-lifecycle + тесты на происхождение якорей (первая редакция теста была ложно-зелёной на составной мутации)

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 5ca7c7204..2a298df05 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -812,5 +812,101 @@ def test_pool_priority_rule_reaches_roles_that_receive_model_routing():
 def test_obsolete_priority_formulation_is_gone_everywhere():
     from app.pipeline import build_system_prompt
     for role in ("orchestrator", "sub-orchestrator", "worker", "full-cycle"):
         out = build_system_prompt("default", role)
         assert OBSOLETE_PRIORITY_ANCHOR not in out, f"{role}: осталась старая формулировка приоритета"
+
+
+# --- #219: контракт делегирования «таблица, а не область» -------------------
+# Якоря — ЦЕЛЬНЫЕ фразы, выписанные вручную из файла-владельца
+# (pipelines/default/prompts/modules/worker-lifecycle.md). Не извлекать их из
+# источника программно: клауза, извлечённая из уже переформатированного файла,
+# находится в сборке всегда и делает тест слепым к переносу строки (#210).
+FAN_CONTRACT_ANCHORS = (
+    "Order a **schema** — the exact columns — not a subject area.",
+    "Give the **counting rule verbatim**",
+    "Numbers from different\nchildren are not addable unless you defined the count.",
+    "**Forbid conclusions and recommendations.**",
+    "**The join and the verdict are yours.**",
+    "Choosing which two columns to compare IS the",
+)
+
+# Роль, которая НЕ умеет спавнить, не должна получать контракт: лишний текст в
+# промпте терминальной роли — это плата без применения.
+FAN_CONTRACT_SPAWNERS = ("orchestrator", "sub-orchestrator", "full-cycle")
+FAN_CONTRACT_TERMINAL = ("worker",)
+
+
+def _spawn_capable_roles_from_config():
+    """Список берётся из КОНФИГА, а не из константы выше: если появится новая
+    спавнящая роль, тест обязан покраснеть, а не молча её пропустить."""
+    from app.pipeline import load_pipeline
+    cfg = load_pipeline("default")
+    roles = [n for n, r in cfg.roles.items() if r.can_spawn]
+    assert roles, "ни одна роль не умеет спавнить — проверка выродилась"
+    return roles
+
+
+def _norm(text: str) -> str:
+    """Схлопывает переносы и отступы. Якорь остаётся ЦЕЛЬНОЙ фразой (ловит удаление),
+    но переживает переформатирование файла — подгонять литерал под текущую вёрстку
+    нельзя, он сломается на следующем же реflow (#210)."""
+    import re
+    return re.sub(r"\s+", " ", text).strip()
+
+
+def test_fan_contract_reaches_every_spawn_capable_role():
+    from app.pipeline import build_system_prompt
+    for role in _spawn_capable_roles_from_config():
+        out = _norm(build_system_prompt("default", role))
+        for anchor in FAN_CONTRACT_ANCHORS:
+            assert _norm(anchor) in out, f"{role}: нет якоря контракта веера {anchor!r}"
+
+
+def test_fan_contract_absent_from_terminal_roles():
+    from app.pipeline import build_system_prompt
+    for role in FAN_CONTRACT_TERMINAL:
+        out = build_system_prompt("default", role)
+        assert "Order a **schema**" not in _norm(out), (
+            f"{role}: не умеет спавнить, но получил контракт делегирования"
+        )
+
+
+FAN_CONTRACT_OWNER = "modules/worker-lifecycle.md"
+
+
+def test_fan_contract_comes_from_its_owner_module_and_nowhere_else():
+    """AC-3, автоматизируемая половина — проверяется ПРОИСХОЖДЕНИЕ, а не наличие.
+
+    Первая редакция этого теста грепала собранный промпт и была ЛОЖНО-ЗЕЛЁНОЙ:
+    составная мутация «пункт удалён из роли + фраза внедрена в base.md» её
+    проходила (замер #219, воспроизведён дефект #198). Инструкция при этом
+    материально теряется — она уезжает в общий слой, где достаётся и терминальным
+    ролям, и теряет свой контекст. Поэтому каждый якорь обязан иметь РОВНО ОДНОГО
+    владельца, и владелец — именно модуль ниже.
+
+    Вторую половину AC-3 — «нет ли той же мысли, сформулированной иначе» — греп не
+    закрывает по построению; она остаётся ручной проверкой артефакта.
+    """
+    from pathlib import Path
+    root = Path(__file__).resolve().parents[1] / "pipelines" / "default" / "prompts"
+    files = {p: _norm(p.read_text(encoding="utf-8")) for p in root.rglob("*.md")}
+    for anchor in FAN_CONTRACT_ANCHORS:
+        owners = [p for p, text in files.items() if _norm(anchor) in text]
+        assert len(owners) == 1, (
+            f"якорь {anchor!r}: владельцев должно быть ровно 1, найдено {len(owners)}: "
+            f"{[str(p) for p in owners]}"
+        )
+        assert str(owners[0]).endswith(FAN_CONTRACT_OWNER), (
+            f"якорь {anchor!r} уехал из {FAN_CONTRACT_OWNER} в {owners[0]}"
+        )
+
+
+def test_child_is_not_told_to_self_terminate_on_exhaustion():
+    """M1: ребёнок останавливается по собственной оценке полноты, и она слепа.
+    Формулировка «продолжай, пока вопрос не исчерпан» не должна вернуться."""
+    from app.pipeline import build_system_prompt
+    for role in _spawn_capable_roles_from_config():
+        out = build_system_prompt("default", role)
+        assert "until the question is exhausted" not in out.replace(
+            'continue "until the question is exhausted"', ""
+        ), f"{role}: вернулась формулировка про самостоятельное исчерпание"
### 9b1b48b54 #219: #219 T1b: красные тесты проводки — два гейта, killed-токен, девять неприкосновенных путей

diff --git a/app/manager.py b/app/manager.py
index 8b18e5dd7..7695e5cac 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -978,10 +978,18 @@ class SessionManager:
 
     async def remove(self, session_id: str) -> None:
         from app.bg_jobs import bg_manager
         await bg_manager.cancel_by_session(session_id)
         session = self.sessions.get(session_id)
+        # #219 T1b, AC-2: убитый ребёнок обязан породить ПОЛОЖИТЕЛЬНЫЙ терминальный
+        # токен. Гейт на `fire_auto_report` его породить не может — тот выходит
+        # раньше `on_idle` для `_manually_interrupted` (`session_turns.py:266`).
+        # Без этого веер висит до дедлайна при уже известном исходе.
+        _killed_name = session.name if session else (get_session(session_id) or {}).get("name")
+        if _killed_name:
+            from app import fan_barrier
+            fan_barrier.on_child_killed(_killed_name)
         if session is None:
             row = get_session(session_id)
             if row is None:
                 return
             session = self._hydrate_row(row)
### f5910ff9c #224: #224: plan + acceptance tests committed RED (T1-T7)

diff --git a/app/pipeline.py b/app/pipeline.py
index 538b362ce..5589625b5 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -181,11 +181,14 @@ class PromptLayers(BaseModel):
 class Defaults(BaseModel):
     """Дефолты пайплайна. Роль переопределяет: скаляр — replace, список — union."""
     model_config = ConfigDict(extra="forbid")
     model: str = "opus"
     skills: AllOrList = "all"
-    mcp_servers: AllOrList = "all"
+    # Fail-CLOSED (#224): `"all"` в `_merge_list` ПОГЛОЩАЕТ любой список, поэтому пайплайн,
+    # забывший строку `mcp_servers:`, раздавал бы каждой роли все user-level MCP-серверы
+    # вместе с их секретами. Раздача остаётся возможной — но только когда её попросили явно.
+    mcp_servers: AllOrList = []
     inherit_claude_md: bool = True
     prompt_layers: PromptLayers = Field(default_factory=PromptLayers)
     worktree: Worktree = Field(default_factory=Worktree)
     base_branch_strategy: BranchStrategy = "parent"
     docs_scaffold: bool = True