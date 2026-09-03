# Задача #90 — аудит lifecycle worktree / merge

Дата: 2026-07-26

База аудита: `2ec163a` (`fix: worktree naming by repo root; drop auto-commit of user WIP on spawn`)

Фаза: 1, только исследование; код не изменялся

## Вопрос и критерий

**Контекст:** создание, merge, switch, повторное использование и удаление worker-worktree в
`app/workspace.py`, spawn/state restore в `app/manager.py`, HTTP lifecycle в
`app/routes/sessions.py`, MCP-контракты в `app/mcp_stdio.py`.

**Проверяемое изменение:** заменить догадки по имени каталога, комментариям и локальному
`main` на проверяемые Git-факты и один хранимый lifecycle-контракт.

**Baseline:** код в `2ec163a`, включая уже внесённые исправления repo-slug и удаления
`_auto_commit_if_dirty`.

**Критерий:** spawn/merge/switch/remove должен:

1. работать в `main`, `master` и parent-feature сценариях;
2. не менять и не прятать пользовательский WIP;
3. возвращать успех только после фактического Git/DB-успеха;
4. хранить отдельно фактическую ветку worktree и ветку-базу;
5. не требовать от LLM ручного `stop_worker` для штатного DONE → merge;
6. не оставлять DB/task/worktree в противоречащих состояниях.

## Гипотезы

### H1 — четыре заявленных дефекта изолированы

Каждый симптом вызван одной локальной ошибкой: guard checked-out target, литерал `main`,
форматирование результата линковки, слишком ранний merge.

**Фальсификатор:** те же факты независимо вычисляются ещё в одном месте либо исправление
симптома оставляет spawn/switch/remove с тем же отказом.

### H2 — общий механизм системный

Lifecycle хранит один факт несколькими способами (`scope`/repo, `branch`/base,
Git status/session status, task row/result DTO), а копируемые при spawn данные не имеют
явной политики обновления.

**Фальсификатор:** полный поиск call-site и временные репозитории показывают единый источник
для каждого факта и отсутствие расхождений после merge/reconnect/failure.

**Итог:** H1 опровергнута, H2 подтверждена. Четыре заявленных бага реальны, но их blast
radius шире: найдено ещё восемь подтверждённых lifecycle-дефектов.

## Метод и доказательства

- Прочитан весь набор символов `app/workspace.py`; отдельно пройдены spawn/state restore в
  `app/manager.py`, send/merge/switch/wip/delete в `app/routes/sessions.py` и MCP-обёртки.
- Git-утверждения проверены в изолированных репозиториях через
  `tempfile.TemporaryDirectory(..., dir="/tmp")`, `git init`, реальные worktree и реальные
  commit/reset/merge. Временные каталоги удалены контекстным менеджером.
- Task-link проверен на отдельной SQLite через `ORCHESTRA_DB_PATH=/tmp/...`; live DB не
  изменялась.
- Timing DONE → turn-end измерен read-only запросом к
  `/mnt/data/Projects/Python/orchestra/data/orchestra.db`.
- Живые `worktrees/` и записи live DB не изменялись.

## Заявленные дефекты

### D1 🔴 Merge в checked-out ветку parent заблокирован

**Статус: CONFIRMED — прямой Git-эксперимент + код guard.**

**Механизм.** `merge_worktree_to_main()` всегда выбирает primary checkout через
`_resolve_repo()`. До merge он вызывает `_is_branch_checked_out_elsewhere(repo, target,
Path(repo))` и возвращает ошибку, если target принадлежит linked worktree. Для
worker-spawns-worker это штатное состояние: parent feature-ветка checked out в parent
worktree, child ответвлён от неё.

**Эксперимент E1.**

```text
canonical checkout rc=128:
fatal: 'parent-feature' is already used by worktree at '/tmp/.../parent1'

worktree .../child1
branch refs/heads/task-90/child
worktree .../parent1
branch refs/heads/parent-feature

merge in target worktree rc=0; parent HEAD=parent-feature; child file=child
```

Git запрещает второй checkout target, но `git merge --squash child` в worktree, который
уже владеет target, работает.

**Предлагаемый фикс.**

1. Разрешать target-ветку в `git worktree list --porcelain` в конкретный checkout path.
2. Если target уже checked out, выполнять precheck/squash/commit именно там; если нет —
   сохранять нынешний primary-checkout path.
