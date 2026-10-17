# Context for item-44

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/runtime_router.py b/app/runtime_router.py
index a588998dd..6af87a181 100644
--- a/app/runtime_router.py
+++ b/app/runtime_router.py
@@ -13,50 +13,62 @@ from typing import AsyncIterator, Awaitable, Callable, Literal, Mapping, Protoco
 
 from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
 
 from app.models import get_model_spec, resolve_model
 from app.quota_runway import RunwayVerdict, as_utc, next_weekly_reset, weekly_runway
 
 
 ROUTING_CONTRACT_VERSION = "routing-v2"
 ROUTING_POLICY_SCHEMA_VERSION = 1
 QUOTA_OBSERVATION_MAX_AGE_SECONDS = 300.0
 FIVE_HOUR_WINDOW_MINUTES = 300
 WEEKLY_WINDOW_MINUTES = 10080
 
 TaskClass = Literal[
     "worker_general",
     "orchestrator_free_text",
     "review",
     "continuation",
 ]
 CandidateState = Literal["normal", "reserve_only", "unavailable", "excluded"]
+TASK_CLASSES = frozenset(
+    {"worker_general", "orchestrator_free_text", "review", "continuation"}
+)
+# Not policy, not configurable. `review`: a cheap model missed a real double-count that Sol
+# caught, so final review never routes to the weak lane. `continuation`: switching models inside
+# the codex runtime resets the native session (`resume_across_models=False`), so moving running
+# work onto Spark would end the thing it claims to continue.
+SPARK_FORBIDDEN_CLASSES = frozenset({"review", "continuation"})
 PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
 
 # A lane is (quota bucket, runtime, model). Runtime alone cannot key selection: Spark shares the
 # `codex` runtime with Sol but spends a different bucket, so one field would answer "which pool"
 # and "which reviewer is independent" differently. Independence stays a runtime question, quota
 # stays a bucket question, and selection is keyed by lane.
 LANE_CLAUDE = "claude"
 LANE_CODEX = "codex"
 LANE_CODEX_SPARK = "codex_spark"
-LANE_PREFERENCE = (LANE_CODEX_SPARK, LANE_CODEX, LANE_CLAUDE)
+# Order is quality-first inside Codex: Sol takes the work while its bucket is healthy, and the
+# weaker Spark lane is reached only when Sol is not selectable. Spark-first would downgrade every
+# eligible task even on an idle pool — a silent quality loss, which is the one thing this feature
+# is forbidden to do. Claude stays last so Codex-first survives.
+LANE_PREFERENCE = (LANE_CODEX, LANE_CODEX_SPARK, LANE_CLAUDE)
 LANE_RUNTIMES = {LANE_CLAUDE: "claude", LANE_CODEX: "codex", LANE_CODEX_SPARK: "codex"}
 LANE_BUCKETS = {LANE_CLAUDE: "anthropic", LANE_CODEX: "codex", LANE_CODEX_SPARK: "codex_spark"}
 QUOTA_BUCKETS = frozenset(LANE_BUCKETS.values())
 
 
 class _StrictPolicyModel(BaseModel):
     model_config = ConfigDict(extra="forbid", frozen=True)
 
 
 class RoutingModelsV1(_StrictPolicyModel):
     claude: str
     codex: str | None = None
     spark: str | None = None
 
     @model_validator(mode="after")
     def validate_runtimes(self) -> "RoutingModelsV1":
         claude = resolve_model(self.claude)
         if get_model_spec(claude).runtime != "claude":
             raise ValueError("models.claude must resolve to the Claude runtime")
         object.__setattr__(self, "claude", claude)
@@ -103,58 +115,96 @@ class ClaudeQuotaPolicyV1(_StrictPolicyModel):
 class CodexQuotaPolicyV1(_StrictPolicyModel):
     normal_below_pct: float = Field(ge=0, le=100)
     unavailable_at_pct: float = Field(ge=0, le=100)
 
     @field_validator("*", mode="before")
     @classmethod
     def validate_number(cls, value: object) -> object:
         if isinstance(value, bool) or not isinstance(value, (int, float)):
             raise ValueError("quota threshold must be numeric")
         if not math.isfinite(float(value)):
             raise ValueError("quota threshold must be finite")
         return value
 
     @model_validator(mode="after")
     def validate_order(self) -> "CodexQuotaPolicyV1":
         if self.normal_below_pct >= self.unavailable_at_pct:
             raise ValueError("codex.normal_below_pct must be below unavailable_at_pct")
         return self
 
 
+class SparkQuotaPolicyV1(_StrictPolicyModel):
+    normal_below_pct: float = Field(ge=0, le=100)
+    unavailable_at_pct: float = Field(ge=0, le=100)
+    # Empty by default on purpose: Spark's real preconditions (file count, explicit AC, a test
+    # command) are not expressible by any server-owned task class, and asking the agent would put
+    # the decision back where this feature took it from. The lane stays visible and unused until
+    # an operator states which classes may use it.
+    eligible_classes: tuple[str, ...] = ()
+
+    @field_validator("normal_below_pct", "unavailable_at_pct", mode="before")
+    @classmethod
+    def validate_number(cls, value: object) -> object:
+        if isinstance(value, bool) or not isinstance(value, (int, float)):
+            raise ValueError("quota threshold must be numeric")
+        if not math.isfinite(float(value)):
+            raise ValueError("quota threshold must be finite")
+        return value
+
+    @model_validator(mode="after")
+    def validate_order_and_classes(self) -> "SparkQuotaPolicyV1":
+        if self.normal_below_pct >= self.unavailable_at_pct:
+            raise ValueError("spark.normal_below_pct must be below unavailable_at_pct")
+        for task_class in self.eligible_classes:
+            if task_class not in TASK_CLASSES:
+                raise ValueError(f"unknown task class {task_class!r} in spark.eligible_classes")
+            if task_class in SPARK_FORBIDDEN_CLASSES:
+                raise ValueError(
+                    f"spark.eligible_classes must not contain {task_class!r}"
+                )
+        return self
+
+
 class RoutingPolicyV1(_StrictPolicyModel):
     schema_version: Literal[1]
     revision: int = Field(ge=0)
     mode: Literal["manifest_default", "quota"]
     codex_access: Literal["all", "review_only", "off"] = "all"
     models: RoutingModelsV1 | None = None
     claude: ClaudeQuotaPolicyV1 | None = None
     codex: CodexQuotaPolicyV1 | None = None
+    spark: SparkQuotaPolicyV1 | None = None
 
     @field_validator("schema_version", "revision", mode="before")
     @classmethod
     def validate_integer(cls, value: object) -> object:
         if isinstance(value, bool) or not isinstance(value, int):
             raise ValueError("schema_version and revision must be integers")
         return value
 
     @model_validator(mode="after")
     def validate_activation(self) -> "RoutingPolicyV1":
+        # Document consistency is checked in every mode: thresholds for a lane that has no model
+        # are meaningless whether or not quota routing is active, and letting them sit in a
+        # manifest_default document would make switching modes fail later instead of at write.
+        if self.spark is not None and (self.models is None or self.models.spark is None):
+            raise ValueError("spark thresholds require models.spark")
         if self.mode == "manifest_default":
             return self
         if self.models is None or self.claude is None:
             raise ValueError("quota mode requires models and claude thresholds")
         if self.codex_access != "off" and (
             self.models.codex is None or self.codex is None
         ):
             raise ValueError(
                 "quota mode with Codex access requires models.codex and codex thresholds"
             )
         return self
 
     @classmethod
     def manifest_default(cls, revision: int = 0) -> "RoutingPolicyV1":
         return cls(
             schema_version=ROUTING_POLICY_SCHEMA_VERSION,
             revision=revision,
             mode="manifest_default",
         )
 
