<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну конечно, RED-оракулы ещё и от `PYTHONPATH` умеют краснеть 😑

## Summary

План архитектурно связный, но к Phase 3 не готов: ключевые AC проверяются синтаксическим наличием аргументов, а не сохранением данных и атомарностью. При `PYTHONPATH=.` все пять oracle-файлов действительно RED; команда из плана без него даёт import failure для T1/T3.

## Findings

### blocking: T1 не является шипуемым вертикальным срезом

[plan.md:113](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:113>) делает `provenance` обязательным до T2/T3. При этом текущие [manager.py:1119](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/app/manager.py:1119>) и [manager.py:1151](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/app/manager.py:1151>) вызывают `session.send(..., delivery=...)` без `provenance`; после отдельного мержа T1 initial/direct delivery начнут падать с `TypeError`. Границу и всех её вызывающих нужно поставлять одним срезом либо временно оставить совместимость.

### blocking: T2 oracle проверяет форму, а не persistence contract

В [test_t2_writer_seams_433.py:45](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t2_writer_seams_433.py:45>) проверяется только наличие keyword `provenance`, а в [test_t2_writer_seams_433.py:49](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t2_writer_seams_433.py:49>) — наличие слов `origin` и `origin_detail` в SQL-строке. `provenance=None`, неправильная сериализация, неверные bind-параметры и запись вне транзакции пройдут. AC о валидной строке и атомарном переходе состояния этим oracle не доказан.

### blocking: T1 oracle не покрывает заявленный value-object contract

[plan.md:35](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/plan.md:35>) требует дедупликацию с сохранением порядка, canonical JSON round-trip и проверку `subtype/ref`, а [test_t1_provenance_contract_433.py:8](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t1_provenance_contract_433.py:8>) этого не проверяет. Также отсутствует проверка нового контракта `InjectedMessage` из [plan.md:37](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/plan.md:37>); реализация может оставить старые `origin/job_id` и всё равно пройти T1.

### blocking: T3 ingress oracle пропускает durable entry points

Сканер в [test_t3_ingress_consumers_433.py:30](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:30>) ищет только вызовы с именем `send` и проверяет лишь имя keyword. Он не видит `send_initial_delivery` и `send_message_delivery`, а выражение `provenance=object()` тоже будет принято. Поэтому заявленные «29 ingress» и durable delivery forwarding механически не защищены.

### blocking: T3 consumer ACs не имеют поведенческого покрытия

[plan.md:129](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/plan.md:129>) требует field-driven поведение TG, runtime history, retry, limit-wake и MCP logs, но oracle проверяет только отсутствие нескольких точных строк в [test_t3_ingress_consumers_433.py:60](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:60>) и отдельно тестирует лишь mailbox/RAG. Эквивалентный parser с другой формой или always-human классификация пройдут.

### blocking: `origin_detail` имеет несовместимые типовые границы

План требует object в snapshot/SSE ([plan.md:39](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:39>)), T3 передаёт в RAG JSON string ([test_t3_ingress_consumers_433.py:120](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:120>)), а T4 использует object ([test_t4_frontend_origin_433.py:57](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t4_frontend_origin_433.py:57>)). Дополнительно текущая явная проекция `_SYNC_COLS` в [db.py:2442](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/app/db.py:2442>) не содержит новые поля. Нужно явно определить тип на каждом boundary и добавить HTTP/SSE-проверку.

### blocking: T5 не доказывает offline/CLI safety

Тест в [test_t5_offline_migration_433.py:54](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:54>) подменяет глобальный `db.DB_PATH` тем же `tmp_path`, который передаёт миграции, а затем вызывает только `migrate_database(..., apply=True)` ([строка 141](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:141>)). Скрипт, игнорирующий явный путь, мутирующий по умолчанию или не реализующий `--db/--apply`, пройдёт. Нужен CLI-тест с различными global/explicit paths, dry-run и apply.

### blocking: T5 не проверяет атомарность и WAL-безопасность

В [test_t5_offline_migration_433.py:141](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:141>) выполняются только два последовательных успешных запуска. Нет сбоя посреди пачки с проверкой rollback, consistent backup, concurrent WAL reader или доказательства отсутствия частичного обновления. Процедура из [plan.md:159](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:159>) сама по себе тестом не является.

### suggestion: T5 не проверяет precedence на конфликтующих данных