3. Перед изменением target требовать чистое дерево; не прятать WIP автоматически.
4. Оставить общий repo lock и после успеха reset child-worktree к target commit.

**Риск.** Merge меняет файлы parent worktree, из которого parent может продолжать текущий
turn. Нужны clean-tree preflight и тест, что меняется только target checkout, а child
сбрасывается после commit. Блокировать `running` parent нельзя: именно parent вызывает
`merge_worker` из активного turn.

### D2 🔴 `main` — не дефолт, а размноженный литерал

**Статус: CONFIRMED — три Git-эксперимента и полный поиск литералов.**

**Механизм.** Открытый баг auto-switch — лишь один call-site:

- `manager._resolve_base_branch()` возвращает `"main"` для strategy=main и fallback;
- `workspace.create_worktree()` имеет fallback `"main"`;
- `mcp_stdio.merge_worker()` / route merge имеют default target=`main`;
- `mcp_stdio.switch_worker_branch()` / route switch /
  `workspace.switch_worktree_branch()` имеют default `refs/heads/main`;
- auto-switch в route `send_message()` явно передаёт `refs/heads/main`;
- MCP/route/workspace WIP сравнивают с `refs/heads/main`;
- route `delete_session()` проверяет `git rev-list main..HEAD`.

То есть master-only ломает не только auto-switch, но и default spawn, default merge,
WIP и безопасный kill. Parent-feature даёт ложный unmerged на kill.

**Эксперимент E2 — master-only после успешного merge.**

```text
repository HEAD branch=master
refs/heads/main reset rc=128:
fatal: ambiguous argument 'refs/heads/main': unknown revision
refs/heads/master reset rc=0: HEAD is now at ... #90: squash
HEAD-relative reset rc=0: HEAD is now at ... #90: squash
```

**Эксперимент E3 — kill guard.**

```text
master-only:
main..HEAD rc=128: fatal: ambiguous argument 'main..HEAD'
master..HEAD rc=0: 0

child уже сброшен к parent-feature:
child HEAD equals parent-feature=yes
main..HEAD count=1; parent-feature..HEAD count=0
```

**Эксперимент E13 — default spawn.**

```text
RuntimeError: git worktree add failed: fatal: invalid reference: main
explicit master branch=feat/.../master-worker
```

**Контрпроверка E12.** У локального Git нет надёжного позднего ответа «какая ветка была
дефолтной»: после `master → checkout feature/current` symbolic `HEAD` равен
`feature/current`, а без remote `refs/remotes/origin/HEAD` отсутствует.

```text
initial branch=master; after checkout symbolic HEAD=feature/current
origin/HEAD rc=128: fatal: ref refs/remotes/origin/HEAD is not a symbolic ref
```

**Предлагаемый фикс.** Не угадывать default при каждой операции. Добавить один хранимый
факт `base_branch` к session:

- при spawn разрешить его один раз: explicit argument → parent branch для strategy=parent
  → проверяемый repo mainline для strategy=main;
- mainline разрешать независимо от текущего checkout: symbolic remote `HEAD`, либо
  единственная существующая well-known ветка из `main`/`master`; если обе существуют,
  remote `HEAD` отсутствует или repo использует иной trunk — fail loud и требовать
  explicit `base_branch`;
- fallback strategy=parent без доступной parent branch проходит через тот же resolver, а
  не возвращает строку `main`;
- MCP defaults сделать пустыми sentinel-значениями, route подставляет `session.base_branch`;
- explicit merge target обновляет `base_branch`;
- auto-switch, WIP и kill используют тот же `base_branch`;
- `branch` остаётся только фактическим именем ветки worktree.

**Риск.** Нужна additive DB migration и стратегия для старых rows без `base_branch`.
Нельзя молча заполнить их текущим primary `HEAD`: E12 доказывает, что это может быть
feature-ветка. Для legacy rows применяется тот же строгий resolver; неоднозначная row
остаётся без destructive lifecycle operation до явного ref.

### D3 🔴 Успешная линковка коммитов отображается как `FAILED — unknown`

**Статус: CONFIRMED — отдельная SQLite и реальный MCP renderer.**

**Механизм.**

1. `tm.link_commits_to_task()` записывает коммит и возвращает task-row; если задача не
   найдена — `None`.
2. `merge_session()` передаёт этот объект в `linked_tasks` без нормализации.
3. `mcp_stdio.merge_worker()` ожидает другой DTO: `{ok, added, error}`.
4. У task-row нет `ok`, поэтому успешная запись печатается как ошибка без `error`.
   `None` для неизвестной задачи вообще не выводится.

