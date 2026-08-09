# #170 — Phase 3 implementation report

Статус: **DONE**. T1→T5 выполнены в утверждённом порядке только в worktree.
Seedon, production, systemd, live SQLite и активные сессии не изменялись;
restart/deploy не выполнялись.

## Результат по тикетам

### T1 — readiness hot-version skew

FastAPI теперь отдаёт dual envelope из одного `QuotaDecision`: canonical
`decision_state`/`decision_reset_at` и безопасную legacy-проекцию
`state=available|reset`. Unknown/blocked без реального reset получают только
короткий synthetic legacy `reset_at`; canonical timestamps не подменяются.

Новый MCP client:

- legacy server без policy блокирует как `weekly_quota_upgrade_required`;
- current v1 принимается только со свежими Unix либо timezone-aware ISO
  timestamps;
- canonical state принимается только при exact integer `wire_version=2`;
- malformed, stale, future, expired и version-inconsistent responses
  fail-closed до background job;
- `not_applicable` допускается только при совпадении `provider=grok` и модели.

Граница центрального evaluator не менялась: `94.999%` allow, `95.0%` и
`100%` block. Rollout invariant остаётся server-first: сначала dual FastAPI,
затем client; rollback server при живом legacy MCP запрещён. Никаких вторых
client-side quota sources/evaluators нет.

Before: `4 failed in 8.07s` — legacy diagnosis был generic unknown, expired
available запускал review, endpoint не имел dual fields. After: `64 passed in
6.81s`; rollout subset трижды `31 passed` за `5.37/5.54/5.84s`. После
self-review version-binding guard: `68 passed in 5.89s`. Пять независимых
мутаций — 5/5 red.

### T2 — runtime-specific turn-end quota telemetry

Turn-end и DB теперь используют один выбранный свежий snapshot: Claude видит
только Claude `5h/7d`, Sol — Codex `primary/secondary`, Spark — nested Spark
windows. Stale/missing/malformed cache не подставляет чужие окна и не выводит
quota suffix. Admission path не изменён.

Before: Sol печатал `| 5h:88% 7d:100%` из Claude cache, `1 failed in 5.15s`.
After: targeted `13 passed in 6.14s`; async integration трижды `2 passed` за
`5.12/4.65/4.63s`. Три независимые мутации — 3/3 red.

### T3 — managed-worker isolation

Каждый Orchestra-managed `CodexBackend` запускается с
`features.multi_agent=false`, включая non-orchestrator workers. Поддерживаемая
Orchestra delegation сохранена: MCP `spawn_worker` и `can_spawn` роли не
удалены.

Before: worker command не содержал disable flag, `1 failed in 4.46s`. After:
парный isolation/delegation набор трижды `2 passed` за `4.15/3.97/4.04s`;
manifest assertion отдельно прошёл. Две независимые мутации — 2/2 red.

### T4 — skill/worktree guard

Skill injector возвращает structured diagnosis, сохраняя публичный
count-only API. Tracked `.codex` file остаётся byte-for-byte и с clean git;
недоступный native skill home включает один bounded canonical prompt index с
явным marker при лимите 16,000 characters. Reconnect не дублирует warning или
index.

Codex preflight читает effective `project_doc_max_bytes`, считает UTF-8 bytes,
проверяет boundary `actual==budget`, находит первую не полностью попавшую
строку и до CLI connect добавляет короткий ephemeral warning/instruction
дочитать хвост. `.codex`, `AGENTS.md` и Codex config не меняются. При
недоказанном budget exact truncation не утверждается.

Before: tracked-file scenario заканчивался без fallback
(`AttributeError`, `1 failed in 4.47s`); measured `155284 > 65536` не давал
pre-connect diagnosis. After: focused `8 passed in 4.60s`, wider suite `215
passed in 44.19s`, async/reconnect трижды `3 passed` за `4.07/4.11/4.23s`.
Четыре независимые мутации — 4/4 red.

### T5 — fixed-workload A/B gate

Сохранены redacted hashed workloads, raw-run schema и воспроизводимый gate.
Разрешённых comparable Sol runs нет: baseline `0`, candidate `0`, required
`12` на arm. Verdict — **NO_CHANGE**. Поэтому runtime/prompt для repeated
reads/context/test polling не менялся.

Quantified recommendation сохранена без заявления о regression: в audited
session было `193` read actions, `2.34 MB` tool results, `39` результатов
≥16 KiB и `31.06s` explicit poll wall. Следующий candidate допускается только
после hash-matched A/B, correctness/no-loss и gain выше измеренного
baseline split-half noise, включая distant-domain workload.

## Изменённые файлы

- Runtime: `app/backend_codex.py`, `app/mcp_stdio.py`, `app/prompting.py`,
  `app/quota_gate.py`, `app/routes/system.py`, `app/runtime_registry.py`,
  `app/session.py`, `app/session_turns.py`.
- Behavioral tests: 10 соответствующих `tests/test_*.py` файлов.
- Evidence: `docs/tasks/170/measurements/` и этот report/review.

Не менялись delivery/MCP transport, compact/precompact и #97.

## Verification

- 14/14 named independent mutations дали красный behavioral result и были
  восстановлены до следующего прогона.
- Combined targeted suite: `564 passed in 70.75s`.
- Финальный T1 после self-review fix: `68 passed in 5.89s`.
- Обязательная команда
  `uv run python -m pytest -x -q > /tmp/pytest-170-final.log 2>&1` завершилась
  с exit `0`; лог `9032` bytes / `118` lines, `uv.lock` unchanged,
  `git diff --check` clean. После успешного pytest интерпретатор напечатал пять
  existing `BaseSubprocessTransport.__del__: RuntimeError: Event loop is
  closed` cleanup warnings; test failure они не создали.
- `ruff` отсутствует в project environment (`Failed to spawn: ruff`), поэтому
  отдельный lint verdict недоступен; syntax/import/runtime paths покрыты full
  pytest.

## Review

Единственная разрешённая попытка external `codex_review` была fail-closed до
job creation на legacy readiness response. Gate не обходился, Claude и direct
Codex не использовались. Strict Sol self-review нашёл и исправил один
version-binding blocker до финального suite; unresolved CRITICAL/HIGH нет.
Полный verdict: `docs/tasks/170/codex-review-impl.md` — **PASS; external verdict
unavailable**.

## Breaking / rollout / TODO

- Breaking API для поддерживаемых клиентов нет: server dual-envelope сохраняет
  legacy fields, current-v1 и v2 paths покрыты matrix tests.
- Runtime rollout всё ещё требует dual-server-first; этот commit ничего не
  deploy/restart.
- T5 optimization остаётся quantified recommendation до появления разрешённых
  comparable A/B runs.
