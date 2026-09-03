# #166 — отчёт

Разбор корня — в `research.md`. Здесь только сделанное.

## Что чинили

Гипотеза из постановки (расчётная ветка берётся по схеме имени) **опровергнута замером**:
`_session_snapshot` уже читает ветку из worktree и делал это всегда. Живой путь потери работы
один — **повтор `merge_worker` с тем же `operation_id`**, где сохранённый результат отдавался
дословно без единого обращения к воркеру. Согласовано с оркестратором как A′ вместо A.

## Коммиты

| Коммит | Что |
|---|---|
| `48612c0` | Воспроизведение: стенд на настоящем git + красный тест |
| `d4f3209` | **A′** — повтор `operation_id` сверяется с живым воркером |
| `c975daf` | **B** — формулировки перестали запрещать проверку артефакта |

## A′ — `app/merge_operations.py`

`accept_merge_operation`: ранний возврат терминальной записи разделён на активные и терминальные
состояния. `PENDING/RUNNING` возвращаются как раньше (протокол STILL RUNNING не тронут).
Терминальные проходят через новый `_replay_drift`:

- воркер там же (ветка И HEAD совпали с `accepted_*`) → прежний дословный результат, 200.
  Идемпотентность цела;
- воркер уехал → `FAILED` / `REPLAY_WORKER_MOVED`, 409. В сообщении и в `details` — обе ветки
  и оба HEAD, принятый и фактический;
- воркера не удалось опросить → `FAILED` / `REPLAY_VERIFICATION_FAILED`, 409.
  Fail-closed во вторую сторону: «не смог проверить» не читается как «всё хорошо».

Почему сверка здесь, а не в `accept_operation_snapshot`: до неё управление на этом пути не
доходит вовсе. `request_hash` считается по `{name, scope, target, next_task_id, squash}` —
состояние воркера в него не входит by design, поэтому переезд на adhoc хеш не меняет.

## B — `app/merge_operations.py` + `app/mcp_stdio.py`

Запрет на РУЧНОЙ мерж оставлен везде (11 мест) — он верен. Убран запрет на ПРОВЕРКУ:

- `next_action` `FINALIZE_SAME_OPERATION` (2 места): было «do not repeat or manually apply the
  Git merge», стало «do not manually apply the Git merge» + явное «Verifying the merged artifact
  is expected — check the target branch and worker_wip before reporting this task done»;
- докстринг `merge_worker`: сказано, что повтор `operation_id` подхватывает ТУ операцию, а не
  текущее состояние воркера, и что проверка артефакта не считается ручным мержем;
- текст STILL RUNNING: добавлено, что делать, если повтор отказан из-за переезда воркера.

Это не косметика: `operation_id` — публичный параметр тула, и докстринг с текстом STILL RUNNING
прямо ВЕЛЕЛИ агенту идти по единственному пути, где терялась работа.

## Приёмка — ДО и ПОСЛЕ на одном воспроизведении

Сценарий: PARTIAL → `_auto_switch_before_delivery` заводит adhoc → воркер коммитит → повтор
`merge_worker` с тем же `operation_id`.

**ДО** (`48612c0`, красный 4/4):

```
main до/после: 1 → 1                       ← в цели НОЛЬ коммитов
operation_state: PARTIAL
git.status: SUCCEEDED                      ← ЛОЖЬ
git.commits_merged: 3
git.worker_branch: feat/.../drift-worker   ← ветка, где воркера уже нет
git.worker_head: 7362d1c4...               ← HEAD до переезда
next_action: "Finalize this operation; do not repeat or manually apply the Git merge."
```

**ПОСЛЕ** (`c975daf`):

```
фактическая ветка: adhoc-1786019003-1/drift-worker | HEAD: 43e588933f00
main до/после: 1 / 1
operation_state: FAILED
git.status: FAILED                         ← больше не лжёт
git.worker_branch: adhoc-1786019003-1/drift-worker   ← ФАКТИЧЕСКАЯ
git.worker_head: 43e588933f00453d6585ccd1b9cdd9a606289c03
error.code: REPLAY_WORKER_MOVED
error.message: This operation was accepted for branch feat/.../drift-worker at 6d2ade19…,
  but the worker is now on branch adhoc-1786019003-1/drift-worker at 43e58893…. The stored
  result describes the earlier branch and says nothing about the worker's current commits.
error.details: accepted_worker_branch / accepted_worker_head / actual_worker_branch / actual_worker_head
next_action: "Check what is unmerged on adhoc-1786019003-1/drift-worker (worker_wip), then
  start a new operation with a fresh operation_id."
```

