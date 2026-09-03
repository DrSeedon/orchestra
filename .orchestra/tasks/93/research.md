# #93 — атомарные spawn/switch/task переходы: исследование

## Вопрос и критерий ответа

**Контекст.** После T1–T5 Git merge уже умеет выбирать реальную target-ветку,
откатывать неудачный squash и ждать явного конца turn. T6 должен закрыть переходы,
в которых Git-состояние, строка `sessions`, `needs_switch` и статус задачи меняются
разными шагами.

**Изменение под проверкой.** Общий порядок блокировок и success-bound запись
состояния для `spawn_worker → create_session`, `send` с `needs_switch`, отдельного
`switch_worker_branch` и `merge_worker(next_task_id=...)`.

**Baseline.** Текущая комбинация предварительных проверок, manager session lock,
`AgentSession._lifecycle_lock`, repo flock и нескольких независимых SQLite-записей.

**Измеримый outcome.** После любого успеха память, DB, actual branch/HEAD/index и
task status описывают одно состояние. После любого отказа до commit point все эти
состояния остаются прежними. Два конкурентных вызова имеют тот же результат, что
один из двух допустимых последовательных порядков. Ошибка обязана называть
частичный успех, если откат уже небезопасен.

## Гипотезы и фальсификаторы

1. **H1:** два одинаковых HTTP spawn в одном процессе создают два worktree, потому
   что duplicate-check не защищён lock. **Фальсификатор:** первая coroutine должна
   опубликовать UNIQUE reservation до первого `await`, и вторая должна увидеть её.
2. **H2:** ранняя строка `sessions` является безопасной reservation. **Фальсификатор:**
   `ensure_loaded` способен гидратировать её до завершения spawn и запустить backend
   не в созданном worktree.
3. **H3:** `needs_switch` является линейным gate перед новым turn. **Фальсификатор:**
   `send` проходит guard до merge, а после merge начинает turn при
   `needs_switch=true`.
4. **H4:** failure из `switch_worktree_branch` не меняет репозиторий. **Фальсификатор:**
   busy target или conflict меняет branch/ref/HEAD/index при `ok=false`.
5. **H5:** bare task number однозначно определяет задачу. **Фальсификатор:** один
   `par_number` существует в нескольких проектах живой DB.

## Предварительный гейт: ревью T3

До исследования T6 production-only diff коммита `4badfa3` был передан Codex с
точным ограничением на `app/workspace.py`, `app/tm.py`, `app/routes/sessions.py` и
`app/mcp_stdio.py`. Первый инфраструктурный запуск завис при обновлении model cache;
повтор того же review-session на 197 строках production diff завершился вердиктом
**APPROVED**, без blocking/suggestion/question. Codex отдельно проверил rollback
related/unrelated commit failures, child reset и нормализованный link DTO [S1].

## Findings

### F1. Точный same-name/same-scope race в текущем single-process пути не воспроизводится

**CONFIRMED / исходная формулировка REFUTED** — direct measurement + DB constraint.

`create_session()` синхронно делает `get_session_by_name()` и `save_session()` до
первого `await`; `sessions` имеет `UNIQUE(name, scope)` [S2][S3]. В одном uvicorn
event loop вторая coroutine не может вклиниться между этими операциями. В разных
процессах окончательным арбитром остаётся SQLite UNIQUE.

```text
E1 same-scope asyncio.gather:
results=[('A','ok',<uuid>),
         ('B','ValueError',"worker 'same' already exists ...")]
duplicate_check_results=[None,<first uuid>]
db_rows=1 registry=1

E2 forced cross-thread precheck interleaving:
one INSERT won; second INSERT -> UNIQUE constraint failed: sessions.name, sessions.scope
```

Следствие: отдельный lock не нужен для исправления несуществующего «двойного
успеха». Но ранняя DB reservation создаёт другие, подтверждённые дефекты F2–F4.

### F2. Reservation публикуется как обычный IDLE worker и может ожить в primary checkout

**CONFIRMED** — deterministic barrier experiment.