**Эксперимент E5.**

```text
link return ok=None; added=None
stored=[{"hash": "abc1234", "message": "#90: merged", ...}]
MCP rendering=Merged 1 commit from branch task-90/w |
  ⚠️ 90: FAILED — unknown
```

**Предлагаемый фикс.** Сделать единый result-contract:
`{ok: true, added: N, task: ...}` либо `{ok: false, error: "task ... not found"}`.
Route не должен прокидывать внутренний task-row как transport result. Тест должен
проверять и DB `git_commits`, и MCP-текст.

**Риск.** Сейчас других call-site `link_commits_to_task()` нет, но внешний API может
зависеть от task-row. Безопаснее нормализовать в route либо изменить функцию и её
единственный call-site одним коммитом.

### D4 🔴 Merge сразу после DONE отвергается как `worker is running`

**Статус: CONFIRMED — live read-only measurement.**

**Механизм.** Явный `send_message(DONE)` доставляется родителю в середине turn. Worker
остаётся `RUNNING` до backend `turn_end`. Исправление `fe9a9b5` добавило polling на 2 с,
но timeout был выбран без измерения реального хвоста.

Read-only выборка за 2026-07-26: финальные worker-репорты без последующих tool-вызовов,
для которых следующий `turn ended` наступил в пределах 120 с.

```text
n=46  min=3.434s  avg=14.426s  max=43.820s
>2s: 46/46  >10s: 30/46  >20s: 6/46  >30s: 3/46
```

Юнит-тест `test_merge_waits_for_running_worker_to_finish_turn` не опровергает это: mock
меняет status на первом вызове `sleep`, поэтому тест проверяет только ветвление, не
production duration.

**Предлагаемый фикс.** Ввести явный awaitable lifecycle signal `turn_finished`, который
очищается при переходе в RUNNING и выставляется после обработки `turn_end`/interrupt/error.
`merge_session()` ждёт signal, затем под lifecycle lock повторно проверяет status.
MCP timeout должен покрывать тот же bounded server timeout. Не заменять 2 секунды другим
угаданным числом и не делать скрытый `stop_worker`: interrupt превращает нормальное
завершение в failed/interrupted turn.

`WAITING` не эквивалентен merge-ready: `finish_turn_status()` выставляет его при активном
background job, который позже может разбудить worker и начать новый turn. После signal
merge разрешён только при `IDLE`; при `WAITING` должен быть явный отказ/ожидание завершения
job, а не изменение worktree под будущим wake-up.

**Риск.** Status меняется в нескольких error/retry путях; event обязан обновляться одним
централизованным методом, иначе появится новый второй источник правды. Persistent Claude
listener нельзя ждать как task целиком — нужен именно turn signal. Нельзя ставить signal
раньше `finish_turn_status()`, иначе merge увидит прежний `RUNNING`.

## Найдено сверх задания

### X1 🔴 После merge `session.branch` не совпадает с реальной веткой

**Статус: CONFIRMED — Git-эксперимент E11.**

`_reset_worktree_to_ref()` делает `reset --hard <target SHA>`, но не checkout target.
Worktree остаётся на `task-90/<worker>`. Route затем пишет `found.branch = target`.
При reconnect `_load_from_db()` читает реальный branch и перезаписывает snapshot обратно,
заодно теряя сведения о merge target.

```text
merge result branch=task-90/branch-worker; target=main
actual worker branch=task-90/branch-worker; HEAD equals main=True
route assignment: found.branch = target
```

**Фикс:** разделить `branch` (фактический Git branch) и `base_branch` (target/base для
следующей операции); route после merge не должен лгать о checkout.

**Риск:** migration и UI/API consumers, которые могли неявно трактовать `branch` как base.

### X2 🔴 Squash commit failure оставляет partial state

**Статус: CONFIRMED — реальные rejecting pre-commit hooks, E9/E19.**

Оба merge-пути оставляют target checkout изменённым:

- `_cherry_pick_branch()` вызывает `git commit`, не проверяет return code и всегда
  возвращает `ok=True`;
- обычный related-history path замечает ненулевой commit rc и возвращает `ok=False`, но
  не сбрасывает уже staged squash diff к `old_head`.