Фикстура проверяет receipt rows с обычным текстом и legacy prefixes отдельно, поэтому неправильный порядок `receipt → prefix → explicit rules` не проявится. Нужны конфликтующие пары — например receipt `operator:*` плюс `[from:agent]` — и проверки всех заявленных 181-class rules и machine-readable counters.

### question: RED-команды в плане не воспроизводятся буквально

В текущем worktree `uv run pytest -q ...` даёт `ModuleNotFoundError: app` для импортных частей T1/T3, а `env PYTHONPATH=. uv run pytest -q ...` даёт заявленные 3/6/12/1/1 failures. Поскольку [plan.md:26](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/plan.md:26>) прямо требует останавливать работу при collection/premise drift, нужно зафиксировать окружение запуска.

## Verdict

**Changes requested.** Основные блокеры — не сама B1-модель, а незащищённые persistence/receipt boundaries, преждевременное обязательное API и отсутствие поведенческих oracle для большинства consumers. Сейчас план выглядит как миграция в костюме зелёного теста: костюм есть, атомарности внутри не видно.

## Author resolution before round 2

- T1 premature API: accepted; T1 now ships only the canonical B1 value + the existing background `InjectedMessage` caller. T2 switches required send signatures and every producer in one atomic ticket.
- T1 value contract: accepted; `78bd511e` checks canonical storage bytes, order-preserving sender dedupe, subtype/ref validation, and removal of legacy `InjectedMessage.origin/job_id`.
- T2 representation-only oracle: accepted; `78bd511e` executes all three `AgentSession.send` branches, real compact, canonical DB round-trip, and both durable transactions with an abort trigger proving rollback before successful prepare.
- T3 durable/consumer gaps: accepted; the scanner includes both durable manager methods, and behavior checks now cover runtime history, retry subtype, DB/API/sync dict boundaries, TG/MCP labels, mailbox/RAG, and limit-wake ref spoofing.
- Boundary types: accepted; plan now states SQLite JSON text → decoded dict at every `db.get_*` boundary; `_SYNC_COLS` is checked.
- T5 CLI/atomicity/precedence: accepted; final RED invokes real CLI with explicit target != global env path, default dry-run, trigger rollback, WAL reader, `Connection.backup`, conflicting receipt/prefix rows, all 181 classes, JSON counters and second-run no-op.
- PYTHONPATH: the root-shell commands succeeded without it, but the reviewer environment did not. Final commands explicitly use `env PYTHONPATH=.`.

Final frozen oracle commit: `78bd511e`. Earlier T1/T2/T3/T5 bytes in `05327bf1` are excluded; T4 remains the valid neutral-body oracle introduced by `05327bf1` and is included unchanged in `78bd511e`.

## Round (2026-09-02T02:53:16Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну конечно, финальный раунд тоже нашёл пару финальных мин 🧨

## Re-review status

Scoped `git diff` is empty; `git status` shows only untracked `docs/tasks/433/plan.md`. Current oracle replay with `PYTHONPATH=.` gives the claimed assertion-only RED counts: 2/7/17/1/1.

- **FIXED** — PYTHONPATH/reproducibility: [plan.md:106](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:106>).
- **FIXED** — premature required send boundary: [plan.md:36](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:36>).
- **FIXED** — T2 representation-only oracle: [test_t2_writer_seams_433.py:181](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t2_writer_seams_433.py:181>).
- **FIXED** — incomplete T1 value object: [test_t1_provenance_contract_433.py:14](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t1_provenance_contract_433.py:14>).
- **STILL BROKEN** — durable ingress scanner now sees the methods, but still validates only presence of a `provenance` keyword: [test_t3_ingress_consumers_433.py:16](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:16>), [test_t3_ingress_consumers_433.py:54](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:54>).
- **FIXED** — missing consumer behavior coverage: [test_t3_ingress_consumers_433.py:143](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:143>).
- **FIXED** — JSON text/object boundary definition: [plan.md:39](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:39>).
- **FIXED** — CLI target and dry-run coverage: [test_t5_offline_migration_433.py:152](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:152>).
- **FIXED** — rollback/WAL/backup controls: [test_t5_offline_migration_433.py:164](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:164>).
- **FIXED** — receipt/prefix precedence conflicts: [test_t5_offline_migration_433.py:71](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:71>).

## New findings

### blocking: T2 still bypasses the real `_log` path