До `create_worktree()` в DB сохраняется `AgentSession` с default `IDLE`, исходным
`cwd`, пустыми `worktree_path`/`branch`; registry заполняется только после Git и
`session.start()` [S2]. `get_by_name` и `ensure_loaded` не различают reservation и
готовую строку: DB-only row гидратируется в отдельный object/lock [S2].

```text
E3 while create_worktree was blocked:
during_spawn={loaded:true,cwd:<primary repo>,worktree:null,registry_object:true}
after_spawn=same DB id, different registry object,
            final cwd=<worktree>, provisional cwd=<primary repo>
```

Конкурентный `send` способен стартовать backend в checkout владельца, после чего
завершающийся spawn заменит registry object. Per-object lifecycle lock этого не
лечит: locks принадлежат двум разным объектам.

### F3. Cancellation во время `asyncio.to_thread(create_worktree)` оставляет orphan

**CONFIRMED** — real Git + blocked thread.

Отмена `await asyncio.to_thread(...)` не останавливает системный thread. Exception
handler видит ещё пустой `session.worktree_path`, удаляет DB row и возвращает
cancelled, а thread позднее заканчивает `git worktree add` [S2].

```text
E4:
create_task=cancelled
after_cancel_rows=0; task=in_progress
thread_result=('ok','task-1/cancelled')
after_thread_worktree_exists=true; git_worktree_count=2
```

Все мутирующие spawn-thread операции должны закончиться до compensation. Простое
`except CancelledError` без shield/await не закрывает этот механизм.

### F4. DB identity и Git/worktree identity расходятся для cross-project spawn

**CONFIRMED** — two-source code trace + real Git barrier experiment.

MCP сохраняет caller `SCOPE`, даже если `repo_path` указывает на другой проект
[S4]. DB identity — `(scope,name)`, но filesystem identity —
`<repo_slug>/<name>`, а branch identity — `task-<id>/<name>` [S3][S5]. Поэтому две
сессии с разными scope проходят DB UNIQUE, но сталкиваются в одном repo/path/ref.
`create_worktree` сейчас не входит в repo flock.

```text
E5 two scopes, same repo/name:
both manager calls failed inside Git
session rows=[]; both tasks=in_progress
primary worktree only; orphan refs task-1/same and task-2/same remain

direct barrier:
.git/worktrees/same-name/index.lock contention; both orphan refs remain
```

Текущая live DB не содержит уже сложившейся коллизии: 111 non-archived rows,
0 duplicate `(name,scope)`, 0 duplicate nonempty `worktree_path`; из 93 доступных
worktree `.git` записей нет duplicate `(git-common-dir,name)` [E12]. Это
counter-evidence распространённости, но не опровержение воспроизводимого race.

### F5. Spawn меняет task до всех fallible шагов и стирает archive до валидации

**CONFIRMED** — failure injection + code order.

Порядок сейчас: delete archived row → validation → initial session save →
`api_update_task(...in_progress)` → Git/scaffold/save/start/registry [S2]. Exception
cleanup удаляет новую session/worktree, но не возвращает task status и не может
восстановить archived logs.

```text
E6 create_worktree failure:
error=RuntimeError('simulated worktree failure')
task_updates=[('93',{'status':'in_progress'})]
session_rows_after_rollback=0

E7 second-save failure after real Git:
session_rows=0; task=('in_progress', revision=1)
worktree removed; branch task-1/fail retained

E8 invalid base after archived row existed:
archived_rows_after_failure=0
```

Task transition должен идти только после готового worktree, `session.start`, final
session publication и registry insertion. Удаление archive и INSERT новой строки
должны быть одной короткой DB transaction непосредственно в commit point.

### F6. `needs_switch` читается вне общего lock и не является send gate

**CONFIRMED** — deterministic interleaving.

HTTP send проверяет и сбрасывает `needs_switch` до manager session lock и до
`_lifecycle_lock`; explicit merge использует порядок session → lifecycle → repo и
записывает `needs_switch=true` под обоими locks [S6]. `SessionManager.send` сейчас
просто вызывает `AgentSession.send`, а background jobs и limit wake местами вызывают
`session.send` напрямую [S2][S7].