```text
E9, unrelated:
result={'ok': True, 'commits_merged': 1, 'strategy': 'cherry-pick', ...}
HEAD-unchanged=True; staged=source.txt

E19, related:
result={'ok': False, 'error': 'squash commit failed: '}
HEAD-unchanged=True
status=A  child.txt
```

**Фикс:** в обоих путях проверять commit rc, включать stdout+stderr в ошибку и при любом
отказе после изменения target делать доказанный rollback index/worktree к `old_head`;
не reset-ить worker и не возвращать merged commits.

**Риск:** rollback нельзя делать после уже созданного commit или по неверному checkout;
нужны два теста с реальным hook failure (related/unrelated), проверяющие `HEAD`, index,
worktree status и неизменность worker branch.

### X3 🔴 Stash restore может превратить успешный merge в неразличимый failure

**Статус: CONFIRMED — реальный stash conflict, E10.**

Primary checkout с WIP автоматически stashed. Squash commit создаётся, child уже
сбрасывается к target, затем `stash pop` конфликтует. `finally` перезаписывает успешный
result на `ok=False`; error берётся только из stderr, хотя Git пишет конфликт в stdout.

```text
result={'ok': False, 'state': 'stash_pop_failed',
        'error': 'stash pop failed after merge: '}
main latest=#90: #90: child
worker-reset-to-main=True
main status=UU shared.txt
```

Повтор merge уже не исправляет состояние: child-коммиты сброшены, target-коммит существует,
а caller получил failure.

**Фикс:** рекомендуемый вариант — reject dirty target до merge и полностью удалить
auto-stash из merge path. Если stash сохраняется, result должен быть
`merged_restore_failed` с новым commit SHA и stdout+stderr; generic retry запрещён.

**Риск:** fail-loud clean precondition меняет прежнее удобство, но исключает скрытое
вмешательство в пользовательский WIP и частичный успех.

### X4 🔴 Remove/cleanup рапортует успех при оставшемся worktree

**Статус: CONFIRMED — controlled Git failure E8 и unloaded session E14.**

Есть два независимых механизма:

1. `remove_worktree()` логирует ненулевой rc `git worktree remove`, но не возвращает
   failure и не бросает exception. `cleanup_stale_worktrees()` без проверки добавляет
   path в `removed`.
2. `SessionManager.remove()` удаляет worktree только для session, находящейся в
   `self.sessions`. Detached DB session архивируется без cleanup.

```text
E8:
worktree remove failed: simulated git refusal
cleanup returned=['.../cleanup-worker']; path-still-exists=True

E14:
loaded-before=False; worktree-before=True
db-status-after=archived; worktree-after=True
```

**Фикс:** `remove_worktree()` должен вернуть success/raise; manager должен hydrate row до
pop и удалять worktree для loaded и detached session; archive выполняется только после
успешного удаления либо доказанного отсутствия path. Cleanup добавляет path в `removed`
только после фактического исчезновения.

`cleanup_stale_worktrees()` после `2ec163a` корректно обходит первый уровень независимо от
его имени; переменная `scope_dir` и логи `empty scope dir` теперь только врут читателю.
Реальной фильтрации по scope там нет. Переименовать в `repo_dir`, но не менять алгоритм.

**Риск:** kill старого повреждённого worktree начнёт честно падать вместо молчаливого
archive. Это требуемый fail-loud contract, но UI/MCP должны показать точную ошибку.

### X5 🟠 Repo slug коллизионен

**Статус: CONFIRMED — pure-function experiment E6.**

`_slugify(str(repo))` заменяет разные символы на `-` и обрезает результат до 80 знаков.
Два разных длинных repo path получили одинаковый slug:

```text
len(a)=80 len(b)=80 equal=True
slug=tmp-same-segment-same-segment-same-segment-same-segment-same-segment-same-segmen
```

При одинаковом worker name второй repo получит ложное `worktree already exists`.

**Фикс:** readable prefix + стабильный hash канонического repo path. Existing paths из DB
не мигрировать; новый формат применять только при новом spawn.

**Риск:** тесты, ожидающие точный `_slugify(path)`, нужно заменить проверкой
детерминированности/уникальности.

### X6 🟠 Копируемые config/skills остаются birth snapshots

**Статус: CONFIRMED — config experiment E7 + ранее зафиксированный live skill incident в
`BUGS.md`.**

`create_worktree()` копирует manifest `copies` один раз. Reconnect вызывает только
`sync_agents_md()`; прочие copies не обновляются. Отдельно manager инъектит
`.claude/skills/` только при spawn.