## Про `git.status` отдельно (спрашивали явно)

Проверено, **не в порядке было — стало в порядке**. Поле `git.status` живёт отдельно от
`operation_state`: в стухшем ответе снаружи PARTIAL, внутри `SUCCEEDED`, и инцидент читали
именно по внутреннему полю. После A′ на всех отказных путях `_base_result` для нетерминальных
состояний ставит `git.status = "FAILED"`, `commits_merged` отсутствует (0).

Закреплено тестом `test_refusal_never_reports_git_status_succeeded` — проверяет ОБА вида
расхождения (сменилась ветка; та же ветка, новый HEAD) и утверждает `git.status == "FAILED"`
и `commits_merged == 0`. Первая редакция этого теста из-за однострочника с walrus вызывала
фабрику дважды и не ждала корутину — ветка «сменилась ветка» тогда не проверялась;
переписано явным `if/else`, `RuntimeWarning` ушёл.

## Тесты

`tests/test_merge_branch_drift.py` — 7 тестов, стенд на настоящем git (без реальных веток
«в цели ноль коммитов» не доказать):

| Тест | Что держит |
|---|---|
| `test_replay_of_same_operation_id_after_worker_moved_is_not_success` | ЯДРО: повтор после переезда ≠ успех |
| `test_replay_of_same_operation_id_without_drift_stays_idempotent` | воркер не уехал → результат дословно тот же |
| `test_replay_refuses_when_worker_cannot_be_inspected` | fail-closed во вторую сторону |
| `test_refusal_never_reports_git_status_succeeded` | внутреннее поле `git.status` на обоих видах дрейфа |
| `test_finalize_action_no_longer_forbids_verification` | B: запрет на ручной мерж есть, на проверку — нет |
| `test_merge_after_adhoc_switch_does_not_report_stale_success` | страж F1 (зелёный и на main) |
| `test_stale_operation_is_not_reused_after_branch_change` | страж F2 (зелёный и на main) |

Прогон: `tests/test_merge_branch_drift.py` + `test_merge_operations.py` + `test_adhoc_switch.py`
— **38 passed, 4 прогона подряд** (асинхрон). Полный сьют не гонялся — запрещено без лока.

### Мутация (через `git show`, не `git stash`)

| Что откатывали | Маркер `grep -c` | Результат |
|---|---|---|
| весь A′ (`git show 48612c0:app/merge_operations.py`) | `_replay_drift` → 0 | ядро КРАСНЕЕТ |
| восстановление | `_replay_drift` → 2 | зелено |
| только B (`git show d4f3209:app/merge_operations.py`) | `worker_wip before reporting` → 0, `_replay_drift` → 2 | краснеет РОВНО B-тест, тесты A′ зелёные |
| восстановление | оба маркера на месте | 38 passed |

Раздельная мутация показывает, что тесты держат разные дефекты, а не один общий.

## Окно MCP↔route

`app/mcp_stdio.py` подхватывается немедленно, `app/routes/` живёт до рестарта. Изменения в MCP —
**только текст** (докстринг + строка STILL RUNNING), контракт не тронут. Функциональная часть
целиком в `app/merge_operations.py`. Ветка рендерера `FAILED/UNKNOWN` в `_merge_tool_result`
байт-в-байт совпадает с main (проверено `git diff main...HEAD` — совпадений по этой ветке нет),
поэтому старый MCP в памяти отрисует новый отказ уже имеющимся кодом. Рестарт не требуется и
не делался: на сервисе работают оркестратор и соседний воркер.

## Ревью

**Внешнего ревью нет.** Codex недоступен до 08.08 (квота исчерпана терминально). Всё выше —
self-review, за вердикт независимой проверки не выдаётся.

## Осталось неподтверждённым

Версия кода на VPN-Service не проверена — доступа к контуру нет. Инцидент мог идти этим путём
(тогда объяснение полное) либо по более старому коду. Отметка UNCERTAIN в `research.md`
сохранена намеренно. На дефект это не влияет: он воспроизведён на нашем main.

## Breaking

Нет. Меняется поведение ровно одного пути — повтора `operation_id` при УЕХАВШЕМ воркере: раньше
стухший «успех», теперь отказ 409. Повтор при неизменившемся воркере работает как прежде.