```text
E9 block merge after send's guard, then release merge:
merge_ok=true; send_ok=true
final_status='running'; final_needs_switch=true
guard_before_wait=false; guard_inside_lifecycle=true

E10 two concurrent sends on needs_switch worker:
git_switch_calls=2; persist_calls=2; sends=2
```

Точный gate должен жить в `SessionManager.send`, а все внешние wake/delivery paths
должны проходить через него. Порядок: manager session lock → при необходимости
lifecycle lock → repo lock → lifecycle persist; затем lifecycle lock отпускается,
но manager lock удерживается во время `AgentSession.send()`. Нельзя вызывать
не-reentrant `AgentSession.send()` при уже удерживаемом lifecycle lock.

### F7. `switch_worktree_branch(ok=false)` бывает разрушительным

**CONFIRMED** — два real Git experiments.

Функция делает `reset --hard from_ref` до repo flock и до проверки, занят ли target.
При conflict она оставляет target checkout, `MERGE_HEAD` и unmerged index, а route
трактует наличие `result.branch` как успех, очищает `needs_switch`, назначает task и
вызывает task update [S5][S6].

```text
E11a busy target + force:
result={ok:false,error:"checked out in another worktree"}
old task branch/head: 5cb1c6 -> main f4f90e
old commit unreachable from old branch

E11b conflict:
result={ok:false,branch:'task-2/worker',state:'conflict',conflicts:['shared.txt']}
actual branch=task-2/worker; index='UU shared.txt'; MERGE_HEAD=true
route persisted task_id=93, needs_switch=false; task -> in_progress
```

Для T6 выбран rollback, а не новая persisted conflict state: `ok=false` обязан
восстановить original branch/HEAD, target ref, чистый index и отсутствие MERGE_HEAD.
Это меньше schema/API изменений и сохраняет rolling compatibility MCP↔старый route.

### F8. `merge(next_task_id)` валидирует next task после успешного merge

**CONFIRMED** — route harness.

`next_task_id` нормализуется только после Git merge, commit linking, RAG scheduling и
persist `needs_switch=true` [S6].

```text
E12 next_task_id='not-a-task':
HTTP 500 Invalid task_id after merge result ok=true
persisted={task_id:'',needs_switch:true}
MCP renders the whole call as "Merge failed"
```

Синтаксис, project и наличие task должны проверяться до Git. Если сам merge успешен,
а последующий switch/task update нет, ответ обязан оставаться merge-success с явным
`switch`/`task_status` partial result; откатывать уже принятый merge опаснее.

### F9. Task number без project — реальная неоднозначность, не fixture edge

**CONFIRMED** — primary DB query in read-only mode.

Spawn, standalone switch и merge-next вызывают `api_update_task(par)` без project.
`resolve_task_ref` при bare number ищет глобально и бросает `ValueError`, если номер
есть в нескольких проектах [S2][S6][S8]. Callers глотают это как warning.

```text
E13 live DB (SQLite URI mode=ro; PRAGMA query_only=ON):
duplicate par_number across projects=111
24 distinct active numeric task refs: ambiguous=18, unique=5, missing=1
17 live scopes: mapped to tm_projects=11, unmapped=6
active task sessions in unmapped scopes=0
```

Задача должна резолвиться по `tm_projects.scope == session.scope`, а не по номеру.
Если scope не сопоставлен project, код обязан fail loud до Git для явного task_id,
а не возвращаться к глобальному поиску.

Codex оспорил этот источник identity: при cross-project spawn `repo_path` и scope
различаются, поэтому project якобы должен следовать repo. Live measurement отверг
эту альтернативу для текущего контракта MCP: из 20 cross-project worktrees 8 имеют
numeric task; 6 задач существуют **только** в project caller scope, 0 — только в
repo project, 1 — в обоих, 1 отсутствует в обоих. У 7/8 repo scope вообще не
зарегистрирован в `tm_projects` [E15]. Следовательно, authoritative task owner —
переданный caller `session.scope`; repo identity отдельно управляет только Git.

