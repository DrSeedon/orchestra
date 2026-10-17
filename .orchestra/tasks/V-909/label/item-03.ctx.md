# Context for item-03

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/db.py b/app/db.py
index 0d5b86bf4..aae323b60 100644
--- a/app/db.py
+++ b/app/db.py
@@ -69,43 +69,42 @@ _QUOTA_CONTROLLER_TRIGGERS = {
     "quota_controller_policy_audit_no_update",
     "quota_controller_policy_audit_no_delete",
     "quota_controller_policy_audit_no_replace",
 }
 
 # Единственный текст DDL полосы: миграция пересобирает таблицу этим же
 # оператором, потому что страж схемы сверяет сохранённый CREATE дословно, а
 # ALTER TABLE ... RENAME записал бы в sqlite_master другой текст.
 _QUOTA_POLICY_TABLE_SQL = """
         CREATE TABLE IF NOT EXISTS quota_controller_policy (
             lane TEXT PRIMARY KEY CHECK (lane IN ('sol','luna','spark','claude')),
             threshold REAL NOT NULL CHECK (threshold >= 0 AND threshold <= 100),
             revision INTEGER NOT NULL CHECK (revision >= 1),
             source TEXT NOT NULL,
             reason TEXT NOT NULL,
             updated_at TEXT NOT NULL
         )
         """
 
 # Пороги совпадают с fallback-константами гейта (app/quota_gate.py
-# LANE_DEFAULT_THRESHOLDS); равенство закреплено тестом. claude=90 — абсолютный
-# worker-стоп принятой политики #227 (pipelines/default/pipeline.yaml:17
-# absolute_block_pct, app/manager.py:646).
+# LANE_DEFAULT_THRESHOLDS); равенство закреплено тестом. Обоснование каждого числа —
+# там же, у констант: в манифесте пайплайна их больше нет (#329).
 QUOTA_POLICY_DEFAULTS = {"sol": 95.0, "luna": 98.0, "spark": 95.0, "claude": 90.0}
 QUOTA_POLICY_SOURCE = "temporary_static_override"
 QUOTA_POLICY_LABEL = "TEMPORARY STATIC OVERRIDE"
 
 _quota_controller_expected_sql: dict[tuple[str, str], str] | None = None
 
 
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
 
 
diff --git a/app/manager.py b/app/manager.py
index 89f7da03c..a8ee316ba 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1,27 +1,26 @@
 """SessionManager — registry, lifecycle, persistence for all agent sessions."""
 
 import asyncio
 import itertools
 import json
 import logging
-import math
 import os
 import re
 import sqlite3
 import subprocess
 import sys
 import time
 import uuid
 from contextlib import asynccontextmanager
 from dataclasses import dataclass
 from datetime import datetime, timezone
 from pathlib import Path
 from typing import Awaitable, Callable, Optional
 
 from app.session import AgentSession, AgentStatus
 from app.prompting import (
     is_orchestrator_role, safe_format_prompt,
     prompt_template_hash, inject_skills_to_worktree, load_worker_memory,
     refresh_worker_memory, strip_worker_memory,
 )
 
@@ -71,110 +70,40 @@ _adhoc_serial = itertools.count(1)
 
 def enc_cli_dir(cwd: str) -> str:
     """~/.claude/projects/<this> — cwd with '/' and '.' mapped to '-'. Case preserved.
 
     The leading '-' (from the leading '/') is part of the name and must stay:
     stripping it produced a directory the CLI never reads. The CLI also maps
     dots in temporary paths to '-'. scripts/migrate_agent.py re-exports this
     function so the encoding cannot drift a second time.
     """
     return cwd.replace("/", "-").replace(".", "-")
 
 
 @dataclass(frozen=True, slots=True)
 class OrphanProcessIdentity:
     pid: int
     started_at: int
 
 # Клиент MCP отваливается по таймауту через 30 с (mcp_stdio.py). Ждём заведомо меньше,
 # чтобы вызывающий получил внятный отказ, а не ReadTimeout, неотличимый от мёртвого сервера.
 LOCK_WAIT_LIMIT_SECONDS = 25.0
