# #436 — план структурного review receipt pipeline

## Preconditions

- Реализация не начинается до merge #433: `app/mcp_stdio.py` и `app/db.py` сейчас принадлежат той задаче.
- До реализации юзер должен выбрать способ записи author outcome в блоке ниже. План намеренно не подменяет этот выбор.
- Текст ревью остаётся только в `artifact_path`. В receipt нет `content`, `last_output`, полного JSONL или копии prose.
- Нельзя обещать review recall/completeness. Отчётные метрики — только наличие/происхождение квитанции, verdict и зафиксированный author outcome.

## Предлагаемый минимальный receipt

Одна строка на один вызов/round, keyed by immutable `receipt_id`; повтор записи с тем же id — idempotent no-op.

```text
receipt_id, schema_version
runtime, reviewer_model, model_source
session_id, worker_name, scope, task_id, task_source
artifact_path, mode, round, job_id, usage_event_id
requested_at, completed_at, status
return_code, failure_code
artifact_exists, artifact_bytes, artifact_sha256
verdict_present, verdict_value
jsonl_response_present, recovery_source
author_outcome, outcome_source, outcome_evidence_ref
notification_event_id
```

`model_source` и `outcome_source` обязательны: `direct`, `derived`, `unknown`. Исторический default никогда не нормализуется в `direct`. `outcome_evidence_ref` — путь/строка/commit reference, не текст finding.

`round` резервируется при старте атомарно. Если сохранить только `resume`, гонка двух вызовов одного slug снова даст неверный порядок. `status` различает `requested`, `completed`, `failed`, `timed_out`, `interrupted`; `return_code=0` не превращается автоматически в `completed`.

## Решение юзера: вариант B

| Вариант | Как фиксируется `accepted / disputed / partial` | Цена кода/операции | Риск пропуска |
|---|---|---|---|
| A. Обязательное поле в следующем вызове | Следующий `codex_review`/resume передаёт `author_outcome` и `outcome_evidence_ref`; сервер валидирует enum и receipt id | Небольшое расширение аргументов и один write; нет нового MCP имени | Если следующего вызова не будет, outcome останется `unknown`; «обязательность» привязана к продолжению debate |
| B. Отдельный тул `record_review_outcome` | Автор после чтения artifact вызывает тул с receipt id, исходом и доказательством; повтор идемпотентен | Один новый MCP tool + schema/CRUD + один дополнительный вызов | Самый явный durable event; забытый вызов сразу виден как `unknown`, но тул надо реально вызвать |
| C. Обязательная строка в отчёте воркера | Финальный отчёт содержит точную строку `Review outcome: ...`; ingestion/parser переносит её в receipt | Самая низкая цена интерфейса, если parser уже существует | Prompt-only вариант запрещён: #174 уже показал несостоятельность. Без машинного parser это лишь ещё одна необязательная проза |

Юзер выбрал B: реализуется только отдельный MCP tool `record_review_outcome`. Варианты A и C сняты и не добавляются «на всякий случай».

## Вертикальные тикеты и разные красные швы

### T1 — receipt storage (`app/db.py`)