### F10. Текущий repo flock не межпроцессный

**CONFIRMED** — primary Python semantics measured directly.

Merge/switch/remove строят lock filename из process-randomized `hash(str(repo))`;
create lock не берёт вообще [S5].

```text
E14 two fresh Python processes, same repo string:
process_hash_a=-6232322252651945391
process_hash_b=7206289694431308350
same=false
```

Lock key должен быть стабильным digest canonical git-common-dir. Один repo lock
должен охватывать create/merge/switch/remove; в switch — preflight, mutation и
rollback целиком.

## Подтверждённый lock order и commit points

```text
spawn (новая identity):
  in-process (scope,name) spawn lock
    → stable repo flock внутри create_worktree
    → prepared session.start(persist=False)
    → shielded finalize без compensation после входа:
        one DB transaction: delete matching archived + insert ready session
        → registry publish (без await после DB commit)
        → project-scoped task status update

existing session lifecycle:
  manager.get_session_lock(session.id)
    → loaded AgentSession._lifecycle_lock
      → durable write-ahead quarantine before fallible Git mutation
      → stable repo flock
      → Git success
      → sessions lifecycle persist
    → release lifecycle lock
    → AgentSession.send() when applicable (it takes lifecycle itself)
```

SQLite transaction нельзя держать через `await` или Git. Git и task DB не могут
быть одной ACID transaction, поэтому их commit points должны быть упорядочены, а
post-Git task failure — возвращён как явный partial result, не ложный Git failure.
Write-ahead quarantine нужен не для обычного rollback, а для fail-closed recovery:
если process/rollback/persistence ломается после начала Git mutation, reload всё
равно видит `task_id=''`/`needs_switch=true`. После полного rollback прежний snapshot
восстанавливается; если restore DB не удался, durable quarantine остаётся.
Cancellation до `finalize` дожидается preparation и компенсирует Git. После запуска
shielded `finalize` cancellation дожидается результата и не удаляет опубликованный
worker. Между DB commit и registry assignment нет `await`, поэтому asyncio не может
вставить cancellation в эту пару; task update выполняется внутри того же shielded
finalize через thread и возвращает warning, если DB task write не удался.

## Инварианты реализации

1. Ready session не видна в DB/registry до окончания worktree/scaffold/start.
2. Cancellation ждёт окончания мутирующего thread, затем удаляет его результат;
   после ответа нет работающего thread, способного создать orphan.
3. Один `(scope,name)` spawn выполняется за раз; один canonical repo мутируется
   одним стабильным flock во всех процессах.
4. `needs_switch=true` означает `task_id=''`; ни один внешний fresh turn не
   начинается до успешного auto-switch и persisted `needs_switch=false`.
5. Обычный `switch ok=false` не меняет original/target refs, branch, HEAD, index,
   session DB, task DB. Если сам rollback не удался, ответ имеет отдельный
   `state=rollback_failed` с actual branch/HEAD/conflicts; route сохраняет
   quarantine snapshot (`task_id=''`, `needs_switch=true`) и не обновляет task.
   Central send gate блокирует новый turn, пока auto-switch не сможет получить
   clean tree. Ошибка quarantine persistence добавляется в partial result и loaded
   memory всё равно остаётся gated — молчаливого «ничего не изменилось» нет.
6. `needs_switch=false + task_id=N` означает clean index, actual
   `task-N/<name>` branch и совпадение memory/DB.
7. Task `in_progress` записывается только после Git + lifecycle/session success и
   всегда через project, однозначно полученный из session scope. Prevalidation
   сохраняет immutable task DB id + `sync_revision`; post-Git conditional update не
   делает повторный lookup по переиспользуемому par number.
8. Invalid/missing next task отклоняется до merge; failure после успешного merge
   маркируется как partial success, а не `Merge failed`.

## Counter-evidence и границы

- На текущем single-process server exact same-scope double-success не существует;
  добавлять глобальный spawn mutex вместо сохранения DB/OS арбитров было бы лечением
  симптома из старой версии. Lock нужен для publication/cross-scope Git identity.