-# Keep policy telemetry inside the 30s MCP request budget. Slow/missing telemetry is
-# advisory failure: the model gate logs it and admits the worker.
-WORKER_MODEL_POLICY_TIMEOUT_SECONDS = 12.0
-WEEKLY_WINDOW_SECONDS = 7 * 24 * 60 * 60
-
-
-async def _worker_model_policy_usage() -> dict:
-    """Read only the live Anthropic payload behind GET /api/usage."""
-    from app.quota_gate import QUOTA_OBSERVATION_MAX_AGE
-    from app.routes.system import current_quota_observation
-
-    observation = await current_quota_observation(required_provider="anthropic")
-    providers = observation.get("providers") if isinstance(observation, dict) else None
-    timestamps = (
-        observation.get("observed_at_by_provider")
-        if isinstance(observation, dict)
-        else None
-    )
-    observed_at = timestamps.get("anthropic") if isinstance(timestamps, dict) else None
-    age = time.time() - observed_at if isinstance(observed_at, (int, float)) else math.inf
-    if isinstance(observed_at, bool) or not 0 <= age < QUOTA_OBSERVATION_MAX_AGE:
-        raise RuntimeError("fresh Anthropic worker quota telemetry is unavailable")
-
-    anthropic = providers.get("anthropic") if isinstance(providers, dict) else None
-    windows = anthropic.get("windows") if isinstance(anthropic, dict) else None
-    seven_day = next(
-        (
-            window for window in windows
-            if isinstance(window, dict) and window.get("id") == "seven_day"
-        ),
-        None,
-    ) if isinstance(windows, list) else None
-    if seven_day is None:
-        raise RuntimeError("Anthropic seven-day worker quota telemetry is unavailable")
-    return {"anthropic": {"seven_day": seven_day}}
-
-
-def _policy_utilization(usage: dict, provider: str, window: str) -> float:
-    data = usage.get(provider)
-    value = data.get(window, {}).get("utilization") if isinstance(data, dict) else None
-    if (
-        isinstance(value, bool)
-        or not isinstance(value, (int, float))
-        or not math.isfinite(float(value))
-        or not 0 <= float(value) <= 100
-    ):
-        raise ValueError(f"{provider}.{window}.utilization is missing or malformed")
-    return float(value)
-
-
-def _policy_window_elapsed(usage: dict) -> tuple[float | None, str]:
-    anthropic = usage.get("anthropic")
-    seven_day = anthropic.get("seven_day") if isinstance(anthropic, dict) else None
-    raw = seven_day.get("resets_at") if isinstance(seven_day, dict) else None
-    if not isinstance(raw, str) or not raw.strip():
-        return None, "anthropic.seven_day.resets_at is missing"
-    try:
-        reset_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
-    except ValueError:
-        return None, "anthropic.seven_day.resets_at is malformed"
-    if reset_at.tzinfo is None:
-        return None, "anthropic.seven_day.resets_at has no timezone"
-    remaining = (reset_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
-    if remaining <= 0:
-        return None, "anthropic.seven_day.resets_at is in the past"
-    if remaining > WEEKLY_WINDOW_SECONDS:
-        return None, "anthropic.seven_day.resets_at is beyond the weekly window"
-    return 100.0 * (1.0 - remaining / WEEKLY_WINDOW_SECONDS), ""
-
-
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
     оставляло ни строки в журнале и ни поля в ответе — снаружи оно было неотличимо от
     зависшего сервера.
@@ -513,43 +442,40 @@ def _make_mcp_config(name: str, scope: str, role: str = "worker",
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
-        self._worker_model_policy_latches: dict[
-            tuple[str, str, float, float, float, float], tuple[bool, bool]
-        ] = {}
         # wired callback (set by tg_bridge.start_bridge) — manager does not import tg_bridge
         self.tg_topics_remover: Optional[Callable[[list[str]], Awaitable[dict]]] = None
         # #220 T2: рестарт закрывает приём новых ходов, пока дренажит уже идущие
         self.draining = False
         # #237 T3: sessions this restart attempt already handed to systemd. Objects, not ids:
         # a rollback has to reach their backends, and an abandoned restart may leave them out
         # of `self.sessions`.
         self._prepared_restart: list = []
 
     @property
     def _prepared_restart_sessions(self) -> set[str]:
         """Ids of the sessions currently prepared for handover (#237 T3)."""
         return {session.id for session in self._prepared_restart}
 
     def begin_drain(self) -> None:
         """Закрыть приём новых ходов. СИНХРОННО — в этом весь смысл.
 
         Ни одного `await` здесь быть не должно: флаг обязан встать раньше, чем цикл
         событий отдаст управление кому-то ещё. Иначе ход, уже прошедший проверку
         гейта, успеет присвоить себе RUNNING после того, как дренаж снял снимок
@@ -584,121 +510,70 @@ class SessionManager:
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
 
     async def _enforce_worker_model_policy(
         self,
         pipeline: str,
         role: str,
         model: str,
         override_reason: str,
     ) -> None:
         cfg = load_pipeline(pipeline)
-        role_spec = cfg.roles.get(role)
-        if role_spec is None or role_spec.kind == "orchestrator":
+        # Исключение оркестраторов живёт ОДНИМ владельцем — в вызывающем коде
+        # (`if planned_initial_turn and not is_orch`), тем же условием пропускающем
+        # и quota-гейт. Копии здесь нет намеренно: она была недостижима через
+        # единственный call site и давала иллюзию покрытия — мутация «снять
+        # исключение» оставляла тест зелёным (#329).
+        if role not in cfg.roles:
             return
         policy = cfg.worker_model_policy
         if policy is None:
             return
 
         reason = override_reason.strip()
         if reason:
             logger.warning(
                 "worker model policy overridden: pipeline=%s role=%s model=%s reason=%s",
                 pipeline, role, model, reason,
             )
             return
         if model in policy.always_allowed:
             return
-
-        alternatives = ", ".join(policy.alternatives)
-        guarded = policy.quota_guarded
-        if model != guarded.model:
-            raise ValueError(
-                f"worker model '{model}' is not allowed by pipeline '{pipeline}'. "
-                f"Use {alternatives}, or pass model_policy_override_reason with a non-empty reason."
-            )
-
-        try:
-            async with asyncio.timeout(WORKER_MODEL_POLICY_TIMEOUT_SECONDS):
-                usage = await _worker_model_policy_usage()
-            claude = _policy_utilization(usage, "anthropic", "seven_day")
-        except Exception as error:
-            logger.error(
-                "worker model policy telemetry unavailable; allowing model=%s: %s: %s",
-                model, type(error).__name__, err_text(error),
-            )
-            return
-
-        key = (
-            pipeline, model,
-            guarded.pace_block_lead_pp, guarded.pace_unblock_lead_pp,
-            guarded.absolute_block_pct, guarded.absolute_unblock_pct,
-        )
-        pace_blocked, absolute_blocked = self._worker_model_policy_latches.get(
-            key, (False, False),
+        # Расход здесь не читается вовсе: потолок пула принуждает quota-гейт
+        # (полоса в `quota_controller_policy`), он зовётся строкой ниже по тому же
+        # спавну. Здесь остаётся только допуск, не зависящий от расхода.
+        raise ValueError(
+            f"worker model '{model}' is not admitted for workers by pipeline '{pipeline}' "
+            f"(models outside the admitted set are refused by default). "
+            f"Use {', '.join(policy.alternatives)}, or pass model_policy_override_reason "
+            "with a non-empty reason."
         )
 
-        if claude >= guarded.absolute_block_pct:
-            absolute_blocked = True
-        elif claude <= guarded.absolute_unblock_pct:
-            absolute_blocked = False
-
-        elapsed, pace_error = _policy_window_elapsed(usage)
-        lead = None
-        if elapsed is None:
-            logger.warning("worker model policy pace check skipped: %s", pace_error)
-        else:
-            lead = claude - elapsed
-            if lead >= guarded.pace_block_lead_pp:
-                pace_blocked = True
-            elif lead <= guarded.pace_unblock_lead_pp:
-                pace_blocked = False
-
-        self._worker_model_policy_latches[key] = pace_blocked, absolute_blocked
-        active: list[str] = []
-        if elapsed is not None and pace_blocked:
-            active.append(
-                f"window elapsed {round(elapsed, 1):g}%, pace lead {round(lead, 1):g} pp "
-                f"(blocks at >= {guarded.pace_block_lead_pp:g} pp, unlocks at "
-                f"<= {guarded.pace_unblock_lead_pp:g} pp)"
-            )
-        if absolute_blocked:
-            active.append(
-                f"absolute worker stop {guarded.absolute_block_pct:g}% remains latched until "
-                f"<= {guarded.absolute_unblock_pct:g}%"
-            )
-        if active:
-            raise ValueError(
-                f"worker model '{model}' is blocked by Claude weekly policy: "
-                f"Claude 7d {claude:g}%; {'; '.join(active)}. Use {alternatives}, or pass "
-                "model_policy_override_reason with a non-empty reason."
-            )
-
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
                              planned_initial_turn: bool = False,
                              model_policy_override_reason: str = "") -> AgentSession:
         normalized_scope = scope.rstrip("/")
         key = (normalized_scope, name)
         lock = self._spawn_locks.setdefault(key, asyncio.Lock())
         async with lock:
             return await self._create_session_locked(
                 name=name,
                 scope=normalized_scope,
diff --git a/app/pipeline.py b/app/pipeline.py
index 5db7f9740..3c3356133 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -161,105 +161,72 @@ class PromptLayers(BaseModel):
 
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
 
 
-class QuotaGuardedModelPolicy(BaseModel):
-    """One worker model guarded by Claude weekly pace and an absolute ceiling."""
-
-    model_config = ConfigDict(extra="forbid")
-    model: str
-    pace_block_lead_pp: float
-    pace_unblock_lead_pp: float
-    absolute_block_pct: float
-    absolute_unblock_pct: float
-
-    @field_validator("model")
-    @classmethod
-    def _canonical_model(cls, v: str) -> str:
-        if not _model_is_known(v):
-            logger.warning("worker model policy: unknown quota-balanced model '%s'", v)
-        return _canon_model(v)
-
-    @model_validator(mode="after")
-    def _valid_hysteresis(self) -> "QuotaGuardedModelPolicy":
-        if not -100 <= self.pace_unblock_lead_pp < self.pace_block_lead_pp <= 100:
-            raise ValueError(
-                "worker model policy requires -100 <= pace_unblock_lead_pp "
-                "< pace_block_lead_pp <= 100"
-            )
-        if not 0 <= self.absolute_unblock_pct < self.absolute_block_pct <= 100:
-            raise ValueError(
-                "worker model policy requires 0 <= absolute_unblock_pct "
-                "< absolute_block_pct <= 100"
-            )
-        return self
+class WorkerModelPolicy(BaseModel):
+    """Static, spend-independent model admission for roles whose kind is worker.
 
+    One mechanism, fail-closed: a model absent from `always_allowed` is refused,
+    so a model newly added to the registry is denied to workers until someone
+    admits it deliberately. There is deliberately no second deny list — two gates
+    over one thought diverge (#329).
 
-class WorkerModelPolicy(BaseModel):
-    """Server-enforced model admission for roles whose manifest kind is worker."""
+    Everything about pools — utilization, pace, reserve — belongs to the quota
+    controller (hot policy in `quota_controller_policy` + `app/quota_gate.py`) and
+    does not exist here at all.
+    """
 
     model_config = ConfigDict(extra="forbid")
     always_allowed: list[str]
-    denied: list[str]
-    quota_guarded: QuotaGuardedModelPolicy
     alternatives: list[str]
 
-    @field_validator("always_allowed", "denied", "alternatives")
+    @field_validator("always_allowed", "alternatives")
     @classmethod
     def _canonical_models(cls, values: list[str]) -> list[str]:
         result: list[str] = []
         for value in values:
             if not _model_is_known(value):
                 logger.warning("worker model policy: unknown model '%s'", value)
             model = _canon_model(value)
             if model in result:
                 raise ValueError(f"worker model policy contains duplicate model '{model}'")
             result.append(model)
         return result
 
     @model_validator(mode="after")
     def _valid_sets(self) -> "WorkerModelPolicy":
-        if self.quota_guarded.model in self.always_allowed:
-            raise ValueError("quota-guarded model cannot also be always allowed")
-        overlap = set(self.always_allowed) & set(self.denied)
-        if self.quota_guarded.model in self.denied:
-            overlap.add(self.quota_guarded.model)
-        if overlap:
-            raise ValueError(
-                f"worker model policy allows and denies the same model: {sorted(overlap)}"
-            )
         missing = set(self.alternatives) - set(self.always_allowed)
         if missing:
             raise ValueError(
                 f"worker model policy alternatives must be always allowed: {sorted(missing)}"
             )
         return self
 
 
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
diff --git a/app/quota_gate.py b/app/quota_gate.py
index 33de0fd5b..1416f42e8 100644
--- a/app/quota_gate.py
+++ b/app/quota_gate.py
@@ -1,41 +1,47 @@
 """Admission policy for new subscription-backed worker turns."""
 
 from __future__ import annotations
 
 import math
 import time
 from dataclasses import dataclass, replace
 from datetime import datetime, timezone
 from typing import Awaitable, Callable, Mapping
 
 from app.models import backend_for_model, resolve_model
 from app.runtime_registry import get_runtime
 
 
 WEEKLY_WINDOW_MINUTES = 10080
 WORKER_WEEKLY_LIMIT_PCT = 95.0
 LUNA_WORKER_WEEKLY_LIMIT_PCT = 98.0
-# Абсолютный worker-стоп пула Claude из принятой политики #227
-# (pipelines/default/pipeline.yaml:17 absolute_block_pct, app/manager.py:646):
-# последние 10 п.п. недели резервируются под оркестраторов и кеш. Оркестраторы
-# гейт не проходят вовсе (app/session.py:1207, :2032, :2248).
+# Абсолютный worker-стоп недельного пула Claude. ЗДЕСЬ живёт обоснование числа —
+# в манифесте его больше нет (#329 вырезал оттуда всё про расход, чтобы у логики
+# пулов остался один владелец):
+#   последние 10 п.п. недели резервируются под ОРКЕСТРАТОРОВ и кеш. Упереться в
+#   недельный лимит Claude больно — работать становится нечем, поэтому воркеры
+#   останавливаются раньше, чем пул кончится. Оркестраторы этот гейт не проходят
+#   вовсе (app/session.py:1207, :2032, :2248), то есть резерв достаётся им.
+# Происхождение: политика #227 (там же был отменённый ныне гистерезис возврата 87%).
+# Значение — только дефолт: действующий порог берётся из полосы `claude` таблицы
+# `quota_controller_policy` и меняется оператором горячо.
 CLAUDE_WORKER_WEEKLY_LIMIT_PCT = 90.0
 # Совпадение с сидом БД (app/db.py QUOTA_POLICY_DEFAULTS) закреплено тестом.
 LANE_DEFAULT_THRESHOLDS = {
     "sol": WORKER_WEEKLY_LIMIT_PCT,
     "luna": LUNA_WORKER_WEEKLY_LIMIT_PCT,
     "spark": WORKER_WEEKLY_LIMIT_PCT,
     "claude": CLAUDE_WORKER_WEEKLY_LIMIT_PCT,
 }
 QUOTA_OBSERVATION_MAX_AGE = 300.0
 SPARK_MODEL = "gpt-5.3-codex-spark"
 READINESS_POLICY = "worker-weekly-v1"
 READINESS_WIRE_VERSION = 2
 LEGACY_QUOTA_RECHECK_SECONDS = 60.0
 
 
 @dataclass(frozen=True)
 class QuotaDecision:
     state: str
     model: str
     provider: str
diff --git a/docs/tasks/329/report.md b/docs/tasks/329/report.md
new file mode 100644
index 000000000..7e62921e4
--- /dev/null
+++ b/docs/tasks/329/report.md
@@ -0,0 +1,203 @@
+# #329 — логика пулов уезжает из манифеста к своему единственному владельцу
+
+## ⚠️ Перед мержем прочитать: ЖИВОЙ процесс отвергает новый манифест
+
+Замерено, а не предположено. Живой сервис поднят 18.08 08:08 с кодом `5a9ff796`; его схема
+`WorkerModelPolicy` требует полей `denied` и `quota_guarded`. Прогон новой формы манифеста через
+ЭТУ схему:
+
+```
+ЖИВАЯ схема ОТВЕРГЛА блок: ValidationError
+  denied         Field required
+  quota_guarded  Field required
+ЖИВАЯ схема отвергла ВЕСЬ манифест: ValidationError
+```
+
+`load_pipeline` поднимает `ValidationError` наружу (docstring: «:raises pydantic.ValidationError»),
+а манифест читается из ГЛАВНОГО чекаута — то есть эффект наступает в момент мержа, не рестарта.
+Пострадает не только гейт моделей: на `load_pipeline` висят каталог ролей и сборка системного
+промпта (`ROLE_SYSTEM_PROMPT`), то есть спавны живых агентов.
+
+**Выбран вариант 2** (рестарт делает только юзер по явной команде, а он не за пультом): код и
+тесты мержатся сейчас, блок манифеста **выключен** отдельным коммитом и включается в окно
+рестарта. До включения живой процесс видит `worker_model_policy is None` — ровно то, что там и
+было последние сутки, то есть мерж не меняет ничего для работающих агентов.
+
+## 🔧 Окно рестарта: что сделать и чем проверить
+
+**1. Включить блок** — снять `# ` с трёх строк в `pipelines/default/pipeline.yaml`
+(`# worker_model_policy:` и две под ним). Команда прогонялась дословно на этом дереве:
+
+```bash
+sed -i -e 's/^# worker_model_policy:/worker_model_policy:/' \
+       -e 's/^#   \(always_allowed\|alternatives\):/  \1:/' pipelines/default/pipeline.yaml
+```
+
+**2. Новая схема приняла манифест** (до рестарта, в главном чекауте):
+
+```bash
+uv run python -c "from app.pipeline import load_pipeline; p = load_pipeline('default').worker_model_policy; print(p.always_allowed, p.alternatives)"
+```
+Ожидаемый вывод — не пусто и без исключения:
+`['gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.3-codex-spark', 'claude-opus-5[1m]'] ['gpt-5.6-sol', 'gpt-5.6-luna']`.
+Тесты зелены в ОБОИХ состояниях блока (проверено: выключен — 101 passed, включён — 117 passed),
+так что `main` не краснеет ни до, ни после включения.
+
+**3. Рестарт** — командой юзера.
+
+**4. Живой процесс принял манифест** (отрицательный признак ловится сразу: битый манифест
+выкидывает пайплайн из списка, `list_pipelines` фильтрует по `valid`):
+
+```bash
+curl -s -H "Authorization: Bearer $INTERNAL_TOKEN" localhost:8888/api/pipelines | grep -c '"name":"default"'
+```
+Ожидание: `1`.
+
+**5. Положительный признак, что допуск ПРИНУЖДАЕТСЯ** (не «должно работать», а проверяемо):
+спавн воркера на невпущенной модели обязан быть отбит, причём НОВЫМ текстом —
+`spawn_worker(name="probe-329", model="gpt-5.6-terra", …)` → `ApiToolError` с подстрокой
+
+```
+not admitted for workers by pipeline 'default'
+```
+
+Текст и есть маркер версии: старый код (5a9ff796) на том же месте отвечал
+`is not allowed by pipeline '<pipeline>'`. Проба безопасна — отказ происходит до любых
+side-effects (ни сессии, ни worktree; в тестах это закреплено `assert mgr.sessions == {}`).
+Если вместо отказа воркер СОЗДАЛСЯ — значит блок не включился или рестарт не состоялся.
+
+## Что действует когда
+
+| что | сейчас (до рестарта) | после рестарта |
+|---|---|---|
+| Полоса `claude` = 90% для воркеров (гейт) | **уже действует** — вошло с #318, `quota_controller_policy` читается на каждый спавн и ход | без изменений |
+| Ползунки порогов, карта квот на фронте | уже действуют (JS/CSS отдаются из чекаута) | без изменений |
+| Статический допуск моделей воркерам (`always_allowed`) | **не действует**: блок выключен, `worker_model_policy is None` — как и последние сутки | начинает действовать (включение блока + рестарт) |
+| Вырезанные из манифеста проценты/темп/резерв | в живом процессе их и так нет (блок был закомментирован) | нет и в коде |
+
+## 1. Что вырезано
+
+Из манифеста и из кода ушло ВСЁ, что читает расход:
+- `quota_guarded` целиком (`model`, `pace_block_lead_pp`, `pace_unblock_lead_pp`,
+  `absolute_block_pct`, `absolute_unblock_pct`) и класс `QuotaGuardedModelPolicy`;
+- из `app/manager.py` — `_worker_model_policy_usage()`, `_policy_utilization()`,
+  `_policy_window_elapsed()`, константы `WORKER_MODEL_POLICY_TIMEOUT_SECONDS`,
+  `WEEKLY_WINDOW_SECONDS`, словарь латчей `_worker_model_policy_latches` и весь блок
+  pace/ceiling-решения (≈80 строк);
+- из `scripts/check_pipeline_manifest.py` — сбор id моделей из `denied`/`quota_guarded`.
+
+Осталось: `always_allowed` + `alternatives`. Принуждение — в коде
+(`SessionManager._enforce_worker_model_policy`, вызов из `create_session` до любых side-effects),
+не в промпте: замер #227 (промптовый запрет модели не сработал 1 из 1) продолжает действовать как
+основание.
+
+## 2. Аллоулист, а не денилист — и почему
+
+Развилку закрыл оркестратор: остаётся **fail-closed** допуск. Модель, отсутствующая в
+`always_allowed`, отклоняется, поэтому новая модель в реестре по умолчанию недоступна воркерам.
+Второго механизма (явного deny-списка Fable/Terra) намеренно нет — это был бы второй гейт на ту же
+мысль. Намерение «эти две не хотим» живёт в комментарии манифеста и в тексте отказа, а не в
+отдельной проверке.
+
+Схемное следствие: `denied` из `WorkerModelPolicy` удалён совсем, `alternatives` обязано быть
+подмножеством `always_allowed` (иначе отказ предлагал бы то, чего сам не впускает).
+
+## 3. Где теперь живёт обоснование `claude = 90`
+
+У самой константы — `CLAUDE_WORKER_WEEKLY_LIMIT_PCT` в `app/quota_gate.py`. Туда перенесён весь
+текст: последние 10 п.п. недели резервируются под оркестраторов и кеш, оркестраторы гейт не
+проходят вовсе (`app/session.py:1207`, `:2032`, `:2248`), происхождение — политика #227.
+`app/db.py` (сид полос) теперь ссылается на константы гейта, а не на строку манифеста, которой
+больше нет. Само значение — только дефолт: действующий порог живёт в полосе `claude` таблицы
+`quota_controller_policy` и меняется оператором горячо.
+
+## 4. Гистерезис 87% — потеря разобрана данными, дребезг невозможен
+
+Вопрос оркестратора: что будет на дребезге у границы 90%, раз гейт решает на каждый ход.
+
+Ответ из живой истории (`usage_snapshots`, копия через `Connection.backup`, 9 950 снимков,
+05.07–18.08, интервал ~5 мин, медиана 300.7 с):
+
+```
+переходов всего: 10025
+уменьшений процента: 11 | из них <= 20 п.п.: 0 | > 20 п.п. (сбросы окна): 11
+макс. маленькое уменьшение: 0
+пересечений порога 90 вниз: 3 | вверх: 3
+колебаний вокруг 90 (>=90 → <90 → >=90): 0
+различных значений: 101, нецелых: 0 (проценты приходят целыми)
+```
+
+Внутри окна ряд не убывает НИ РАЗУ: единственные падения — сбросы, и все они ≥20 п.п. Значит,
+перейдя 90%, утилизация остаётся выше порога до сброса, а после сброса оказывается далеко ниже
+него. Дребезг у границы невозможен по форме данных, и гистерезису здесь нечего защищать —
+отдельный тикет не нужен.
+
+Замечание о методе: первая версия этой проверки резала «окна» по смене `seven_day_resets_at` и
+дала «0 падений, 0 пересечений» — но `resets_at` у Anthropic скользящий и меняется почти в каждом
+снимке (9 949 смен из 9 949), то есть проверка была ВАКУУМНОЙ и не могла покраснеть. Настоящий
+ответ получен по самому ряду процентов.
+
+## 5. Найденный по дороге дефект: исключение оркестраторов имело двух владельцев
+
+Мутация «снять исключение оркестраторов внутри `_enforce_worker_model_policy`» оставила тест
+ЗЕЛЁНЫМ (16 passed). Причина: до функции орк вообще не доходит — call site гейтит сам
+(`if planned_initial_turn and not is_orch`), и `is_orch` выводится из того же факта манифеста
+(`kind == "orchestrator"`, `_role_is_orchestrator`). То есть внутренняя проверка была недостижима
+через единственный call site и создавала иллюзию покрытия.
+
+Убрал дубль, оставив одного владельца — call site (он же пропускает орков мимо quota-гейта).
+После этого мутация на реальном шве (`not is_orch` снято) краснит ровно тест исключения.
+Побочный эффект, названный вслух: если `_enforce_worker_model_policy` когда-нибудь позовут в
+обход `create_session`, орк-роль там больше не будет освобождена — в текущем коде такого
+вызывающего нет (`grep`: один call site).
+
+## 6. Мутации (протокол: `cp` → мутация → `mv` → `grep -c` до/после → `touch` → зелёный повтор)
+
+| # | мутация | что покраснело | после отката |
+|---|---|---|---|
+| N1 | `if model in policy.always_allowed` → `not in` (принуждение снято) | 14 из 16 | 16 passed |
+| N2 | снято исключение орков ВНУТРИ функции | **ничего** — так и нашёлся дубль (см. §5) | 16 passed |
+| N2b | снято исключение орков на реальном шве (`not is_orch`) | `test_orchestrators_are_exempt_even_on_a_model_workers_may_not_use` | 16 passed |
+| N3 | удалён вызов `_enforce_worker_model_policy` (проводка) | 6: все четыре запрещённые модели + override + независимость от расхода | 16 passed |
+| N4b | блок манифеста снова закомментирован (валидный YAML) | тест активности блока — та версия, что требовала включённого блока | 101 passed |
+| N5 | блок исчез совсем: ни активного, ни закомментированного | `test_worker_model_policy_is_active_or_explicitly_staged_and_free_of_spend` | 101 passed |
+| N6 | выключенный блок протащил `quota_guarded` | тот же тест | 101 passed |
+
+N4 (первая попытка) закомментировал только две строки из трёх и сломал YAML — покраснели 88
+тестов, то есть мутант проверял не то, что задумано; переделан как N4b.
+
+## 7. Тесты (правки авторизованы оркестратором)
+
+Удалены тесты вырезанного поведения: pace/гистерезис/абсолютный потолок/латчи/чтение телеметрии
+policy (`test_policy_loader_requests_only_anthropic`, `test_opus_*_hysteresis`,
+`test_fast_claude_pace_*`, `test_balance_telemetry_*`, `test_slow_anthropic_telemetry_*` —
+последний опирался на удалённую константу таймаута; ограничение времени телеметрии осталось внутри
+`current_quota_observation(timeout=12)`).
+
+Сохранены и усилены:
+- `test_model_outside_the_admitted_set_never_reaches_a_session` — 4 параметра: Fable, Terra
+  (намеренно не впущены) и `claude-sonnet-5[1m]`, `grok-4.5` (зарегистрированы, но не открыты) —
+  это и есть проверка fail-closed; каждый случай ещё и доказывает, что телеметрия расхода НЕ
+  читается (`current_quota_observation` подменён на падающий двойник);
+- `test_orchestrators_are_exempt_even_on_a_model_workers_may_not_use` — орк спавнится на Fable;
+- `test_admission_is_independent_of_how_much_quota_is_left` — пул на 1% и на 99% дают одинаковые
+  ответы допуска;
+- `test_quota_gate_blocks_opus_worker_above_the_claude_lane` — новый: потолок пула принуждает
+  ГЕЙТ (91% > полосы 90%), а не манифест;
+- fail-open/громкость quota-гейта на том же спавне (4 теста) — без изменений по смыслу.
+
+Схемные тесты переписаны под новую форму: `tests/test_pipeline.py` теперь проверяет, что манифест
+со `quota_guarded` ОТВЕРГАЕТСЯ, а `alternatives` вне `always_allowed` — тоже.
+
+`tests/test_default_pipeline.py` пришлось привести в соответствие с выключенным блоком, не делая
+тест вакуумным. Он допускает ОБА состояния и в каждом требует одного и того же: блок либо активен,
+либо лежит закомментированным ЯВНО (исчезнуть не может — N5); в любом состоянии его форма —
+ровно `{always_allowed, alternatives}`, без единого поля про расход (N6); схема принимает его
+через `WorkerModelPolicy.model_validate`; Fable и Terra в допуск не входят; и отдельной строкой
+фиксируется, что выключенный блок означает именно «не принуждается»
+(`load_pipeline(...).worker_model_policy is None` ровно тогда, когда блок закомментирован).
+
+Прогоны: `test_worker_model_policy` 16 passed, `test_pipeline` 97 passed,
+`test_default_pipeline` 101 passed, вместе с `test_check_pipeline_manifest`, `test_quota_gate`,
+`test_quota_map_api`, `test_quota_policy` — 272 passed.
+`scripts/check_pipeline_manifest.py --check` — OK.
diff --git a/docs/workers/feat-quota-front.md b/docs/workers/feat-quota-front.md
index e5efc92f8..b81e497b9 100644
--- a/docs/workers/feat-quota-front.md
+++ b/docs/workers/feat-quota-front.md
@@ -20,24 +20,41 @@ called from a running event loop`. Починено в `tests/conftest.py`: це
 `test_frontend.py` 82 errors → 0).
 
 **Урок дороже самого факта:** моё первое лечение было «называй файл так, чтобы сортировался рядом,
 и гоняй отдельным прогоном» — его отбил тест-гейт, потому что отдельный прогон делает ЧЕЛОВЕК, а
 гейт собирает мапнутые тесты в один процесс. Лечение, которое держится на договорённости о способе
 запуска, в автоматике не исполняется вовсе. Проверять такой фикс надо ровно тем прогоном, который
 упал, а не «у меня локально зелено».
 
 Диагностика загрязнения петли — тест на три строки:
 `print(asyncio.events._get_running_loop())` до и после подозреваемого файла.
 
 ## Фронт этого проекта проверяется подменой файлов на живом :8888
 `page.route("**/static/js/analytics.js*", → fulfill(path=<мой worktree>))` плюс то же для
 `style.css`; логин берётся из `.env` (`DASHBOARD_USER`/`DASHBOARD_PASSWORD`), форма — поля
 `username`/`password`. Факт применения — `page.evaluate("typeof <новый символ>")`, а не скриншот.
 Живые данные при этом идут от СТАРОГО питона (правка Python доедет только рестартом), поэтому так
 проверяется именно деградация нового JS на старом бэкенде. Чтобы увидеть панель на настоящих
 числах без рестарта: `curl /api/usage` с `INTERNAL_TOKEN` → `system._provider_usage_snapshot(...)`
 → `build_quota_map()` офлайн на временной БД → отдать payload в браузерный harness.
 
+## Правку СХЕМЫ манифеста проверять живой схемой, а не своей
+Манифест читается из ГЛАВНОГО чекаута, значит новая форма `pipeline.yaml` начинает действовать в
+момент МЕРЖА, а код-валидатор — только после рестарта. Если из схемы убраны обязательные поля,
+живой процесс отвергнет ВЕСЬ манифест (`load_pipeline` поднимает `ValidationError` наружу, на нём
+висят каталог ролей и `ROLE_SYSTEM_PROMPT`, то есть спавны). Проба на 10 строк, делать ДО мержа:
+взять код живого процесса (`git log main --before='<время старта сервиса>' -1` → `git show
+<sha>:app/pipeline.py`), загрузить его через `importlib.util.spec_from_file_location` и прогнать
+новый манифест его схемой. Замер #329: `ЖИВАЯ схема ОТВЕРГЛА блок: denied Field required,
+quota_guarded Field required`. Отсюда правило: мерж манифеста и рестарт — одно окно, либо манифест
+уходит отдельным коммитом в окно рестарта.
+
+## Мутируй ту проверку, которая РЕАЛЬНО работает, а не одноимённую
+#329: мутация «снять исключение оркестраторов» внутри `_enforce_worker_model_policy` оставила тест
+зелёным — до функции орк не доходит, его гейтит call site (`if planned_initial_turn and not
+is_orch`). Два владельца одной мысли, из них работает только внешний. Зелёный мутант здесь — не
+«тест дырявый», а находка: ищи, кто на самом деле принимает решение, и мутируй его.
+
 ## Harness модалки аналитики
 `tests/test_usage_analytics_frontend.py::_page` строит DOM-скелет и подключает мои
 `app/static/js/*` и `style.css` из worktree; `window.api` там — одна заглушка на все URL.
 Если нужен разный ответ по URL, переопределять `window.api` СВОИМ `page.evaluate` после `_page`.
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 1f92f4e1e..4711191a2 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -1,38 +1,44 @@
 name: default
 description: Upstream-derived v2.18 pipeline with local models and runtime modules.
 validation: fail-open
-# ВРЕМЕННО ВЫКЛЮЧЕНО: живой процесс загружен со старой Pydantic-схемой extra='forbid',
-# поэтому новое поле роняет загрузку ВСЕГО манифеста. Снять '# ' со следующего блока
-# вместе с рестартом Orchestra; после этого значения и пороги меняются горячо.
-# Норма — utilization не более чем на 5–10 п.п. впереди прошедшего окна: 11 п.п. —
-# первый целый пункт снаружи, возврат на 7 п.п. даёт гистерезис. Потолок 90% резервирует
-# последние 10% под оркестраторов/кеш; возврат на 87% даёт отдельный гистерезис.
+# Статический, НЕ зависящий от расхода допуск моделей для воркеров. Всё про пулы —
+# проценты, темп, резерв — живёт у quota-контроллера (полосы в таблице
+# `quota_controller_policy`, принуждение в `app/quota_gate.py`) и здесь намеренно
+# отсутствует: два владельца одного числа расходятся (#329).
+# Список работает как fail-closed допуск: чего в нём нет — воркеру запрещено, поэтому
+# новая модель в реестре по умолчанию недоступна, пока её осознанно не впустили.
+# Второго, явного deny-списка нет специально — это был бы второй гейт на ту же мысль.
+# Намеренно не впущены: Fable (вдвое дороже Opus по лимитам, выжигает 5h окно) и Terra.
+# Потолок пула Claude для воркеров (90% недельного окна) задаёт полоса `claude`
+# квота-политики; обоснование числа — у константы CLAUDE_WORKER_WEEKLY_LIMIT_PCT
+# в `app/quota_gate.py`.
+#
+# ВЫКЛЮЧЕН ДО РЕСТАРТА — причина ОБРАТНАЯ прошлому разу (#227). Тогда новое ПОЛЕ
+# роняло старую схему; теперь схема потеряла обязательные `denied` и `quota_guarded`,
+# и живой процесс (код 5a9ff796) отвергает ВЕСЬ манифест: проба его же схемой дала
+# `denied Field required, quota_guarded Field required`. Манифест читается из главного
+# чекаута, то есть эффект наступил бы в момент МЕРЖА, а не рестарта, и снёс бы спавны
+# (на load_pipeline висят каталог ролей и ROLE_SYSTEM_PROMPT).
+# Снять '# ' с трёх строк ниже В ОКНО РЕСТАРТА; порядок и проверки — docs/tasks/329/report.md.
 # worker_model_policy:
-#   always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark]
-#   denied: ["claude-fable-5[1m]", gpt-5.6-terra]
-#   quota_guarded:
-#     model: claude-opus-5[1m]
-#     pace_block_lead_pp: 11
-#     pace_unblock_lead_pp: 7
-#     absolute_block_pct: 90
-#     absolute_unblock_pct: 87
+#   always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark, "claude-opus-5[1m]"]
 #   alternatives: [gpt-5.6-sol, gpt-5.6-luna]
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
diff --git a/scripts/check_pipeline_manifest.py b/scripts/check_pipeline_manifest.py
index 3499dd695..5fa0ac4ba 100755
--- a/scripts/check_pipeline_manifest.py
+++ b/scripts/check_pipeline_manifest.py
@@ -170,45 +170,41 @@ def _manifest_model_ids(data: dict) -> set[str]:
             ids.add(value)
         elif isinstance(value, list):
             for item in value:
                 _take(item)
 
     defaults = data.get("defaults")
     if isinstance(defaults, dict):
         _take(defaults.get("model"))
     for spec in (data.get("roles") or {}).values():
         if not isinstance(spec, dict):
             continue
         _take(spec.get("model"))
         effort = spec.get("effort")
         if isinstance(effort, dict):
             for key in effort:
                 if key != "default":
                     _take(key)
     policy = data.get("worker_model_policy")
     if isinstance(policy, dict):
         _take(policy.get("always_allowed"))
-        _take(policy.get("denied"))
         _take(policy.get("alternatives"))
-        guarded = policy.get("quota_guarded")
-        if isinstance(guarded, dict):
-            _take(guarded.get("model"))
     return ids
 
 
 def disagreements(manifest_path: Path) -> list[str]:
     """Пути, которых манифест требует, а на диске нет; плюс процитированные id моделей.
 
     Пустой список = согласовано. Цитата id в промпте — та же дыра, что скобка
     ``(xhigh)`` в #207: копия расходится с владельцем (#209).
     """
     if not manifest_path.is_file():
         return [f"manifest not found: {manifest_path}"]
     data = yaml.safe_load(manifest_path.read_text()) or {}
     roles = data.get("roles")
     if not isinstance(roles, dict) or not roles:
         return [f"{manifest_path}: no roles to check"]
     root = manifest_path.parent
     errors: list[str] = []
     for name, spec in roles.items():
         role_file = root / "prompts" / "roles" / f"{name}.md"
         if not role_file.is_file():
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index edf0ca3f5..99dea0580 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -55,68 +55,79 @@ class TestDefaultManifestLoads:
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
 
-    def test_worker_model_policy_is_staged_for_restart(self):
-        assert P.load_pipeline(PIPELINE).worker_model_policy is None
-        text = (P.PIPELINES_DIR / PIPELINE / "pipeline.yaml").read_text()
-        commented = """# worker_model_policy:
-#   always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark]
-#   denied: [\"claude-fable-5[1m]\", gpt-5.6-terra]
-#   quota_guarded:
-#     model: claude-opus-5[1m]
-#     pace_block_lead_pp: 11
-#     pace_unblock_lead_pp: 7
-#     absolute_block_pct: 90
-#     absolute_unblock_pct: 87
-#   alternatives: [gpt-5.6-sol, gpt-5.6-luna]"""
-        assert commented in text
-        active = "\n".join(line.removeprefix("# ") for line in commented.splitlines())
-        policy = P.WorkerModelPolicy.model_validate(
-            yaml.safe_load(active)["worker_model_policy"]
-        )
+    def test_worker_model_policy_is_active_or_explicitly_staged_and_free_of_spend(self):
+        """Блок может быть ВЫКЛЮЧЕН решением (мерж без рестарта, #329), но не может
+        просто исчезнуть: выключенный обязан лежать закомментированным, проходить
+        схему при включении и не содержать ничего про расход."""
+        path = P.PIPELINES_DIR / PIPELINE / "pipeline.yaml"
+        text = path.read_text()
+        raw = yaml.safe_load(text).get("worker_model_policy")
+        active = raw is not None
+        if not active:
+            block = []
+            for line in text.splitlines():
+                if line.startswith("# worker_model_policy:"):
+                    block = [line]
+                elif block and line.startswith("#   "):
+                    block.append(line)
+                elif block:
+                    break
+            assert block, (
+                "worker_model_policy не активен и не найден закомментированным: "
+                "выключать его можно только явно"
+            )
+            raw = yaml.safe_load(
+                "\n".join(line.removeprefix("# ").removeprefix("#") for line in block)
+            )["worker_model_policy"]
+
+        # Форма одна и та же в обоих состояниях: ничего про расход, схема принимает.
+        assert set(raw) == {"always_allowed", "alternatives"}, raw
+        for spend_field in ("quota_guarded", "denied", "pace_block_lead_pp", "absolute_block_pct"):
+            assert spend_field not in raw
+        policy = P.WorkerModelPolicy.model_validate(raw)
         assert policy.always_allowed == [
-            "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark",
+            "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "claude-opus-5[1m]",
         ]
-        assert policy.denied == ["claude-fable-5[1m]", "gpt-5.6-terra"]
-        assert policy.quota_guarded.model == "claude-opus-5[1m]"
-        assert policy.quota_guarded.pace_block_lead_pp == 11
-        assert policy.quota_guarded.pace_unblock_lead_pp == 7
-        assert policy.quota_guarded.absolute_block_pct == 90
-        assert policy.quota_guarded.absolute_unblock_pct == 87
         assert policy.alternatives == ["gpt-5.6-sol", "gpt-5.6-luna"]
+        for never in ("claude-fable-5[1m]", "gpt-5.6-terra"):
+            assert never not in policy.always_allowed
+
+        # Выключенный блок означает именно «не принуждается», и это видно загрузчику.
+        assert (P.load_pipeline(PIPELINE).worker_model_policy is not None) is active
 
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
diff --git a/tests/test_pipeline.py b/tests/test_pipeline.py
index 5f0621194..9069fb0bc 100644
--- a/tests/test_pipeline.py
+++ b/tests/test_pipeline.py
@@ -92,84 +92,70 @@ class TestLoadPipeline:
 
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
 
-    @pytest.mark.parametrize("block,unblock", [(7, 7), (6, 7), (101, 7)])
-    def test_worker_model_policy_rejects_invalid_hysteresis(
-        self, pipelines_root, block, unblock,
-    ):
+    def test_worker_model_policy_rejects_spend_fields(self, pipelines_root):
+        """Логику пулов в манифесте не принимаем: у неё один владелец — контроллер (#329)."""
         manifest = _MINIMAL.format(name="demo").replace(
             "    defaults:\n",
             "    worker_model_policy:\n"
             "      always_allowed: [gpt-5.6-sol]\n"
-            "      denied: ['claude-fable-5[1m]']\n"
+            "      alternatives: [gpt-5.6-sol]\n"
             "      quota_guarded:\n"
             "        model: 'claude-opus-5[1m]'\n"
-            f"        pace_block_lead_pp: {block}\n"
-            f"        pace_unblock_lead_pp: {unblock}\n"
             "        absolute_block_pct: 90\n"
-            "        absolute_unblock_pct: 87\n"
-            "      alternatives: [gpt-5.6-sol]\n"
             "    defaults:\n",
         )
         _write_pipeline(pipelines_root, "demo", manifest)
 
-        with pytest.raises(ValueError, match="pace_unblock_lead_pp < pace_block_lead_pp"):
+        with pytest.raises(ValueError, match="quota_guarded"):
             P.load_pipeline("demo")
 
-    @pytest.mark.parametrize("block,unblock", [(87, 87), (86, 87), (101, 87)])
-    def test_worker_model_policy_rejects_invalid_absolute_hysteresis(
-        self, pipelines_root, block, unblock,
+    def test_worker_model_policy_rejects_suggesting_a_model_it_does_not_admit(
+        self, pipelines_root,
     ):
         manifest = _MINIMAL.format(name="demo").replace(
             "    defaults:\n",
             "    worker_model_policy:\n"
             "      always_allowed: [gpt-5.6-sol]\n"
-            "      denied: ['claude-fable-5[1m]']\n"
-            "      quota_guarded:\n"
-            "        model: 'claude-opus-5[1m]'\n"
-            "        pace_block_lead_pp: 11\n"
-            "        pace_unblock_lead_pp: 7\n"
-            f"        absolute_block_pct: {block}\n"
-            f"        absolute_unblock_pct: {unblock}\n"
-            "      alternatives: [gpt-5.6-sol]\n"
+            "      alternatives: [gpt-5.6-luna]\n"
             "    defaults:\n",
         )
         _write_pipeline(pipelines_root, "demo", manifest)
 
-        with pytest.raises(ValueError, match="absolute_unblock_pct < absolute_block_pct"):
+        with pytest.raises(ValueError, match="alternatives must be always allowed"):
             P.load_pipeline("demo")
 
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
diff --git a/tests/test_worker_model_policy.py b/tests/test_worker_model_policy.py
index c9a0fa979..afe7fc5b9 100644
--- a/tests/test_worker_model_policy.py
+++ b/tests/test_worker_model_policy.py
@@ -1,430 +1,279 @@
-import asyncio
+"""Статический допуск моделей воркерам — единственное, что осталось в манифесте (#329).
+
+Всё про расход (проценты, темп, резерв, латчи) вырезано: этим владеет quota-контроллер
+(полосы в `quota_controller_policy` + `app/quota_gate.py`). Здесь проверяется, что
+- допуск fail-closed: чего нет в списке — не поедет, включая новые модели реестра;
+- решение НЕ зависит от телеметрии расхода (отказ происходит, не прочитав её вовсе);
+- оркестраторы освобождены;
+- quota-гейт на том же спавне остаётся fail-open и громким.
+"""
+
 import logging
 from datetime import datetime, timedelta, timezone
 from unittest.mock import AsyncMock, patch
 
 import pytest
 
 from app.quota_gate import get_worker_admission as _real_get_worker_admission
 
 
 @pytest.fixture
 def mgr(tmp_path, monkeypatch):
     db_path = tmp_path / "test.db"
     monkeypatch.setattr("app.db.DB_PATH", db_path)
     from app.db import init_db
     init_db()
     worktree_root = tmp_path / "worktrees"
     worktree_root.mkdir()
     monkeypatch.setattr("app.workspace.WORKTREE_ROOT", worktree_root)
     import app.manager as manager
     from app.pipeline import WorkerModelPolicy, load_pipeline
 
     policy = WorkerModelPolicy.model_validate({
-        "always_allowed": ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark"],
-        "denied": ["claude-fable-5[1m]", "gpt-5.6-terra"],
-        "quota_guarded": {
-            "model": "claude-opus-5[1m]",
-            "pace_block_lead_pp": 11,
-            "pace_unblock_lead_pp": 7,
-            "absolute_block_pct": 90,
-            "absolute_unblock_pct": 87,
-        },
+        "always_allowed": [
+            "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "claude-opus-5[1m]",
+        ],
         "alternatives": ["gpt-5.6-sol", "gpt-5.6-luna"],
     })
     config = load_pipeline("default").model_copy(update={"worker_model_policy": policy})
     monkeypatch.setattr(manager, "load_pipeline", lambda _name: config)
     SessionManager = manager.SessionManager
     return SessionManager()
 
 
 def _usage(utilization: float, elapsed_pct: float | None = None) -> dict:
     seven_day = {"utilization": utilization}
     if elapsed_pct is not None:
         remaining = timedelta(days=7 * (1 - elapsed_pct / 100))
         seven_day["resets_at"] = (datetime.now(timezone.utc) + remaining).isoformat()
     return {"anthropic": {"seven_day": seven_day}}
 
 
 async def _spawn(mgr, name: str, model: str, **kwargs):
     from tests.conftest import make_backend_mock
 
     with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
         return await mgr.create_session(
             name=name,
             scope="/model-policy",
             cwd="/tmp",
             model=model,
             role=kwargs.pop("role", "worker"),
             planned_initial_turn=True,
             **kwargs,
         )
 
 
-@pytest.mark.asyncio
-async def test_policy_loader_requests_only_anthropic(monkeypatch):
-    import app.manager as manager
+def _forbid_telemetry(monkeypatch):
+    """Любое чтение расхода на этом спавне — провал: допуск от него не зависит."""
     import app.routes.system as system
 
-    now = datetime.now(timezone.utc).timestamp()
-    loader = AsyncMock(return_value={
-        "providers": {
-            "anthropic": {
-                "windows": [{
-                    "id": "seven_day",
-                    "utilization": 10,
-                    "resets_at": datetime.now(timezone.utc).isoformat(),
-                }],
-            },
-        },
-        "observed_at_by_provider": {"anthropic": now},
-    })
-    monkeypatch.setattr(system, "current_quota_observation", loader)
+    probe = AsyncMock(side_effect=AssertionError("static model policy read spend telemetry"))
+    monkeypatch.setattr(system, "current_quota_observation", probe)
+    return probe
 
-    await manager._worker_model_policy_usage()
 
-    loader.assert_awaited_once_with(required_provider="anthropic")
+@pytest.mark.asyncio
+@pytest.mark.parametrize(
+    "model",
+    [
+        "claude-fable-5[1m]",   # намеренно не впущена: вдвое дороже Opus по лимитам
+        "gpt-5.6-terra",        # намеренно не впущена: решение юзера
+        "claude-sonnet-5[1m]",  # зарегистрирована, но воркерам не открыта
+        "grok-4.5",             # другой рантайм, тоже не открыт
+    ],
+)
+async def test_model_outside_the_admitted_set_never_reaches_a_session(
+    mgr, monkeypatch, model,
+):
+    probe = _forbid_telemetry(monkeypatch)
+
+    with pytest.raises(ValueError, match=r"not admitted for workers.*gpt-5\.6-sol"):
+        await _spawn(mgr, "denied", model)
+
+    assert mgr.sessions == {}
+    probe.assert_not_awaited()
 
 
 @pytest.mark.asyncio
-async def test_warm_anthropic_cache_still_blocks_fast_opus_without_other_refresh(
+@pytest.mark.parametrize(
+    "model", ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "claude-opus-5[1m]"],
+)
+async def test_admitted_models_spawn(mgr, monkeypatch, model):
+    monkeypatch.setattr(
+        "app.quota_gate.get_worker_admission",
+        AsyncMock(side_effect=RuntimeError("quota telemetry offline")),
+    )
+
+    worker = await _spawn(mgr, model.rsplit("-", 1)[-1], model)
+
+    assert worker.model == model
+
+
+@pytest.mark.asyncio
+async def test_override_reason_admits_a_model_outside_the_set_and_is_logged(
+    mgr, monkeypatch, caplog,
+):
+    monkeypatch.setattr(
+        "app.quota_gate.get_worker_admission",
+        AsyncMock(side_effect=RuntimeError("quota telemetry offline")),
+    )
+
+    with caplog.at_level(logging.WARNING, logger="app.manager"):
+        worker = await _spawn(
+            mgr,
+            "override-terra",
+            "gpt-5.6-terra",
+            model_policy_override_reason="pilot #329 comparison",
+        )
+
+    assert worker.model == "gpt-5.6-terra"
+    assert "pilot #329 comparison" in caplog.text
+
+
+@pytest.mark.asyncio
+async def test_orchestrators_are_exempt_even_on_a_model_workers_may_not_use(
     mgr, monkeypatch,
 ):
+    probe = _forbid_telemetry(monkeypatch)
+
+    orchestrator = await _spawn(
+        mgr,
+        "fable-orchestrator",
+        "claude-fable-5[1m]",
+        role="orchestrator",
+        is_orchestrator=True,
+    )
+
+    assert orchestrator.is_orchestrator
+    assert orchestrator.model == "claude-fable-5[1m]"
+    probe.assert_not_awaited()
+
+
+@pytest.mark.asyncio
+async def test_admission_is_independent_of_how_much_quota_is_left(mgr, monkeypatch):
+    """Пул на нуле или почти исчерпан — статический допуск отвечает одинаково."""
     import app.routes.system as system
 
-    now = datetime.now(timezone.utc).timestamp()
-    warm = _usage(64, 28)["anthropic"]
     monkeypatch.setattr(
-        system,
-        "_usage_cache",
-        {"data": warm, "ts": now, "token": None},
+        "app.quota_gate.get_worker_admission",
+        AsyncMock(side_effect=RuntimeError("quota telemetry offline")),
     )
-    fetch_anthropic = AsyncMock(side_effect=AssertionError("warm cache was refreshed"))
-    fetch_codex = AsyncMock(side_effect=AssertionError("Codex telemetry was requested"))
-    monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
-    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)
-
-    with pytest.raises(ValueError, match=r"Claude 7d 64%.*window elapsed 28%"):
-        await _spawn(mgr, "warm-cache-opus", "claude-opus-5[1m]")
+    for utilization, name in ((1, "empty-pool"), (99, "full-pool")):
+        now = datetime.now(timezone.utc).timestamp()
+        monkeypatch.setattr(
+            system, "_usage_cache",
+            {"data": _usage(utilization, 50)["anthropic"], "ts": now, "token": None},
+        )
+        worker = await _spawn(mgr, f"opus-{name}", "claude-opus-5[1m]")
+        assert worker.model == "claude-opus-5[1m]"
 
-    assert mgr.sessions == {}
-    fetch_anthropic.assert_not_awaited()
-    fetch_codex.assert_not_awaited()
+        with pytest.raises(ValueError, match="not admitted for workers"):
+            await _spawn(mgr, f"terra-{name}", "gpt-5.6-terra")
 
 
+# ── quota-гейт на том же спавне: он и владеет расходом ───────────────────────
 @pytest.mark.asyncio
 async def test_warm_anthropic_cache_normal_control_passes_real_spawn_seam(
     mgr, monkeypatch,
 ):
     import app.routes.system as system
 
     now = datetime.now(timezone.utc).timestamp()
     warm = _usage(39, 30)["anthropic"]
     monkeypatch.setattr(system, "_usage_cache", {"data": warm, "ts": now, "token": None})
     fetch_anthropic = AsyncMock(side_effect=AssertionError("warm cache was refreshed"))
     fetch_codex = AsyncMock(side_effect=AssertionError("Codex telemetry was requested"))
     monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
     monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)
     monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)
 
     worker = await _spawn(mgr, "warm-normal-opus", "claude-opus-5[1m]")
 
     assert worker.model == "claude-opus-5[1m]"
     fetch_anthropic.assert_not_awaited()
     fetch_codex.assert_not_awaited()
 
 
+@pytest.mark.asyncio
+async def test_quota_gate_blocks_opus_worker_above_the_claude_lane(mgr, monkeypatch):
+    """Потолок пула теперь принуждает гейт, а не манифест: 91% > полосы claude 90%."""
+    import app.routes.system as system
+
+    now = datetime.now(timezone.utc).timestamp()
+    monkeypatch.setattr(
+        system, "_usage_cache",
+        {"data": _usage(91, 50)["anthropic"], "ts": now, "token": None},
+    )
+    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)
+
+    from app.quota_gate import QuotaGateError
+
+    with pytest.raises(QuotaGateError) as caught:
+        await _spawn(mgr, "opus-over-lane", "claude-opus-5[1m]")
+
+    assert caught.value.code == "weekly_quota_blocked"
+    assert caught.value.decision.threshold == 90.0
+    assert mgr.sessions == {}
+
+
 @pytest.mark.asyncio
 async def test_stale_anthropic_cache_refresh_failure_is_fail_open_and_loud(
     mgr, monkeypatch, caplog,
 ):
     import app.routes.system as system
 
     now = datetime.now(timezone.utc).timestamp()
     stale = _usage(95, 95)["anthropic"]
     monkeypatch.setattr(
         system,
         "_usage_cache",
         {"data": stale, "ts": now - 301, "token": None},
     )
     monkeypatch.setattr(system, "_read_oauth_credentials", lambda: ("token", None, None))
     fetch_anthropic = AsyncMock(side_effect=RuntimeError("offline"))
     fetch_codex = AsyncMock(side_effect=AssertionError("Codex telemetry was requested"))
     monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
     monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)
     monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)
 
     with caplog.at_level(logging.ERROR, logger="app.manager"):
         worker = await _spawn(mgr, "stale-cache-opus", "claude-opus-5[1m]")
 
     assert worker.model == "claude-opus-5[1m]"