Добавить schema/migration и минимальные `review_receipt_create`, `review_receipt_finish`, `review_receipt_get` (названия уточнить после #433). Уникальность — `receipt_id`; обновление completion не должно менять исходные immutable поля. Unknown хранится явно, не через NULL-смысл.

Красный оракул: `tests/test_review_receipt_storage_436.py::test_receipt_round_trip_preserves_provenance_and_unknowns` на `tmp_path` с подменённым `DB_PATH`; до реализации падает именно на отсутствии storage API/table. Это отдельный шов схемы, не вызов MCP.

### T2 — start receipt (`app/mcp_stdio.py`)

В `codex_review` после resolution model/session/task и до POST bg-job создать receipt с выбранной model (не readiness model), runtime, task, output path, job-independent request id и reserved round. При ошибке валидации/квоты не создавать ложный started receipt.

Красный оракул: `tests/test_review_receipt_start_436.py::test_start_receipt_uses_resolved_model_task_artifact_and_reserved_round` через fake `_api`, проверяет вызов storage seam и payload bg-job. До реализации отсутствует именно start write; T1 storage уже может быть зелёным отдельно.

### T3 — terminal classification/recovery (`app/codex_review_artifact.py`, `app/mcp_stdio.py`)

На завершении команды связать receipt с job id и записать реальный rc, artifact existence/size/hash, verdict presence, failure/status и notification event. При `rc=0` + пустом artifact искать последний `item.type=agent_message` в JSONL; если найден — атомарно восстановить текст в исходный artifact, поставить `recovery_source=jsonl_agent_message`, но не копировать его в БД. Если event не найден — `unknown`/failure, без повторного Codex-вызова.

Красный оракул: `tests/test_review_receipt_terminal_436.py::test_zero_rc_empty_artifact_is_not_success_and_jsonl_recovery_is_positive` прогоняет fake command/finalizer на временных путях и отдельно проверяет две ветви (JSONL agent message есть / нет). До реализации нет terminal receipt update; этот шов не проверяет start payload или SQL schema.

### T4 — historical migration (`scripts/migrate_review_receipts.py`)

Сделать `--dry-run` и guarded `--apply`: frozen manifest 437 paths, SHA/size, evidence source, migration revision; apply перечитывает вход и отказывается при drift. Статусы: direct, derived, unknown. Для 276 historical-default models навсегда записать `model_source=derived`; для старых текстовых `FIXED`/`DISAGREE` не притворяться машинным author outcome. Миграция идемпотентна и не пишет текст review в receipt.

Красный оракул: `tests/test_review_receipt_migration_436.py::test_migration_keeps_derived_model_and_unknown_outcome_distinct` на synthetic 3-file manifest + отдельной временной SQLite. До реализации отсутствует скрипт/manifest contract; это не повторяет T1/T3. Обязательная safety-проверка rehearsal: до/после число строк боевой `sessions` совпадает; production DB в тесте не открывается `db.init_db()` без подмены пути.

### T5 — выбранный author-outcome interface

Реализовать `record_review_outcome(receipt_id, outcome, outcome_evidence_ref)` с enum `{accepted, disputed, partial}` и доказательством для `disputed`; A/C не добавлять.

Красный оракул выбранного B: `tests/test_review_receipt_outcome_tool_436.py::test_outcome_tool_is_idempotent_and_rejects_missing_dispute_evidence` — прямой MCP tool path, не вызов DB primitive. Мутация, убирающая wiring MCP→DB, обязана краснить этот тест; мутация самого DB primitive также обязана краснить его.

## Files

Точные production/test файлы будущей реализации (после merge #433 и выбора варианта):

- `app/db.py` — receipt schema, immutable/idempotent CRUD, migration hook.
- `app/mcp_stdio.py` — start receipt, job linkage, выбранный A или B tool (если B).
- `app/codex_review_artifact.py` — terminal rc/artifact/verdict/JSONL recovery seam, только если owner #433 не вынесет эту запись в другой finalizer.
- `scripts/migrate_review_receipts.py` — one-shot frozen-manifest migration.
- `tests/test_review_receipt_storage_436.py` — T1 red/green oracle.
- `tests/test_review_receipt_start_436.py` — T2 red/green oracle.
- `tests/test_review_receipt_terminal_436.py` — T3 red/green oracle.
- `tests/test_review_receipt_migration_436.py` — T4 red/green oracle.
- `tests/test_review_receipt_outcome_tool_436.py` — выбранный T5 seam B; A/C test files не создаются.
- `docs/tasks/436/migration-manifest.json` — frozen input/evidence manifest, не текстовой review owner; создаётся только при запуске миграции.

На текущей фазе изменены только `docs/tasks/436/research.md` и этот `plan.md`.

## Проверка и rollout

1. После #433 перечитать merged `app/db.py` и `app/mcp_stdio.py`, заново проверить ownership seams и не переносить receipt в text/log duplicate.
2. Заморозить красные оракулы по отдельным швам T1–T4; T5 замораживать только после выбора варианта.
3. Прогнать каждый targeted test на своей временной БД. Для любого test-layer процесса явно задавать `ORCHESTRA_DB_PATH`/`DB_PATH`; сохранить счётчик `data/orchestra.db:sessions` до/после rehearsal.
4. На synthetic manifest проверить drift refusal, повторный apply и derived/unknown provenance.
5. Только после зелёных тестов и отдельного решения о live migration сделать read-only backup `data/orchestra.db`, dry-run, сверку количества/идентичности receipts и затем apply. Новых Codex-вызовов для self-review без отдельной необходимости не добавлять.

## Не входит

- Сравнение Luna и Sol по наблюдательному корпусу #435.
- Метрика полноты/recall ревью.
- Копия текста artifact в SQLite, новый text owner или восстановление утраченного текста без живого JSONL evidence.
- Повторные Codex-вызовы для исторических пустых артефактов.

## Review resolution

- Luna implementation pass: `docs/tasks/436/review-implementation-luna.md`. Findings checked against current code; receipt IDs now include round, migration is one transaction with backup, conflicting replays fail, outcome CAS checks the winner, terminal artifact facts are scoped to successful/current execution, receipt linkage is best-effort after job creation, and the returned text exposes `receipt_id` without changing the existing structured envelope.
- Sol targeted pass: `docs/tasks/436/codex-review-sol.md`, one fresh `gpt-5.6-sol` session. Four blockers were checked: `--apply` now creates a durable backup before `init_db()`, apply requires SHA-256 and size, replay conflicts compare the complete candidate row, and every scratch path includes the receipt id. No second Sol round is permitted.
