# #170 — Phase 2 plan review

## External verdict

**external verdict unavailable.** Обязательный
`codex_review(mode="exec", target="docs/tasks/170/plan.md")` был вызван один
раз без обхода и до запуска review job вернул:

```text
weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for
gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy).
```

Live response в error details был legacy `{provider: codex, state: available,
reason, reset_at}` без `policy`. Resume невозможен: review session/job не был
создан. Claude, direct `codex exec`, смена модели и bypass readiness не
использовались.

## Strict Sol self-review

Проверен сам план и точные seams текущего кода:

- historical pre-`8369737` `_quota_refusal` и current
  `app/mcp_stdio.py::_quota_refusal`;
- `QuotaDecision.to_dict`, `_weekly_status`, `evaluate_worker_admission` и
  `/api/usage/readiness`;
- `_format_limits`, `_cached_quota_state` и current turn-end call site;
- Codex `connect()` command, Orchestra MCP tool allowlist;
- skill injection guard, session connect order и runtime skill-index fallback.

Review искал fail-open, несовместимый wire type, неподдерживаемый rollout
порядок, тесты формы вместо поведения, diff без mutation evidence и изменение
опровергнутых latency paths.

### [high, resolved] Current v1 timestamps — Unix seconds, не только ISO

Первый draft требовал timezone-aware timestamps, но current
`QuotaDecision.to_dict()` реально отдаёт `observed_at`/`valid_until` как
`float`. Это сделало бы заявленную совместимость `new MCP ↔ current v1
FastAPI` ложной. План исправлен: новый parser принимает finite positive Unix
seconds и timezone-aware ISO, а naive/malformed ISO отвергает. AC теперь
отдельно закрывает обе формы и exact 300 s boundary.

### [high, resolved] `not_applicable` не имеет freshness timestamps

`evaluate_worker_admission()` для positively resolved Grok возвращает
`not_applicable` с `observed_at=None` и `valid_until=None`. Без исключения
общий freshness guard заблокировал бы заведомо вне-policy runtime. План
исправлен: freshness обязателен только для quota-applicable verdict;
`not_applicable` допускается лишь как результат central model policy, а не по
произвольному client payload.

### [medium, resolved] Нельзя ломать int contract skill injector

`inject_skills_to_worktree()` используется несколькими manager/session и test
call sites, часть проверяет `== 0/1`. Замена return type на dataclass создала
бы горизонтальный compatibility churn. План исправлен: одна внутренняя
reporting implementation, backward-compatible int wrapper, detailed session
path без дублирования guards.

### [high, accepted invariant] Safe availability с pre-v1 server невозможна

Legacy readiness response не содержит weekly utilization, threshold,
`observed_at` или `valid_until`. Ни `state=available`, ни свежесть HTTP-ответа
не доказывают hard weekly `<95%`. Поэтому `new client + pre-v1 server` в плане
намеренно fail-closed `upgrade_required`; это degraded compatibility, а не
нулевой downtime. Единственный безопасный rollout — dual server first.

Counter-check: разрешить этот ответ означало бы буквально восстановить
доказанный fail-open. Добавить client-side quota lookup означало бы второй
evaluator и возможный drift от server execution gate. Оба варианта отвергнуты.

### [medium, accepted trade-off] Legacy parser не умеет точную причину unknown

Pre-v1 MCP различает только `available` и `reset`. Dual server поэтому должен
проецировать `blocked` и `unknown` в `reset` с будущим compatibility retry
timestamp. Старый клиент может назвать unknown «quota exhausted», но процесс
не стартует; canonical `decision_state`, real freshness и
`decision_reset_at` остаются неповреждёнными для нового клиента. Точная
диагностика на старом parser без его обновления невозможна. План требует
отдельного поля и теста, чтобы synthetic timestamp не выдавался за provider
reset.

### [medium, accepted residual] Oversized-doc fallback не гарантирует действие модели

Pre-connect detection, byte count, first truncated line, session warning и
no-overwrite проверяются детерминированно. Инструкция дочитать хвост в
ephemeral system prompt уменьшает риск потери поздних правил, но её исполнение
остаётся model behavior; автоматическое повышение cap или инъекция всего хвоста
увеличили бы context и могли бы повторить измеренную проблему. Поэтому план не
обещает полную загрузку как runtime invariant и не меняет repo/config. Если
Phase 3 не сможет поведенчески подтвердить чтение хвоста без live session,
результат должен быть сформулирован как ранняя диагностика + safe prompt
fallback, не как guaranteed full-doc load.

### [medium, verified] Managed isolation сохраняет Orchestra delegation

Native Codex delegation контролируется CLI flag
`features.multi_agent=false`; Orchestra delegation приходит отдельным MCP tool
`spawn_worker`. Paired behavioral tests проверяют оба пути независимо. Поэтому
unconditional native disable не требует удалять `spawn_worker`, менять
pipeline `can_spawn` или отключать supported full-cycle delegation.

### [medium, verified] Telemetry selector не требует нового cache/fetch path

`_cached_quota_state(runtime, model)` уже выбирает Claude, Sol и nested Spark
cache с TTL. План переиспользует этот selector/snapshot для DB и видимого
форматтера вместо нового network fetch или глобального cache. Stale/missing
data даёт отсутствие suffix, а не подстановку чужого runtime. Это ограничивает
изменение turn-end presentation/persistence seam и не затрагивает readiness.

### [medium, verified] A/B gate не маскирует отсутствие доказательств

T5 заранее измеряет baseline noise, сохраняет workload hash и требует
correctness/no-loss до latency/tool-call метрик. При недоступной Sol quota или
эффекте не выше noise обязательный результат — no runtime/prompt change и
quantified recommendation. Это согласуется с forensic finding: repeated reads
и polling измерены, но causal gain пока не доказан.

## Scope audit

- Пять vertical tickets имеют files, behavioral before/after, AC,
  reproducible commands, независимые мутации и `blocked-by`.
- T1–T4 заканчиваются наблюдаемым end-to-end поведением, а не горизонтальным
  слоем helper/tests.
- T5 допускает runtime diff только после отдельного A/B; при no-change mutation
  неприменима и это явно записано.
- Delivery, MCP transport/cancellation, compact/precompact и #97 исключены.
- Seedon, production, restart, live sessions и чужие agents не используются.

## Self-review verdict

**APPROVE — no unresolved blocking/high findings.** Два high и один medium
дефект draft исправлены в `plan.md`. Остались два явно ограниченных trade-off:
pre-v1 server даёт safe unavailability до server-first rollout, а oversized
doc fallback не выдаётся за гарантию model compliance.

Это strict self-review, не внешний Codex verdict; формулировка
`external verdict unavailable` должна сохраниться в PLAN READY и дальнейших
артефактах до появления настоящего review output.
