# V-620 — воркер после merge(continue) навсегда привязан к задаче

## Причина клинча

1. `merge_worker(task_outcome="continue")` финализирует задачу с `terminal_session.task_id = <та же>`,
   и `apply_merge_finalization` пересоздаёт ветку `task-<ref>/<name>` от цели (`force=True`).
   Итог: HEAD воркера == HEAD цели, прогон задачи (`review_receipts`, `subject_kind='task_run'`,
   `status='requested'`) остаётся открытым — так задумано для continue.
2. `merge_worker(task_outcome="complete", next_task_id=...)` доходит до `merge_worktree_to_main`,
   который при `target_before == worker_head` возвращает `NO_COMMITS_MERGED` («point to the same
   commit»). Финализация, единственное место, где прогон закрывается штатно, не запускается.
3. `switch_worker_branch` переключает git-ветку и зовёт `api_update_task_if_current(next,
   status="in_progress")` → `_open_task_run_for_task` → `db.task_run_receipt_open` видит открытый
   прогон этой же сессии для старой задачи → `ValueError: open task run conflicts with current
   assignment provenance`; роут откатывает ветку. `force=True` касается только git и не помогает.

## Решение (вариант C, выбран владельцем)

Мерж не менялся: отказ «ветка равна main» остаётся, пустых коммитов и новых типов квитанций нет.
Привязку снимает `switch_worker_branch`.

- `app/routes/sessions.py::switch_branch` — при переводе на ДРУГУЮ задачу, пока у сессии есть
  прежняя (`previous_task_id`), под session- и lifecycle-локом и ДО git снимается состояние
  ветки: `_unlanded_work` = `branch_wip_status(worktree, base_ref=<persisted base>)` +
  `inspect_worktree_identity`. Пусто (нет незакоммиченного, включая untracked, и нет коммитов
  `base..HEAD`) → `release_previous = {session_id, done_note, worker_head}` уходит в назначение
  новой задачи. Не пусто → привязка не трогается: обычный перевод идёт прежним путём (git сам
  отказывает на грязном/несмерженном без force; с force назначение падает на открытом прогоне и
  откатывается, к тексту ошибки добавлено, какую работу держит воркер), а `complete_previous`
  отказывает 409 до git. Ошибка чтения состояния считается «работа есть» (fail-closed).
- `app/tm.py::api_update_task_if_current(release_previous=...)` → `_release_previous_binding` в
  той же `BEGIN IMMEDIATE`-транзакции, что назначает новую задачу: отказ, если прежняя задача
  зарезервирована merge-операцией; по умолчанию — `release_session_task_binding(keep_task_id=новая)`
  (прогон `interrupted/binding_released`, задача → `new`, либо наследник, если на ней есть другой
  живой воркер); с `done_note` — отказ при других живых воркерах, прогон `completed`, задача
  `done`, `worker_session_id=NULL`. Провал назначения откатывает и выпуск.
  Ответ несёт `previous_tasks: [{task, outcome: released|done}]`.
- `app/db.py::task_run_receipt_finish(acceptance_note, worker_head)` — основание и HEAD
  закрытия пишутся в `verdict_value`/`verdict_present`/`worker_head` строки прогона (у task_run
  эти колонки раньше не использовались; ревью-строки читаются отдельно).
- `app/mcp_stdio.py::switch_worker_branch` — параметры `complete_previous`, `acceptance_note`;
  успешный текст называет судьбу прежней задачи. `complete_previous` несовместим с
  `force`/`promote_current`, требует непустой `acceptance_note` и наличие прежней задачи при
  другом `task_id` (иначе 400).

## Проверка

Интерпретатор `/home/kesha/orchestra/.venv/bin/python -m pytest`; импортированный app —
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/bench-opus55/app`.

`tests/test_switch_after_continue_620.py` — реальный git-репозиторий, реальные
`execute_merge_session(continue)`, `switch_worktree_branch`, `_existing_branch_verdict`;
БД и хранилище задач изолированы conftest. Задача 5 привязана `bind_task_to_session`
(открытый прогон), коммит, merge(continue) → HEAD воркера == main, прогон 5 открыт.

- `test_switch_releases_clean_worker_and_requeues_previous_task` — перевод на 6: задача 5 `new`
  без воркера, прогон 5 `interrupted/binding_released`, прогон 6 открыт, задача 6 `in_progress`
  за воркером, сессия на `task-6/<name>`.
- `test_switch_with_complete_previous_closes_task_as_done_with_note` — без note → 400 и ничего не
  тронуто; с note → 5 `done`, прогон `completed` с note и HEAD, 6 назначена.
- `test_switch_keeps_binding_while_worker_holds_unlanded_work[held × mode]` — незакоммиченный файл
  или несмерженный коммит × {plain, force, complete_previous}: привязка к 5 и её прогон целы,
  6 в очереди, сессия на 5; `complete_previous` → 409.

На коде без правки (`git stash push -- app`): `4 failed, 2 passed` — оба положительных теста
падают ровно с дословной ошибкой инцидента (`branch switch rolled back after task assignment
failed: ValueError: open task run conflicts with current assignment provenance`), плюс оба
`complete_previous`-варианта (параметра не было). Отрицательные plain/force без правки зелёные
— это прежние защиты. Мутация `_unlanded_work → всегда пусто` краснит
`[force-unmerged_commit]` и оба `[complete_previous-*]`; plain-варианты и force+uncommitted
держит сам git-слой переключения.

Обычный complete с реальными коммитами —
`tests/test_task_tracker_integration.py::test_t3_real_complete_merge_transfers_commits_before_closing_task`
(реальный git, задача done, main сдвинулся), входит в прогон ниже.

## Прогон затронутых модулей

31 модуль (все тесты, ссылающиеся на merge/switch/task-run/lifecycle-функции, плюс
`test_mcp_stdio.py`, `test_reducer_role.py`): `1 failed, 726 passed` за 128 с. Единственный
красный — `tests/test_work_acceptance.py::test_failed_acceptance_still_blocks_new_work_without_review`
(`inconclusive` вместо `failed`): красный и на коде без правки (проверено отдельным прогоном с
`git stash push -- app`), причина уже записана в TODO.md — литерал `python` в оракуле, которого
нет на PATH рантайма. К V-620 не относится.

## Остаточный риск

- Поведение по умолчанию изменилось для любого чистого воркера с прежней задачей: перевод
  возвращает её в очередь (`new`). Раньше без открытого прогона (старые задачи) она молча
  оставалась `in_progress` за ушедшим воркером, с открытым — перевод падал.
- «Несмерженные коммиты» считаются как `git log base..HEAD`: ветка, уже слитая сквошем, но не
  сброшенная на базу, выглядит несмерженной — привязка сохраняется (fail-closed), закрывать её
  тогда надо мержем.
- С `force=True` и несмерженными коммитами перевод, как и раньше, сначала переключает git с
  force и лишь потом откатывается на провале назначения; судьбу коммитов при таком откате эта
  задача не меняла и отдельно не проверяла.
- Через live MCP-клиент не прогонялось. Python-правки (`app/routes`, `app/tm.py`, `app/db.py`,
  `app/mcp_stdio.py`) заработают только после рестарта Orchestra, который инициирует владелец.