```text
source=VALUE=v2; worktree-after-reconnect-sync=VALUE=v1
```

Для `.claude/skills/` уже зафиксирован live-пример: давно созданный Claude-worker сохранил
удалённый из pipeline skill `self-analysis`.

**Фикс:** явно разделить immutable birth snapshot и managed mirror. `.claude/skills/`
синхронизировать exact-set атомарно на backend reconnect. Для arbitrary manifest copies
не включать слепой overwrite: либо документировать snapshot, либо добавить явный
`managed_copies` contract.

**Риск:** автоматическое обновление произвольного copied файла может затереть локальную
правку worker. Поэтому skills (полностью managed directory) и generic copies нельзя
чинить одной безусловной функцией.

### X7 🔴 Switch/state transitions не атомарны и оставляют partial conflict

**Статус: CONFIRMED — controlled async interleaving E15/E16 + реальный Git conflict E18.**

- route switch проверяет `running` **до** `manager.get_session_lock()`, под lock status
  не перепроверяет. Сообщение может запустить turn между проверкой и Git switch.
- auto-switch в route `send_message()` вообще не использует per-session merge/switch lock.
- route switch вызывает `api_update_task(..., in_progress)` даже при `ok=False`.
- при существующей `new_branch` `switch_worktree_branch()` checkout-ит её и делает
  `git merge from_ref`; при конфликте оставляет index в состоянии merge и возвращает
  `{ok: false, branch: ..., state: conflict}`. Route считает наличие `branch` достаточным,
  записывает новый `task_id`, сбрасывает `needs_switch` и затем ставит задачу in_progress.
- spawn ставит task `in_progress` до `create_worktree()`/`session.start()`; rollback session
  не возвращает task.

```text
E15: status when git switch called=running; result={'ok': True, ...}
E16: switch result={'ok': False, 'error': 'missing base'};
     task updates=[('2', {'status': 'in_progress'})]
E18: result={'ok': False, 'branch': 'task-2/worker',
             'conflicts': ['shared.txt'], 'state': 'conflict', ...}
     actual-branch=task-2/worker; unmerged=['shared.txt']
```

**Фикс:** один порядок lock для merge/switch/send-auto-switch; status recheck под lifecycle
lock. Task переводить в `in_progress` только после успешного spawn/switch. Switch обязан
либо rollback/`merge --abort` и восстановить исходную ветку при конфликте, либо ввести
отдельный resumable-conflict contract; текущее смешение failure с persisted success
недопустимо. Spawn failure не должен оставлять task начатой без worker.

**Риск:** lock ordering должен быть одинаковым в трёх routes, иначе возможен deadlock.
Нужны конкурентный тест и реальный Git conflict test, а не только happy-path mocks.

### X8 🔴 Merge state расходится с persistence

**Статус: CONFIRMED — реальный detached merge E17 + DB schema/call-sites.**

`manager.get_by_name()` намеренно возвращает `_hydrate_row(..., loaded=False)`, если
session отсутствует в live registry. `merge_session()` разрешает такой объект и выполняет
Git merge/linking, но обновление `branch`, `task_id` и `needs_switch` находится под
`if found.loaded`. Поэтому после успешного detached merge DB продолжает описывать старую
задачу и ветку. Дополнительно `needs_switch` отсутствует в schema и `save_session()`: даже
для loaded session это поле живёт только в памяти и теряется при рестарте. Тот же класс уже
проявляется в E14: detached row является штатным результатом lookup, но
`manager.remove()` ищет только `self.sessions` и пропускает worktree.

```text
E17:
lookup-loaded=False; merge-ok=True
before branch=task-90/detached task_id=90
after  branch=task-90/detached task_id=90
needs_switch-column=False
main-has-child=True
```

**Фикс:** lifecycle mutations должны иметь один persistence helper для loaded и detached
session: live object → поля + `_persist()`, detached → атомарный DB update. После merge
сохранять фактическую `branch`, очищать `task_id` и выставлять `needs_switch`; после
утверждения D2 отдельно сохранять `base_branch=target`.

**Риск:** detached status — DB snapshot, а не гарантия отсутствия живого backend в другом
процессе. Repo/session lock и проверка owner process должны предшествовать Git mutation;
простого `UPDATE sessions` после merge недостаточно.

## Counter-evidence и границы