@@ -627,40 +677,41 @@ def evaluate_routing(
     access_reason = f"codex_access={policy.codex_access} excludes {request.task_class}"
     if codex_allowed:
         candidates[LANE_CODEX] = _codex_candidate(
             policy,
             providers.get(bucket_of(LANE_CODEX)),
             observed_at.get(bucket_of(LANE_CODEX)),
             bucket_of(LANE_CODEX) in terminal_limited_buckets,
             checked_at,
         )
     else:
         candidates[LANE_CODEX] = _candidate(
             LANE_CODEX,
             policy.models.codex or "",
             "excluded",
             access_reason,
         )
 
     if policy.models.spark is not None:
         candidates[LANE_CODEX_SPARK] = _spark_candidate(
             policy,
+            request,
             providers.get(bucket_of(LANE_CODEX_SPARK)),
             observed_at.get(bucket_of(LANE_CODEX_SPARK)),
             bucket_of(LANE_CODEX_SPARK) in terminal_limited_buckets,
             codex_allowed,
             access_reason,
             checked_at,
         )
 
     ordered = tuple(
         candidates[lane] for lane in LANE_PREFERENCE if lane in candidates
     )
     chosen, degraded = _choose_candidate(request, candidates)
     latches = tuple(
         candidate.window_id
         for candidate in ordered
         if candidate.lane == LANE_CLAUDE
         and candidate.state == "reserve_only"
         and candidate.window_id is not None
         and candidate.window_id not in latched_window_ids
     )
@@ -889,85 +940,110 @@ def _codex_candidate(
     utilization = weekly["utilization"]
     reset = _future_datetime(weekly.get("resets_at"), now)
     reset_at = reset.isoformat() if reset is not None else None
     if utilization >= policy.codex.unavailable_at_pct:
         state: CandidateState = "unavailable"
         reason = "codex_weekly_hard_stop"
     elif utilization >= policy.codex.normal_below_pct:
         state = "reserve_only"
         reason = "codex_weekly_reserve"
     else:
         state = "normal"
         reason = "codex_quota_normal"
     return _candidate(
         LANE_CODEX, model, state, reason,
         utilization=utilization, observed_at=timestamp, reset_at=reset_at,
     )
 
 
 def _spark_candidate(
     policy: RoutingPolicyV1,
+    request: RoutingInput,
     provider: object,
     observed_at: object,
     terminal_limited: bool,
     codex_allowed: bool,
     access_reason: str,
     now: datetime,
 ) -> CandidateVerdict:
     """Never select Spark; observe it exactly as widely as the Sol lane, never wider.
 
     Eligibility needs preconditions (file count, explicit AC, a test command) that no
     server-owned task class expresses, so the lane stays excluded until an operator opts in.
     When telemetry is read it is real and comes from `codex_spark`, never from `codex`.
 
     Access gating comes first and suppresses the observation, mirroring the Sol lane: under
     `codex_access=off`, or `review_only` outside a review, neither Codex lane is consulted and
     both report the access reason without telemetry. Observing one Codex lane while the other is
     access-excluded would make the candidate shape depend on the task class, which is exactly the
     non-determinism this router exists to remove.
     """
     assert policy.models is not None and policy.models.spark is not None
     model = policy.models.spark
     if not codex_allowed:
         return _candidate(LANE_CODEX_SPARK, model, "excluded", access_reason)
     if terminal_limited:
         return _candidate(LANE_CODEX_SPARK, model, "unavailable", "spark_terminal_limit")
     fresh, timestamp, reason = _fresh_provider(provider, observed_at, now)
     if not fresh:
         return _candidate(LANE_CODEX_SPARK, model, "unavailable", reason, observed_at=timestamp)
     weekly, error = _quota_window(provider, WEEKLY_WINDOW_MINUTES)
     if error:
         return _candidate(
             LANE_CODEX_SPARK, model, "unavailable", f"spark_weekly_{error}",
             observed_at=timestamp,
         )
     assert weekly is not None
     reset = _future_datetime(weekly.get("resets_at"), now)
-    return _candidate(
-        LANE_CODEX_SPARK,
-        model,
-        "excluded",
-        "spark_not_eligible",
-        utilization=weekly["utilization"],
-        observed_at=timestamp,
-        reset_at=reset.isoformat() if reset is not None else None,
+    utilization = weekly["utilization"]
+    shared = {
+        "utilization": utilization,
+        "observed_at": timestamp,
+        "reset_at": reset.isoformat() if reset is not None else None,
+        "detail": request.task_class,
+    }
+
+    def verdict(state: CandidateState, reason: str) -> CandidateVerdict:
+        return _candidate(LANE_CODEX_SPARK, model, state, reason, **shared)
+
+    if policy.spark is None:
+        return verdict("excluded", "spark_not_eligible")
+
+    # A session already running on Spark keeps its lane: eligibility governs where NEW work may
+    # be placed, never where running work lives. Evicting it would be the very session reset the
+    # `continuation` prohibition exists to prevent.
+    staying = (
+        request.task_class == "continuation"
+        and request.current_model is not None
+        and _lane_for_model(request.current_model) == LANE_CODEX_SPARK
     )
+    # No second runtime check for the forbidden classes: policy validation rejects them and every
+    # policy is read through it, so such a branch would be unreachable by construction. The rule
+    # has one owner — `SparkQuotaPolicyV1.validate_order_and_classes`.
+    if not staying and request.task_class not in policy.spark.eligible_classes:
+        return verdict("excluded", f"spark_not_eligible_for_{request.task_class}")
+
+    if utilization >= policy.spark.unavailable_at_pct:
+        return verdict("unavailable", "spark_weekly_hard_stop")
+    if utilization >= policy.spark.normal_below_pct:
+        return verdict("reserve_only", "spark_weekly_reserve")
+    return verdict("normal", "spark_quota_normal")
 
 
 def _bucket_for_model(model: str) -> str | None:
     """Model to quota bucket, resolved by the single existing owner of that mapping.
 
     `quota_gate` is scheduled for deletion in #187 T3; this mapping must MOVE with it rather
     than be deleted, otherwise the router loses the only definition of which pool a model spends.
     """
     from app.quota_gate import quota_bucket_for_model
 
     return quota_bucket_for_model(model)
 
 
 def _lane_for_model(model: str) -> str:
     bucket = _bucket_for_model(model)
     for lane, lane_bucket in LANE_BUCKETS.items():
         if lane_bucket == bucket:
             return lane
     raise ValueError(f"model {model!r} has no routable quota lane")
 
diff --git a/docs/tasks/216/codex-review-impl.md b/docs/tasks/216/codex-review-impl.md
index 64922717d..5cf6b9158 100644
--- a/docs/tasks/216/codex-review-impl.md
+++ b/docs/tasks/216/codex-review-impl.md
@@ -30,20 +30,80 @@ Verdict: STILL BROKEN as a staged change; otherwise approved once the Round 2 wo
 Раунд 2 снял единственный содержательный спор: ревьюер принял симметрию с полосой Sol как
 верный контракт и подтвердил, что потребителя, которому нужна телеметрия исключённой доступом
 полосы, не существует. Семантика не менялась — менялись мой докстринг и AC плана, оба
 переоценивали поведение.
 
 Второе замечание раунда 2 было практическим и верным: правки лежали в рабочем дереве, но не в
 индексе (`MM`/`AM`, а `plan.md` вовсе не проиндексирован), и коммит взял бы прежнюю версию.
 Проиндексировано полностью; проверено прогоном по одному содержимому индекса
 (`git stash --keep-index`) — **78 passed**, после чего рабочее дерево восстановлено.
 
 Вердикт записи: **approved once staged**, условие выполнено и проверено. Потолок раундов для кода
 (3) не исчерпан: второй раунд закрыл обе находки.
 
 ## Infrastructure note
 
 Оба раунда артефакт записался штатно — после хотфикса #217 (`7283e769`). Остаточный след прежней
 несовместимости виден в хвосте job'а: `Codex usage unaccounted: caller did not provide usage
 attribution` — мой MCP-процесс поднят до #215 и атрибуцию расхода не передаёт. Результат ревью
 это больше не уничтожает (ровно та развязка, которую просили в баг-репорте); недоучёт расхода
 уйдёт при следующем реконнекте.
+
+- Attempt 1 (T2) started 2026-08-12: review of the T2 diff (Spark opt-in, lane order, continuation carve-out).
+
+## Round (2026-08-12T07:12:29Z)
+
+Re-review status: FIXED. T1 staging issue is gone/merged.
+
+New findings:
+
+- suggestion: `RoutingPolicyV1.validate_activation` returns immediately for `manifest_default`, so `"spark thresholds require models.spark"` is not enforced in that mode. If the invariant is unconditional, move that check before the mode return. This does not currently cause wrong routing because manifest mode ignores quota blocks.
+
+- suggestion: Add focused tests showing a staying Spark continuation remains blocked by access gating, terminal limit, stale telemetry, and hard-stop threshold. The production ordering is correct, but the current continuation test would stay green if one of those guards later moved below the carve-out.
+
+Design ruling:
+
+- Sol-first lane preference is correct. Emergency mode explicitly admits `reserve_only`, so choosing reserve Sol over normal Spark preserves the stated quality-first policy. Review independence and Claude fallback still operate correctly; latch computation is lane-filtered and unaffected.
+- The `staying` carve-out is correct. It cannot bypass access, terminal, freshness, or threshold checks because all execute first. A Sol continuation cannot reach Spark because Spark remains ineligible for `continuation`.
+- Removing the duplicate runtime forbidden-class check is sound for production paths: stored and replacement policies both pass through `RoutingPolicyV1.model_validate*`. `model_construct()` could violate this, but no application path uses it.
+- Duplicate/order normalization for `eligible_classes` is unnecessary for routing: membership is the only semantic operation. Canonicalization would only reduce policy-document noise.
+
+Sight-verification quote:
+
+> “Spark adds capacity when the Sol pool is burning; it never becomes the cheap default.”
+
+Verdict: APPROVED — no blocking defect found.
+
+> ⚠ Codex usage unaccounted: caller did not provide usage attribution
+
+## T2 round 1 outcome (author note)
+
+Вердикт **APPROVED**, блокирующих находок нет. Обе suggestion приняты и реализованы в этом же
+тикете:
+
+1. **`spark thresholds require models.spark` проверялся только в quota-режиме** — `validate_activation`
+   выходит раньше при `manifest_default`. Инвариант про согласованность документа, а не про
+   активный режим, поэтому проверка поднята выше раннего `return`. Мутация «вернуть проверку под
+   ранний return» краснит новый тест.
+2. **Carve-out `staying` не должен становиться обходом.** Порядок в коде уже верный (доступ,
+   терминальный лимит, свежесть и пороги идут раньше), но тест continuation остался бы зелёным,
+   если бы гард однажды переехал ниже. Добавлены четыре случая: `codex_access=off`, терминальный
+   лимит бакета, протухшая телеметрия, hard stop по порогу. Мутация «staying обходит hard stop»
+   краснит их.
+
+Ревьюер также подтвердил три моих решения по существу: Sol-first порядок полос (в emergency
+`reserve_only` допустим, поэтому зарезервированный Sol честно выигрывает у свободного Spark),
+корректность carve-out (все гарды исполняются до него) и обоснованность удаления недостижимой
+рантайм-проверки (единственный обход — `model_construct()`, которым приложение не пользуется).
+Нормализация `eligible_classes` признана ненужной: единственная операция над множеством —
+проверка вхождения.
+
+### Зрячесть: подтверждена, но НЕ предъявленной цитатой
+
+Строки «Spark adds capacity when the Sol pool is burning; it never becomes the cheap default»
+**нет ни в одном файле** — это пересказ моего комментария, а не дословная цитата. По моему же
+критерию такая цитата зрячести не доказывает, и записывать «подтверждено цитатой» нельзя.
+
+Зрячесть тем не менее установлена другим путём: ревьюер назвал ранний `return` в
+`validate_activation` и `model_construct()` как единственный обход валидации — обе детали
+специфичны для текущего кода и в запросе ревью не упоминались. То есть код прочитан, а
+самопроверочная цитата собрана небрежно.
diff --git a/docs/tasks/216/plan.md b/docs/tasks/216/plan.md
index 53452536b..a6a7a0c4c 100644
--- a/docs/tasks/216/plan.md
+++ b/docs/tasks/216/plan.md
@@ -155,42 +155,49 @@ ratio         = utilization / (elapsed_share × 100)
 Отдельный `INSERT ... ON CONFLICT DO NOTHING` вне этой транзакции дал бы ровно те гонки, которые
 там уже закрыты: конкурент успел бы закоммитить решение, не увидев появившегося понижения, а сама
 строка храповика могла бы пережить своё решение или потеряться после него. Поэтому snapshot
 храповика читается до вычисления, входит в CAS вместе с latch-снимком и пишется тем же commit'ом.
 
 ### E. Spark не берёт ревью никогда — это решение, а не параметр
 
 Мера уже есть в правилах проекта: «Финальное ревью на Spark пропускает баги → в A/B Spark
 прошляпил реальный double-count, который поймал Sol → финальные ревью не роутить на дешёвую
 модель» (`CLAUDE.md`, раздел «Модели и лимиты»).
 
 Поэтому класс `review` не маршрутизируется на Spark **ни при какой провенансе** — ни при
 codex-реализации (там он ещё и не независим, A), ни при claude-реализации, ни при смешанной, ни
 при неизвестной. Это снимает целый класс двусмысленности: не нужно решать, «независим ли Spark от
 Claude», если он вообще не ревьюер.
 
 Второй жёсткий запрет — `continuation`: смена модели внутри рантайма `codex` обнуляет нативную
 сессию (`resume_across_models=False`, `app/runtime_registry.py:322`; `app/session.py:2604-2606`),
 то есть «продолжение» перестало бы им быть.
 
-Оба запрета — в коде и в валидации policy (`eligible_classes` с `review`/`continuation`
-отвергается при PUT), а не в документации.
+**Уточнено при реализации T2: запрет про РАЗМЕЩЕНИЕ, а не про присутствие.** Сессия, которая уже
+идёт на Spark, остаётся на своей полосе; eligibility решает, куда класть новую работу, и никогда
+не выселяет запущенную. Буквальное «continuation не выбирает Spark» вызывало бы у живой
+Spark-сессии переезд на другую модель — ровно тот сброс, ради предотвращения которого запрет и
+написан.
+
+Оба запрета живут в валидации policy (`eligible_classes` с `review`/`continuation` отвергается
+при PUT). Дублирующей рантайм-проверки НЕТ: policy всегда читается через валидацию, поэтому такая
+ветка недостижима, а недостижимый код у нас запрещён.
 
 ### F. Eligibility Spark по умолчанию пуста
 
 Известные ограничения Spark (`<model-routing>`): только текст, ≤2 файлов, явные AC, заданная
 тестовая команда, контекст <128k; не для ресёрча, архитектуры, картинок, безопасности. Ни одно из
 них не выражается четырьмя серверными классами, а спрашивать у агента — тот самый источник,
 который задача просит убрать (#198). Поэтому `spark.eligible_classes` по умолчанию пусто: полоса
 существует и наблюдается, но ни один класс туда не едет, пока оператор не включит явно.
 
 ### G. Контракт сериализации решения меняется явно
 
 `RoutingDecision.to_dict()` сериализует все поля рекурсивно (`runtime_router.py:189`), значит
 добавление `lane`/`selected_lane` меняет и `decision_json` в audit-таблице, и ответ `/explain`,
 даже когда Spark не настроен. Формулировка «поведение не меняется» для сериализованного контракта
 недостаточна.
 
 Решение: контракт **версионируется явно** — `ROUTING_CONTRACT_VERSION` (`runtime_router.py:20`,
 сейчас `"routing-v1"`) поднимается до `"routing-v2"`, а читатели старых audit-строк обязаны
 трактовать отсутствующий `lane` как `lane == runtime`. Ровно один owner чтения, и никакой
 догадливости на лету. `ROUTING_POLICY_SCHEMA_VERSION` при этом **не** меняется: добавляемые поля
@@ -251,46 +258,53 @@ policy опциональны и старый документ остаётся
     читается с `lane == runtime`. `ROUTING_POLICY_SCHEMA_VERSION` не меняется, старый policy-документ
     остаётся валидным.
   - Continuation находит полосу по модели, а не по рантайму: тест с настроенными обеими
     codex-полосами и `current_model=gpt-5.6-sol` выбирает `codex`, а не `codex_spark`.
   - Мутация «взять utilization Spark из бакета `codex`» краснит тест на фикстуре, где бакеты
     различаются (0% против 51%).
   - Spark не признаётся независимым ревьюером при `implementation_runtimes={"codex"}`.
 - blocked-by: none.
 
 ### T2 — Spark выбирается только по явному opt-in, с двумя запретами в коде
 
 - Files: `app/runtime_router.py`, `tests/test_runtime_router_spark.py`.
 - AC:
   - `SparkQuotaPolicyV1`: `normal_below_pct`, `unavailable_at_pct`, `eligible_classes`
     (по умолчанию пусто). Порядок порогов валидируется как у Codex.
   - Пустой `eligible_classes` или отсутствующий блок → Spark не выбирается никогда; поведение
     идентично T1.
   - `eligible_classes`, содержащий `review` или `continuation`, **отвергается при валидации
     policy** (`ValueError`), а не игнорируется молча.
   - При `eligible_classes=["worker_general"]` и состоянии «`codex` reserve_only, `codex_spark`
-    normal» выбирается полоса `codex_spark`; `reason` называет класс и бакет.
+    normal» выбирается полоса `codex_spark`; бакет виден в `lane`/`bucket`, класс — в `detail`.
+  - **При «`codex` normal, `codex_spark` normal» выбирается `codex`.** Spark добавляет ёмкость,
+    когда бакет Sol горит, и не становится дешёвым дефолтом; иначе это тихая деградация качества.
+  - Сессия, уже идущая на Spark, продолжает идти на Spark; сессия на Sol не переезжает на Spark
+    даже когда её собственный бакет мёртв.
+  - Пороги Spark читаются из его блока policy. Фикстура обязана задавать их ОТЛИЧНЫМИ от
+    codex-порогов, иначе подмена блока неотличима и мутация выживает (замерено).
   - `review` не выбирает Spark при провенансе `claude`, `codex`, смешанной и неизвестной — четыре
     отдельных теста (решение E).
   - Устаревшее/отсутствующее наблюдение бакета `codex_spark` даёт `unavailable` со своей причиной
     и не наследует свежесть бакета `codex`.
-  - Мутация каждого из двух жёстких запретов краснит свой тест.
+  - Мутации краснят свои тесты: порядок полос, снятие eligibility, приём запрещённого класса
+    валидацией, выселение живой Spark-сессии, чтение чужих порогов (оба).
 - blocked-by: T1.
 
 ### T3 — Состояние темпа: измерение и предупреждение, без понижения
 
 - Files: `app/runtime_router.py`, `tests/test_runtime_router_pace.py`; helper начала окна — у
   владельца `app/db.py`.
 - Предусловие: согласован общий helper начала окна по бакету (раздел C). Без него тикет не
   начинается.
 - AC:
   - `pace` — отображение «полоса → `PacePolicyV1`»; значения по умолчанию
     `ratio_alert=2.0`, `warm_up_hours=18`, `min_utilization_pp=15`, `action="warn"`.
   - `pace` для полосы `claude` отвергается при валидации policy (`ValueError`): владелец суждения
     о темпе Claude — метрика `D` из #186, второго быть не должно.
   - Состояние полосы: `ok` | `alert` | `no_data`. `no_data` при: недоступной идентичности окна,
     отсутствующем/нечисловом `window_minutes` или `utilization`, `elapsed_share` вне (0,1],
     `elapsed < warm_up_hours`, `utilization < min_utilization_pp`. Ни в одном случае ratio наружу
     не отдаётся.
   - Начало окна берётся из наблюдённых сбросов, **не** из `resets_at`. Тест: при неизменной
     истории снимков сдвиг `resets_at` на сутки не меняет ни ratio, ни состояние. Мутация «считать
     старт от `resets_at`» краснит этот тест.
diff --git a/docs/tasks/216/t2-report.md b/docs/tasks/216/t2-report.md
new file mode 100644
index 000000000..463b0e925
--- /dev/null
+++ b/docs/tasks/216/t2-report.md
@@ -0,0 +1,115 @@
+# #216 Фаза 3 — T2: Spark выбирается только по явному opt-in оператора
+
+## Результат
+
+Полоса `codex_spark` стала выбираемой, но лишь когда оператор явно перечислил классы задач в
+`spark.eligible_classes`. По умолчанию список пуст, и поведение неотличимо от T1: полоса видна,
+её телеметрия честная, работа туда не уходит.
+
+Поведение системы по-прежнему не изменилось: production-вызывающих у роутера нет, activation —
+cutover #187 T3.
+
+## Две поправки, которые вскрылись на реализации
+
+Обе меняют то, что было записано в плане, поэтому вынесены отдельно.
+
+### 1. Порядок полос развёрнут: `codex` → `codex_spark` → `claude`
+
+В T1 стояло `(codex_spark, codex, claude)`, и пока Spark не выбирался, порядок был ненаблюдаем.
+С включённым выбором он становится решением о качестве: Spark — слабая модель (в правилах проекта
+он ограничен текстом, ≤2 файлов, явными AC и заданной тестовой командой, а на финальном ревью
+однажды пропустил реальный double-count, который поймал Sol). Spark-first означал бы, что **любая**
+подходящая задача уезжает на слабую модель даже при свободном пуле Sol — тихая деградация
+качества, которую задача прямо запрещает.
+
+Теперь Spark добавляет ёмкость ровно тогда, когда бакет Sol не может взять работу. Ревьюер
+подтвердил и пограничный случай: в `emergency` допустим `reserve_only`, поэтому зарезервированный
+Sol честно выигрывает у свободного Spark — политика «качество раньше дешевизны» сохраняется и там.
+
+### 2. Запрет для `continuation` — про размещение, а не про присутствие
+
+Буквальное «continuation не выбирает Spark» выселяло бы сессию, которая **уже** идёт на Spark: её
+перенесли бы на другую модель, а это ровно тот сброс нативной сессии
+(`resume_across_models=False`), ради предотвращения которого запрет и написан. Запрет стал бы
+причиной своего же вреда.
+
+Правило: **eligibility решает, куда класть новую работу, и никогда не выселяет запущенную.**
+Carve-out срабатывает только когда класс — `continuation` и полоса текущей модели — `codex_spark`.
+
+Carve-out не является обходом: доступ, терминальный лимит бакета, свежесть телеметрии и пороги
+исполняются раньше него. Это закреплено четырьмя тестами (`codex_access=off`, терминальный лимит,
+протухший бакет, hard stop), потому что сам по себе порядок в коде — свойство, которое легко
+потерять при следующей правке.
+
+## Удалённый недостижимый код
+
+Рантайм-проверка `SPARK_FORBIDDEN_CLASSES` в `_spark_candidate` убрана: валидация policy отвергает
+`review` и `continuation` в `eligible_classes`, а policy всегда читается через
+`model_validate`/`model_validate_json`. Ветка была недостижима по построению, а недостижимый код у
+нас запрещён. Владелец правила один — `SparkQuotaPolicyV1.validate_order_and_classes`. Ревьюер
+подтвердил: единственный обход — `model_construct()`, которым приложение не пользуется.
+
+## Что изменилось в коде
+
+- `app/runtime_router.py` — `SparkQuotaPolicyV1` (`normal_below_pct`, `unavailable_at_pct`,
+  `eligible_classes` по умолчанию пуст); `RoutingPolicyV1.spark`; инвариант «пороги Spark требуют
+  `models.spark`» **во всех режимах**; `TASK_CLASSES` и `SPARK_FORBIDDEN_CLASSES` одним
+  определением вместо инлайн-литерала; квотные состояния полосы Spark; carve-out `staying`;
+  порядок `LANE_PREFERENCE`.
+- `tests/test_runtime_router_spark.py` — 22 новых теста.
+
+## Проверки
+
+- Целевая группа: **100 passed**, три прогона подряд.
+- Полный сьют сегодня **не запускался** по прямому указанию оркестратора (квота: Codex 57% при
+  пройденных 18% окна). T2 не трогает ничего за пределами роутера и его тестов.
+
+### Мутации (по одной, `cp` → мутация → тест → `mv` → `touch` → повтор)
+
+| мутация | итог |
+|---|---|
+| порядок полос обратно на Spark-first | red |
+| снятие проверки `eligible_classes` | red |
+| валидация принимает запрещённый класс | red |
+| живая Spark-сессия выселяется | red |
+| Spark читает `unavailable_at` из блока Sol | red |
+| Spark читает `normal_below` из блока Sol | red |
+| `staying` обходит hard stop | red |
+| инвариант `models.spark` возвращён под ранний `return` | red |
+
+Восемь из восьми; после каждого отката повтор зелёный.
+
+## Две методические находки, стоившие ошибок
+
+**Мутация выжила из-за фикстуры, а не из-за кода.** «Spark читает пороги Sol» прошла незамеченной,
+потому что в фикстуре у обеих полос стояло `90/95` — подмена блока была неотличима по результату.
+С порогами `50/70` против `90/95` обе мутации краснеют. Прежде чем объявлять мутацию выжившей,
+надо проверить, различает ли фикстура подменяемые величины вообще.
+
+**Откат мутации оставил прогон на мутанте.** `__pycache__` инвалидируется по (mtime, size), и
+откат правки той же длины вернул исходник, но Python продолжил исполнять байткод мутанта: `grep`
+маркера показывал 1, а тест падал. Здесь это дало ложно-красный; зеркальный случай даёт
+ложно-**зелёный**, то есть «тесты прошли» на непроверенном коде. В клаузу мутации добавлен `touch`
+и обязательный зелёный повтор после отката.
+
+## Codex review
+
+Один раунд, вердикт **APPROVED**, блокирующих находок нет. Обе suggestion приняты и реализованы
+здесь же (инвариант во всех режимах; четыре теста на то, что carve-out не обходит гарды).
+
+**Зрячесть подтверждена, но не предъявленной цитатой.** Строки, поданной как дословная, ни в одном
+файле нет — это пересказ моего комментария. Записывать «подтверждено цитатой» нельзя. Зрячесть
+установлена иначе: ревьюер назвал ранний `return` в `validate_activation` и `model_construct()` как
+единственный обход валидации — обе детали специфичны для текущего кода и в запросе не упоминались.
+
+## Breaking
+
+Нет. Схема policy расширена опциональным блоком `spark`; документ без него валиден (тест).
+`ROUTING_POLICY_SCHEMA_VERSION` не менялся. Порядок элементов в массиве `candidates` изменился
+(Sol теперь первым) — потребителей нет, роутер инертен.
+
+## Дальше
+
+T3/T4 — темп и храповик. Перед началом в план вносятся три поправки к контракту от `quota-policy`
+(предикат достоверности строки параметром, обязательная граница окна, последнее вхождение минимума)
+и три дыры в триггерах храповика.
diff --git a/docs/workers/quota-routing.md b/docs/workers/quota-routing.md
index c170d060f..0cd735d93 100644
--- a/docs/workers/quota-routing.md
+++ b/docs/workers/quota-routing.md
@@ -17,40 +17,56 @@
 ## Как мерить квоту, чтобы не соврать
 
 - Серия — `usage_snapshots.provider_usage` (JSON: `anthropic` / `codex` / `codex_spark`, каждый со
   списком `windows`). Ход с привязкой к проценту — `turn_usage.quota_primary_pct`.
 - `quota_primary_pct` **целочисленный**. Поэтому цену хода считать агрегатом по окну `ΔΣ/N`, а не
   дельтами по интервалам, и никогда не отбирать интервалы условием «где счётчик вырос».
 - Темп-метрика бесполезна в начале окна: первые 8–11 часов util=0 → ratio 0 читается как «всё
   спокойно» ровно перед стеной. Нужен warm-up ≥18 ч.
 
 ## `codex_review` сказал FAILED — ревью могло состояться
 
 Сначала `cat /tmp/codex_review_<worker>_<slug>.rc`. Ноль означает, что Codex отработал, а упал
 враппер записи артефакта, и текст цел в `/tmp/codex_review_<worker>_<slug>.jsonl` — вытащить
 блоками `item.type == "agent_message"`. Дважды за 12.08 так восстановил оба раунда ревью плана
 (#216), иначе сгорело бы ~300K токенов Codex на раунд и оба вердикта.
 
 Побочное: если враппер умер, сессия НЕ попадает в `docs/tasks/<id>/codex_sessions.json`, поэтому
 `resume=True` молча начнёт новую — находки прошлого раунда надо пересказать в `context`, иначе
 ревьюер их не помнит.
 
+## После отката мутации — `touch` файла, иначе прогон идёт по мутанту
+
+`__pycache__` инвалидируется по (mtime, size). Откат мутации той же длины возвращает исходник, но
+Python берёт байткод МУТАНТА. Поймал 12.08 в #216 T2: `grep` маркера показывал 1, а тест падал —
+и это ещё повезло, потому что зеркальный случай даёт ЛОЖНО-ЗЕЛЁНЫЙ прогон на мутанте, то есть
+«тесты прошли» при непроверенном коде.
+
+Клауза мутации целиком: `cp F F.bak` → мутация → тест → `mv F.bak F` → **`touch F`** → повтор
+теста. Зелёный повтор после `touch` — часть проверки, а не формальность.
+
+## Мутацию видно только на РАЗЛИЧАЮЩЕЙ фикстуре
+
+Мутация «Spark читает пороги Sol» выжила, потому что в фикстуре у обоих стояло 90/95 — прочитать
+чужое было неотличимо. Развёл 50/70 против 90/95, мутация покраснела. Общее: прежде чем считать
+мутацию выжившей из-за кода, проверь, различает ли фикстура подменяемые величины вообще.
+
 ## Полный прогон с `-x` прячет мой же долг
 
 `pytest -x` останавливается на первом падении, и если первыми падают чужие тесты, до своих не
 доходит. Так `test_route_surface_snapshot` был красным в `main` с мержа #187 T1 (добавил 3 роута,
 не обновил `tests/route_surface_snapshot.json`) — два моих «полных» прогона его не видели.
 **Финальный прогон перед сдачей — без `-x`**, иначе «остальное зелёное» ничем не подтверждено.
 
 ## Перед тикетом на «подключение» — грепни чужие планы
 
 `grep -n "Files:" docs/tasks/*/plan.md` по файлам, которые собираешься трогать. В #216 я написал
 два тикета (обвязка спавна + правка `base.md`), и оба уже стояли в списке файлов #187 T3 — то есть
 я планировал второго владельца одного решения. Поймало ревью, не я.
 
 ## Урок, который стоил blocking-находки на ревью (12.08, #216)
 
 Я сослался на СВОЮ же реализацию (#187 T1) как на готовый примитив — «класс задачи приходит из
 доверенного серверного entrypoint». В коде был только валидируемый enum: провенанс не
 устанавливался, production-вызывающих не было вовсе, потому что T1 намеренно инертен.
 
 **Правило для себя: пишешь «в системе уже есть X», опираясь на собственный прошлый тикет →
diff --git a/tests/test_runtime_router_spark.py b/tests/test_runtime_router_spark.py
index c20da6e2b..d397be38e 100644
--- a/tests/test_runtime_router_spark.py
+++ b/tests/test_runtime_router_spark.py
@@ -283,20 +283,236 @@ def test_decision_contract_is_versioned_and_pins_the_lane_shape():
     }
     for item in payload["candidates"]:
         assert item["bucket"] and item["runtime"]
 
 
 def test_old_policy_document_without_spark_stays_valid():
     document = _policy(spark=None).model_dump_json(exclude_none=True)
     restored = RoutingPolicyV1.model_validate_json(document)
 
     assert restored.models is not None
     assert restored.models.spark is None
     assert restored.schema_version == 1
 
 
 class _PolicyOnlyStore:
     def __init__(self, policy):
         self._policy = policy
 
     def policy_document(self):
         return self._policy.model_dump_json(exclude_none=True)
+
+
+# --- T2: Spark becomes selectable, but only by explicit operator opt-in -------------------
+
+def _spark_policy(*, eligible=("worker_general",), normal=90, stop=95, access="all"):
+    payload = {
+        "schema_version": 1,
+        "revision": 1,
+        "mode": "quota",
+        "codex_access": access,
+        "models": {
+            "claude": "claude-opus-5[1m]",
+            "codex": "gpt-5.6-sol",
+            "spark": SPARK_MODEL,
+        },
+        "claude": {
+            "alert_deficit_hours": 14,
+            "weekly_unavailable_pct": 95,
+            "weekly_min_remaining_pp": 0.3,
+            "five_hour_unavailable_pct": 95,
+        },
+        "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
+        "spark": {
+            "normal_below_pct": normal,
+            "unavailable_at_pct": stop,
+            "eligible_classes": list(eligible),
+        },
+    }
+    return RoutingPolicyV1.model_validate(payload)
+
+
+@pytest.mark.parametrize("forbidden", ["review", "continuation"])
+def test_forbidden_classes_are_rejected_when_the_policy_is_written(forbidden):
+    with pytest.raises(ValidationError, match=f"must not contain '{forbidden}'"):
+        _spark_policy(eligible=(forbidden,))
+
+
+def test_unknown_eligible_class_is_rejected_rather_than_ignored():
+    with pytest.raises(ValidationError, match="unknown task class"):
+        _spark_policy(eligible=("worker_genral",))
+
+
+def test_spark_thresholds_without_a_spark_model_are_rejected():
+    with pytest.raises(ValidationError, match="spark thresholds require models.spark"):
+        RoutingPolicyV1.model_validate(
+            {
+                "schema_version": 1,
+                "revision": 1,
+                "mode": "quota",
+                "models": {"claude": "claude-opus-5[1m]", "codex": "gpt-5.6-sol"},
+                "claude": {
+                    "alert_deficit_hours": 14,
+                    "weekly_unavailable_pct": 95,
+                    "weekly_min_remaining_pp": 0.3,
+                    "five_hour_unavailable_pct": 95,
+                },
+                "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
+                "spark": {"normal_below_pct": 90, "unavailable_at_pct": 95},
+            }
+        )
+
+
+def test_spark_threshold_order_is_validated():
+    with pytest.raises(ValidationError, match="normal_below_pct must be below"):
+        _spark_policy(normal=95, stop=90)
+
+
+def test_empty_eligible_classes_keeps_spark_unselectable():
+    decision = _decide(_spark_policy(eligible=()))
+    spark = _lane(decision, LANE_CODEX_SPARK)
+
+    assert spark.state == "excluded"
+    assert spark.reason == "spark_not_eligible_for_worker_general"
+    assert decision.selected_lane == LANE_CODEX
+
+
+def test_healthy_sol_keeps_the_work_even_when_spark_is_eligible_and_free():
+    """The invariant that stops this feature from being a silent downgrade.
+
+    Spark is the weaker lane. It exists to add capacity when the Sol bucket is burning, not to
+    become a cheaper default: with both lanes normal the work stays on Sol.
+    """
+    decision = _decide(_spark_policy(), _observation(codex=10, spark=0))
+
+    assert decision.selected_lane == LANE_CODEX
+    assert _lane(decision, LANE_CODEX_SPARK).state == "normal"
+
+
+def test_spark_takes_eligible_work_once_the_sol_bucket_is_reserved():
+    decision = _decide(_spark_policy(), _observation(codex=91, spark=0))
+    spark = _lane(decision, LANE_CODEX_SPARK)
+
+    assert _lane(decision, LANE_CODEX).state == "reserve_only"
+    assert decision.selected_lane == LANE_CODEX_SPARK
+    assert decision.selected_model == SPARK_MODEL
+    assert spark.reason == "spark_quota_normal"
+    assert spark.bucket == "codex_spark"
+    assert spark.detail == "worker_general"
+
+
+@pytest.mark.parametrize(
+    "provenance",
+    [frozenset({"claude"}), frozenset({"codex"}), frozenset({"claude", "codex"}), frozenset()],
+)
+def test_review_never_reaches_spark_whatever_wrote_the_code(provenance):
+    decision = _decide(
+        _spark_policy(),
+        _observation(codex=91, spark=0),
+        request=RoutingInput(task_class="review", implementation_runtimes=provenance),
+    )
+    spark = _lane(decision, LANE_CODEX_SPARK)
+
+    assert spark.state == "excluded"
+    assert spark.reason == "spark_not_eligible_for_review"
+    assert decision.selected_lane != LANE_CODEX_SPARK
+
+
+def test_a_session_already_on_spark_keeps_its_lane():
+    """Eligibility places NEW work; it never evicts running work.
+
+    `continuation` can never be opted in, so a naive reading would move a live Spark session onto
+    another model — which resets the native session, the exact harm the prohibition prevents.
+    """
+    decision = _decide(
+        _spark_policy(),
+        _observation(codex=10, spark=0),
+        request=RoutingInput(task_class="continuation", current_model=SPARK_MODEL),
+    )
+
+    assert decision.selected_lane == LANE_CODEX_SPARK
+    assert decision.selected_model == SPARK_MODEL
+    assert _lane(decision, LANE_CODEX_SPARK).reason == "spark_quota_normal"
+
+
+def test_a_sol_session_is_never_moved_onto_spark_when_its_own_bucket_dies():
+    decision = _decide(
+        _spark_policy(),
+        _observation(codex=99, spark=0),
+        request=RoutingInput(task_class="continuation", current_model="gpt-5.6-sol"),
+    )
+
+    assert _lane(decision, LANE_CODEX).state == "unavailable"
+    assert _lane(decision, LANE_CODEX_SPARK).state == "excluded"
+    assert decision.selected_lane != LANE_CODEX_SPARK
+
+
+@pytest.mark.parametrize(
+    ("utilization", "state", "reason"),
+    [(10, "normal", "spark_quota_normal"),
+     (60, "reserve_only", "spark_weekly_reserve"),
+     (80, "unavailable", "spark_weekly_hard_stop")],
+)
+def test_spark_reads_its_own_thresholds(utilization, state, reason):
+    """Spark thresholds are deliberately unlike Sol's (50/70 against 90/95).
+
+    With both set to the same numbers the assertion cannot tell which policy block was read, and
+    a mutation swapping `policy.spark` for `policy.codex` survives — measured, not assumed.
+    """
+    decision = _decide(
+        _spark_policy(normal=50, stop=70),
+        _observation(codex=91, spark=utilization),
+    )
+    spark = _lane(decision, LANE_CODEX_SPARK)
+
+    assert (spark.state, spark.reason) == (state, reason)
+
+
+def test_spark_thresholds_require_a_model_in_manifest_mode_too():
+    """The invariant is about document consistency, so it cannot depend on the active mode."""
+    with pytest.raises(ValidationError, match="spark thresholds require models.spark"):
+        RoutingPolicyV1.model_validate(
+            {
+                "schema_version": 1,
+                "revision": 1,
+                "mode": "manifest_default",
+                "spark": {"normal_below_pct": 50, "unavailable_at_pct": 70},
+            }
+        )
+
+
+@pytest.mark.parametrize(
+    ("case", "expected_state", "expected_reason"),
+    [
+        ("access_off", "excluded", "codex_access=off excludes continuation"),
+        ("terminal", "unavailable", "spark_terminal_limit"),
+        ("stale", "unavailable", None),
+        ("hard_stop", "unavailable", "spark_weekly_hard_stop"),
+    ],
+)
+def test_a_staying_spark_session_is_still_subject_to_every_guard(
+    case, expected_state, expected_reason
+):
+    """The carve-out must not become a bypass.
+
+    Ordering in the code puts access, terminal, freshness and thresholds ahead of `staying`.
+    Without these cases the continuation test would stay green if a guard were ever moved below
+    the carve-out, which would let a dead or unobserved bucket keep taking work.
+    """
+    policy = _spark_policy(normal=50, stop=70, access="off" if case == "access_off" else "all")
+    observation = _observation(codex=10, spark=80 if case == "hard_stop" else 0)
+    if case == "stale":
+        observation["observed_at_by_provider"]["codex_spark"] = NOW.timestamp() - 10_000
+    terminal = frozenset({"codex_spark"}) if case == "terminal" else frozenset()
+
+    decision = _decide(
+        policy,
+        observation,
+        request=RoutingInput(task_class="continuation", current_model=SPARK_MODEL),
+        terminal_limited_buckets=terminal,
+    )
+    spark = _lane(decision, LANE_CODEX_SPARK)
+
+    assert spark.state == expected_state
+    if expected_reason is not None:
+        assert spark.reason == expected_reason
+    assert decision.selected_lane != LANE_CODEX_SPARK


## Later history of the touched files on main (after this commit)

3 later commits touch these paths; the first 40 (oldest first):
7bf04a652 2026-08-12 #216: #216: план T3/T4 — согласованный контракт начала окна и дыры в храповике
0707d9257 2026-08-19 #343: одно правило допуска по квоте, прежние квотные системы вырезаны
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 7bf04a652 #216: #216: план T3/T4 — согласованный контракт начала окна и дыры в храповике

diff --git a/docs/tasks/216/plan.md b/docs/tasks/216/plan.md
index a6a7a0c4c..ccbd65027 100644
--- a/docs/tasks/216/plan.md
+++ b/docs/tasks/216/plan.md
@@ -105,15 +105,59 @@ policy и порогами: `RuntimeRouter → legacy quota_gate → spawn`. К
 Настоящая граница окна наблюдаема: за всю историю счётчик Codex падал 3 раза, и все падения
 резкие (100→0, 26→0, 87→0). Значит начало окна — начало последнего монотонного отрезка в
 `usage_snapshots`, ровно та же задача, которую #186 уже решил для Claude
 (`db.runway_window_start_pct`, `app/db.py:2197`, порог падения 5 pp, обоснование в его докстринге).
 
-**Владелец у этой логики должен остаться один.** Поэтому T3 начинается не с кода, а с запроса к
-`quota-policy`: обобщить их helper на произвольный бакет (`bucket`, порог падения параметром)
-вместо второй копии у меня. Второй экземпляр «где начинается окно» — ровно тот дубль, от которого
-нас предостерегали. Если владелец откажется — тикет блокируется и уходит к оркестратору, а не
-обходится своей копией.
+**Владелец у этой логики один, и это согласовано.** `quota-policy` передал `app/db.py` и
+подтвердил: общая реализация становится владельцем, а `runway_window_start_pct(reset_at)` —
+тонкой обёрткой над ней. Второй экземпляр «где начинается окно» не заводится.
+
+Согласованный контракт (замеры — его, на копии живой БД):
+
+```python
+def provider_window_start_pct(
+    bucket: str,                            # "codex" | "codex_spark" | "anthropic"
+    *,
+    since: datetime,                        # ОБЯЗАТЕЛЬНО, см. ниже
+    drop_pp: float,                         # падение, считающееся обнулением счётчика
+    is_trustworthy: Callable[[Row], bool],  # пригодность строки — своя у каждого бакета
+) -> tuple[float, str] | None
+```
+
+Три вещи, каждая из которых была бы тихим дефектом, если взять контракт наивно:
+
+1. **Предикат достоверности строки — параметр, а не общее правило.** Фильтр
+   `seven_day_resets_at != ''` у #186 не гигиена, а заплатка под #150 в бакете `anthropic`
+   (70 строк с фальшивыми нулями). На codex-строках он режет по признаку ЧУЖОГО бакета:
+   **418 из 2570 снимков (16.3%)** имеют пустой `seven_day_resets_at`, и это говорит лишь о том,
+   что молчал anthropic. Сделать фильтр общим — потерять 16% своей истории; убрать — вернуть #150
+   соседу. Для codex предикат: в `provider_usage` присутствует `<bucket>.windows[…].utilization`.
+2. **Граница окна (`since`) обязательна.** У #186 запрос ограничен `[reset_at − 7d, reset_at)`,
+   поэтому пропущенный сброс безвреден. У меня единственная граница — само падение, а падений за
+   всю историю три, и между вторым и третьим **51 час**. Если сброс не наблюдаем (счётчик стоял на
+   нуле или рос монотонно через него), «последний монотонный отрезок» молча накрывает два окна:
+   база занижена, темп завышен, понижение срабатывает раньше срока. Предохранитель, сам создающий
+   аварию. Заодно снимает полный скан 9049 строк на каждом решении.
+3. **Минимум отрезка — брать ПОСЛЕДНЕЕ вхождение, и обоснование #186 сюда не переносится.**
+   У них выбор «первое против последнего» стоил <1% темпа, поэтому назван дешёвым. На моих данных
+   он двигает базу на **3 ч 16 мин**: отрезок начинается 11.08 00:00:25, а минимум 0 держится до
+   03:16:29 (357 точек). В знаменателе «пройденная доля окна» это не округление. Направление
+   ошибки то же — завышает темп, то есть отказ громкий, — но цифра моя, а не их.
+
+Переносится как есть: минимум отрезка, а не первая точка; граница отрезка по падению от МАКСИМУМА
+отрезка, а не от соседа (спуск мелкими шагами попарным сравнением не виден); переякоривание внутри
+запроса; `None` при молчании источника и честный `0` на свежем окне.
+
+**Обязательно к переносу: `ORDER BY ts ASC, id ASC`.** Второй ключ не косметика — у снимков с
+совпадающим `ts` порядок иначе не определён, и пара `100 → 0` читается как `0 → 100`, то есть
+сброс исчезает. Такие пары в данных есть.
+
+**Порог применимости обязателен из-за кванта.** `codex.primary` квантован в целые проценты
+(2558 точек, 88 уникальных значений, все целые), поэтому при малой утилизации
+`utilization / пройденная доля` — шум кванта, а не темп. Это ровно роль `MIN_WORK_HOURS_FOR_PACE`
+у #186. И отбирать интервалы условием «числитель вырос» нельзя: это отбор по исходу, у соседа он
+завышал результат на 60–150%.
 
 Пока идентичность окна недоступна (нет истории, обнаружен дрейф, бакет молчит) — состояние
 `no_data`, и никакой ratio наружу не публикуется. Формула при известном старте:
 
 ```
@@ -215,13 +259,13 @@ policy опциональны и старый документ остаётся
 ### Новые
 - `tests/test_runtime_router_spark.py`, `tests/test_runtime_router_pace.py`.
 - `docs/tasks/216/report.md`, `docs/tasks/216/measurements/`.
 
 ### Требуют чужого решения до начала работы
-- `app/db.py` — helper начала окна (C), таблица храповика темпа и расширение
-  `commit_runtime_routing_decision` под общий CAS (D). Владелец сейчас `quota-policy` (#186).
-  **Без явной передачи или их правки на своей стороне T3/T4 не начинаются.**
+- `app/db.py` — **передан 12.08**, владелец теперь я: общий `provider_window_start_pct` (C),
+  сведение `runway_window_start_pct` к обёртке, таблица храповика темпа и расширение
+  `commit_runtime_routing_decision` под общий CAS (D).
 - `pipelines/default/prompts/base.md` — уходит в #187 T3 вместе с остальной обвязкой.
 
 ### Не трогать
 - `app/manager.py`, `app/session.py`, `app/pipeline.py` — за #214; подключение к ним — #187 T3.
 - `app/quota_runway.py`, `app/tg_bridge.py` — за #186.
@@ -290,14 +334,13 @@ policy опциональны и старый документ остаётся
     валидацией, выселение живой Spark-сессии, чтение чужих порогов (оба).
 - blocked-by: T1.
 
 ### T3 — Состояние темпа: измерение и предупреждение, без понижения
 
-- Files: `app/runtime_router.py`, `tests/test_runtime_router_pace.py`; helper начала окна — у
-  владельца `app/db.py`.
-- Предусловие: согласован общий helper начала окна по бакету (раздел C). Без него тикет не
-  начинается.
+- Files: `app/runtime_router.py`, `app/db.py` (общий `provider_window_start_pct` + сведение
+  `runway_window_start_pct` к обёртке), `tests/test_runtime_router_pace.py`.
+- Предусловие снято: `app/db.py` передан, контракт согласован (раздел C).
 - AC:
   - `pace` — отображение «полоса → `PacePolicyV1`»; значения по умолчанию
     `ratio_alert=2.0`, `warm_up_hours=18`, `min_utilization_pp=15`, `action="warn"`.
   - `pace` для полосы `claude` отвергается при валидации policy (`ValueError`): владелец суждения
     о темпе Claude — метрика `D` из #186, второго быть не должно.
@@ -306,27 +349,49 @@ policy опциональны и старый документ остаётся
     `elapsed < warm_up_hours`, `utilization < min_utilization_pp`. Ни в одном случае ratio наружу
     не отдаётся.
   - Начало окна берётся из наблюдённых сбросов, **не** из `resets_at`. Тест: при неизменной
     истории снимков сдвиг `resets_at` на сутки не меняет ни ratio, ни состояние. Мутация «считать
     старт от `resets_at`» краснит этот тест.
+  - `provider_window_start_pct` реализует контракт раздела C целиком: обязательный `since`,
+    предикат достоверности параметром, последнее вхождение минимума, `ORDER BY ts ASC, id ASC`.
+    Отдельные тесты: (а) снимок без `since` не компилируется в вызов — параметр обязателен;
+    (б) пропущенный сброс за пределами `since` не втягивает предыдущее окно в отрезок;
+    (в) codex-строки с пустым `seven_day_resets_at` НЕ отбрасываются (иначе теряется 16.3%
+    истории), а anthropic-строки с ним — отбрасываются;
+    (г) две строки с одинаковым `ts` и парой `100 → 0` читаются как сброс, а не как рост —
+    мутация «убрать `id ASC`» краснит именно её.
+  - `runway_window_start_pct(reset_at)` после сведения к обёртке даёт те же результаты, что до
+    правки: тест сравнивает выдачу на фикстуре #186 до и после.
+  - Порог применимости по кванту: при утилизации ниже `min_utilization_pp` состояние `no_data`,
+    потому что у `codex.primary` целые проценты и отношение при малых значениях — шум кванта.
   - При `action="warn"` выбранный кандидат при `alert` **идентичен** выбранному при `ok` — тест
     сравнивает два решения на входах, отличающихся только темпом.
   - Реплей трёх восстановленных окон из `research.md` даёт зафиксированные там состояния: окна
     08-08 20:36 и 08-11 00:00 → `alert` не ранее +18 ч; окно 08-08 05:55→20:31 → `no_data`
     (короче warm-up). Числа берутся из файла замеров, не подгоняются.
-- blocked-by: T1; передача `app/db.py` или правка helper'а владельцем.
+- blocked-by: T1.
 
 ### T4 — Понижение по темпу с храповиком (только при `action="degrade"`)
 
 - Files: `app/runtime_router.py`, `app/db.py` (таблица храповика), тесты.
 - AC:
   - `pace.<lane>.degrade_to_lane` — обязательное поле при `action="degrade"`, валидируется: полоса
     существует в policy, не равна исходной, у неё свой бакет. Отсутствие/самоссылка → `ValueError`
     при PUT, а не выбор «чего-нибудь» в рантайме.
-  - Понижение фиксируется durable-строкой (полоса, идентичность окна); `UPDATE` и `DELETE`
-    запрещены триггерами; прямой `DELETE` даёт `IntegrityError` (тест бьёт по SQL, а не через свой
-    Python).
+  - Понижение фиксируется durable-строкой (полоса, идентичность окна). **Заявление «откат
+    запрещён СХЕМОЙ» проверяется шестью прямыми SQL на копии живой базы и шестью
+    `IntegrityError`**, а не через свои же функции: `quota-policy` делал это заявление четырежды и
+    четырежды был неправ. Три известные дыры, каждая со своим тестом:
+    - `INSERT OR REPLACE` **не** ловится `BEFORE DELETE`: REPLACE удаляет строку сам, а
+      delete-триггеры на этом пути не выполняются при выключенном `PRAGMA recursive_triggers`
+      (по умолчанию выключен) → ловить на `BEFORE INSERT`, где старая строка ещё видна, и держать
+      условие УЗКИМ, иначе триггер сорвёт собственный upsert;
### 0707d9257 #343: одно правило допуска по квоте, прежние квотные системы вырезаны

diff --git a/app/runtime_router.py b/app/runtime_router.py
deleted file mode 100644
index 6af87a181..000000000
--- a/app/runtime_router.py
+++ /dev/null
@@ -1,1160 +0,0 @@
-"""Deterministic server-owned runtime selection from fresh quota telemetry."""
-
-from __future__ import annotations
-
-import asyncio
-import json
-import math
-import uuid
-from contextlib import asynccontextmanager
-from dataclasses import asdict, dataclass
-from datetime import datetime, timezone
-from typing import AsyncIterator, Awaitable, Callable, Literal, Mapping, Protocol
-
-from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
-
-from app.models import get_model_spec, resolve_model
-from app.quota_runway import RunwayVerdict, as_utc, next_weekly_reset, weekly_runway
-
-
-ROUTING_CONTRACT_VERSION = "routing-v2"
-ROUTING_POLICY_SCHEMA_VERSION = 1
-QUOTA_OBSERVATION_MAX_AGE_SECONDS = 300.0
-FIVE_HOUR_WINDOW_MINUTES = 300
-WEEKLY_WINDOW_MINUTES = 10080
-
-TaskClass = Literal[
-    "worker_general",
-    "orchestrator_free_text",
-    "review",
-    "continuation",
-]
-CandidateState = Literal["normal", "reserve_only", "unavailable", "excluded"]
-TASK_CLASSES = frozenset(
-    {"worker_general", "orchestrator_free_text", "review", "continuation"}
-)
-# Not policy, not configurable. `review`: a cheap model missed a real double-count that Sol
-# caught, so final review never routes to the weak lane. `continuation`: switching models inside
-# the codex runtime resets the native session (`resume_across_models=False`), so moving running
-# work onto Spark would end the thing it claims to continue.
-SPARK_FORBIDDEN_CLASSES = frozenset({"review", "continuation"})
-PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
-
-# A lane is (quota bucket, runtime, model). Runtime alone cannot key selection: Spark shares the
-# `codex` runtime with Sol but spends a different bucket, so one field would answer "which pool"
-# and "which reviewer is independent" differently. Independence stays a runtime question, quota
-# stays a bucket question, and selection is keyed by lane.
-LANE_CLAUDE = "claude"
-LANE_CODEX = "codex"
-LANE_CODEX_SPARK = "codex_spark"
-# Order is quality-first inside Codex: Sol takes the work while its bucket is healthy, and the
-# weaker Spark lane is reached only when Sol is not selectable. Spark-first would downgrade every
-# eligible task even on an idle pool — a silent quality loss, which is the one thing this feature
-# is forbidden to do. Claude stays last so Codex-first survives.
-LANE_PREFERENCE = (LANE_CODEX, LANE_CODEX_SPARK, LANE_CLAUDE)
-LANE_RUNTIMES = {LANE_CLAUDE: "claude", LANE_CODEX: "codex", LANE_CODEX_SPARK: "codex"}
-LANE_BUCKETS = {LANE_CLAUDE: "anthropic", LANE_CODEX: "codex", LANE_CODEX_SPARK: "codex_spark"}
-QUOTA_BUCKETS = frozenset(LANE_BUCKETS.values())
-
-
-class _StrictPolicyModel(BaseModel):
-    model_config = ConfigDict(extra="forbid", frozen=True)
-
-
-class RoutingModelsV1(_StrictPolicyModel):
-    claude: str
-    codex: str | None = None
-    spark: str | None = None
-
-    @model_validator(mode="after")
-    def validate_runtimes(self) -> "RoutingModelsV1":
-        claude = resolve_model(self.claude)
-        if get_model_spec(claude).runtime != "claude":
-            raise ValueError("models.claude must resolve to the Claude runtime")
-        object.__setattr__(self, "claude", claude)
-        if self.codex is not None:
-            codex = resolve_model(self.codex)
-            if get_model_spec(codex).runtime != "codex":
-                raise ValueError("models.codex must resolve to the Codex runtime")
-            if _bucket_for_model(codex) != LANE_BUCKETS[LANE_CODEX]:
-                raise ValueError("Spark spends its own bucket — configure it as models.spark")
-            object.__setattr__(self, "codex", codex)
-        if self.spark is not None:
-            spark = resolve_model(self.spark)
-            if get_model_spec(spark).runtime != "codex":
-                raise ValueError("models.spark must resolve to the Codex runtime")
-            if _bucket_for_model(spark) != LANE_BUCKETS[LANE_CODEX_SPARK]:
-                raise ValueError("models.spark must resolve to a model on the codex_spark bucket")
-            object.__setattr__(self, "spark", spark)
-        return self
-
-    def model_for_lane(self, lane: str) -> str | None:
-        return {
-            LANE_CLAUDE: self.claude,
-            LANE_CODEX: self.codex,
-            LANE_CODEX_SPARK: self.spark,
-        }[lane]
-
-
-class ClaudeQuotaPolicyV1(_StrictPolicyModel):
-    alert_deficit_hours: float = Field(ge=0, le=100)
-    weekly_unavailable_pct: float = Field(ge=0, le=100)
-    weekly_min_remaining_pp: float = Field(ge=0, le=100)
-    five_hour_unavailable_pct: float = Field(ge=0, le=100)
-
-    @field_validator("*", mode="before")
-    @classmethod
-    def validate_number(cls, value: object) -> object:
-        if isinstance(value, bool) or not isinstance(value, (int, float)):
-            raise ValueError("quota threshold must be numeric")
-        if not math.isfinite(float(value)):
-            raise ValueError("quota threshold must be finite")
-        return value
-
-
-class CodexQuotaPolicyV1(_StrictPolicyModel):
-    normal_below_pct: float = Field(ge=0, le=100)
-    unavailable_at_pct: float = Field(ge=0, le=100)
-
-    @field_validator("*", mode="before")
-    @classmethod
-    def validate_number(cls, value: object) -> object:
-        if isinstance(value, bool) or not isinstance(value, (int, float)):
-            raise ValueError("quota threshold must be numeric")
-        if not math.isfinite(float(value)):
-            raise ValueError("quota threshold must be finite")
-        return value
-
-    @model_validator(mode="after")
-    def validate_order(self) -> "CodexQuotaPolicyV1":
-        if self.normal_below_pct >= self.unavailable_at_pct:
-            raise ValueError("codex.normal_below_pct must be below unavailable_at_pct")
-        return self
-
-
-class SparkQuotaPolicyV1(_StrictPolicyModel):
-    normal_below_pct: float = Field(ge=0, le=100)
-    unavailable_at_pct: float = Field(ge=0, le=100)
-    # Empty by default on purpose: Spark's real preconditions (file count, explicit AC, a test
-    # command) are not expressible by any server-owned task class, and asking the agent would put
-    # the decision back where this feature took it from. The lane stays visible and unused until
-    # an operator states which classes may use it.
-    eligible_classes: tuple[str, ...] = ()
### 498c0d149 Orchestra: migrate project state to .orchestra

diff --git a/docs/tasks/216/codex-review-impl.md b/docs/tasks/216/codex-review-impl.md
deleted file mode 100644
index 5cf6b9158..000000000
--- a/docs/tasks/216/codex-review-impl.md
+++ /dev/null
@@ -1,109 +0,0 @@
-Spark remains unselectable, but configured Spark telemetry is silently omitted for access-gated task classes, producing a routing-v2 candidate inconsistent with the specified contract.
-
-Review comment:
-
-- [P2] Observe Spark regardless of Codex access mode — /home/kesha/orchestra/worktrees/home-kesha-orchestra/quota-routing/app/runtime_router.py:474-479
-  blocking: When `codex_access="review_only"` handles a non-review task, or access is `off`, this branch skips loading `codex_spark`; `_spark_candidate` then returns the access reason without utilization or timestamp. That violates the T1 contract requiring every configured Spark lane to remain `excluded` with `reason="spark_not_eligible"` and real telemetry ([docs/tasks/216/plan.md:242-243](docs/tasks/216/plan.md#L242-L243)), and contradicts the changed-file statement `"Observe the Spark bucket honestly, but never select it."`. Load `codex_spark` whenever `models.spark` is configured and keep access gating from replacing Spark's observation verdict.
-
-> ⚠ Codex usage unaccounted: caller did not provide usage attribution
-
-## Round (2026-08-12T06:59:35Z)
-
-Re-review status: FIXED in the working tree. I accept symmetry with Sol as the coherent contract: access gating owns observation for both Codex lanes, and no concrete consumer requires telemetry from an access-excluded lane.
-
-New blocking defect:
-
-- NEW BUG: the Round 2 fix is not fully staged. `app/runtime_router.py` and `tests/test_runtime_router_spark.py` are `MM`/`AM`, while `docs/tasks/216/plan.md` is unstaged. Committing the index now would omit the revised contract and symmetry tests, retaining the prior inconsistency.
-
-Sight-verification quote from changed code:
-
-> “When telemetry is read it is real and comes from `codex_spark`, never from `codex`.”
-
-Focused verification: 20 passed.
-
-Verdict: STILL BROKEN as a staged change; otherwise approved once the Round 2 working-tree changes are staged.
-
-> ⚠ Codex usage unaccounted: caller did not provide usage attribution
-
-## Round 2 resolution (author note)
-
-Раунд 2 снял единственный содержательный спор: ревьюер принял симметрию с полосой Sol как
-верный контракт и подтвердил, что потребителя, которому нужна телеметрия исключённой доступом
-полосы, не существует. Семантика не менялась — менялись мой докстринг и AC плана, оба
-переоценивали поведение.
-
-Второе замечание раунда 2 было практическим и верным: правки лежали в рабочем дереве, но не в
-индексе (`MM`/`AM`, а `plan.md` вовсе не проиндексирован), и коммит взял бы прежнюю версию.
-Проиндексировано полностью; проверено прогоном по одному содержимому индекса
-(`git stash --keep-index`) — **78 passed**, после чего рабочее дерево восстановлено.
-
-Вердикт записи: **approved once staged**, условие выполнено и проверено. Потолок раундов для кода
-(3) не исчерпан: второй раунд закрыл обе находки.
-
-## Infrastructure note
-
-Оба раунда артефакт записался штатно — после хотфикса #217 (`7283e769`). Остаточный след прежней
-несовместимости виден в хвосте job'а: `Codex usage unaccounted: caller did not provide usage
-attribution` — мой MCP-процесс поднят до #215 и атрибуцию расхода не передаёт. Результат ревью
-это больше не уничтожает (ровно та развязка, которую просили в баг-репорте); недоучёт расхода
-уйдёт при следующем реконнекте.
-
-- Attempt 1 (T2) started 2026-08-12: review of the T2 diff (Spark opt-in, lane order, continuation carve-out).
-
-## Round (2026-08-12T07:12:29Z)
-
-Re-review status: FIXED. T1 staging issue is gone/merged.
-
-New findings:
-
-- suggestion: `RoutingPolicyV1.validate_activation` returns immediately for `manifest_default`, so `"spark thresholds require models.spark"` is not enforced in that mode. If the invariant is unconditional, move that check before the mode return. This does not currently cause wrong routing because manifest mode ignores quota blocks.
-
-- suggestion: Add focused tests showing a staying Spark continuation remains blocked by access gating, terminal limit, stale telemetry, and hard-stop threshold. The production ordering is correct, but the current continuation test would stay green if one of those guards later moved below the carve-out.
-
-Design ruling:
-
-- Sol-first lane preference is correct. Emergency mode explicitly admits `reserve_only`, so choosing reserve Sol over normal Spark preserves the stated quality-first policy. Review independence and Claude fallback still operate correctly; latch computation is lane-filtered and unaffected.
-- The `staying` carve-out is correct. It cannot bypass access, terminal, freshness, or threshold checks because all execute first. A Sol continuation cannot reach Spark because Spark remains ineligible for `continuation`.
-- Removing the duplicate runtime forbidden-class check is sound for production paths: stored and replacement policies both pass through `RoutingPolicyV1.model_validate*`. `model_construct()` could violate this, but no application path uses it.
-- Duplicate/order normalization for `eligible_classes` is unnecessary for routing: membership is the only semantic operation. Canonicalization would only reduce policy-document noise.
-
-Sight-verification quote:
-
-> “Spark adds capacity when the Sol pool is burning; it never becomes the cheap default.”
-
-Verdict: APPROVED — no blocking defect found.
-
-> ⚠ Codex usage unaccounted: caller did not provide usage attribution
-
-## T2 round 1 outcome (author note)
-
-Вердикт **APPROVED**, блокирующих находок нет. Обе suggestion приняты и реализованы в этом же
-тикете:
-
-1. **`spark thresholds require models.spark` проверялся только в quota-режиме** — `validate_activation`
-   выходит раньше при `manifest_default`. Инвариант про согласованность документа, а не про
-   активный режим, поэтому проверка поднята выше раннего `return`. Мутация «вернуть проверку под
-   ранний return» краснит новый тест.
-2. **Carve-out `staying` не должен становиться обходом.** Порядок в коде уже верный (доступ,
-   терминальный лимит, свежесть и пороги идут раньше), но тест continuation остался бы зелёным,
-   если бы гард однажды переехал ниже. Добавлены четыре случая: `codex_access=off`, терминальный
-   лимит бакета, протухшая телеметрия, hard stop по порогу. Мутация «staying обходит hard stop»
-   краснит их.
-
-Ревьюер также подтвердил три моих решения по существу: Sol-first порядок полос (в emergency
-`reserve_only` допустим, поэтому зарезервированный Sol честно выигрывает у свободного Spark),
-корректность carve-out (все гарды исполняются до него) и обоснованность удаления недостижимой
-рантайм-проверки (единственный обход — `model_construct()`, которым приложение не пользуется).
-Нормализация `eligible_classes` признана ненужной: единственная операция над множеством —
-проверка вхождения.
-
-### Зрячесть: подтверждена, но НЕ предъявленной цитатой
-
-Строки «Spark adds capacity when the Sol pool is burning; it never becomes the cheap default»
-**нет ни в одном файле** — это пересказ моего комментария, а не дословная цитата. По моему же
-критерию такая цитата зрячести не доказывает, и записывать «подтверждено цитатой» нельзя.
-
-Зрячесть тем не менее установлена другим путём: ревьюер назвал ранний `return` в
-`validate_activation` и `model_construct()` как единственный обход валидации — обе детали
-специфичны для текущего кода и в запросе ревью не упоминались. То есть код прочитан, а
-самопроверочная цитата собрана небрежно.
diff --git a/docs/tasks/216/plan.md b/docs/tasks/216/plan.md
deleted file mode 100644
index ccbd65027..000000000
--- a/docs/tasks/216/plan.md
+++ /dev/null
@@ -1,455 +0,0 @@
-# #216 Фаза 2 — план: полоса Spark, состояние темпа, честные границы
-
-Опирается на `docs/tasks/216/research.md` (Фаза 1) и на смерженный inert `RuntimeRouter`
-(#187 T1, `2627b0c9`). Порядок тикетов задан оркестратором: сперва Spark, потом предупреждение по
-темпу, потом симметричный случай.
-
-## Что этот план даёт и чего НЕ даёт
-
-**Честное имя результата: «подготовить маршрутизацию на полосу Spark», а не «Orchestra начнёт
-обходить выжженный пул».** У `RuntimeRouter` сегодня нет ни одного production-вызывающего (F1
-ресёрча). Тикеты T1–T4 расширяют инертный evaluator.
-
-**Подключать роутер к спавну внутри #216 нельзя, и это не выбор объёма, а запрет на второго
-владельца.** Точка `app/manager.py:636` — это существующий `require_worker_admission` из
-`quota_gate`. Поставить роутер перед ним значило бы получить цепочку из двух решателей с разными
-policy и порогами: `RuntimeRouter → legacy quota_gate → spawn`. Кроме того, роутер умеет отвечать
-`queued`, а durable-обработка этого ответа — #187 T2. Всю миграцию вызывающих вместе с удалением
-легаси одним коммитом уже описывает **#187 T3** (`docs/tasks/187/plan.md:432`), и в его списке
-файлов стоят ровно те, что понадобились бы здесь, включая `pipelines/default/prompts/base.md`.
-
-Поэтому #216 не заводит своих тикетов на подключение, а **передаёт требования в #187 T3** (раздел
-ниже). Живая маршрутизация начинается вместе с его cutover, который и так гейтится общим окном
-рестарта.
-
-Что из этого следует для приёмки: **закрытие #216 по T1–T4 означает готовую политику, а не
-изменившееся поведение системы.** Утверждать обратное в отчёте нельзя. Если требования не будут
-приняты в #187 T3 — это блокер, о котором говорят оркестратору, а не тихо закрытая фаза.