- Live DB не содержит текущих duplicate worktree identities; race всё равно
  воспроизведён на real Git и должен быть закрыт до следующего cross-project spawn.
- `spawn_worker` остаётся двумя MCP↔HTTP операциями: create, затем initial send.
  T6 следует уже принятому AC «in_progress после worktree/session start», а не меняет
  rolling contract MCP↔route. Initial delivery failure уже возвращается явно как
  «worker created, task delivery failed» [S4].
- Remove не берёт manager/lifecycle lock — это соседний session/backend risk, который
  не входит в T6. При этом T6 переводит `remove_worktree` и cancellation cleanup на
  **тот же stable repo flock**, поэтому с create/merge/switch на уровне Git они не
  гоняются. Codex смешал эти два уровня блокировки; исключается только session-level
  remove/send coordination, не repo serialization.
- Синхронные task/link SQLite calls удерживают event loop внутри lifecycle lock. Это
  latency risk, но не доказанный state-corruption mechanism T6; task write в T6
  следует вынести через `asyncio.to_thread`, link transaction не менять.

## Затрагиваемые файлы и тесты

- `app/workspace.py`: stable repo lock; create serialization; transactional switch
  rollback.
- `app/db.py`: final ready-session insert с atomic replacement archived row.
- `app/session.py`: start без ранней persistence для unpublished session.
- `app/manager.py`: spawn lock/preparation/cancellation; central send gate; scoped
  post-success task update.
- `app/routes/sessions.py`: prevalidate next task; success-only persistence/update;
  общий manager send path.
- `app/bg_jobs.py`, `app/limit_wake.py`: внешние deliveries через manager gate.
- `app/tm.py`: scope→project task resolution без global fallback.
- `tests/test_workspace.py`, `tests/test_manager.py`, `tests/test_api.py`,
  `tests/test_bg_jobs.py`, `tests/test_limit_wake.py`, `tests/test_db.py`.

Обязательные real/deterministic tests: cancellation during blocked real
`create_worktree`; provisional row invisible; same repo/name across scopes; two
processes share one repo lock; busy-target force rollback; real merge conflict
rollback; merge/send barrier; two concurrent auto-sends; invalid next task before
Git; duplicate par in two projects selects session scope; spawn/switch failure does
not mutate task.

После сужения task/project или repo validation проверить все live
`sessions.scope` **и** canonical repos, полученные из существующих
`worktree_path/.git`/git-common-dir, в read-only режиме. Текущий baseline: 17 scopes,
93 доступных actual worktrees, 1 отсутствующий path.

## Источники

1. **[S1] Primary artifact:** `docs/tasks/93/codex-review-t3.md` и
   `/tmp/task93-t3-core.diff`.
2. **[S2] Primary source:** `app/manager.py` — `create_session`, `send`,
   `get_by_name`, `ensure_loaded`, `persist_lifecycle`.
3. **[S3] Primary source:** `app/db.py` — schema `sessions`, `save_session`,
   `get_session_by_name`, `delete_archived_session`.
4. **[S4] Primary source:** `app/mcp_stdio.py` — `spawn_worker`, `merge_worker`.
5. **[S5] Primary source:** `app/workspace.py` — `create_worktree`,
   `merge_worktree_to_main`, `switch_worktree_branch`, `remove_worktree`.
6. **[S6] Primary source:** `app/routes/sessions.py` — `send_message`,
   `merge_session`, `switch_branch`.
7. **[S7] Primary source:** `app/bg_jobs.py`, `app/limit_wake.py`,
   `app/tg_bridge.py`, `app/routes/system.py` — внешние delivery call-sites.
8. **[S8] Primary source:** `app/tm.py` — `get_project_by_scope`,
   `resolve_task_ref`, `api_update_task`.
9. **[E1–E15] Direct measurements:** временные SQLite/Git repositories under
   `/tmp`; live DB opened only via SQLite URI `mode=ro` plus
   `PRAGMA query_only=ON`. Ни одна live DB row или live worktree не изменялась.