-    assert "fresh Anthropic worker quota telemetry is unavailable" in caplog.text
     assert "worker quota admission telemetry unavailable; allowing" in caplog.text
-    assert fetch_anthropic.await_count == 2
     fetch_codex.assert_not_awaited()
 
 
 @pytest.mark.asyncio
 async def test_unavailable_anthropic_cache_is_fail_open_at_real_spawn_seam(
     mgr, monkeypatch, caplog,
 ):
     import app.routes.system as system
 
     monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0, "token": None})
     monkeypatch.setattr(system, "_read_oauth_credentials", lambda: (None, None, None))
     monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)
 
     with caplog.at_level(logging.ERROR, logger="app.manager"):
         worker = await _spawn(mgr, "unavailable-opus", "claude-opus-5[1m]")
 
     assert worker.model == "claude-opus-5[1m]"
     assert "worker quota admission telemetry unavailable; allowing" in caplog.text
 
 
-@pytest.mark.asyncio
-async def test_slow_anthropic_telemetry_is_fail_open_at_real_spawn_seam(
-    mgr, monkeypatch, caplog,
-):
-    import app.routes.system as system
-
-    calls = 0
-
-    async def slow_then_unavailable(*, required_provider):
-        nonlocal calls
-        assert required_provider == "anthropic"
-        calls += 1
-        if calls == 1:
-            await asyncio.Event().wait()
-        return {
-            "providers": {},
-            "observed_at_by_provider": {},
-        }
-
-    monkeypatch.setattr(system, "current_quota_observation", slow_then_unavailable)
-    monkeypatch.setattr("app.manager.WORKER_MODEL_POLICY_TIMEOUT_SECONDS", 0.01)
-    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)
-
-    with caplog.at_level(logging.ERROR, logger="app.manager"):
-        worker = await _spawn(mgr, "slow-telemetry-opus", "claude-opus-5[1m]")
-
-    assert worker.model == "claude-opus-5[1m]"
-    assert calls == 2
-    assert "TimeoutError" in caplog.text
-    assert "worker quota admission telemetry unavailable; allowing" in caplog.text
-
-
 @pytest.mark.asyncio
 async def test_quota_admission_exception_is_fail_open_and_loud(
     mgr, monkeypatch, caplog,
 ):