- Main-only репозитории и чистый primary checkout скрывают D2/X3; существующие main-centric
  тесты зелёные, но это не опровергает master/parent-feature experiments.
- `cleanup_stale_worktrees()` успешно удаляет обычный clean stale worktree. X4 касается
  error path и detached session, где текущий код даёт ложный success.
- 2-second grace действительно убирает искусственный test race, если status меняется на
  первом poll. Live timing показывает, что production tail всегда длиннее в измеренной
  выборке.
- Direct merge в checked-out parent worktree доказан на clean tree. Поведение при dirty
  parent намеренно не принималось как допустимое: X3 показывает, почему auto-stash не
  является безопасной альтернативой.
- Default branch нельзя достоверно восстановить задним числом во всех локальных repo.
  Поэтому для legacy sessions остаётся migration-риск; он не замаскирован догадкой.

## Порядок работ

1. **T1 — единый branch/base contract.** Добавить `base_branch`, migration и resolution на
   spawn; убрать downstream defaults `main`; исправить `branch` после merge и единообразно
   persist loaded/detached rows. Обязательные tests: master-only default
   spawn/merge/switch/WIP/kill, parent-feature base и detached merge.
2. **T2 — merge в checkout владельца target.** Target-path resolution, clean preflight,
   no auto-stash, squash/commit/reset. Обязательный реальный Git test child → checked-out
   parent.
3. **T3 — честная commit/link транзакция.** Проверить commit rc normal/unrelated,
   rollback target к `old_head` на обоих failure paths, нормализовать link DTO.
   Обязательные real-hook tests для related/unrelated и SQLite+MCP test успешной
   линковки/unknown task.
4. **T4 — DONE → turn-finished synchronization.** Event/condition вместо 2-second guess,
   status recheck и lifecycle lock; тесты для Codex per-turn и Claude persistent модели.
5. **T5 — fail-loud remove/cleanup.** Detached session cleanup, ненулевой Git rc наружу,
   archive только после удаления; `scope_dir` → `repo_dir`.
6. **T6 — атомарный switch/task state.** Единый lock order, recheck, task mutation только
   после success; реальный conflict с доказанным rollback либо resumable state.
7. **T7 — identity/snapshot hardening.** Hash suffix для новых repo dirs; exact-set skill
   sync. Generic copied config оставить отдельным согласуемым contract, не смешивать с
   критическим merge patch.
8. После каждого изменения Git-валидации взять все живые `sessions.scope`, как требует
   задача, **и** actual repo каждого `worktree_path` через Git common-dir; объединить и
   дедуплицировать canonical repo paths. Иначе cross-project session проверит scope
   родителя вместо repo, переданного в `repo_path`. Отдельно прогнать полный pytest.

## Затрагиваемые файлы для Фазы 2

- `app/workspace.py`
- `app/manager.py`
- `app/routes/sessions.py`
- `app/mcp_stdio.py`
- `app/session.py` / `app/session_turns.py` — только если утверждён turn-finished signal
- `app/db.py` / `app/session.py` — если утверждён `base_branch` column
- `app/tm.py` — единый link result
- `app/prompting.py` — отдельный snapshot/skills ticket
- `tests/test_workspace.py`
- `tests/test_manager.py`
- `tests/test_api.py`
- `tests/test_mcp_stdio.py`
- task-manager tests для link contract

## Adversarial review

Codex Round 1 не завершился из-за инфраструктурного timeout. Содержательный Round 2 нашёл
три дыры: mainline ошибочно выводился из текущего checkout, related-history commit failure
не требовал rollback, а live validation смотрела только `sessions.scope`. Все три
перепроверены кодом/экспериментом, исправлены в этом документе и закрыты в Round 3.
Итог: **APPROVED**, новых findings в согласованной области нет.

Полный протокол: `docs/tasks/90/codex-review-audit.md`.

## Источники

1. Код `2ec163a`: `app/workspace.py`, `app/manager.py`,
   `app/routes/sessions.py`, `app/mcp_stdio.py`, `app/tm.py`,
   `app/session.py`, `app/session_turns.py`.
2. Git history: `2ec163a`; предыдущий merge grace `fe9a9b5`.
3. Direct experiments E1–E19, `/tmp`, 2026-07-26; raw ключевые outputs приведены выше.
4. Live SQLite read-only measurement, logs date `2026-07-26`, 46 terminal worker reports.
5. `BUGS.md`, Open + incident `.claude/skills/` от 2026-07-26.