The branch tests replace `session._log` entirely ([test_t2_writer_seams_433.py:49](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t2_writer_seams_433.py:49>)), while the direct DB test supplies provenance explicitly ([test_t2_writer_seams_433.py:162](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t2_writer_seams_433.py:162>)). A broken `AgentSession._log` forwarding implementation, or a `db.add_log` that silently accepts missing provenance, can therefore pass despite [plan.md:36](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:36>).

### blocking: receipt provenance and idempotency hash are not tested end-to-end

The durable test checks only the resulting log row ([test_t2_writer_seams_433.py:239](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t2_writer_seams_433.py:239>); it never verifies provenance stored in the receipt, retry reuse, or that changing provenance changes the payload conflict under [plan.md:38](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:38>). It also does not execute either durable manager delivery path, so a manager can discard provenance before `AgentSession.send`.

### blocking: T3 does not exercise HTTP/SSE serialization

The “API boundary” test calls `db.get_log/get_logs/...` directly ([test_t3_ingress_consumers_433.py:226](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t3_ingress_consumers_433.py:226>)); it never invokes the FastAPI snapshot or SSE routes. A route can still re-encode `origin_detail` as a JSON string while all current T3 assertions pass, contradicting [plan.md:39](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/plan.md:39>).

### blocking: T4 does not test malformed detail with explicit user origin

The cases cover missing payload and invalid `origin`, but not `origin: "user"` with malformed, missing, or non-object `origin_detail` ([test_t4_frontend_origin_433.py:56](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t4_frontend_origin_433.py:56>)). A renderer that trusts `origin === "user"` would pass this oracle while violating the fail-safe rule in [plan.md:14](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:14>).

### blocking: T5 creates contradictory receipt state

The fixture passes explicit `unknown` provenance to every new receipt ([test_t5_offline_migration_433.py:48](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:48>)), then expects migration to classify the same receipt as `agent` or `user` from legacy fields ([test_t5_offline_migration_433.py:114](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:114>). This conflicts with immutable accepted receipt provenance in [plan.md:38](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:38>); use legacy receipt rows for migration tests or pass the correct provenance and test reclassification separately.

### suggestion: T5 does not assert complete JSON counters

The plan requires totals, category counts, target path, session count, and update fields ([plan.md:73](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/plan.md:73>)), but the test checks only a few keys: `mode`, `would_update`, `updated`, and `invalid` ([test_t5_offline_migration_433.py:152](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:152>), [test_t5_offline_migration_433.py:187](</mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-msg-origin/docs/tasks/433/test_t5_offline_migration_433.py:187>)).

## Verdict

**CHANGES REQUESTED.** The major round-1 issues were addressed, but the remaining blockers affect receipt immutability, fail-loud persistence, HTTP/SSE boundaries, and fail-safe frontend behavior. No third review round is requested; these are the final recorded blockers.

## Post-ceiling author resolution (no third review permitted)

The final findings were fixed in frozen RED commit `de813880`; the reviewer verdict above remains `CHANGES REQUESTED` because the prose ceiling forbids another model round.

- `_log` bypass: fixed — session/compact tests execute real `_log` and capture its actual `add_log` call; DB round-trip remains separate.
- Receipt/hash/manager path: fixed — receipt provenance is asserted, changed provenance must conflict under the same delivery id, trigger rollback + successful prepare are both run, and both durable manager methods forward exact object identity to a recording session.
- Ingress `object()` loophole: fixed — AST accepts only inline `MessageProvenance`, a variable named `provenance`, or `.provenance` from an envelope.
- HTTP/SSE gap: fixed — actual `get_session_logs` and `stream_session_logs` route functions are invoked and must emit detail objects.
- Explicit-user malformed detail: fixed — missing, string, and empty-senders detail cases all require Unknown left rendering.
- Contradictory receipt state: fixed — only fixture receipts downgraded to pre-B1 `schema_version=1` are reconstructed; a new-version explicit-unknown receipt with contradictory agent prefix remains unknown.
- Counters: fixed — exact summary keys, six category keys, resolved target, row/session totals, invalid count, would-update and updated values are asserted in all modes.

Command replay after `de813880`: T1 `2 failed`, T2 `7 failed`, T3 `18 failed`, T4 `1 failed`, T5 `1 failed`; `rg` over the logs found no collection/import/TypeError outcome. All failures remain missing-behavior assertions.
