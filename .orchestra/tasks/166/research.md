# #166 — `merge_worker` отдаёт SUCCEEDED, когда не смержено ничего

## Вопрос

- **Контекст:** `merge_worker` (MCP `app/mcp_stdio.py:1233`) поверх операций `app/merge_operations.py`.
- **Что проверяем:** каскад из постановки задачи — сбойный merge → `needs_switch` →
  `_auto_switch_before_delivery` заводит `adhoc-*` → расчётная ветка для мержа остаётся
  `feat/<scope>/<name>` → отпечаток совпадает → возвращается старая терминальная операция.
- **Базис:** текущий `main` (`d8f036c`).
- **Измеримый исход:** число коммитов в целевой ветке до/после повторного `merge_worker`
  и поля `git.status` / `worker_branch` / `worker_head` в ответе.

## Гипотезы и их фальсификаторы

| # | Гипотеза | Фальсификатор | Итог |
|---|----------|---------------|------|
| H1 | Ветка для мержа берётся по СХЕМЕ имени (`feat/<slug>/<name>`), поэтому расходится с фактической | Показать, что источник ветки — фактическое состояние worktree | **ОПРОВЕРГНУТА** |
| H2 | `_terminal_snapshot_matches` совпадает после переезда на adhoc и отдаёт старую операцию | Показать `MATCH: False` при смене ветки | **ОПРОВЕРГНУТА** |
| H3 | Стухший ответ приходит по НОВОМУ пути — повтору с тем же `operation_id` | Показать, что новый `operation_id` даёт честный мерж, а тот же — стухший ответ | **ПОДТВЕРЖДЕНА** |

## Находки

### F1 — расчётная ветка НЕ берётся из схемы имени. Гипотеза фикса из задачи не нужна. `ОПРОВЕРГНУТО`

`_session_snapshot` (`app/merge_operations.py:339-356`) читает ветку и HEAD прямо из worktree
через `inspect_worktree_identity` — то самое, что задача предлагала внедрить:

```python
branch, head = inspect_worktree_identity(row.get("worktree_path") or "")
```

Это единственный источник `accepted["worker_branch"]` (`:883`, `:896-901`), и он же
пересверяется в `_verify_accepted_snapshot` (`:359-378`) уже под claim. Схема имени
(`feat/<repo_slug>/<name>`, `app/workspace.py:508`) участвует только при СОЗДАНИИ worktree.

Тип доказательства: **прямое измерение** (тир 1) + чтение первоисточника (тир 2).
`git log -S"inspect_worktree_identity" main -- app/merge_operations.py` → строка существует с
момента появления модуля (`81ac2c3`), позже не менялась. То есть дефекта «ветка по схеме»
на текущем коде нет вовсе.

Измерение (стенд `tests/test_merge_branch_drift.py`, настоящий git):

```
adhoc: adhoc-1786018426-1/drift-worker  новый коммит: 93eac704
main до/после: 1 2
op id: cdf06d9d-...  is_stale: False
state: PARTIAL
git: {"commits_merged": 1, "worker_branch": "adhoc-1786018426-1/drift-worker",
      "worker_head": "93eac70431...", "target_after": "93eac70431..."}
```

Повторный `merge_worker` с НОВЫМ `operation_id` после переезда на adhoc сливает именно
adhoc-ветку: `main` вырос 1 → 2, `worker_branch` в ответе — фактическая adhoc-ветка.
Потери работы на этом пути нет.

### F2 — отпечаток терминальной операции ловит смену ветки. Кеш не сломан. `ОПРОВЕРГНУТО`

`_terminal_snapshot_matches` (`:194-203`) сравнивает `terminal_worker_branch` с
`accepted["worker_branch"]`, а accepted — живое состояние (F1). Прямой замер сравнения:

```
adhoc: adhoc-1786018459-1/drift-worker  head: 0a21cc94
accepted.worker_branch: adhoc-1786018459-1/drift-worker
terminal_worker_branch: feat/tmp-.../drift-worker
terminal_worker_head:   0a21cc94        ← HEAD СОВПАЛ
MATCH: False                            ← спасла ветка, не HEAD
```

Отдельно ценно: HEAD здесь совпал (adhoc заведён от той же точки, воркер ещё не коммитил),
и защитой сработала именно ветка. То есть в отпечатке полезны ОБА поля, убирать нельзя ни одно.
Тип доказательства: **прямое измерение** (тир 1).

### F3 — стухший ответ приходит по повтору с тем же `operation_id`. `ПОДТВЕРЖДЕНО`

`accept_merge_operation` (`app/merge_operations.py:865-872`):

```python
existing = await asyncio.to_thread(get_operation_record, canonical_id)
digest = request_hash(request)
if existing:
    if existing["request_hash"] != digest:
        return _idempotency_conflict(canonical_id, existing, digest), 409
    if existing["state"] == "PENDING":
        ensure_operation_runner(canonical_id)
    return existing["result"], 202 if existing["state"] in {"PENDING", "RUNNING"} else 200
```

На этой ветке сохранённый результат отдаётся **дословно**, и воркер не опрашивается ни разу:
ни `_session_snapshot`, ни `_terminal_snapshot_matches` до неё не доходят — обе защиты из F1/F2
живут НИЖЕ, в `accept_operation_snapshot`, куда управление уже не попадает.
`request_hash` считается по `{name, scope, target, next_task_id, squash}` — состояние воркера
в него не входит by design, поэтому переезд на adhoc-ветку хеш не меняет.

Путь достижим не случайно, а по инструкции: докстринг `merge_worker` (`app/mcp_stdio.py:1235-1239`)
и текст ответа на `PENDING/RUNNING` (`:1130`) прямо велят агенту повторять с ТЕМ ЖЕ
`operation_id`, а `operation_id` — публичный параметр тула (`:1233`).

Измерение — воспроизведение один в один с инцидентом VPN-Service:

```
adhoc: adhoc-1786018486-1/drift-worker   новый коммит: a7ab25fb
main до/после: 1 1                       ← в цели НОЛЬ коммитов
op id вернулся: ae5117ca-...  тот же: True
state: PARTIAL
git: {"status": "SUCCEEDED", "commits_merged": 3,
      "worker_branch": "feat/tmp-.../drift-worker",   ← ветка, где воркера УЖЕ НЕТ
      "worker_head": "7362d1c4...",                    ← HEAD до переезда
      "target_before": "000...0", "target_after": "111...1"}
next_action: {"code": "FINALIZE_SAME_OPERATION",
              "message": "Finalize this operation; do not repeat or manually apply the Git merge."}
```

Совпадение с инцидентом по всем наблюдаемым признакам: идентичный ответ при повторах, тот же
`operation_id` и `request_id`, `commits_merged: 3`, `git.status = SUCCEEDED`, `worker_head`
двухдневной давности, `target_before/after` из первой операции, ноль смерженного по факту.
Тип доказательства: **прямое измерение** (тир 1), 4 прогона подряд — красный 4/4.

### F4 — `git.status` живёт отдельно от `operation_state` и обманывает первым. `ПОДТВЕРЖДЕНО`

В воспроизведении `operation_state = PARTIAL`, но `git.status = SUCCEEDED`. Ровно это и читает
агент: `_merge_tool_result` (`app/mcp_stdio.py:1153+`) для PARTIAL печатает текст ошибки, но
`commits_merged: 3` и `git.status: SUCCEEDED` уезжают в структурированный результат. Инцидент
описан как «git.status SUCCEEDED» — то есть смотрели именно на это поле.
Тип доказательства: чтение первоисточника (тир 2) + измерение (тир 1).

### F5 — `next_action` запрещает единственную рабочую проверку. `ПОДТВЕРЖДЕНО`