-    monkeypatch.setattr(
-        "app.manager._worker_model_policy_usage",
-        AsyncMock(return_value=_usage(39, 30)),
-    )
     monkeypatch.setattr(
         "app.quota_gate.get_worker_admission",
         AsyncMock(side_effect=RuntimeError("admission unavailable")),
     )
 
     with caplog.at_level(logging.ERROR, logger="app.manager"):
         worker = await _spawn(mgr, "admission-error-opus", "claude-opus-5[1m]")
 
     assert worker.model == "claude-opus-5[1m]"
     assert "worker quota admission check failed; allowing" in caplog.text
     assert "admission unavailable" in caplog.text
-
-
-@pytest.mark.asyncio
-async def test_fast_claude_pace_rejects_opus_worker_before_publish(mgr, monkeypatch):
-    monkeypatch.setattr(
-        "app.manager._worker_model_policy_usage",
-        AsyncMock(return_value=_usage(64, 28)),
-    )
-


## Later history of the touched files on main (after this commit)

157 later commits touch these paths; the first 40 (oldest first):
8c5ea3647 2026-08-18 #329: включён worker_model_policy — рестарт 18.08 17:31 UTC загрузил новую схему
b643c67e3 2026-08-19 #230: горячее применение правок и живучесть ходов при рестарте
fabb50edb 2026-08-19 #314: #314: Фаза 1 — что должно решать допуск: дефицит рабочих часов против процента
98ae5885b 2026-08-19 ревью не обязательно и без замены ревьюера; code-quality вынесен в модуль; оба контракта закрыты тестами
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
af58227ee 2026-08-19 #346: #346: правило формата ответа юзеру — блок <user-answer-format> в роли оркестратора
eac83b8aa 2026-08-19 #348: #348: шесть правил про поведение агентов перенесены из CLAUDE.md к владельцам в pipelines/
eb9d6ce28 2026-08-19 #349: #349: check_pipeline_manifest — якоря нового контракта ревью + числа внутри примера
e91247c9c 2026-08-19 #353: #353: unify quota panel and add traces
b1b77132a 2026-08-19 #355: #355: make quota gate thresholds configurable via env
a44feb4bb 2026-08-19 #356: #356: route usage bars to quota release status
f590cdd11 2026-08-20 #360: решающее окно квоты выбирается по длине, а не по имени поля
9248be4cd 2026-08-22 #365: харнес на OpenRouter из приватного форка — рантайм harness, шесть бесплатных моделей
0a00e9d2b 2026-08-22 скилл eli5 — только оркестраторам
c74d0d75b 2026-08-22 #368: #368: Phase 1 — исследование источников счётчика запросов OpenRouter (гибрид: локальный счёт + /activity)
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)
9936efa4a 2026-08-23 #217: keep bounded local rule edits in orchestrator
e2ecc033d 2026-08-23 #293: #293: freeze ownership lifecycle red tests
b460149d4 2026-08-23 #379: #379: research socket restart failure
71374ea56 2026-08-23 #385: #385: research deferred turn control and provenance
81a1c60f8 2026-08-24 #380: #380: research durable send acceptance
f8295d11e 2026-08-24 #386: #386: research regression-aware merge gate
9d2627281 2026-08-24 Merge origin/main into main (2026-08-24 sync)
e7d521de5 2026-08-24 fix: preserve generated images across chat switches
2fa666288 2026-08-24 #337: #337: add durable primary TG file receipts
2fcc0e2fa 2026-08-24 chore: remove inert blob and stale docs artifacts
499176cc2 2026-08-24 chore: remove second dead-code batch
6f874ace5 2026-08-24 #248: make task state platform-owned and restart-safe
f3ae49867 2026-08-25 Merge remote-tracking branch 'origin/main'
e493f2082 2026-08-25 #352: #352: add recovery and private pack replay
0ce9151a0 2026-08-25 #361: research live knowledge activation
a2c45a484 2026-08-25 #396: restore weekly limits card and reuse renderer
bf1d013c4 2026-08-25 #365: send dashboard voice asynchronously
0349fc14c 2026-08-26 Repair Orchestra startup and dashboard resilience
507b63d81 2026-08-26 #401: expose quota delivery refusals
aaa98a8fd 2026-08-26 #402: freeze red batch delivery oracles
ad76ba42e 2026-08-27 #411: freeze reliable restart oracles
6cbd918de 2026-08-27 #413: freeze immediate restart oracles
b757e8343 2026-08-28 порог Sol по параболе: жжём пул Codex в начале окна
57038767b 2026-08-30 #417: switch memory prompt to file-first retrieval

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 8c5ea3647 #329: включён worker_model_policy — рестарт 18.08 17:31 UTC загрузил новую схему

diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 4711191a2..0cab77354 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -18,13 +18,13 @@ validation: fail-open
 # и живой процесс (код 5a9ff796) отвергает ВЕСЬ манифест: проба его же схемой дала
 # `denied Field required, quota_guarded Field required`. Манифест читается из главного
 # чекаута, то есть эффект наступил бы в момент МЕРЖА, а не рестарта, и снёс бы спавны
 # (на load_pipeline висят каталог ролей и ROLE_SYSTEM_PROMPT).
 # Снять '# ' с трёх строк ниже В ОКНО РЕСТАРТА; порядок и проверки — docs/tasks/329/report.md.
-# worker_model_policy:
-#   always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark, "claude-opus-5[1m]"]
-#   alternatives: [gpt-5.6-sol, gpt-5.6-luna]
+worker_model_policy:
+  always_allowed: [gpt-5.6-sol, gpt-5.6-luna, gpt-5.3-codex-spark, "claude-opus-5[1m]"]
+  alternatives: [gpt-5.6-sol, gpt-5.6-luna]
 defaults:
   model: opus
   skills: []
   mcp_servers: []
   inherit_claude_md: true
### b643c67e3 #230: горячее применение правок и живучесть ходов при рестарте

diff --git a/app/manager.py b/app/manager.py
index a8ee316ba..3069c00f3 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -1,10 +1,11 @@
 """SessionManager — registry, lifecycle, persistence for all agent sessions."""
 
 import asyncio
 import itertools
 import json
