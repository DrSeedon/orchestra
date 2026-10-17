# Context for item-32

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/manager.py b/app/manager.py
index a710a2fae..cfc525829 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1,26 +1,27 @@
 """SessionManager — registry, lifecycle, persistence for all agent sessions."""
 
 import asyncio
 import itertools
 import json
 import logging
+import math
 import os
 import re
 import sqlite3
 import subprocess
 import sys
 import time
 import uuid
 from contextlib import asynccontextmanager
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Awaitable, Callable, Optional
 
 from app.session import AgentSession, AgentStatus
 from app.prompting import (
     is_orchestrator_role, safe_format_prompt,
     prompt_template_hash, inject_skills_to_worktree, load_worker_memory,
     refresh_worker_memory, strip_worker_memory,
 )
 
 # Matches "task-42/worker-name" or "PAR-42/worker-name" — extracts task number from branch
@@ -49,40 +50,66 @@ from app.pipeline import (
     load_pipeline,
     resolve_effort,
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
+# Keep policy telemetry inside the 30s MCP request budget. Slow/missing telemetry is
+# advisory failure: the model gate logs it and admits the worker.
+WORKER_MODEL_POLICY_TIMEOUT_SECONDS = 12.0
+
+
+async def _worker_model_policy_usage() -> dict:
+    """Read the same live payload served by GET /api/usage."""
+    from app.routes.system import get_usage
+
+    usage = await get_usage()
+    if not isinstance(usage, dict):
+        raise RuntimeError("GET /api/usage returned no worker quota telemetry")
+    return usage
+
+
+def _policy_utilization(usage: dict, provider: str, window: str) -> float:
+    data = usage.get(provider)
+    value = data.get(window, {}).get("utilization") if isinstance(data, dict) else None
+    if (
+        isinstance(value, bool)
+        or not isinstance(value, (int, float))
+        or not math.isfinite(float(value))
+        or not 0 <= float(value) <= 100
+    ):
+        raise ValueError(f"{provider}.{window}.utilization is missing or malformed")
+    return float(value)
 
 
 class LockBusy(RuntimeError):
     """Лок сессии занят дольше отведённого: у вызова есть кто уступить и кому повторить."""
 
     def __init__(self, what: str, worker: str, waited: float):
         self.what, self.worker, self.waited = what, worker, waited
         super().__init__(
             f"worker '{worker}' is busy: another operation has held the session lock for "
             f"{waited:.0f}s (message delivery or merge in flight). Nothing was changed — "
             f"retry {what} in ~30s."
         )
 
 
 @asynccontextmanager
 async def wait_for_session_lock(lock, *, what: str, worker: str, limit: float | None = None):
     """Взять лок сессии так, чтобы ожидание было ВИДНО снаружи.
 
     Замер #27: доставка держит лок секундами (коннект CLI-бэкенда 1.6–2.0 с, а `connect()`
     внутри разрешает себе до 60 с), git при этом занимает 0.01 с. Раньше ожидание не
@@ -418,40 +445,41 @@ def _make_mcp_config(name: str, scope: str, role: str = "worker",
 def _crosses_repo_boundary(parent_dir: str, child_repo: str) -> bool:
     """Родитель и ребёнок в РАЗНЫХ репозиториях? Спрашиваем git, а не сравниваем пути.
 
     Каталог `seedon/site` лежит внутри `seedon`, но это другой репозиторий; префиксное
     сравнение путей ответило бы «тот же» (#69). Не смогли определить — считаем, что
     граница НЕ пересечена: тогда исходная ошибка о ненайденной ветке уйдёт наверх как есть,
     без выдуманного объяснения.
     """
     try:
         return repo_root(parent_dir) != repo_root(child_repo)
     except Exception as exc:
         logger.warning("не смог сравнить репозитории '%s' и '%s': %s", parent_dir, child_repo, exc)
         return False
 
 
 class SessionManager:
     def __init__(self):
         self.sessions: dict[str, AgentSession] = {}
         self._session_locks: dict[str, asyncio.Lock] = {}
         self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
+        self._worker_model_policy_latches: dict[tuple[str, str, float, float], bool] = {}
         # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
         # #220 T2: рестарт закрывает приём новых ходов, пока дренажит уже идущие
         self.draining = False
 
     def begin_drain(self) -> None:
         """Закрыть приём новых ходов. СИНХРОННО — в этом весь смысл.
 
         Ни одного `await` здесь быть не должно: флаг обязан встать раньше, чем цикл
         событий отдаст управление кому-то ещё. Иначе ход, уже прошедший проверку
         гейта, успеет присвоить себе RUNNING после того, как дренаж снял снимок
         живых ходов, и попадёт под сигнал как раз тот, кого дренаж защищал.
         """
         self.draining = True
 
     def end_drain(self) -> None:
         """Открыть приём обратно. Нужен тестам и отменённому рестарту."""
         self.draining = False
 
     def get_session_lock(self, session_id: str) -> asyncio.Lock:
@@ -469,92 +497,159 @@ class SessionManager:
         # reproduced: one green `pytest tests/test_build_signal.py` erased both decoys).
         if "pytest" in sys.modules:
             logger.warning("worktree cleanup task not started: running under pytest")
             return
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
 
+    async def _enforce_worker_model_policy(
+        self,
+        pipeline: str,
+        role: str,
+        model: str,
+        override_reason: str,
+    ) -> None:
+        cfg = load_pipeline(pipeline)
+        role_spec = cfg.roles.get(role)
+        if role_spec is None or role_spec.kind == "orchestrator":
+            return
+        policy = cfg.worker_model_policy
+        if policy is None:
+            return
+
+        reason = override_reason.strip()
+        if reason:
+            logger.warning(
+                "worker model policy overridden: pipeline=%s role=%s model=%s reason=%s",
+                pipeline, role, model, reason,
+            )
+            return
+        if model in policy.always_allowed:
+            return
+
+        alternatives = ", ".join(policy.alternatives)
+        balanced = policy.quota_balanced
+        if model != balanced.model:
+            raise ValueError(
+                f"worker model '{model}' is not allowed by pipeline '{pipeline}'. "
+                f"Use {alternatives}, or pass model_policy_override_reason with a non-empty reason."
+            )
+
+        try:
+            async with asyncio.timeout(WORKER_MODEL_POLICY_TIMEOUT_SECONDS):
+                usage = await _worker_model_policy_usage()
+            claude = _policy_utilization(usage, "anthropic", "seven_day")
+            codex = _policy_utilization(usage, "codex", "primary")
+        except Exception as error:
+            logger.error(
+                "worker model policy telemetry unavailable; allowing model=%s: %s: %s",
+                model, type(error).__name__, err_text(error),
+            )
+            return
+
+        gap = claude - codex
+        key = (pipeline, model, balanced.block_gap_pp, balanced.unblock_gap_pp)
+        blocked = self._worker_model_policy_latches.get(
+            key, gap > balanced.unblock_gap_pp,
+        )
+        if gap >= balanced.block_gap_pp:
+            blocked = True
+        elif gap <= balanced.unblock_gap_pp:
+            blocked = False
+        self._worker_model_policy_latches[key] = blocked
+        if blocked:
+            raise ValueError(
+                f"worker model '{model}' is blocked while subscription pools are imbalanced: "
+                f"Claude 7d {claude:g}%, Codex {codex:g}% (gap {gap:g} pp; "
+                f"unlocks at <= {balanced.unblock_gap_pp:g} pp and blocks at "
+                f">= {balanced.block_gap_pp:g} pp). Use {alternatives}, or pass "
+                "model_policy_override_reason with a non-empty reason."
+            )
+
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
                              tg_topic: bool = False,
-                             planned_initial_turn: bool = False) -> AgentSession:
+                             planned_initial_turn: bool = False,
+                             model_policy_override_reason: str = "") -> AgentSession:
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
                 planned_initial_turn=planned_initial_turn,
+                model_policy_override_reason=model_policy_override_reason,
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
                              tg_topic: bool = False,
-                             planned_initial_turn: bool = False) -> AgentSession:
+                             planned_initial_turn: bool = False,
+                             model_policy_override_reason: str = "") -> AgentSession:
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
 
@@ -632,40 +727,43 @@ class SessionManager:
         # Worker persistent memory: docs/workers/{name}.md or docs/workers/{role}.md
         # Survives kill/respawn/compact — worker writes rules here, they auto-inject next time
         memory_repository = repo_path if use_worktree and repo_path else ""
         worker_memory = load_worker_memory(name, role, scope, memory_repository)
         if worker_memory:
             prompt += f"\n\n<worker-memory>\n{worker_memory}\n</worker-memory>"
 
         if not parent_id and parent_name:
             p_session = self.get_by_name(parent_name, scope)
             if p_session:
                 parent_id = p_session.id
 
         # R2: валидация спавна ДО любых side-effects (worktree/start). Единственный
         # источник прав — манифест пайплайна: другого пути принятия решения о спавне
         # в коде нет. Нет манифеста → FileNotFoundError пробрасывается
         # (fail loud, единый источник = pipelines/).
         parent_role = self._resolve_role(parent_name, scope) if parent_name else ""
         validate_spawn(pipeline, parent_role, role if explicit_role else "")
 
         if planned_initial_turn and not is_orch:
+            await self._enforce_worker_model_policy(
+                pipeline, role, model, model_policy_override_reason,
+            )
             from app.quota_gate import get_worker_admission, require_worker_admission
 
             require_worker_admission(await get_worker_admission(model))
 
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
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index e542f09e1..39f724941 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -706,48 +706,50 @@ async def _quota_refusal(model: str) -> ApiToolError | None:
         readiness = await _api("GET", "/api/usage/readiness", params={"model": model})
     except Exception as error:
         return _weekly_quota_unknown(
             model, f"{type(error).__name__}: {err_text(error)}",
         )
     return _quota_refusal_from_readiness(
         model, readiness, now=time.time(),
     )
 
 
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
-                       tg_topic: bool = False) -> str:
+                       tg_topic: bool = False,
+                       model_policy_override_reason: str = "") -> str:
     """Spawn a new worker agent in a git worktree. Model is REQUIRED — choose it by the `<model-routing>` block in your own prompt, which is the single source of truth for routing (model ids are deliberately not repeated here: a duplicated list rots).
     base_branch — от какой локальной ветки ответвить worktree. Пусто ("") = авто по
     стратегии пайплайна: parent → ветка родителя, main → проверяемый mainline репозитория.
     При неоднозначности spawn требует явную ветку.
     mcp_servers — JSON-объект с доп. MCP-серверами для воркера (формат как в .mcp.json: {"name": {"command": ..., "args": [...]}}). Мерджится с дефолтным Orchestra MCP; ключ "orchestra" игнорируется. Переживает рестарт.
     owned_dirs — JSON-массив директорий которыми владеет воркер, напр. ["app/api/", "app/models/"]. Инжектится в промпт воркера ("трогай только это"). Пересечение с owned_dirs другого живого воркера → БЛОК (spawn fails).
-    tg_topic — если True, агент получит собственный TG топик для логов и сообщений."""
+    tg_topic — если True, агент получит собственный TG топик для логов и сообщений.
+    model_policy_override_reason — явное исключение из серверной model policy. Пусто = исключения нет; непустая причина записывается в лог."""
     if not model:
         raise ApiToolError(
             code="invalid_argument",
             message="model is required; choose it by the <model-routing> block in your prompt",
             details={"field": "model"},
         )
     scope = SCOPE or repo_path
     body = {
         "name": name, "scope": scope, "cwd": repo_path,
         "model": model, "system_prompt": system_prompt,
         "use_worktree": True, "repo_path": repo_path,
         "base_branch": base_branch,
         "role": role,
         "parent_name": WORKER_NAME,
         "planned_initial_turn": True,
     }
     if mcp_servers:
         import json
         try:
             parsed = json.loads(mcp_servers)
@@ -772,40 +774,42 @@ async def spawn_worker(name: str, task: str, repo_path: str,
             if isinstance(parsed, list):
                 body["owned_dirs"] = parsed
             else:
                 raise ApiToolError(
                     code="invalid_argument",
                     message="owned_dirs must be a JSON array",
                     details={"field": "owned_dirs"},
                 )
         except json.JSONDecodeError as e:
             raise ApiToolError(
                 code="invalid_argument",
                 message=f"owned_dirs is not valid JSON: {e}",
                 details={"field": "owned_dirs"},
             ) from e
     if task_id:
         body["task_id"] = task_id
     if description:
         body["description"] = description
     if tg_topic:
         body["tg_topic"] = True
+    if model_policy_override_reason:
+        body["model_policy_override_reason"] = model_policy_override_reason
     result = await _api("POST", "/api/sessions", json=body)
     if isinstance(result, dict) and result.get("error"):
         raise ApiToolError(code="domain_error", message=f"Spawn failed: {result['error']}")
     required = ("worktree_path", "branch", "repo_path", "git_common_dir")
     missing = [
         field for field in required
         if (
             not isinstance(result, dict)
             or not isinstance(result.get(field), str)
             or not result[field].strip()
         )
     ]
     if missing:
         next_action = {
             "code": "INSPECT_BEFORE_RETRY",
             "message": "Inspect list_agents before retrying; creation outcome is unknown.",
         }
         raise ApiToolError(
             code="invalid_response",
             message=(
diff --git a/app/pipeline.py b/app/pipeline.py
index 5589625b5..16faa1eca 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -161,40 +161,105 @@ class PromptLayers(BaseModel):
 
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
 
 
+class QuotaBalancedModelPolicy(BaseModel):
+    """One worker model whose admission follows the live Claude/Codex balance."""
+
+    model_config = ConfigDict(extra="forbid")
+    model: str
+    block_gap_pp: float
+    unblock_gap_pp: float
+
+    @field_validator("model")
+    @classmethod
+    def _canonical_model(cls, v: str) -> str:
+        if not _model_is_known(v):
+            logger.warning("worker model policy: unknown quota-balanced model '%s'", v)
+        return _canon_model(v)
+
+    @model_validator(mode="after")
+    def _valid_hysteresis(self) -> "QuotaBalancedModelPolicy":
+        if not 0 <= self.unblock_gap_pp < self.block_gap_pp <= 100:
+            raise ValueError(
+                "worker model policy requires 0 <= unblock_gap_pp < block_gap_pp <= 100"
+            )
+        return self
+
+
+class WorkerModelPolicy(BaseModel):
+    """Server-enforced model admission for roles whose manifest kind is worker."""
+
+    model_config = ConfigDict(extra="forbid")
+    always_allowed: list[str]
+    denied: list[str]
+    quota_balanced: QuotaBalancedModelPolicy
+    alternatives: list[str]
+
+    @field_validator("always_allowed", "denied", "alternatives")
+    @classmethod
+    def _canonical_models(cls, values: list[str]) -> list[str]:
+        result: list[str] = []
+        for value in values:
+            if not _model_is_known(value):
+                logger.warning("worker model policy: unknown model '%s'", value)
+            model = _canon_model(value)
+            if model in result:
+                raise ValueError(f"worker model policy contains duplicate model '{model}'")
+            result.append(model)
+        return result
+
+    @model_validator(mode="after")
+    def _valid_sets(self) -> "WorkerModelPolicy":
+        if self.quota_balanced.model in self.always_allowed:
+            raise ValueError("quota-balanced model cannot also be always allowed")
+        overlap = set(self.always_allowed) & set(self.denied)
+        if self.quota_balanced.model in self.denied:
+            overlap.add(self.quota_balanced.model)
+        if overlap:
+            raise ValueError(
+                f"worker model policy allows and denies the same model: {sorted(overlap)}"
+            )
+        missing = set(self.alternatives) - set(self.always_allowed)
+        if missing:
+            raise ValueError(
+                f"worker model policy alternatives must be always allowed: {sorted(missing)}"
+            )
+        return self
+
+
 class Defaults(BaseModel):
     """Дефолты пайплайна. Роль переопределяет: скаляр — replace, список — union."""
     model_config = ConfigDict(extra="forbid")
     model: str = "opus"
     skills: AllOrList = "all"
     # Fail-CLOSED (#224): `"all"` в `_merge_list` ПОГЛОЩАЕТ любой список, поэтому пайплайн,
     # забывший строку `mcp_servers:`, раздавал бы каждой роли все user-level MCP-серверы
     # вместе с их секретами. Раздача остаётся возможной — но только когда её попросили явно.
     mcp_servers: AllOrList = []
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
@@ -298,40 +363,41 @@ class RoleSpec(BaseModel):
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
     description: str = ""
     validation: ValidationMode = "fail-closed"
     defaults: Defaults = Field(default_factory=Defaults)
+    worker_model_policy: WorkerModelPolicy | None = None
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
diff --git a/app/routes/sessions.py b/app/routes/sessions.py
index 538782ca2..5521e769d 100644
--- a/app/routes/sessions.py
+++ b/app/routes/sessions.py
@@ -111,40 +111,41 @@ def _session_base_branch(session, requested: str = "") -> str:
 class CreateSessionRequest(BaseModel):
     name: str
     cwd: str
     model: str = "claude-sonnet-5[1m]"
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
     planned_initial_turn: bool = False
+    model_policy_override_reason: str = ""
 
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
@@ -216,40 +217,41 @@ async def create_session(req: CreateSessionRequest):
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
             planned_initial_turn=req.planned_initial_turn,
+            model_policy_override_reason=req.model_policy_override_reason,
         )
         d = session.to_dict()
         if req.use_worktree:
             d["repo_path"] = session._spawn_repo_path
             d["git_common_dir"] = session._spawn_git_common_dir
         if session._spawn_warning:
             d["spawn_warning"] = session._spawn_warning
         return d
     except QuotaGateError as e:
         return JSONResponse(e.envelope(), status_code=e.status_code)
     except ValueError as e:
         return JSONResponse({"error": str(e)}, status_code=409)
     except sqlite3.IntegrityError:
         return JSONResponse({"error": f"session '{req.name}' already exists"}, status_code=409)
     except Exception as e:
         import traceback
         logger.error(f"spawn failed: {traceback.format_exc()}")
         return JSONResponse({"error": str(e)}, status_code=500)
 
 
diff --git a/docs/tasks/227/codex-review-impl.md b/docs/tasks/227/codex-review-impl.md
new file mode 100644
index 000000000..fb2e5f0ae
--- /dev/null
+++ b/docs/tasks/227/codex-review-impl.md
@@ -0,0 +1,20 @@
+The policy decisions and compatibility plumbing are otherwise coherent, but the telemetry path lacks the explicitly required timeout boundary. A stalled usage refresh can therefore prevent worker admission instead of failing open.
+
+Review comment:
+
+- [P1] blocking: Bound the telemetry lookup with a timeout — /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-model-gate/app/manager.py:548-548
+  When `/api/usage` stalls while refreshing any provider, this await can block worker creation indefinitely rather than fulfilling the required fail-open-on-timeout behavior. `_get_usage_data()` also refreshes unrelated Grok telemetry and provides no overall deadline here, so wrap the policy lookup in a bounded timeout and treat `TimeoutError` through the existing loud fail-open branch.
+
+> ⚠ Codex usage unaccounted: ValueError: Codex completed turn reported zero tokens
+
+## Round (2026-08-13T05:50:24Z)
+
+Re-review status: **FIXED**. Telemetry lookup is bounded at 12 seconds, and `TimeoutError` reaches the existing loud fail-open path.
+
+New findings: None.
+
+Verdict: **APPROVED**
+
+Test: `uv run pytest -q tests/test_worker_model_policy.py::test_balance_telemetry_timeout_is_fail_open_and_loud`
+
+Output: `1 passed in 5.73s`
diff --git a/docs/tasks/227/report.md b/docs/tasks/227/report.md
new file mode 100644
index 000000000..0d8847981
--- /dev/null
+++ b/docs/tasks/227/report.md
@@ -0,0 +1,51 @@
+# #227 — серверный model gate для worker spawn
+
+## Результат
+
+`spawn_worker` больше не полагается на соблюдение текстового model-routing. Политика живёт в
+`pipelines/default/pipeline.yaml`, типизированно грузится общим pipeline loader и проверяется в
+`SessionManager` до создания worktree, старта backend и публикации сессии.
+
+- Всегда разрешены `gpt-5.6-sol`, `gpt-5.6-luna`, `gpt-5.3-codex-spark`.
+- Явно запрещены `claude-fable-5[1m]` и `gpt-5.6-terra`; прочие не перечисленные worker-модели
+  тоже отклоняются.
+- `claude-opus-5[1m]` управляется разрывом `anthropic.seven_day.utilization -
+  codex.primary.utilization`: блокировка при `>=6` п.п., разблокировка при `<=3` п.п.; внутри
+  полосы сохраняется предыдущее состояние. После холодного старта значение внутри deadband
+  консервативно считается заблокированным. При текущих `63% / 8%` разрыв равен `55` п.п.
+- Полоса 3 п.п. выведена из формы телеметрии: оба отображаемых целых счётчика могут сдвинуться
+  на один пункт за выборку, то есть совместный шаг разрыва достигает 2 п.п.; deadband взят на
+  один пункт шире.
+- Роли с `kind: orchestrator` освобождены от worker policy.
+- `model_policy_override_reason` работает только с непустой причиной; причина пишется в warning.
+- Недоступная, malformed или зависшая телеметрия пропускает спавн и пишет error. Общий дедлайн
+  чтения `/api/usage` — 12 секунд, меньше 30-секундного MCP request budget.
+- Битый YAML/типизированный manifest остаётся fail-closed по существующему контракту pipeline
+  loader; fail-open относится к runtime model gate и его телеметрии.
+
+## Окно несовместимости MCP ↔ route
+
+- **Новый MCP + старый route.** Обычный спавн не содержит нового поля и идёт прежним путём.
+  При явном исключении новый MCP посылает поле, старый Pydantic request его игнорирует как extra;
+  старый manager ещё не имеет гейта, поэтому спавн проходит, но причина исключения не логируется.
+- **Старый MCP + новый route.** Поля нет, route подставляет `""`; новый manager применяет policy
+  как к спавну без исключения. Sol/Luna/Spark проходят, перекошенный Opus и статически запрещённые
+  модели получают 409. Исключение недоступно до реконнекта агента на новый MCP.
+
+После мержа код manager/route начнёт действовать только после рестарта Orchestra. Манифестные
+списки и пороги после активации кода горячие: pipeline loader перечитывает YAML по
+`(имя, путь, mtime_ns, размер)`.
+
+## Проверки
+
+- Красный оракул до реализации: `10 failed` на отсутствующих policy seam/manifest field.
+- Узкий регресс: `290 passed in 20.20s`.
+- Мутация на зелёном: удалён единственный вызов `_enforce_worker_model_policy` (`marker-before=1`)
+  → `test_skewed_pools_reject_opus_worker_before_publish` красный `DID NOT RAISE`; после отката,
+  `touch` и `marker-after=1` → `1 passed`.
+- Codex review, раунд 1: blocking — у telemetry lookup не было общего timeout.
+- После фикса Codex дословно: `Re-review status: **FIXED**.` / `New findings: None.` /
+  `Verdict: **APPROVED**`. Его независимый прогон timeout-оракула: `1 passed in 5.73s`.
+
+Полный suite не запускался по условию задачи. Попытка полного `tests/test_manager.py` была
+остановлена как непропорционально долгая; этот прогон не используется как evidence.
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 76590114a..b4efe6404 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -1,23 +1,35 @@
 name: default
 description: Upstream-derived v2.18 pipeline with local models and runtime modules.
 validation: fail-open
+# Percentages are displayed as whole points; both counters can move by one displayed
+# point between samples, so the observed gap has a 2 pp joint step. A 3 pp deadband
+# is the smallest band wider than that step: Opus opens at <=3 pp and closes at >=6 pp.
+# At the current 63% Claude / 8% Codex reading the 55 pp gap is unambiguously closed.
+worker_model_policy:
+  always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark]
+  denied: ["claude-fable-5[1m]", gpt-5.6-terra]
+  quota_balanced:
+    model: claude-opus-5[1m]
+    block_gap_pp: 6
+    unblock_gap_pp: 3
+  alternatives: [gpt-5.6-sol, gpt-5.6-luna]
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
 # `effort` у ВСЕХ четырёх ролей задан одной и той же КАРТОЙ модель→ступень (#214): роль одна, а
 # модель выбирается при спавне, и оптимум у моделей разный. Ключом обязана быть МОДЕЛЬ, а не
 # рантайм: Sol и Luna оба `codex` (`backend_for_model`) и требуют разных ступеней.
 # Разрешение (`pipeline.resolve_effort`): точный id модели → рантайм → `default` → нет эффорта.
 # Скаляр остаётся валидным — просто здесь он больше не используется.
 # Оркестраторы подняты с `medium` до `high` по прямому указанию юзера (#214): #208 меряло только
 # рабочие роли, но medium→high — САМЫЙ крупный шаг лестницы Opus (+2.9 пункта), и переносить его
diff --git a/tests/test_api.py b/tests/test_api.py
index 3b3d9284f..e331591d8 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -2703,40 +2703,70 @@ async def test_create_session_passes_pipeline_and_profile(monkeypatch):
     async def fake_create(**kwargs):
         captured.update(kwargs)
 
         class _Sess:
             def to_dict(self):
                 return {"name": kwargs["name"], "id": "sid"}
         return _Sess()
 
     monkeypatch.setattr(mainmod.manager, "create_session", fake_create)
     monkeypatch.setattr(sysmod, "_is_safe_path", lambda p: True)
 
     req = sessmod.CreateSessionRequest(
         name="w1", cwd="/tmp", model="claude-sonnet-5[1m]",
         pipeline="default", profile="work",
     )
     await sessmod.create_session(req)
     assert captured["pipeline"] == "default"
     assert captured["profile"] == "work"
 
 
+@pytest.mark.asyncio
+async def test_create_session_passes_model_policy_override_reason(monkeypatch):
+    import app.main as mainmod
+    import app.routes.sessions as sessmod
+    import app.routes.system as sysmod
+    captured = {}
+
+    async def fake_create(**kwargs):
+        captured.update(kwargs)
+
+        class _Sess:
+            _spawn_warning = ""
+
+            def to_dict(self):
+                return {"name": kwargs["name"], "id": "sid"}
+
+        return _Sess()
+
+    monkeypatch.setattr(mainmod.manager, "create_session", fake_create)
+    monkeypatch.setattr(sysmod, "_is_safe_path", lambda p: True)
+    req = sessmod.CreateSessionRequest(
+        name="w1", cwd="/tmp", model="claude-opus-5[1m]",
+        model_policy_override_reason="pilot #227",
+    )
+
+    await sessmod.create_session(req)
+
+    assert captured["model_policy_override_reason"] == "pilot #227"
+
+
 @pytest.mark.asyncio
 async def test_create_worktree_response_contains_server_repo_metadata(
     monkeypatch, tmp_path,
 ):
     import subprocess
 
     import app.main as mainmod
     import app.routes.sessions as sessmod
     import app.routes.system as sysmod
 
     repo = tmp_path / "repo"
     repo.mkdir()
     subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
     repo_root = str(repo.resolve())
     common_dir = str((repo / ".git").resolve())
 
     async def fake_create(**kwargs):
         repo.rename(tmp_path / "repo-moved-after-start")
 
         class _Sess:
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 5235f7558..69e5dcc0a 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -51,40 +51,52 @@ class TestDefaultManifestLoads:
     def test_kinds_match_upstream(self):
         """orchestrator и sub-orchestrator — kind:orchestrator; worker/full-cycle — kind:worker."""
         cfg = P.load_pipeline(PIPELINE)
         assert cfg.roles["orchestrator"].kind == "orchestrator"
         assert cfg.roles["sub-orchestrator"].kind == "orchestrator"
         assert cfg.roles["worker"].kind == "worker"
         assert cfg.roles["full-cycle"].kind == "worker"
 
     def test_defaults_reproduce_upstream(self):
         """Дефолты пайплайна = поведение апстрима: model opus, без skills/mcp-форса,
         base_branch_strategy main, docs_scaffold off, слои БЕЗ _pipeline.md."""
         cfg = P.load_pipeline(PIPELINE)
         d = cfg.defaults
         assert d.model == "opus"
         assert d.skills == []  # default НЕ форсит skills:all (skills задаёт роль)
         assert d.mcp_servers == []  # апстрим не прокидывает user-MCP
         assert d.base_branch_strategy == "main"  # все worktree от main
         assert d.docs_scaffold is False  # апстрим не скаффолдит doc-папки
         assert d.inherit_claude_md is True  # CLAUDE.md проекта копируется в worktree
 
+    def test_worker_model_policy_is_manifest_owned(self):
+        policy = P.load_pipeline(PIPELINE).worker_model_policy
+        assert policy is not None
+        assert policy.always_allowed == [
+            "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark",
+        ]
+        assert policy.denied == ["claude-fable-5[1m]", "gpt-5.6-terra"]
+        assert policy.quota_balanced.model == "claude-opus-5[1m]"
+        assert policy.quota_balanced.block_gap_pp == 6
+        assert policy.quota_balanced.unblock_gap_pp == 3
+        assert policy.alternatives == ["gpt-5.6-sol", "gpt-5.6-luna"]
+
     def test_prompt_layers_have_no_pipeline_layer(self):
         """У апстрима НЕТ _pipeline.md — только base + роль."""
         cfg = P.load_pipeline(PIPELINE)
         assert cfg.defaults.prompt_layers.orchestrator == ["base.md", "roles/{role}.md"]
         assert cfg.defaults.prompt_layers.worker == ["base.md", "roles/{role}.md"]
         assert "_pipeline.md" not in cfg.defaults.prompt_layers.orchestrator
         assert "_pipeline.md" not in cfg.defaults.prompt_layers.worker
 
     def test_worktree_copies_match_upstream_project_files(self):
         """worktree.copies = его PROJECT_FILES (workspace.py:14), симлинков нет."""
         cfg = P.load_pipeline(PIPELINE)
         assert cfg.defaults.worktree.copies == [
             "CLAUDE.md", ".mcp.json", ".env", ".worktreeinclude"]
         assert cfg.defaults.worktree.symlinks == []
 
     def test_listed_as_valid(self):
         """list_pipelines() видит default и помечает valid=True."""
         entries = {p["name"]: p for p in P.list_pipelines()}
         assert PIPELINE in entries
         assert entries[PIPELINE]["valid"] is True
diff --git a/tests/test_manager.py b/tests/test_manager.py
index 351faf2ad..4a351985a 100644
--- a/tests/test_manager.py
+++ b/tests/test_manager.py
@@ -52,40 +52,41 @@ class TestCreateSession:
         self, mgr, monkeypatch,
     ):
         from app.quota_gate import QuotaGateError, evaluate_worker_admission
 
         async def blocked(_model, observation_loader=None):
             now = datetime.now(timezone.utc).timestamp()
             return evaluate_worker_admission(
                 "claude-sonnet-5[1m]",
                 {"anthropic": {"label": "Claude", "windows": [{
                     "window_minutes": 10080, "utilization": 95,
                 }]}},
                 {"anthropic": now},
                 now=now,
             )
 
         monkeypatch.setattr("app.quota_gate.get_worker_admission", blocked)
         with pytest.raises(QuotaGateError):
             await mgr.create_session(
                 name="blocked-worker", scope="/s", cwd="/tmp",
                 model="claude-sonnet-5[1m]", planned_initial_turn=True,
+                model_policy_override_reason="exercise weekly quota gate in isolation",
             )
 
         assert mgr.sessions == {}
 
     @pytest.mark.asyncio
     async def test_idle_create_is_control_action_and_does_not_read_quota(
         self, mgr, monkeypatch,
     ):
         gate = AsyncMock(side_effect=AssertionError("idle create read quota"))
         monkeypatch.setattr("app.quota_gate.get_worker_admission", gate)
 
         session = await mgr.create_session(
             name="idle-worker", scope="/s", cwd="/tmp",
             model="claude-sonnet-5[1m]", planned_initial_turn=False,
         )
 
         assert session.name == "idle-worker"
         gate.assert_not_awaited()
 
     @pytest.mark.asyncio
diff --git a/tests/test_mcp_stdio.py b/tests/test_mcp_stdio.py
index a91adc5ca..18d788998 100644
--- a/tests/test_mcp_stdio.py
+++ b/tests/test_mcp_stdio.py
@@ -515,40 +515,76 @@ async def test_spawn_base_branch_default_empty(monkeypatch):
     # parent → от ветки родителя, иначе main. Явная ветка переопределяет стратегию.
     import app.mcp_stdio as m
     monkeypatch.setattr(m, "SCOPE", "/s")
     monkeypatch.setattr(m, "WORKER_NAME", "x")
     captured = {}
     async def fake_api(method, path, **kw):
         if path == "/api/sessions":
             captured.update(kw.get("json", {}))
             return {
                 "worktree_path": "/worktrees/w",
                 "branch": "task-1/w",
                 "repo_path": "/s",
                 "git_common_dir": "/s/.git",
             }
         return {"ok": True}
     with patch.object(m, "_api", side_effect=fake_api):
         await m.spawn_worker(name="w", task="t", repo_path="/s", model="claude-sonnet-5[1m]")
     assert captured["base_branch"] == ""
 
 
+@pytest.mark.asyncio
+@pytest.mark.parametrize("reason,expected", [
+    ("", None),
+    ("pilot #227", "pilot #227"),
+])
+async def test_spawn_sends_model_policy_override_only_when_requested(
+    monkeypatch, reason, expected,
+):
+    import app.mcp_stdio as m
+    monkeypatch.setattr(m, "SCOPE", "/s")
+    monkeypatch.setattr(m, "WORKER_NAME", "orchestrator")
+    captured = {}
+
+    async def fake_api(method, path, **kw):
+        if path == "/api/sessions":
+            captured.update(kw["json"])
+            return {
+                "worktree_path": "/worktrees/w",
+                "branch": "task-227/w",
+                "repo_path": "/s",
+                "git_common_dir": "/s/.git",
+            }
+        return {"ok": True}
+
+    with patch.object(m, "_api", side_effect=fake_api):
+        await m.spawn_worker(
+            name="w", task="t", repo_path="/s", model="claude-opus-5[1m]",
+            model_policy_override_reason=reason,
+        )
+
+    if expected is None:
+        assert "model_policy_override_reason" not in captured
+    else:
+        assert captured["model_policy_override_reason"] == expected
+
+
 @pytest.mark.asyncio
 async def test_spawn_marks_parent_as_initial_task_sender(monkeypatch):
     import app.mcp_stdio as m
     monkeypatch.setattr(m, "SCOPE", "/s")
     monkeypatch.setattr(m, "WORKER_NAME", "parent-orchestrator")
     calls = []
 
     async def fake_api(method, path, **kw):
         calls.append((method, path, kw.get("json")))
         if path == "/api/sessions":
             return {
                 "worktree_path": "/worktrees/child",
                 "branch": "task-1/child",
                 "repo_path": "/s",
                 "git_common_dir": "/s/.git",
             }
         return {"ok": True}
 
     with patch.object(m, "_api", side_effect=fake_api):
         await m.spawn_worker(
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index 302b17c49..b563536a4 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -92,40 +92,61 @@ class TestLoadPipeline:
 
     def test_cache_invalidated_when_file_changes(self, pipelines_root):
         """#214: правка манифеста при живом сервере видна БЕЗ рестарта.
 
         Контракт сменился намеренно: раньше кеш держал первый разбор до
         ``cache_clear()``, теперь ключ включает mtime+размер файла. Это цена за то,
         чтобы «всем Opus поставить high» делалось одной правкой yaml, а живые агенты
         подхватывали её на своём следующем ходе (`AgentSession._apply_manifest_effort`).
         """
         d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
         first = P.load_pipeline("demo")
         assert first.roles["hand"].effort is None
 
         (d / "pipeline.yaml").write_text(
             _MINIMAL.format(name="demo").replace(
                 "        can_spawn: []\n", "        can_spawn: []\n        effort: high\n", 1))
         second = P.load_pipeline("demo")
         assert second is not first
         assert second.roles["hand"].effort == "high"
 
+    @pytest.mark.parametrize("block,unblock", [(3, 3), (2, 3), (101, 3)])
+    def test_worker_model_policy_rejects_invalid_hysteresis(
+        self, pipelines_root, block, unblock,
+    ):
+        manifest = _MINIMAL.format(name="demo").replace(
+            "    defaults:\n",
+            "    worker_model_policy:\n"
+            "      always_allowed: [gpt-5.6-sol]\n"
+            "      denied: ['claude-fable-5[1m]']\n"
+            "      quota_balanced:\n"
+            "        model: 'claude-opus-5[1m]'\n"
+            f"        block_gap_pp: {block}\n"
+            f"        unblock_gap_pp: {unblock}\n"
+            "      alternatives: [gpt-5.6-sol]\n"
+            "    defaults:\n",
+        )
+        _write_pipeline(pipelines_root, "demo", manifest)
+
+        with pytest.raises(ValueError, match="unblock_gap_pp < block_gap_pp"):
+            P.load_pipeline("demo")
+
     def test_file_changed_during_read_is_not_cached(self, pipelines_root, monkeypatch):
         """Неатомарная запись извне: содержимое не должно попасть в кеш и наружу.
 
         Опасен не битый YAML (его отвергнет схема), а НЕДОПИСАННЫЙ, но синтаксически
         валидный: роль получила бы неполную карту эффорта, и та уехала бы живым агентам.
         """
         d = _write_pipeline(pipelines_root, "demo", _MINIMAL.format(name="demo"))
         target = d / "pipeline.yaml"
         full = _MINIMAL.format(name="demo").replace(
             "        can_spawn: []\n", "        can_spawn: []\n        effort: high\n", 1)
         real_read = P.Path.read_text
         torn = {"n": 0}
 
         def read_then_grow(self, *a, **kw):
             text = real_read(self, *a, **kw)
             if self == target and torn["n"] == 0:
                 torn["n"] += 1
                 target.write_text(full)  # «дописали» файл ровно между read и stat
             return text
 
diff --git a/tests/test_worker_model_policy.py b/tests/test_worker_model_policy.py
new file mode 100644
index 000000000..07a705c9f
--- /dev/null
+++ b/tests/test_worker_model_policy.py
@@ -0,0 +1,179 @@
+import logging
+from unittest.mock import AsyncMock, patch
+
+import pytest
+
+
+@pytest.fixture
+def mgr(tmp_path, monkeypatch):
+    db_path = tmp_path / "test.db"
+    monkeypatch.setattr("app.db.DB_PATH", db_path)
+    from app.db import init_db
+    init_db()
+    worktree_root = tmp_path / "worktrees"
+    worktree_root.mkdir()
+    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", worktree_root)
+    from app.manager import SessionManager
+    return SessionManager()
+
+
+def _usage(claude: float, codex: float) -> dict:
+    return {
+        "anthropic": {"seven_day": {"utilization": claude}},
+        "codex": {"primary": {"utilization": codex}},
+    }
+
+
+async def _spawn(mgr, name: str, model: str, **kwargs):
+    from tests.conftest import make_backend_mock
+
+    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
+        return await mgr.create_session(
+            name=name,
+            scope="/model-policy",
+            cwd="/tmp",
+            model=model,
+            role=kwargs.pop("role", "worker"),
+            planned_initial_turn=True,
+            **kwargs,
+        )
+
+
+@pytest.mark.asyncio
+async def test_skewed_pools_reject_opus_worker_before_publish(mgr, monkeypatch):
+    monkeypatch.setattr(
+        "app.manager._worker_model_policy_usage",
+        AsyncMock(return_value=_usage(63, 8)),
+    )
+
+    with pytest.raises(ValueError, match=r"Claude 7d 63%.*Codex 8%.*gpt-5\.6-sol.*gpt-5\.6-luna"):
+        await _spawn(mgr, "blocked-opus", "claude-opus-5[1m]")
+
+    assert mgr.sessions == {}
+
+
+@pytest.mark.asyncio
+async def test_opus_override_requires_reason_and_logs_it(mgr, monkeypatch, caplog):
+    monkeypatch.setattr(
+        "app.manager._worker_model_policy_usage",
+        AsyncMock(return_value=_usage(63, 8)),
+    )
+
+    with caplog.at_level(logging.WARNING, logger="app.manager"):
+        worker = await _spawn(
+            mgr,
+            "override-opus",
+            "claude-opus-5[1m]",
+            model_policy_override_reason="pilot #227 comparison",
+        )
+
+    assert worker.model == "claude-opus-5[1m]"
+    assert "pilot #227 comparison" in caplog.text
+
+
+@pytest.mark.asyncio
+async def test_orchestrators_are_exempt_from_worker_model_policy(mgr, monkeypatch):
+    usage = AsyncMock(side_effect=AssertionError("orchestrator read worker policy telemetry"))
+    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)
+
+    orchestrator = await _spawn(
+        mgr,
+        "opus-orchestrator",
+        "claude-opus-5[1m]",
+        role="orchestrator",
+        is_orchestrator=True,
+    )
+
+    assert orchestrator.is_orchestrator
+    usage.assert_not_awaited()
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-luna"])
+async def test_allowed_codex_worker_models_do_not_read_balance(mgr, monkeypatch, model):
+    usage = AsyncMock(side_effect=AssertionError("allowed model read balance telemetry"))
+    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)
+
+    worker = await _spawn(mgr, model.rsplit("-", 1)[-1], model)
+
+    assert worker.model == model
+    usage.assert_not_awaited()
+
+
+@pytest.mark.asyncio
+async def test_balanced_pools_allow_opus_worker(mgr, monkeypatch):
+    monkeypatch.setattr(
+        "app.manager._worker_model_policy_usage",
+        AsyncMock(return_value=_usage(14, 12)),
+    )
+
+    worker = await _spawn(mgr, "balanced-opus", "claude-opus-5[1m]")
+
+    assert worker.model == "claude-opus-5[1m]"
+
+
+@pytest.mark.asyncio
+async def test_opus_balance_gate_has_hysteresis(mgr, monkeypatch):
+    usage = AsyncMock(side_effect=[
+        _usage(20, 13),  # gap 7: latch blocked
+        _usage(20, 16),  # gap 4: remain blocked
+        _usage(20, 17),  # gap 3: unlock
+        _usage(20, 16),  # gap 4: remain open
+        _usage(20, 14),  # gap 6: block again
+    ])
+    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)
+
+    with pytest.raises(ValueError):
+        await _spawn(mgr, "gap-7", "claude-opus-5[1m]")
+    with pytest.raises(ValueError):
+        await _spawn(mgr, "gap-4-blocked", "claude-opus-5[1m]")
+    assert (await _spawn(mgr, "gap-3", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
+    assert (await _spawn(mgr, "gap-4-open", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
+    with pytest.raises(ValueError):
+        await _spawn(mgr, "gap-6", "claude-opus-5[1m]")
+
+
+@pytest.mark.asyncio
+async def test_fable_is_denied_by_manifest_policy(mgr, monkeypatch):
+    usage = AsyncMock(side_effect=AssertionError("static deny read balance telemetry"))
+    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)
+
+    with pytest.raises(ValueError, match=r"claude-fable-5\[1m\].*not allowed.*gpt-5\.6-sol"):
+        await _spawn(mgr, "fable", "claude-fable-5[1m]")
+
+    usage.assert_not_awaited()
+
+
+@pytest.mark.asyncio
+async def test_balance_telemetry_failure_is_fail_open_and_loud(mgr, monkeypatch, caplog):
+    monkeypatch.setattr(
+        "app.manager._worker_model_policy_usage",
+        AsyncMock(side_effect=RuntimeError("usage unavailable")),
+    )
+
+    with caplog.at_level(logging.ERROR, logger="app.manager"):
+        worker = await _spawn(mgr, "fail-open-opus", "claude-opus-5[1m]")
+
+    assert worker.model == "claude-opus-5[1m]"
+    assert "usage unavailable" in caplog.text
+
+
+@pytest.mark.asyncio
+async def test_balance_telemetry_timeout_is_fail_open_and_loud(mgr, monkeypatch, caplog):
+    import asyncio
+
+    entered = asyncio.Event()
+
+    async def stuck_usage():
+        entered.set()
+        await asyncio.Event().wait()
+
+    monkeypatch.setattr("app.manager._worker_model_policy_usage", stuck_usage)
+    monkeypatch.setattr("app.manager.WORKER_MODEL_POLICY_TIMEOUT_SECONDS", 0.01)
+
+    with caplog.at_level(logging.ERROR, logger="app.manager"):
+        worker = await _spawn(mgr, "timeout-opus", "claude-opus-5[1m]")
+
+    assert entered.is_set(), "timeout probe never entered the telemetry loader"
+    assert worker.model == "claude-opus-5[1m]"
+    assert "TimeoutError" in caplog.text


## Later history of the touched files on main (after this commit)

251 later commits touch these paths; the first 40 (oldest first):
6163944bb 2026-08-13 #227: временно отключить worker_model_policy в манифесте — живой процесс со старой схемой роняет загрузку целиком; вернуть при рестарте
59ee1b11c 2026-08-13 #227: #227: gate Opus by Claude weekly pace
85b6174ee 2026-08-13 #246: #246: validate task creation project scopes
d485e1c52 2026-08-13 #258: #258: research safe orphan process identity
83eda0e05 2026-08-13 #241: #241: tag the owner only when the turn calls notify_user
017ca19c0 2026-08-13 #237: #237: research seamless active-turn restart
e9c34833e 2026-08-14 #265: #265: canary handshake so a same-name Grok MCP server cannot impersonate ours
96192b400 2026-08-14 #36: #36: unknown roles fail closed in validate_spawn
01f4794e2 2026-08-14 #200: #200: one CLI path encoder in app.manager.enc_cli_dir
8b8d73c37 2026-08-14 #275: #275: persist child fan reports to a path the parent can see
b703d5857 2026-08-14 #192: #192: load idle unloaded sessions in change_model via ensure_loaded
083c83426 2026-08-14 feat: кнопка очистки сессии агента (обнуляет session_id, worktree не трогает)
cbc3eca2b 2026-08-14 Merge remote-tracking branch 'origin/main'
3ed249ecf 2026-08-14 #276: #276: fan terminal only on explicit kind or turn end
4b3ebde4d 2026-08-14 #240: #240: platform runs the ticket acceptance command before squash
0220d2a2d 2026-08-14 #278: #278: skip unfinished Antigravity RED tests; drop dead can_spawn leftover
4b0611cfb 2026-08-14 #240: #240: drop worker-set acceptance_command in task_create
e439707ce 2026-08-14 #250: #250: refuse unreviewable diffs at merge
077a795c7 2026-08-14 #281: #281: bind orchestrator HTTP privilege to a per-MCP proof
5a11c5a14 2026-08-14 #280: #280: drop vacuum fail-open spawn test; deny unknown parent role
00fbfec58 2026-08-16 fix: make session clearing forget imported context
43eb156aa 2026-08-16 Merge origin/main into VPS main
e114aadcf 2026-08-16 #293: #293: freeze VPN project registration oracle
0015743d7 2026-08-16 #296: #296: implement risk-based review routing
b0b72d655 2026-08-16 #294: #294: plan secure artifact links
bd4f6e61a 2026-08-16 #304: #304: select codex review model explicitly
c3c9e2071 2026-08-17 #313: #313: route merge helper for request fixture in tests
1e020d60e 2026-08-17 #311: #311: freeze durable delivery RED oracles
9a1e2d108 2026-08-17 #314: #314: freeze enforcement and analytics RED oracles
b604ef449 2026-08-17 #305: #305: serialize managed Codex cold starts
3c037bdb8 2026-08-18 #290: cross-runtime handoff + канареечный скип по продовому предикату (scratch/290, вердикт #328)
1fe3cf1d7 2026-08-18 #329: один владелец логики пулов — квотная арифметика вырезана из манифеста, блок выключен до рестарта
8c5ea3647 2026-08-18 #329: включён worker_model_policy — рестарт 18.08 17:31 UTC загрузил новую схему
b643c67e3 2026-08-19 #230: горячее применение правок и живучесть ходов при рестарте
98ae5885b 2026-08-19 ревью не обязательно и без замены ревьюера; code-quality вынесен в модуль; оба контракта закрыты тестами
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
af58227ee 2026-08-19 #346: #346: правило формата ответа юзеру — блок <user-answer-format> в роли оркестратора
eac83b8aa 2026-08-19 #348: #348: шесть правил про поведение агентов перенесены из CLAUDE.md к владельцам в pipelines/
0d8208a77 2026-08-21 опрос дашборда: фазовый сдвиг и 304 на /api/sessions
1ecd00717 2026-08-21 bg_list показывает расписание, время срабатывания и команду

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 6163944bb #227: временно отключить worker_model_policy в манифесте — живой процесс со старой схемой роняет загрузку целиком; вернуть при рестарте

diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index b4efe6404..0d4106fbb 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -3,18 +3,20 @@ description: Upstream-derived v2.18 pipeline with local models and runtime modul
 validation: fail-open
 # Percentages are displayed as whole points; both counters can move by one displayed
 # point between samples, so the observed gap has a 2 pp joint step. A 3 pp deadband
 # is the smallest band wider than that step: Opus opens at <=3 pp and closes at >=6 pp.
 # At the current 63% Claude / 8% Codex reading the 55 pp gap is unambiguously closed.
-worker_model_policy:
-  always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark]
-  denied: ["claude-fable-5[1m]", gpt-5.6-terra]
-  quota_balanced:
-    model: claude-opus-5[1m]
-    block_gap_pp: 6
-    unblock_gap_pp: 3
-  alternatives: [gpt-5.6-sol, gpt-5.6-luna]
+# ВРЕМЕННО ОТКЛЮЧЕНО до рестарта (#227): живой процесс поднят со схемой БЕЗ
+# worker_model_policy:
+# worker_model_policy, и Pydantic extra='forbid' роняет ЗАГРУЗКУ ВСЕГО манифеста.
+#   always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark]
+#   denied: ["claude-fable-5[1m]", gpt-5.6-terra]
+#   quota_balanced:
+#     model: claude-opus-5[1m]
+#     block_gap_pp: 6
+#     unblock_gap_pp: 3
+#   alternatives: [gpt-5.6-sol, gpt-5.6-luna]
 defaults:
   model: opus
   skills: []
   mcp_servers: []
   inherit_claude_md: true
### 59ee1b11c #227: #227: gate Opus by Claude weekly pace

diff --git a/app/manager.py b/app/manager.py
index cfc525829..52836d73e 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -68,20 +68,42 @@ _adhoc_serial = itertools.count(1)
 # чтобы вызывающий получил внятный отказ, а не ReadTimeout, неотличимый от мёртвого сервера.
 LOCK_WAIT_LIMIT_SECONDS = 25.0
 # Keep policy telemetry inside the 30s MCP request budget. Slow/missing telemetry is
 # advisory failure: the model gate logs it and admits the worker.
 WORKER_MODEL_POLICY_TIMEOUT_SECONDS = 12.0
+WEEKLY_WINDOW_SECONDS = 7 * 24 * 60 * 60
 
 
 async def _worker_model_policy_usage() -> dict:
-    """Read the same live payload served by GET /api/usage."""
-    from app.routes.system import get_usage
-
-    usage = await get_usage()
-    if not isinstance(usage, dict):
-        raise RuntimeError("GET /api/usage returned no worker quota telemetry")
-    return usage
+    """Read only the live Anthropic payload behind GET /api/usage."""
+    from app.quota_gate import QUOTA_OBSERVATION_MAX_AGE
+    from app.routes.system import current_quota_observation
+
+    observation = await current_quota_observation(required_provider="anthropic")
+    providers = observation.get("providers") if isinstance(observation, dict) else None
+    timestamps = (
+        observation.get("observed_at_by_provider")
+        if isinstance(observation, dict)
+        else None
+    )
+    observed_at = timestamps.get("anthropic") if isinstance(timestamps, dict) else None
+    age = time.time() - observed_at if isinstance(observed_at, (int, float)) else math.inf
+    if isinstance(observed_at, bool) or not 0 <= age < QUOTA_OBSERVATION_MAX_AGE:
+        raise RuntimeError("fresh Anthropic worker quota telemetry is unavailable")
+
+    anthropic = providers.get("anthropic") if isinstance(providers, dict) else None
+    windows = anthropic.get("windows") if isinstance(anthropic, dict) else None
+    seven_day = next(
+        (
+            window for window in windows
+            if isinstance(window, dict) and window.get("id") == "seven_day"
+        ),
+        None,
+    ) if isinstance(windows, list) else None
+    if seven_day is None:
+        raise RuntimeError("Anthropic seven-day worker quota telemetry is unavailable")
+    return {"anthropic": {"seven_day": seven_day}}
 
 
 def _policy_utilization(usage: dict, provider: str, window: str) -> float:
     data = usage.get(provider)
     value = data.get(window, {}).get("utilization") if isinstance(data, dict) else None
@@ -93,10 +115,30 @@ def _policy_utilization(usage: dict, provider: str, window: str) -> float:
     ):
         raise ValueError(f"{provider}.{window}.utilization is missing or malformed")
     return float(value)
 
 
+def _policy_window_elapsed(usage: dict) -> tuple[float | None, str]:
+    anthropic = usage.get("anthropic")
+    seven_day = anthropic.get("seven_day") if isinstance(anthropic, dict) else None
+    raw = seven_day.get("resets_at") if isinstance(seven_day, dict) else None
+    if not isinstance(raw, str) or not raw.strip():
+        return None, "anthropic.seven_day.resets_at is missing"
+    try:
+        reset_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
+    except ValueError:
+        return None, "anthropic.seven_day.resets_at is malformed"
+    if reset_at.tzinfo is None:
+        return None, "anthropic.seven_day.resets_at has no timezone"
+    remaining = (reset_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
+    if remaining <= 0:
+        return None, "anthropic.seven_day.resets_at is in the past"
+    if remaining > WEEKLY_WINDOW_SECONDS:
+        return None, "anthropic.seven_day.resets_at is beyond the weekly window"
+    return 100.0 * (1.0 - remaining / WEEKLY_WINDOW_SECONDS), ""
+
+
 class LockBusy(RuntimeError):
     """Лок сессии занят дольше отведённого: у вызова есть кто уступить и кому повторить."""
 
     def __init__(self, what: str, worker: str, waited: float):
         self.what, self.worker, self.waited = what, worker, waited
@@ -460,11 +502,13 @@ def _crosses_repo_boundary(parent_dir: str, child_repo: str) -> bool:
 class SessionManager:
     def __init__(self):
         self.sessions: dict[str, AgentSession] = {}
         self._session_locks: dict[str, asyncio.Lock] = {}
         self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
-        self._worker_model_policy_latches: dict[tuple[str, str, float, float], bool] = {}
+        self._worker_model_policy_latches: dict[
+            tuple[str, str, float, float, float, float], tuple[bool, bool]
+        ] = {}
         # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
         # #220 T2: рестарт закрывает приём новых ходов, пока дренажит уже идущие
         self.draining = False
 
@@ -538,45 +582,70 @@ class SessionManager:
             return
         if model in policy.always_allowed:
             return
 
         alternatives = ", ".join(policy.alternatives)
-        balanced = policy.quota_balanced
-        if model != balanced.model:
+        guarded = policy.quota_guarded
+        if model != guarded.model:
             raise ValueError(
                 f"worker model '{model}' is not allowed by pipeline '{pipeline}'. "
                 f"Use {alternatives}, or pass model_policy_override_reason with a non-empty reason."
             )
 
         try:
             async with asyncio.timeout(WORKER_MODEL_POLICY_TIMEOUT_SECONDS):
                 usage = await _worker_model_policy_usage()
             claude = _policy_utilization(usage, "anthropic", "seven_day")
-            codex = _policy_utilization(usage, "codex", "primary")
         except Exception as error:
             logger.error(
                 "worker model policy telemetry unavailable; allowing model=%s: %s: %s",
                 model, type(error).__name__, err_text(error),
             )
             return
 
-        gap = claude - codex
-        key = (pipeline, model, balanced.block_gap_pp, balanced.unblock_gap_pp)
-        blocked = self._worker_model_policy_latches.get(
-            key, gap > balanced.unblock_gap_pp,
+        key = (
+            pipeline, model,
+            guarded.pace_block_lead_pp, guarded.pace_unblock_lead_pp,
+            guarded.absolute_block_pct, guarded.absolute_unblock_pct,
         )
-        if gap >= balanced.block_gap_pp:
-            blocked = True
-        elif gap <= balanced.unblock_gap_pp:
-            blocked = False
-        self._worker_model_policy_latches[key] = blocked
-        if blocked:
+        pace_blocked, absolute_blocked = self._worker_model_policy_latches.get(
+            key, (False, False),
+        )
+
+        if claude >= guarded.absolute_block_pct:
+            absolute_blocked = True
### 85b6174ee #246: #246: validate task creation project scopes

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 39f724941..3e045d52c 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1749,21 +1749,25 @@ async def get_worker_info(name: str) -> str:
         result["cache_status"] = _cache_pill(result)  # 🔥 hot Nm / 🟡 warm / 🧊 cold
     return json.dumps(result, ensure_ascii=False)
 
 
 @mcp.tool()
-async def task_create(title: str, project: str, price: int = 0,
+async def task_create(title: str, project: str = "", price: int = 0,
                       description: str = "", assignee: str = "",
                       status: str = "new", priority: int = 2) -> str:
     """Create a new task. Returns task number and details.
+    project: registered project scope or id; omitted uses the caller's mapped scope.
     price in exact currency units (e.g. 20000 = 20 000). 0 is valid (no price).
     priority: 0=critical, 1=high, 2=medium (default), 3=low."""
-    result = await _api("POST", "/api/tm/tasks", json={
-        "title": title, "project": project, "price": price,
+    payload = {
+        "title": title, "price": price,
         "description": description, "assignee": assignee, "status": status,
         "scope": SCOPE, "priority": priority,
-    })
+    }
+    if project:
+        payload["project"] = project
+    result = await _api("POST", "/api/tm/tasks", json=payload)
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     if isinstance(result, dict):
         result = dict(result)
         result.setdefault("description", description)
diff --git a/tests/test_api.py b/tests/test_api.py
index e331591d8..af6e1bfd5 100644
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -124,10 +124,112 @@ class TestDashboard:
         assert r.status_code == 200
         assert "text/html" in r.headers["content-type"]
 
 
 class TestTaskProjectIdentity:
+    def test_create_rejects_unregistered_project_without_creating_it(self, client):
+        from app import tm
+
+        _seed_case_variant_tasks()
+        with tm._conn() as conn:
+            now = tm._now()
+            conn.execute(
+                "INSERT INTO tm_projects (id, name, prefix, scope, created_at) "
+                "VALUES (?, ?, ?, ?, ?)",
+                ("orchestra", "orchestra", "ORC", None, now),
+            )
+            tm.create_task(
+                conn, "orchestra", "legacy ghost", status="cancelled", par_number=5,
+            )
+
+        response = client.post(
+            "/api/tm/tasks",
+            json={"title": "ghost", "project": "orchestra", "scope": "/lower"},
+        )
+
+        assert response.status_code == 400
+        assert response.json() == {
+            "error": (
+                "project 'orchestra' is not registered; allowed project scopes: "
+                "/lower, /upper"
+            ),
+        }
+        with tm._conn() as conn:
+            assert tm.resolve_project_id(conn, "orchestra")["scope"] is None
+            assert conn.execute(
+                "SELECT COUNT(*) FROM tm_tasks WHERE title = 'ghost'"
+            ).fetchone()[0] == 0
+
+        legacy_read = client.get("/api/tm/tasks/5", params={"project": "orchestra"})
+        legacy_update = client.put(
+            "/api/tm/tasks/5",
+            params={"project": "orchestra"},
+            json={"title": "legacy retained"},
+        )
+        assert legacy_read.status_code == 200
+        assert legacy_update.status_code == 200
+
+    def test_create_defaults_to_callers_mapped_scope(self, client):
+        _seed_case_variant_tasks()
+
+        response = client.post(
+            "/api/tm/tasks",
+            json={"title": "mapped", "scope": "/lower"},
+        )
+
+        assert response.status_code == 200
+        assert response.json()["project"] == "seedon"
+
+    def test_create_accepts_registered_scope_as_explicit_project(self, client):
+        _seed_case_variant_tasks()
+
+        response = client.post(
+            "/api/tm/tasks",
+            json={"title": "cross-project", "project": "/upper", "scope": "/lower"},
+        )
+
+        assert response.status_code == 200
+        assert response.json()["project"] == "Seedon"
+
+    def test_project_id_scope_collision_fails_closed_for_create_get_and_update(self, client):
+        from app import tm
+
+        with tm._conn() as conn:
+            now = tm._now()
+            conn.execute(
+                "INSERT INTO tm_projects (id, name, prefix, scope, created_at) "
+                "VALUES (?, ?, ?, ?, ?)",
+                ("selector", "By id", "BID", "/by-id", now),
+            )
+            conn.execute(
+                "INSERT INTO tm_projects (id, name, prefix, scope, created_at) "
+                "VALUES (?, ?, ?, ?, ?)",
+                ("by-scope", "By scope", "BSC", "selector", now),
+            )
+            by_id = tm.create_task(conn, "selector", "id task", par_number=1)
+            tm.create_task(conn, "by-scope", "scope task", par_number=1)
+
+        create = client.post(
+            "/api/tm/tasks",
+            json={"title": "must not exist", "project": "selector"},
+        )
+        read = client.get("/api/tm/tasks/1", params={"project": "selector"})
+        write = client.put(
+            "/api/tm/tasks/1",
+            params={"project": "selector"},
+            json={"title": "must not change"},
+        )
+
+        for response in (create, read, write):
+            assert response.status_code == 400
+            assert "project id 'selector' conflicts with scope of project 'by-scope'" in (
+                response.json()["error"]
+            )
+        with tm._conn() as conn:
+            assert conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0] == 2
+            assert tm.get_task_by_id(conn, by_id["id"])["title"] == "id task"
+
     def test_explicit_project_wins_over_scope_for_read(self, client):
         _seed_case_variant_tasks()
### d485e1c52 #258: #258: research safe orphan process identity

diff --git a/app/manager.py b/app/manager.py
index 52836d73e..3f3cd1871 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -11,10 +11,11 @@ import sqlite3
 import subprocess
 import sys
 import time
 import uuid
 from contextlib import asynccontextmanager
+from dataclasses import dataclass
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Awaitable, Callable, Optional
 
 from app.session import AgentSession, AgentStatus
@@ -62,10 +63,16 @@ from app.tasks import spawn_supervised
 
 logger = logging.getLogger(__name__)
 
 _adhoc_serial = itertools.count(1)
 
+
+@dataclass(frozen=True, slots=True)
+class OrphanProcessIdentity:
+    pid: int
+    started_at: int
+
 # Клиент MCP отваливается по таймауту через 30 с (mcp_stdio.py). Ждём заведомо меньше,
 # чтобы вызывающий получил внятный отказ, а не ReadTimeout, неотличимый от мёртвого сервера.
 LOCK_WAIT_LIMIT_SECONDS = 25.0
 # Keep policy telemetry inside the 30s MCP request budget. Slow/missing telemetry is
 # advisory failure: the model gate logs it and admits the worker.
@@ -2019,13 +2026,13 @@ class SessionManager:
         swept = 0
         for session_id, fd in inherited:
             if session_id in self.sessions:
                 continue
             close_orphan_fd(fd)
-            pid = pids.get(fd)
-            if pid:
-                terminate_orphan_process(pid)
+            identity = pids.get(fd)
+            if identity:
+                terminate_orphan_process(identity)
             logger.warning(
                 "orphan sweep: closed fd %s of unknown session %s", fd, session_id)
             swept += 1
         return swept
 
@@ -2296,37 +2303,38 @@ def close_orphan_fd(fd: int) -> None:
         os.close(fd)
     except OSError as error:
         logger.warning("could not close orphan fd %s: %s", fd, err_text(error))
 
 
-def orphan_pids() -> dict[int, int]:
-    """Map inherited descriptor -> CLI pid, for descriptors whose session is gone (#230 T7).
+def orphan_pids() -> dict[int, OrphanProcessIdentity]:
+    """Map inherited descriptor -> stored CLI identity, for descriptors whose session is gone.
 
-    The pid was written at handover (`sessions.cli_pid`). A row that no longer exists leaves
-    the pid unknown, and then closing the descriptor is all we can honestly do.
+    Both fields come from the same handover row. A row that no longer exists leaves the identity
+    unknown, and then closing the descriptor is all we can honestly do.
     """
     from app.db import _conn
 
-    mapping: dict[int, int] = {}
+    mapping: dict[int, OrphanProcessIdentity] = {}
     with _conn() as c:
         rows = c.execute(
-            "SELECT id, cli_pid FROM sessions WHERE cli_pid IS NOT NULL AND cli_pid != 0"
+            "SELECT id, cli_pid, cli_started_at FROM sessions "
+            "WHERE cli_pid IS NOT NULL AND cli_pid != 0"
         ).fetchall()
-    by_session = {row["id"]: int(row["cli_pid"]) for row in rows}
+    by_session = {
+        row["id"]: OrphanProcessIdentity(
+            pid=int(row["cli_pid"]),
+            started_at=int(row["cli_started_at"] or 0),
+        )
+        for row in rows
+    }
     for session_id, fd in _inherited_named_fds():
-        pid = by_session.get(session_id)
-        if pid:
-            mapping[fd] = pid
+        identity = by_session.get(session_id)
+        if identity:
+            mapping[fd] = identity
     return mapping
 
 
-def terminate_orphan_process(pid: int) -> None:
-    """Reap an agent process nobody owns any more (#230 T7)."""
-    import signal
+def terminate_orphan_process(identity: OrphanProcessIdentity) -> None:
+    """Reap a verified agent process nobody owns any more (#258)."""
+    from app import backend_jsonrpc
 
-    try:
-        os.kill(pid, signal.SIGTERM)
-        logger.warning("orphan sweep: sent SIGTERM to unowned agent pid %s", pid)
-    except ProcessLookupError:
-        pass
-    except OSError as error:
-        logger.warning("could not terminate orphan pid %s: %s", pid, err_text(error))
+    backend_jsonrpc.terminate_cli_process(identity.pid, None, identity.started_at)
### 83eda0e05 #241: #241: tag the owner only when the turn calls notify_user

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 3e045d52c..f9c71f0a9 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1245,10 +1245,33 @@ async def send_chart(kind: str, title: str, data: dict, caption: str = "") -> st
         exc.details = {**exc.details, "chart_path": path}
         raise
     return f"{sent} | chart: {path}"
 
 
+@mcp.tool()
+async def notify_user(reason: str) -> str:
+    """Дёрнуть юзера тегом в Telegram на границе ЭТОГО хода. Только для оркестраторов.
+
+    Молчание — нормальный режим: без этого вызова тега не будет, и это не забывчивость.
+    Зови, когда юзер обязан узнать СЕЙЧАС: нужно его РЕШЕНИЕ (развилка, которую ты не
+    вправе закрыть сам); ВЫВОД РАЗВЕРНУЛСЯ (сделали не то, о чём договаривались, или
+    отозвано ранее сказанное); ИНЦИДЕНТ на живых системах; РЕЗУЛЬТАТ с числом, меняющий
+    план. НЕ зови на блокеры ревью, мержи, статусы, промежуточные шаги, «воркер
+    начал/закончил» — на это он смотреть не хочет.
+
+    `reason` — одна короткая фраза, ЗАЧЕМ дёрнули; она уедет юзеру вместе с тегом.
+    Тег ставится один раз за ход независимо от числа вызовов.
+    """
+    reason = reason.strip()
+    if not reason:
+        return "notify_user needs a non-empty reason — one short phrase saying WHY."
+    # Тул сознательно ничего не делает: сигналом служит САМА строка вызова в журнале,
+    # которую пишет рантайм, а читает `stream_logs`. Никакого нового контракта
+    # MCP↔route — значит правка доезжает без окна «новый MCP против старого роута».
+    return f"User will be tagged at the end of this turn: {reason}"
+
+
 @mcp.tool()
 async def update_progress(percent: int, status: str) -> str:
     """Update task progress. percent: 0-100, status: short description of current step."""
     result = await _api("POST", f"/api/sessions/{WORKER_NAME}/progress", json={
         "percent": percent, "status": status, "scope": SCOPE,
### 017ca19c0 #237: #237: research seamless active-turn restart

diff --git a/app/manager.py b/app/manager.py
index 3f3cd1871..c7d378592 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -516,10 +516,19 @@ class SessionManager:
         ] = {}
         # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
         # #220 T2: рестарт закрывает приём новых ходов, пока дренажит уже идущие
         self.draining = False
+        # #237 T3: sessions this restart attempt already handed to systemd. Objects, not ids:
+        # a rollback has to reach their backends, and an abandoned restart may leave them out
+        # of `self.sessions`.
+        self._prepared_restart: list = []
+
+    @property
+    def _prepared_restart_sessions(self) -> set[str]:
+        """Ids of the sessions currently prepared for handover (#237 T3)."""
+        return {session.id for session in self._prepared_restart}
 
     def begin_drain(self) -> None:
         """Закрыть приём новых ходов. СИНХРОННО — в этом весь смысл.
 
         Ни одного `await` здесь быть не должно: флаг обязан встать раньше, чем цикл
@@ -1989,14 +1998,15 @@ class SessionManager:
         """
         from app import fdstore
 
         ends: dict[str, dict[str, int]] = {}
         for name, fd in fdstore.acquire_fds().items():
-            parts = name.split(":")
-            if len(parts) != 3 or parts[0] != "agent" or parts[2] not in ("stdin", "stdout"):
+            parsed = parse_fd_store_name(name)
+            if parsed is None:
                 continue
-            ends.setdefault(parts[1], {})[parts[2]] = fd
+            session_id, side = parsed
+            ends.setdefault(session_id, {})[side] = fd
         return {
             session_id: (sides["stdin"], sides["stdout"])
             for session_id, sides in ends.items()
             if "stdin" in sides and "stdout" in sides
         }
@@ -2051,13 +2061,23 @@ class SessionManager:
                 "SELECT id FROM sessions WHERE status IN ('running', 'interrupted')"
             ).fetchall()}
             was_waiting = {r["id"] for r in c.execute(
                 "SELECT id FROM sessions WHERE status = 'waiting'"
             ).fetchall()}
+            # A COMPLETE inherited pair is stronger evidence of a live turn than `session_id`:
+            # the CLI is provably still running and streaming. Requiring session_id here left
+            # such a survivor unloaded, and an unloaded session's descriptors then look like an
+            # orphan to the sweep — we would reap the very agent we just rescued (#237 T2).
+            adoption_filter = ""
+            adoption_params: tuple = ()
+            if adoptable:
+                adoption_filter = f" OR id IN ({','.join('?' * len(adoptable))})"
+                adoption_params = tuple(adoptable)
             resumable = [dict(r) for r in c.execute(
-                "SELECT * FROM sessions WHERE session_id IS NOT NULL "
-                "AND status IN ('running', 'interrupted', 'idle', 'waiting')"
+                f"SELECT * FROM sessions WHERE (session_id IS NOT NULL{adoption_filter}) "
+                "AND status IN ('running', 'interrupted', 'idle', 'waiting')",
+                adoption_params,
             ).fetchall()]
             # Reset to idle before loading: prevents any session from resuming
             # as 'running' (the backend process died on server restart).
             # #230: EXCEPT the sessions whose pipes systemd just handed back — their CLI is
             # alive and their turn is still running, so forgetting it here is exactly the
@@ -2204,12 +2224,12 @@ class SessionManager:
                              session.name, err_text(error))
                 return False
 
         stored: list[str] = []
         try:
-            for name, fd in ((f"agent:{session.id}:stdin", fd_in),
-                             (f"agent:{session.id}:stdout", fd_out)):
+            for name, fd in ((fd_store_name(session.id, "stdin"), fd_in),
+                             (fd_store_name(session.id, "stdout"), fd_out)):
                 fdstore.store_fds(name, [fd])
                 stored.append(name)
             save_handover_state(
                 session.id,
                 getattr(backend, "active_turn_id", "") or "",
@@ -2224,22 +2244,88 @@ class SessionManager:
                 try:
                     fdstore.remove_fds(name)
                 except Exception as rollback_error:
                     logger.error("[%s] could not roll back %s: %s",
                                  session.name, name, err_text(rollback_error))
-            abort = getattr(backend, "abort_handover", None)
-            if abort is not None:
-                # the backend keeps living and will be stopped the old way: leaving it in the
-                # quiescing state would silence its real death
-                abort()
+            # Quiesce already succeeded, so this backend is paused and readerless RIGHT NOW.
+            # Undoing that is mandatory and belongs here, not to the caller: an agent left
+            # quiesced is alive, looks healthy, and is permanently deaf. The earlier code only
+            # cleared the quiescing flag — and the fleet rollback then skipped this very
+            # session BECAUSE the flag was already clear.
+            await self._resume_after_failed_handover(session, backend)
             logger.error(
                 "[%s] handover failed (rolled back %d descriptor(s)), stopping the agent: %s",
                 session.name, len(stored), err_text(error),
             )
             return False
         return True
 
+    @staticmethod
+    async def _resume_after_failed_handover(session, backend) -> None:
+        """Give a quiesced backend its reader back. Never raises."""
+        resume = getattr(backend, "resume_after_aborted_handover", None)
+        if resume is None:
+            return
+        try:
+            await resume()
+        except Exception as error:
+            logger.error("[%s] could not resume after a failed handover: %s",
+                         session.name, err_text(error))
+
+    async def prepare_restart_handover(self, sessions: list) -> dict:
+        """Hand this whole live fleet to systemd, all or none, before any signal (#237 T3).
+
+        Partial success is the state that must not exist: some CLIs keep running while the
+        restart is abandoned, and nobody owns them afterwards. So the first refusal rolls back
+        everything this call already stored.
+        """
+        prepared: list = []
+        for session in sessions:
+            handed = False
+            try:
+                handed = await self._hand_over_backend(session)
+            except Exception as error:
+                logger.error("[%s] handover raised: %s", session.name, err_text(error))
+            if not handed:
+                # The refusing session has already restored itself inside `_hand_over_backend`;
+                # what is left is to undo the ones that DID succeed before it.
+                await self._rollback_handover(prepared)
+                return {
+                    "ok": False,
+                    "reason": f"{session.name} refused the handover",
+                }
+            prepared.append(session)
+        self._prepared_restart = prepared
+        return {"ok": True, "handed_over": [session.id for session in prepared]}
+
+    async def rollback_restart_handover(self) -> None:
+        """Undo a completed fleet handover when the restart will not happen (#237 T3)."""
### e9c34833e #265: #265: canary handshake so a same-name Grok MCP server cannot impersonate ours

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index f9c71f0a9..2d8099a7b 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -13,14 +13,16 @@ import math
 import os
 import shutil
 import re
 import shlex
 import sys
+import tempfile
 import time
 import uuid
 from datetime import datetime, timezone
 from dataclasses import dataclass, field
+from pathlib import Path
 from typing import Any
 
 import httpx
 from mcp.server.fastmcp import FastMCP
 from mcp.types import CallToolResult, TextContent
@@ -47,10 +49,39 @@ WORKER_NAME = os.environ.get("WORKER_NAME", "worker")
 # идентичность СОХРАНЯЕТСЯ и сравнивается позже: держатель тест-лока (#82).
 SESSION_ID = os.environ.get("ORCHESTRA_SESSION_ID", "")
 PARENT_NAME = os.environ.get("PARENT_NAME", "")
 _INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
 ACCESS_MODE = os.environ.get("ORCHESTRA_ACCESS_MODE", "full").strip().lower()
+# Backend plants this nonce in our env. We write a proof file so Grok's same-name
+# MCP merge cannot pass off a foreign `orchestra` server as ours.
+ORCHESTRA_MCP_CANARY_ENV = "ORCHESTRA_MCP_CANARY"
+_ORCHESTRA_MCP_CANARY_RE = re.compile(r"^[0-9a-f]{32}$")
+
+
+def mcp_canary_proof_path(nonce: str) -> Path:
+    return Path(tempfile.gettempdir()) / f"orchestra-mcp-canary-{nonce}"
+
+
+def publish_mcp_identity_canary(environ: dict[str, str] | None = None) -> Path | None:
+    """Prove this process is Orchestra's mcp_stdio, not a same-name impostor.
+
+    Returns the proof path, or None when no canary was planted (non-Grok launch).
+    """
+    env = os.environ if environ is None else environ
+    nonce = str(env.get(ORCHESTRA_MCP_CANARY_ENV) or "").strip()
+    if not nonce:
+        return None
+    if not _ORCHESTRA_MCP_CANARY_RE.fullmatch(nonce):
+        raise RuntimeError("ORCHESTRA_MCP_CANARY is not a 32-char hex nonce")
+    path = mcp_canary_proof_path(nonce)
+    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
+    try:
+        tmp.write_text(nonce, encoding="utf-8")
+        tmp.replace(path)
+    finally:
+        tmp.unlink(missing_ok=True)
+    return path
 
 READ_ONLY_MCP_TOOLS = frozenset({
     "test_lock_status",
     "list_agents",
     "list_orchestrators",
@@ -2338,8 +2369,9 @@ async def codex_review(
         f"SAME output and resume=True. Do not start another codex_review until this one reports back."
     )
 
 
 if __name__ == "__main__":
+    publish_mcp_identity_canary()
     _apply_access_mode()
     logger.info(f"Orchestra MCP stdio (url={ORCHESTRA_URL}, scope={SCOPE})")
     mcp.run(transport="stdio")
### 96192b400 #36: #36: unknown roles fail closed in validate_spawn

diff --git a/app/pipeline.py b/app/pipeline.py
index dbd0867bc..5db7f9740 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -689,46 +689,40 @@ def get_active_pipeline(scope: str = "", parent_pipeline: str = "") -> str:
 # ── Валидация спавна (fail-closed / fail-open) ────────────────────────────
 
 def validate_spawn(pipeline_name: str, parent_role: str | None, child_role: str) -> None:
     """Проверить допустимость спавна ``child_role`` родителем ``parent_role``.
 
-    Режим из ``PipelineConfig.validation``:
-
-    * **fail-closed** (наш дефолт) — неизвестный parent/child → ValueError.
-    * **fail-open** (дух апстрима) — неизвестные роли пропускаются; но явный
-      ``can_spawn``-whitelist при ИЗВЕСТНЫХ ролях действует в обоих режимах.
+    Неизвестная роль родителя или ребёнка — всегда ``ValueError``, в том числе
+    при ``validation: fail-open``. Иначе whitelist ``can_spawn`` действует
+    только на роли из манифеста, а любая чужая строка обходит его целиком (#36).
 
+    ``can_spawn: ['*']`` значит любую *известную* роль, не любую строку.
     Корень (parent пуст/None) — спавн от юзера/UI, всегда разрешён. Пустой
     ``child_role`` (генерик-воркер) разрешён только если ``allow_unrouted_workers``.
 
     :raises ValueError: при запрещённом спавне.
     :raises FileNotFoundError: если манифест отсутствует (manager ловит → fallback).
     """
     cfg = load_pipeline(pipeline_name)
-    fail_closed = cfg.validation == "fail-closed"
 
     if not parent_role:  # корень — спавн от юзера/UI
         return
     parent = cfg.roles.get(parent_role)
     if parent is None:
-        if fail_closed:
-            raise ValueError(
-                f"unknown parent role '{parent_role}' in pipeline '{pipeline_name}'. "
-                f"known={known_roles(pipeline_name)}")
-        return  # fail-open: неизвестный parent → пропуск
+        raise ValueError(
+            f"unknown parent role '{parent_role}' in pipeline '{pipeline_name}'. "
+            f"known={known_roles(pipeline_name)}")
     if not child_role:  # генерик-воркер (роль не указана)
         if not parent.allow_unrouted_workers:
             raise ValueError(
                 f"role '{parent_role}' must specify child role. "
                 f"allowed: {parent.can_spawn or '(none)'}")
         return
     if child_role not in cfg.roles:
-        if fail_closed:
-            raise ValueError(
-                f"unknown role '{child_role}' in pipeline '{pipeline_name}'. "
-                f"known={known_roles(pipeline_name)}")
-        return  # fail-open: неизвестный child → пропуск
+        raise ValueError(
+            f"unknown role '{child_role}' in pipeline '{pipeline_name}'. "
+            f"known={known_roles(pipeline_name)}")
     if "*" in parent.can_spawn:
         return
     if child_role not in parent.can_spawn:
         raise ValueError(
             f"role '{parent_role}' cannot spawn '{child_role}'. "
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index fd898a8c8..d8a956f82 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -487,18 +487,19 @@ class TestDefaultValidateSpawn:
     def test_root_spawn_allowed(self):
         """Корневой спавн (нет родителя) — от юзера/UI, всегда ок."""
         assert P.validate_spawn(PIPELINE, "", "orchestrator") is None
         assert P.validate_spawn(PIPELINE, None, "orchestrator") is None
 
-    def test_fail_open_unknown_child_passes(self):
-        """fail-open: при can_spawn=['*'] и неизвестном child — пропуск (дух апстрима,
-        каталог ролей = подсказка, не жёсткий контракт)."""
-        assert P.validate_spawn(PIPELINE, "orchestrator", "nonexistent-role") is None
-
-    def test_fail_open_unknown_parent_passes(self):
-        """fail-open: неизвестный parent не роняет спавн."""
-        assert P.validate_spawn(PIPELINE, "phantom", "worker") is None
+    def test_fail_open_unknown_child_raises(self):
+        """#36: '*' — любая известная роль, не любая строка."""
+        with pytest.raises(ValueError, match="unknown role"):
+            P.validate_spawn(PIPELINE, "orchestrator", "nonexistent-role")
+
+    def test_fail_open_unknown_parent_raises(self):
+        """#36: неизвестный parent не обходит whitelist."""
+        with pytest.raises(ValueError, match="unknown parent"):
+            P.validate_spawn(PIPELINE, "phantom", "worker")
 
 
 class TestSubOrchestratorGetsMemorySearch:
     """#137: sub-orchestrators work in worktrees and search the same project memory."""
 
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index ec113629b..5f0621194 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -910,25 +910,28 @@ class TestValidateSpawn:
     def test_unknown_parent_fail_closed_raises(self, pipelines_root):
         self._closed(pipelines_root)
         with pytest.raises(ValueError, match="unknown parent"):
             P.validate_spawn("closed", "phantom", "coder")
 
-    # fail-open: нестрого
+    # fail-open: известные роли по-прежнему режет whitelist
     def test_fail_open_forbidden_child_still_raises(self, pipelines_root):
-        # ВАЖНО: fail-open смягчает ТОЛЬКО неизвестные роли; явный whitelist при
-        # известных ролях всё равно действует (coder.can_spawn=[] → terminal)
+        # coder.can_spawn=[] → terminal; неизвестные роли закрывает #36 отдельно
         self._open(pipelines_root)
         with pytest.raises(ValueError, match="cannot spawn"):
             P.validate_spawn("opened", "coder", "lead")
 
-    def test_fail_open_unknown_parent_passes(self, pipelines_root):
+    def test_fail_open_unknown_parent_raises(self, pipelines_root):
+        # #36: fail-open больше не пропускает неизвестного родителя
         self._open(pipelines_root)
-        assert P.validate_spawn("opened", "phantom", "coder") is None
+        with pytest.raises(ValueError, match="unknown parent"):
+            P.validate_spawn("opened", "phantom", "coder")
 
-    def test_fail_open_unknown_child_passes(self, pipelines_root):
+    def test_fail_open_unknown_child_raises(self, pipelines_root):
+        # #36: fail-open больше не пропускает неизвестного ребёнка мимо whitelist
         self._open(pipelines_root)
-        assert P.validate_spawn("opened", "lead", "mystery") is None
+        with pytest.raises(ValueError, match="unknown role"):
+            P.validate_spawn("opened", "lead", "mystery")
 
     def test_wildcard_can_spawn_allows_any(self, pipelines_root):
         _write_pipeline(pipelines_root, "wild", """\
             name: wild
             validation: fail-closed