`FINALIZE_SAME_OPERATION` (`app/merge_operations.py:573-576`, `:698-701`):
«Finalize this operation; do not repeat or manually apply the Git merge.»
Для честного PARTIAL (git-мерж прошёл, упала пост-стадия) формулировка верна. В сценарии F3
операция ВООБЩЕ НЕ ТА, и запрет «не повторяй» закрывает агенту единственный путь к правде.
Текст ничего не говорит про ПРОВЕРКУ артефакта — а именно проверка тут и нужна.
Тип доказательства: чтение первоисточника (тир 2).

## Контрдоводы и что осталось неподтверждённым

- **Каскад из постановки задачи описан по коду, которого нет.** Первопричина (первый PARTIAL
  → `needs_switch` → переезд на adhoc) верна и воспроизводится; неверно звено «расчётная ветка
  берётся по схеме имени» — оно опровергнуто в F1 прямым замером. Это тот случай из граблей
  проекта: поправка права про дефект и неверна про место.
- **Версия кода на VPN-Service не проверена.** Инцидент мог идти и по F3 (тогда объяснение
  полное), и по более старому коду без `inspect_worktree_identity`. Проверить нечем — доступа к
  тому контуру у меня нет. На ТЕКУЩЕМ коде живой путь ровно один: F3. `UNCERTAIN` только про
  историю инцидента, не про дефект.
- **F3 требует, чтобы агент передал `operation_id` явно.** Без него генерируется свежий UUID
  (`:1241`) и путь безопасен (F1). Но передача — не экзотика, а прямая инструкция докстринга,
  и в инциденте наблюдался именно один и тот же `operation_id` трижды.
- **Внешнего ревью нет.** Codex недоступен до 08.08 (квота исчерпана терминально). Всё выше —
  self-review; за вердикт независимой проверки не выдаётся.

## Затронутые файлы

- `app/merge_operations.py:865-872` — ранний возврат сохранённого результата без сверки с воркером (F3).
- `app/merge_operations.py:573-576`, `:698-701` — формулировка `FINALIZE_SAME_OPERATION` (F5).
- `app/mcp_stdio.py:1233-1241` — параметр `operation_id` и докстринг, велящий его повторять.
- `tests/test_merge_branch_drift.py` — стенд воспроизведения на настоящем git.

## Риски и краевые случаи для правки

- **Граница MCP↔route.** `app/mcp_stdio.py` подхватывается немедленно, `app/routes/` живёт в
  памяти systemd до рестарта. Правка не должна менять контракт так, чтобы старый route + новый
  MCP разъехались в окне до рестарта.
- **Идемпотентность ломать нельзя.** Повтор с тем же `operation_id` при НЕИЗМЕНИВШЕМСЯ воркере
  обязан по-прежнему отдавать тот же результат — иначе `STILL RUNNING`-протокол превратится в
  дубли мержей. Проверка должна отличать «воркер там же» от «воркер уехал».
- **Fail-closed в обе стороны.** Сверка обязана падать и когда воркер уехал, и когда воркера
  вообще не удалось опросить; «не смог проверить» ≠ «всё хорошо».
- **Гонка.** Сверка живого состояния на пути повтора добавляет чтение git вне локов операции.
  Ответ обязан оставаться честным и когда воркер уезжает ровно в этот момент.

## Источники

1. `app/merge_operations.py` (текущий `main`, `d8f036c`) — читан построчно.
2. `app/mcp_stdio.py:1040-1300` — читан построчно.
3. `app/manager.py:781-917` — `_auto_switch_before_delivery`, читан построчно.
4. `app/workspace.py:492-560`, `:1093-1200`, `:1691-1730` — читаны построчно.
5. `git log -S"inspect_worktree_identity" main -- app/merge_operations.py` — выполнен.
6. Замеры: `tests/test_merge_branch_drift.py`, логи `/tmp/pytest-166-{repro,probe,reuse,sameid,red}.log`.