+import contextlib
 import logging
 import os
 import re
 import sqlite3
 import subprocess
@@ -1123,10 +1124,13 @@ class SessionManager:
             await asyncio.to_thread(
                 remove_worktree,
                 session.scope,
                 session.worktree_path,
             )
+        # Сессии больше нет — снять её имена из FD store (#230 T2). Иначе store дорастает до
+        # `FileDescriptorStoreMax=256`, и новые агенты молча перестают быть защищёнными.
+        retire_backend_fds(session)
         archive_session(session_id)
         self.sessions.pop(session_id, None)
 
     def refresh_identity(self, session) -> str:
         """Пересобрать MCP-конфиг сессии под её ТЕКУЩИЕ имя и родителя.
@@ -2088,11 +2092,14 @@ class SessionManager:
                         fd_in, fd_out, active_turn_id=row.get("active_turn_id") or None,
                         leftover=row.get("leftover") or "",
                         cli_pid=int(row.get("cli_pid") or 0),
                         cli_started_at=int(row.get("cli_started_at") or 0),
                     )
-                    logger.info("[%s] adopted a live CLI; its turn keeps running", session.name)
+                    logger.info(
+                        "[%s] adopted a live CLI; %s", session.name,
+                        "its turn keeps running" if row.get("active_turn_id")
+                        else "no turn was in flight")
                     continue  # no restart notice: nothing was interrupted
                 if row["id"] in was_waiting:
                     from app.bg_jobs import bg_manager
                     if bg_manager and bg_manager.has_active_jobs(row["id"]):
                         session.status = AgentStatus.WAITING
@@ -2119,11 +2126,14 @@ class SessionManager:
                         fd_in, fd_out, active_turn_id=row.get("active_turn_id") or None,
                         leftover=row.get("leftover") or "",
                         cli_pid=int(row.get("cli_pid") or 0),
                         cli_started_at=int(row.get("cli_started_at") or 0),
                     )
-                    logger.info("[%s] adopted a live CLI; its turn keeps running", session.name)
+                    logger.info(
+                        "[%s] adopted a live CLI; %s", session.name,
+                        "its turn keeps running" if row.get("active_turn_id")
+                        else "no turn was in flight")
                     continue  # no restart notice: nothing was interrupted
                 if row["id"] in was_waiting:
                     from app.bg_jobs import bg_manager
                     if bg_manager and bg_manager.has_active_jobs(row["id"]):
                         session.status = AgentStatus.WAITING
@@ -2347,10 +2357,60 @@ class SessionManager:
             )
         self.sessions.clear()
         self._session_locks.clear()
 
 
+def publish_backend_fds(session) -> bool:
+    """Отдать пайпы агента systemd СРАЗУ при спавне, а не в момент выключения (#230 T2).
+
+    До этого `store_fds` звался ровно из одного места — с пути выключения, — и потому
+    независимость агента была условной: она существовала, только если сервер успел провести
+    транзакцию. При `kill -9`/OOM CLI переживает нас, а дескрипторы умирают вместе с нами, и
+    подхватить его становится нечем.
+
+    Всё или ничего: половина пары выглядит как защищённый агент, которого нельзя принять —
+    для adopt нужны обе стороны. Поэтому упавшая вторая сторона снимает уже положенную первую.
+    """
+    from app import fdstore
+
+    backend = getattr(session, "_backend", None)
+    fd_in = getattr(backend, "fd_in", None)
+    fd_out = getattr(backend, "fd_out", None)
+    if fd_in is None or fd_out is None:
+        return False  # рантайм без собственных пайпов (Claude): передавать нечего
+
+    stored: list[str] = []
+    try:
+        for name, fd in ((fd_store_name(session.id, "stdin"), fd_in),
+                         (fd_store_name(session.id, "stdout"), fd_out)):
+            fdstore.store_fds(name, [fd])
+            stored.append(name)
+    except Exception as error:
+        # Громко: молчаливый отказ вернул бы прежнюю условную независимость, ничего об этом
+        # не сказав, то есть тот же дефект, но уже невидимый.
+        logger.error("[%s] could not publish agent pipes to systemd: %s",
+                     getattr(session, "name", session.id), err_text(error))
+        for name in stored:
+            with contextlib.suppress(Exception):
+                fdstore.remove_fds(name)
+        return False
+    return True
+
+
+def retire_backend_fds(session) -> None:
+    """Снять имена, когда сессия закончилась штатно (#230 T2).
+
+    Без этого store упирается в `FileDescriptorStoreMax=256`, и новые сессии молча перестают
+    быть защищёнными — то есть защита исчезает ровно тогда, когда агентов стало много.
+    """
+    from app import fdstore
+
+    for side in ("stdin", "stdout"):
+        with contextlib.suppress(Exception):
+            fdstore.remove_fds(fd_store_name(session.id, side))
+
+
 def fd_store_name(session_id: str, side: str) -> str:
     """The FDNAME an agent pipe is stored under (#237 T2).
 
     Dots, not colons: `:` separates entries in LISTEN_FDNAMES, and systemd answers a name
     containing it by silently storing everything as `stored` instead.
### fabb50edb #314: #314: Фаза 1 — что должно решать допуск: дефицит рабочих часов против процента

diff --git a/app/db.py b/app/db.py
index aae323b60..390bb2e05 100644
--- a/app/db.py
+++ b/app/db.py
@@ -37,12 +37,16 @@ _QUOTA_CONTROLLER_TABLE_COLUMNS = {
     "quota_controller_evidence_sets": (
         "evidence_id", "created_at", "dataset_start", "dataset_end", "policy_version",
         "regime_set_hash", "source_digest", "prospective", "metrics_json",
         "reasons_json", "eligible",
     ),
+    # Порядок и состав ОБЯЗАНЫ совпадать с `_QUOTA_POLICY_TABLE_SQL` и со списком
+    # переносимых колонок в дрейф-починке — это три копии одного перечня, и
+    # расхождение любой пары ловится здесь громко (#314).
     "quota_controller_policy": (
         "lane", "threshold", "revision", "source", "reason", "updated_at",
+        "deficit_hours", "min_work_hours",
     ),
     "quota_controller_policy_audit": (
         "audit_id", "actor", "created_at", "old_json", "new_json", "reason",
         "revision", "action",
     ),
@@ -79,11 +83,17 @@ _QUOTA_POLICY_TABLE_SQL = """
             lane TEXT PRIMARY KEY CHECK (lane IN ('sol','luna','spark','claude')),
             threshold REAL NOT NULL CHECK (threshold >= 0 AND threshold <= 100),
             revision INTEGER NOT NULL CHECK (revision >= 1),
             source TEXT NOT NULL,
             reason TEXT NOT NULL,
-            updated_at TEXT NOT NULL
+            updated_at TEXT NOT NULL,
+            -- Порог дефицита рабочих часов и окно применимости темпа (#314).
+            -- NULL = деградация по дефициту выключена; это и есть аварийный выключатель.
+            -- Отдельные колонки, а не переиспользование `threshold`: у того CHECK 0..100 —
+            -- инвариант ПРОЦЕНТА, и расширять его под часы значило бы его потерять.
+            deficit_hours REAL CHECK (deficit_hours IS NULL OR deficit_hours >= 0),
+            min_work_hours REAL CHECK (min_work_hours IS NULL OR min_work_hours >= 0)
         )
         """
 
 # Пороги совпадают с fallback-константами гейта (app/quota_gate.py
 # LANE_DEFAULT_THRESHOLDS); равенство закреплено тестом. Обоснование каждого числа —
@@ -435,22 +445,30 @@ def _migrate_quota_policy_lanes(c: sqlite3.Connection) -> None:
         return
     if _normalize_schema_sql(row["sql"]) == _normalize_schema_sql(_QUOTA_POLICY_TABLE_SQL):
         return
     c.execute("BEGIN IMMEDIATE")
     try:
+        # Перечень колонок ОБЯЗАН совпадать с `_QUOTA_POLICY_TABLE_SQL`. Забыть здесь новую
+        # колонку — значит молча обнулить операторские значения при первом же дрейфе:
+        # таблица на месте, строки на месте, а деградация выключена (#314).
+        existing = {row[1] for row in c.execute("PRAGMA table_info(quota_controller_policy)")}
+        carried = [
+            name for name in (
+                "lane", "threshold", "revision", "source", "reason", "updated_at",
+                "deficit_hours", "min_work_hours",
+            ) if name in existing
+        ]
         rows = [
             tuple(item) for item in c.execute(
-                "SELECT lane, threshold, revision, source, reason, updated_at "
-                "FROM quota_controller_policy"
+                f"SELECT {', '.join(carried)} FROM quota_controller_policy"
             )
         ]
         c.execute("DROP TABLE quota_controller_policy")
         c.execute(_QUOTA_POLICY_TABLE_SQL)
         c.executemany(
-            "INSERT INTO quota_controller_policy "
-            "(lane, threshold, revision, source, reason, updated_at) "
-            "VALUES (?, ?, ?, ?, ?, ?)",
+            f"INSERT INTO quota_controller_policy ({', '.join(carried)}) "
+            f"VALUES ({', '.join('?' * len(carried))})",
             rows,
         )
         c.commit()
     except Exception:
         c.rollback()
@@ -502,13 +520,18 @@ def quota_controller_connection(path: str | Path) -> sqlite3.Connection:
 
 class QuotaPolicyRevisionMismatch(RuntimeError):
     """The operator policy changed after a caller read its revision."""
 
 
+def _opt_float(value: object) -> float | None:
+    return None if value is None else float(value)
+
+
 def _quota_policy_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
     return conn.execute(
-        "SELECT lane, threshold, revision, source, reason, updated_at "
+        "SELECT lane, threshold, revision, source, reason, updated_at, "
+        "deficit_hours, min_work_hours "
         "FROM quota_controller_policy ORDER BY CASE lane "
         "WHEN 'claude' THEN 0 WHEN 'sol' THEN 1 WHEN 'luna' THEN 2 ELSE 3 END"
     ).fetchall()
 
 
@@ -543,10 +566,12 @@ def quota_policy_snapshot() -> dict:
             "threshold": float(row["threshold"]),
             "revision": int(row["revision"]),
             "source": row["source"],
             "reason": row["reason"],
             "updated_at": row["updated_at"],
+            "deficit_hours": _opt_float(row["deficit_hours"]),
+            "min_work_hours": _opt_float(row["min_work_hours"]),
         }
         for row in rows
     }
     revision = max(item["revision"] for item in lanes.values())
     latest = max(rows, key=lambda row: row["updated_at"])
@@ -639,10 +664,156 @@ def rollback_quota_policy(*, actor: str, reason: str = "operator rollback to def
     return replace_quota_policy(
         dict(QUOTA_POLICY_DEFAULTS), actor=actor, reason=reason, action="rollback",
     )
 
 
+def set_runway_policy(
+    *,
+    lane: str,
+    deficit_hours: float | None,
+    min_work_hours: float | None,
+    source: str = "operator",
+    reason: str,
+    actor: str = "operator",
+) -> dict:
+    """Записать порог дефицита для полосы. `deficit_hours=None` — выключить деградацию.
+
+    Читается на КАЖДОЕ решение (`quota_policy_snapshot` без кеша), поэтому запись здесь —
+    и есть обратимость без рестарта. Пишем в ту же аудит-таблицу, что и пороги процента:
+    окно без срабатываний обязано быть отличимо от окна, в котором механизм выключили.
+    """
+    if lane not in QUOTA_POLICY_DEFAULTS:
+        raise ValueError(f"unknown quota policy lane: {lane}")
+    reason = str(reason or "").strip()
+    if not reason:
+        raise ValueError("runway policy reason is required")
+    for name, value in (("deficit_hours", deficit_hours), ("min_work_hours", min_work_hours)):
+        if value is None:
+            continue
+        if isinstance(value, bool) or not isinstance(value, (int, float)):
+            raise ValueError(f"runway policy {name} must be numeric")
+        if not math.isfinite(float(value)) or float(value) < 0:
+            raise ValueError(f"runway policy {name} must be a finite non-negative number")
+    with _conn() as conn:
+        _ensure_quota_controller_schema(conn)
+        _ensure_quota_policy_defaults(conn)
+        conn.commit()
+        conn.execute("BEGIN IMMEDIATE")
+        rows = _quota_policy_rows(conn)
### 98ae5885b ревью не обязательно и без замены ревьюера; code-quality вынесен в модуль; оба контракта закрыты тестами

diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 0cab77354..0f87cbb52 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -92,11 +92,11 @@ roles:
     label: Worker
     order: 2
     model: claude-opus-5[1m]
     effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, codex-debate]
-    modules: [git-workflow, report-format, self-improvement, memory-search]
+    modules: [code-quality, git-workflow, report-format, self-improvement, memory-search]
     can_spawn: []
     allow_unrouted_workers: false
     tg: {emoji: "⚙️"}
     when: Clear task for a known module, implementation from detailed spec, bug fix with known repro
     not_for: Tasks needing research or unknown scope — use full-cycle
@@ -115,11 +115,11 @@ roles:
     # короче наших сессий. Правка обратимая и наблюдаемая: пошли разваливающиеся длинные ходы →
     # вернуть xhigh, и это будет данными, а не спором. Относится к ключу Opus; у Sol ступень
     # своя (#214, основания — в комментарии над `roles:`).
     effort: {"claude-opus-5[1m]": high, gpt-5.6-sol: xhigh, gpt-5.6-luna: high, default: high}
     skills: [html-artifacts, codex-debate]
-    modules: [model-routing, research-method, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
+    modules: [model-routing, research-method, code-quality, git-workflow, worker-lifecycle, report-format, self-improvement, memory-search]
     can_spawn: ["*"]
     allow_unrouted_workers: false
     tg: {emoji: "🔄"}
     when: New feature with unknowns, large refactoring (5+ files), external integration, deep research (find out everything about X), empirical measurement / benchmarks, anything where wrong approach = wasted day
     not_for: Trivial bug fixes, config changes, one-line implementation from a clear spec
diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 99dea0580..59e2d103e 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -197,17 +197,40 @@ class TestDefaultRolesResolve:
         assert P.get_role(PIPELINE, "sub-orchestrator").modules == [
             "model-routing", "git-workflow", "orchestration", "worker-lifecycle",
             "background-jobs", "task-management", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "worker").modules == [
-            "git-workflow", "report-format", "self-improvement", "memory-search",
+            "code-quality", "git-workflow", "report-format", "self-improvement", "memory-search",
         ]
         assert P.get_role(PIPELINE, "full-cycle").modules == [
-            "model-routing", "research-method", "git-workflow", "worker-lifecycle",
+            "model-routing", "research-method", "code-quality", "git-workflow", "worker-lifecycle",
             "report-format", "self-improvement", "memory-search",
         ]
 
+    def test_code_quality_has_one_owner_and_reaches_both_working_roles(self):
+        """#prompt-cleanup: блок жил ДВУМЯ дословными копиями в roles/worker.md и
+        roles/full-cycle.md. Копия расходится молча, поэтому владелец теперь модуль.
+
+        Проверяются обе стороны: текст доезжает до рабочих ролей ровно один раз И его
+        больше нет в файлах ролей. Без второй половины тест зелёный и на возвращённой копии.
+        """
+        module = P.prompt_path(PIPELINE, "modules/code-quality.md").read_text().strip()
+        bullets = [ln.strip() for ln in module.splitlines() if ln.startswith("- ")]
+        assert len(bullets) >= 12, "модуль потерял пункты — якоря стали слабее"
+
+        for role in ("worker", "full-cycle"):
+            out = P.build_system_prompt(PIPELINE, role)
+            assert out.count(module) == 1, f"{role}: code-quality должен прийти ровно из модуля"
+            src = P.prompt_path(PIPELINE, f"roles/{role}.md").read_text()
+            assert "<code-quality>" not in src, (
+                f"roles/{role}.md: копия блока вернулась в файл роли"
+            )
+
+        for role in ("orchestrator", "sub-orchestrator"):
+            out = P.build_system_prompt(PIPELINE, role)
+            assert "<code-quality>" not in out, f"{role}: правила написания кода протекли"
+
     def test_model_routing_reaches_only_spawn_capable_roles(self):
         """Маршрутизация инлайнится ровно тем, кто умеет спавнить, и ровно из модуля (#203).
 
         Якоря берутся ИЗ САМОГО модуля, а не выписаны руками: проверка по тегу-обёртке
         и по паре фраз про Luna оставалась зелёной, когда в `base.md` копировали пункт
@@ -518,19 +541,59 @@ class TestRiskBasedReviewRouting:
             "The author never self-certifies risk or oracle strength",
             "**High-risk is evidence-derived, not author-declared.**",
             "**NO MODEL REVIEW**",
             "**one fresh Luna review**",
             "**one targeted Sol escalation**",
-            "**Sol review is mandatory regardless of size**",
-            "**targeted Opus cross-family review**",
-            "`cross-family verdict unavailable`",
+            "**Sol pass on a high-risk surface**",
             "**Docs / fact extraction**",
             "**One round by default.**",
         )
         for anchor in anchors:
             assert policy.count(anchor) == 1, f"canonical review contract lacks {anchor!r}"
 
+    def test_review_is_optional_and_has_no_substitute_reviewer(self):
+        """Решение юзера 19.08: ревью полезно, но НЕ обязательно, и заменять недоступный
+        Codex другой моделью запрещено — маршрут «поднять Opus вместо Codex» стоил четырёх
+        платных ревьюеров за один день.
+
+        Проверяются обе половины: новый контракт присутствует И старый отсутствует. Одна
+        половина без другой ложно-зелёная: текст можно дописать, не убрав обязательность,
+        и можно убрать маршрут замены, оставив floor, который заставит искать его заново.
+        """
+        policy = P.prompt_path(PIPELINE, "skills/codex-debate.md").read_text()
+        present = (
+            "**Ревью доступно, но не обязательно",
+            "Codex недоступен → ревью НЕ делается",
+            "не поднимать\nOpus, не спавнить ревьюера-агента",
+        )
+        for anchor in present:
+            assert policy.count(anchor) == 1, f"новый контракт ревью потерял {anchor!r}"
+        # Формулировка отчёта при недоступном Codex названа и в правиле, и в инструкции
+        # запуска — здесь проверяется наличие, а не единственность.
+        assert "`Review: none — Codex unavailable`" in policy, (
+            "не назван исход, который агент обязан записать вместо ревью"
+        )
+
+        # Обязательность и маршрут замены не должны вернуться ни в одной из форм,
+        # которые этот файл уже использовал.
+        forbidden = (
+            "mandatory",
+            "targeted Opus cross-family review",
+            "cross-family verdict unavailable",
+            "Opus запускается свежей reviewer-сессией",
+            "review route unavailable",
+        )
+        for stale in forbidden:
+            assert stale not in policy, f"вернулась обязательность/замена ревьюера: {stale!r}"
+
+        # И то же самое там, где правило реально исполняется: спавнит ревьюера оркестратор,
+        # а скилл он грузит отдельно — запрет обязан доехать в сам промпт.
+        out = P.build_system_prompt(PIPELINE, "orchestrator")
+        assert "you never spawn a\nreviewer agent as a substitute" in out, (
+            "оркестратор — тот, кто спавнит; без этой строки запрет ничем не принуждается"
+        )
+
     def test_canonical_skill_exposes_direct_luna_review_and_sol_default(self):
         policy = P.prompt_path(PIPELINE, "skills/codex-debate.md").read_text()
         assert 'codex_review(model="gpt5.6luna", ...)' in policy
         assert "backward-compatible default всегда Sol" in policy
         assert "`codex_review` — Sol-only" not in policy
### 0707d9257 #343: одно правило допуска по квоте, прежние квотные системы вырезаны

diff --git a/app/db.py b/app/db.py
index 390bb2e05..62f1e81f6 100644
--- a/app/db.py
+++ b/app/db.py
@@ -12,101 +12,10 @@ from pathlib import Path
 
 logger = logging.getLogger("db")
 
 _DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"
 
-_QUOTA_CONTROLLER_TABLE_COLUMNS = {
-    "quota_controller_decisions": (
-        "decision_id", "created_at", "mode", "source", "session_id", "turn_gen",
-        "task_id", "task_class", "model", "fast_mode", "critical_intent_id",
-        "policy_version", "regime_set_hash", "observation_at", "observation_json",
-        "decision_json", "legacy_decision_json",
-    ),
-    "quota_controller_outcomes": (
-        "decision_id", "terminal_event_id", "submitted_at", "ended_at", "settled_at",
-        "status", "concurrent_dispatches", "actual_json",
-    ),
-    "quota_controller_inflight_reservations": (
-        "decision_id", "bucket", "window_id", "reserved_pp", "state", "created_at",
-        "updated_at",
-    ),
-    "quota_controller_reserve_intents": (
-        "intent_id", "created_at", "deadline_at", "task_id", "logical_work_id",
-        "reason", "lane", "task_class", "model", "turn_count", "state", "revision",
-        "created_by",
-    ),
-    "quota_controller_evidence_sets": (
-        "evidence_id", "created_at", "dataset_start", "dataset_end", "policy_version",
-        "regime_set_hash", "source_digest", "prospective", "metrics_json",
-        "reasons_json", "eligible",
-    ),
-    # Порядок и состав ОБЯЗАНЫ совпадать с `_QUOTA_POLICY_TABLE_SQL` и со списком
-    # переносимых колонок в дрейф-починке — это три копии одного перечня, и
-    # расхождение любой пары ловится здесь громко (#314).
-    "quota_controller_policy": (
-        "lane", "threshold", "revision", "source", "reason", "updated_at",
-        "deficit_hours", "min_work_hours",
-    ),
-    "quota_controller_policy_audit": (
-        "audit_id", "actor", "created_at", "old_json", "new_json", "reason",
-        "revision", "action",
-    ),
-}
-
-_QUOTA_CONTROLLER_INDEXES = {
-    "idx_quota_controller_decisions_dispatch",
-    "idx_quota_controller_decisions_created",
-    "idx_quota_controller_inflight_bucket",
-    "idx_quota_controller_evidence_created",
-    "idx_quota_controller_policy_audit_created",
-}
-
-_QUOTA_CONTROLLER_TRIGGERS = {
-    "quota_controller_decisions_no_update",
-    "quota_controller_decisions_no_delete",
-    "quota_controller_decisions_no_replace",
-    "quota_controller_outcomes_no_update",
-    "quota_controller_outcomes_no_delete",
-    "quota_controller_outcomes_no_replace",
-    "quota_controller_evidence_no_update",
-    "quota_controller_evidence_no_delete",
-    "quota_controller_evidence_no_replace",
-    "quota_controller_policy_audit_no_update",
-    "quota_controller_policy_audit_no_delete",
-    "quota_controller_policy_audit_no_replace",
-}
-
-# Единственный текст DDL полосы: миграция пересобирает таблицу этим же
-# оператором, потому что страж схемы сверяет сохранённый CREATE дословно, а
-# ALTER TABLE ... RENAME записал бы в sqlite_master другой текст.
-_QUOTA_POLICY_TABLE_SQL = """
-        CREATE TABLE IF NOT EXISTS quota_controller_policy (
-            lane TEXT PRIMARY KEY CHECK (lane IN ('sol','luna','spark','claude')),
-            threshold REAL NOT NULL CHECK (threshold >= 0 AND threshold <= 100),
-            revision INTEGER NOT NULL CHECK (revision >= 1),
-            source TEXT NOT NULL,
-            reason TEXT NOT NULL,
-            updated_at TEXT NOT NULL,
-            -- Порог дефицита рабочих часов и окно применимости темпа (#314).
-            -- NULL = деградация по дефициту выключена; это и есть аварийный выключатель.
-            -- Отдельные колонки, а не переиспользование `threshold`: у того CHECK 0..100 —
-            -- инвариант ПРОЦЕНТА, и расширять его под часы значило бы его потерять.
-            deficit_hours REAL CHECK (deficit_hours IS NULL OR deficit_hours >= 0),
-            min_work_hours REAL CHECK (min_work_hours IS NULL OR min_work_hours >= 0)
-        )
-        """
-
-# Пороги совпадают с fallback-константами гейта (app/quota_gate.py
-# LANE_DEFAULT_THRESHOLDS); равенство закреплено тестом. Обоснование каждого числа —
-# там же, у констант: в манифесте пайплайна их больше нет (#329).
-QUOTA_POLICY_DEFAULTS = {"sol": 95.0, "luna": 98.0, "spark": 95.0, "claude": 90.0}
-QUOTA_POLICY_SOURCE = "temporary_static_override"
-QUOTA_POLICY_LABEL = "TEMPORARY STATIC OVERRIDE"
-
-_quota_controller_expected_sql: dict[tuple[str, str], str] | None = None
-
-
 def _resolve_db_path() -> Path:
     """Путь к БД: ORCHESTRA_DB_PATH из env (если задан) или дефолт data/orchestra.db.
 
     Позволяет разным worktree/веткам и тестам держать свою БД, не блокируя
     друг друга через SQLite-лок при параллельной работе.
@@ -119,373 +28,10 @@ def _resolve_db_path() -> Path:
 
 
 DB_PATH = _resolve_db_path()
 
 
-class RoutingPolicyRevisionMismatch(RuntimeError):
-    """The routing policy changed after the caller evaluated its decision."""
-
-
-class RoutingLatchSnapshotMismatch(RuntimeError):
-    """The durable latch set changed after the caller evaluated its decision."""
-
-
-def _create_quota_controller_schema(c: sqlite3.Connection) -> None:
-    """Create the shadow controller schema as one transactional unit."""
-    c.execute("BEGIN IMMEDIATE")
-    statements = (
-        """
-        CREATE TABLE IF NOT EXISTS quota_controller_decisions (
-            decision_id TEXT PRIMARY KEY,
-            created_at TEXT NOT NULL,
-            mode TEXT NOT NULL CHECK (mode IN ('shadow','advisory','enforce')),
-            source TEXT NOT NULL CHECK (source IN ('snapshot','dispatch','replay')),
-            session_id TEXT NOT NULL DEFAULT '',
-            turn_gen INTEGER,
-            task_id TEXT NOT NULL DEFAULT '',
-            task_class TEXT NOT NULL,
-            model TEXT NOT NULL,
-            fast_mode INTEGER NOT NULL CHECK (fast_mode IN (0,1)),
-            critical_intent_id TEXT,
-            policy_version INTEGER NOT NULL,
-            regime_set_hash TEXT NOT NULL,
-            observation_at TEXT,
-            observation_json TEXT NOT NULL CHECK (json_valid(observation_json)),
-            decision_json TEXT NOT NULL CHECK (json_valid(decision_json)),
-            legacy_decision_json TEXT NOT NULL CHECK (json_valid(legacy_decision_json))
-        )
-        """,
-        """
-        CREATE TABLE IF NOT EXISTS quota_controller_outcomes (
-            decision_id TEXT PRIMARY KEY
### af58227ee #346: #346: правило формата ответа юзеру — блок <user-answer-format> в роли оркестратора

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index eb01b9b92..3e2780e5c 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -377,10 +377,55 @@ class TestTelegramFormattingOwnership:
             assembled = P.build_system_prompt(PIPELINE, role)
             assert self.OPEN not in assembled, f"Telegram rules leaked into {role}"
             assert block not in assembled, f"Telegram rules leaked into {role}"
 
 
+class TestUserAnswerFormatOwnership:
+    """#346: формат ответа ЮЗЕРУ доезжает до роли, которая говорит с ним, и только до неё."""
+
+    OPEN = "<user-answer-format>"
+    CLOSE = "</user-answer-format>"
+    USER_ROLE = "orchestrator"
+    OTHER_ROLES = ("sub-orchestrator", "worker", "full-cycle")
+    # Разметочный шум (заборы, разделители таблиц) якорем быть не может: он есть в любом промпте.
+    NOISE = ("```", "|---|--:|--:|")
+
+    def _source_block(self) -> tuple[str, list[str]]:
+        source = P.prompt_path(PIPELINE, "roles/orchestrator.md").read_text(encoding="utf-8")
+        start = source.find(self.OPEN)
+        end = source.find(self.CLOSE, start)
+        assert start != -1 and end != -1, "User answer format section is missing from its owner"
+        block = source[start:end + len(self.CLOSE)]
+        clauses = [
+            line.strip() for line in block.splitlines()
+            if line.strip() and line.strip() not in self.NOISE
+        ]
+        assert len(clauses) >= 20, "User answer format section is unexpectedly short"
+        return block, clauses
+
+    def test_every_source_clause_reaches_the_assembled_user_prompt(self):
+        """Якоря даёт файл-источник, а не выписанные руками фразы."""
+        _block, clauses = self._source_block()
+        assembled = P.build_system_prompt(PIPELINE, self.USER_ROLE)
+        for clause in clauses:
+            assert clause in assembled, f"User answer format clause did not assemble: {clause!r}"
+
+    def test_user_answer_format_does_not_leak_to_non_user_roles(self):
+        block, _clauses = self._source_block()
+        assert self.OPEN in P.build_system_prompt(PIPELINE, self.USER_ROLE)
+        for role in self.OTHER_ROLES:
+            assembled = P.build_system_prompt(PIPELINE, role)
+            assert self.OPEN not in assembled, f"User answer format leaked into {role}"
+            assert block not in assembled, f"User answer format leaked into {role}"
+
+    def test_no_role_still_carries_the_withdrawn_no_tables_rule(self):
+        """Снятая формулировка не должна вернуться: она противоречит правилу «числа — в таблицу»."""
+        for role in (self.USER_ROLE, *self.OTHER_ROLES):
+            assembled = P.build_system_prompt(PIPELINE, role)
+            assert "Tables are hard to read on a phone" not in assembled, role
+
+
 # ── modules: инлайн переиспользуемых блоков после слоёв роли ────────────────
 
 class TestDefaultModulesInline:
     GIT_MARKER = "Each worker runs in an isolated"
     ORCH_MARKER = "## Role: Orchestrator"
### eac83b8aa #348: #348: шесть правил про поведение агентов перенесены из CLAUDE.md к владельцам в pipelines/

diff --git a/tests/test_default_pipeline.py b/tests/test_default_pipeline.py
index 3e2780e5c..e8e66ecd9 100644
--- a/tests/test_default_pipeline.py
+++ b/tests/test_default_pipeline.py
@@ -377,10 +377,65 @@ class TestTelegramFormattingOwnership:
             assembled = P.build_system_prompt(PIPELINE, role)
             assert self.OPEN not in assembled, f"Telegram rules leaked into {role}"
             assert block not in assembled, f"Telegram rules leaked into {role}"
 
 
+class TestBehaviourRulesLandedAtOwners:
+    """#348: шесть правил про поведение агентов переехали из CLAUDE.md к владельцам в pipelines/.
+
+    Каждая строка — правило: якорь в промпте, файл-владелец, роли-адресаты и снятая
+    формулировка из CLAUDE.md. Утечка проверяется по всем остальным ролям.
+    """
+
+    ALL_ROLES = ("orchestrator", "sub-orchestrator", "worker", "full-cycle")
+    ORCH = ("orchestrator", "sub-orchestrator")
+    SPAWNERS = ("orchestrator", "sub-orchestrator", "full-cycle")
+
+    RULES = (
+        ("Finished research is retold, not linked.",
+         "roles/orchestrator.md", ("orchestrator",), "Завершённый research пересказывай"),
+        ("Facts from a command arrive as a file, never retyped.",
+         "modules/worker-lifecycle.md", SPAWNERS, "требуй `cmd > path.txt 2>&1`"),
+        ("No barrier → name the LAST child as the collector",
+         "modules/orchestration.md", ORCH, "барьер `open_fan`"),
+        ("Two children check each other only across a VERBATIM overlap.",
+         "modules/worker-lifecycle.md", SPAWNERS, "пересекающиеся задания ради взаимной проверки"),
+        ("Plain text in your chat reaches the USER",
+         "base.md", ALL_ROLES, "plain text в чате = сообщение ЮЗЕРУ"),
+        ("A candidate you rule out on paper is not ruled out.",
+         "modules/research-method.md", ("full-cycle",), "Ресёрч ОТВЕРГАЕТ вариант"),
+    )
+
+    @pytest.mark.parametrize("anchor,owner,audience,_old", RULES)
+    def test_rule_text_lives_in_exactly_one_owner_file(self, anchor, owner, audience, _old):
+        """Владелец один: якорь есть в назначенном файле и больше нигде в промптах пайплайна."""
+        assert anchor in P.prompt_path(PIPELINE, owner).read_text(encoding="utf-8"), owner
+        root = P.prompt_path(PIPELINE, "base.md").parent
+        holders = [f.name for f in sorted(root.rglob("*.md"))
+                   if anchor in f.read_text(encoding="utf-8")]
+        assert holders == [Path(owner).name], f"{anchor!r} лежит в {holders}"
+
+    @pytest.mark.parametrize("anchor,owner,audience,_old", RULES)
+    def test_rule_reaches_its_audience_once(self, anchor, owner, audience, _old):
+        for role in audience:
+            assembled = P.build_system_prompt(PIPELINE, role)
+            assert assembled.count(anchor) == 1, f"{role}: {assembled.count(anchor)} копий {anchor!r}"
+
+    @pytest.mark.parametrize("anchor,owner,audience,_old", RULES)
+    def test_rule_does_not_leak_to_other_roles(self, anchor, owner, audience, _old):
+        for role in self.ALL_ROLES:
+            if role in audience:
+                continue
+            assert anchor not in P.build_system_prompt(PIPELINE, role), f"утечка в {role}: {anchor!r}"
+
+    @pytest.mark.parametrize("anchor,_owner,_audience,old", RULES)
+    def test_moved_rule_is_gone_from_claude_md(self, anchor, _owner, _audience, old):
+        """Правило про ПОВЕДЕНИЕ агента не должно остаться второй копией в CLAUDE.md."""
+        claude = Path(__file__).resolve().parents[1] / "CLAUDE.md"
+        assert old not in claude.read_text(encoding="utf-8"), old
+
+
 class TestUserAnswerFormatOwnership:
     """#346: формат ответа ЮЗЕРУ доезжает до роли, которая говорит с ним, и только до неё."""
 
     OPEN = "<user-answer-format>"
     CLOSE = "</user-answer-format>"
### eb9d6ce28 #349: #349: check_pipeline_manifest — якоря нового контракта ревью + числа внутри примера

diff --git a/scripts/check_pipeline_manifest.py b/scripts/check_pipeline_manifest.py
index 5fa0ac4ba..3694106ef 100755
--- a/scripts/check_pipeline_manifest.py
+++ b/scripts/check_pipeline_manifest.py
@@ -52,23 +52,35 @@ _REVIEW_POLICY_ANCHORS = (
     "The author never self-certifies risk or oracle strength",
     "**High-risk is evidence-derived, not author-declared.**",
     "**NO MODEL REVIEW**",
     "**one fresh Luna review**",
     "**one targeted Sol escalation**",
-    "**Sol review is mandatory regardless of size**",
-    "**targeted Opus cross-family review**",
-    "`cross-family verdict unavailable`",
+    # Ревью перестало быть обязательным, а замена недоступного Codex другой моделью
+    # запрещена (#346, решение юзера 19.08). Якоря снятого контракта заменены якорями
+    # нового: вычеркнуть их значило бы оставить проверку без утверждения на этом месте.
+    "**Ревью доступно, но не обязательно",
+    "Codex недоступен → ревью НЕ делается",
+    "Замену ревьюеру не искать",
     "**Docs / fact extraction**",
     "**One round by default.**",
 )
 _STALE_REVIEW_POLICY = (
     "Codex review MANDATORY for complex tasks",
     "Размер диффа основанием для пропуска ревью не является ни в каком случае",
     "Codex follows the worker role's review gate",
     "runs required Codex review",
     "Second opinion (Codex)",
     "Codex review the plan + tickets",
+    # Отрицательная половина #346: ни обязательность, ни маршрут «поднять Opus вместо
+    # Codex» не должны вернуться ни в один промпт — тот маршрут стоил четырёх платных
+    # ревьюеров за день. Совпадает со списком `forbidden` в
+    # tests/test_default_pipeline.py::test_review_is_optional_and_has_no_substitute_reviewer.
+    "review is mandatory regardless of size",
+    "targeted Opus cross-family review",
+    "cross-family verdict unavailable",
+    "Opus запускается свежей reviewer-сессией",
+    "review route unavailable",
 )
 
 
 def _review_policy_errors(
     root: Path,
@@ -135,31 +147,63 @@ def _review_policy_errors(
                     )
 
     return errors
 
 
+def _is_measured_claim(line: str) -> bool:
+    """Одно определение «строка утверждает замер» — для прозы и для содержимого примера."""
+    if _PROCEDURAL_VALUE.search(line):
+        return False
+    if not _MEASURED_VALUE.search(line):
+        return False
+    return bool(
+        _MEASURED_WORDS.search(line)
+        or re.search(r"(?i)\b(?:rounds?|раунд|diff|дифф|threshold|порог)\b", line)
+    )
+
+
 def _prompt_metric_errors(prompt_root: Path) -> list[str]:
-    """Require an inline source on empirical numeric claims, not all numbers."""
+    """Require an inline source on empirical numeric claims, not all numbers.
+
+    Fenced blocks are shown output, not assertions: a reference answer has to look like a
+    real answer, so its numbers stay bare instead of carrying a citation in every cell.
+    The block as a whole is still on the hook — an example running on invented numbers
+    teaches inventing them — so it must name its source somewhere inside (#349).
+    """
     errors: list[str] = []
     for md in sorted(prompt_root.rglob("*.md")):
+        fence_open = 0  # 0 = вне забора, иначе номер строки, которой забор открыт
+        fence_value = fence_source = False
         for line_no, line in enumerate(md.read_text().splitlines(), 1):
-            if _PROCEDURAL_VALUE.search(line):
+            if line.lstrip().startswith("```"):
+                if fence_open:
+                    if fence_value and not fence_source:
+                        rel = md.relative_to(prompt_root.parent)
+                        errors.append(
+                            f"{rel}:{fence_open}: example block shows measured numbers "
+                            f"without naming their source"
+                        )
+                    fence_open = 0
+                else:
+                    fence_open, fence_value, fence_source = line_no, False, False
                 continue
-            if _MEASURED_WORDS.search(line) and _MEASURED_VALUE.search(line):
-                if not _SOURCE_MARKER.search(line):
-                    rel = md.relative_to(prompt_root.parent)
-                    errors.append(
-                        f"{rel}:{line_no}: measured numeric claim lacks inline source marker"
-                    )
-            elif _MEASURED_VALUE.search(line) and re.search(
-                r"(?i)\b(?:rounds?|раунд|diff|дифф|threshold|порог)\b", line
-            ):
-                if not _SOURCE_MARKER.search(line):
-                    rel = md.relative_to(prompt_root.parent)
-                    errors.append(
-                        f"{rel}:{line_no}: measured numeric claim lacks inline source marker"
-                    )
+            if fence_open:
+                # Незакрытый забор проглотил бы остаток файла — итог считается после цикла.
+                fence_value = fence_value or _is_measured_claim(line)
+                fence_source = fence_source or bool(_SOURCE_MARKER.search(line))
+                continue
+            if _is_measured_claim(line) and not _SOURCE_MARKER.search(line):
+                rel = md.relative_to(prompt_root.parent)
+                errors.append(
+                    f"{rel}:{line_no}: measured numeric claim lacks inline source marker"
+                )
+        if fence_open and fence_value and not fence_source:
+            rel = md.relative_to(prompt_root.parent)
+            errors.append(
+                f"{rel}:{fence_open}: example block shows measured numbers "
+                f"without naming their source"
+            )
     return errors
 
 
 def _manifest_model_ids(data: dict) -> set[str]:
     """Versioned ids owned by the manifest — short aliases like ``opus`` are not copies."""