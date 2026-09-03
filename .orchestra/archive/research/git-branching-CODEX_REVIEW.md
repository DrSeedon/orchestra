## Tests
Не применимо — ревью дизайн-документа.

## Summary
Идея “ветка = PAR-задача” рабочая и хорошо попадает в текущую боль system workers. Но дизайн пока недооценивает существующее поведение merge/create worktree: dirty tree silently auto-commit'ится, ветка может быть удалена через `branch -D`, а merge/switch не привязаны к состоянию живого агента. Для MVP не нужно больше абстракций, но нужны жёсткие git/state guardrails, иначе можно смержить незавершённую работу или потерять незамерженную ветку при коллизии имени.

## Замечания
blocking: docs/research/git-branching-design.md:11 + app/workspace.py:97 — дизайн говорит, что merge просто мержит текущую ветку и линкует PAR-коммиты, но реальный `merge_worktree_to_main()` при dirty tree делает `git add -A` и `git commit -m "auto-save: {branch}"`. Это может замержить незавершённые файлы system worker'а, а auto-save commit не содержит `PAR-N`, поэтому не попадёт в task link. Фикс: для PAR-веток merge должен fail loud на dirty tree; worker обязан явно закоммитить с `PAR-N` перед merge.

blocking: docs/research/git-branching-design.md:67 + app/main.py:427 — merge endpoint не проверяет, что агент idle/done; он берёт worktree и сразу вызывает `merge_worktree_to_main()`. Если orchestrator вызовет `merge_worker` пока worker ещё пишет, текущий auto-save подхватит промежуточное состояние. Фикс: `merge_session` должен reject'ить loaded session со статусом `running`, а для unloaded session хотя бы проверять dirty и возвращать ошибку без auto-commit.

blocking: docs/research/git-branching-design.md:70 + app/manager.py:286 — switch branch описан как `checkout` + update `session.branch`, но нет crash recovery. Если процесс упадёт после checkout и до `save_session`, БД и prompt останутся на старой ветке; `_load_from_db()` потом форматирует worker prompt из `db_row["branch"]`. Фикс: при загрузке/перед send читать фактическую ветку из worktree и reconciliate DB, либо хранить временное состояние `switching` и завершать/откатывать switch при старте.

blocking: docs/research/git-branching-design.md:232 + app/workspace.py:86 — merge lock защищает только два merge между собой; он не защищает `switch_branch` и не защищает worktree от активного worker process. Утверждение “второй merge ждёт, безопасно” слишком широкое. Фикс: добавить per-session/worktree lock и использовать его в merge, switch, stop/change-model/send нового задания; минимум для MVP — reject switch/merge если session не idle.

blocking: docs/research/git-branching-design.md:407 + app/workspace.py:47 — существующий `create_worktree()` при любой ошибке делает `git branch -D branch`, затем повторяет worktree add. Для `PAR-192/backend` коллизия имени становится опасной: если ветка уже существует и не checked out, можно удалить незамерженные коммиты. Фикс: перед созданием проверять `git show-ref --verify refs/heads/{branch}`; при существующей ветке возвращать collision или создавать suffix, но никогда не делать `branch -D` для ветки, созданной не текущей попыткой.

blocking: docs/research/git-branching-design.md:245 + app/workspace.py:141 — текущий merge выполняет `git merge branch` в основном repo и фактически мержит в текущий checked-out HEAD, а не гарантированно в `main`. Дизайн сам признаёт риск, но ставит это в фазу 3, хотя это must-have до PAR-веток. Фикс: перед merge проверять `git symbolic-ref --short HEAD == main` или отказаться от checkout-based merge и обновлять `refs/heads/main` через plumbing после precheck.

suggestion: docs/research/git-branching-design.md:155 + app/workspace.py:43 — `create_worktree()` сейчас вызывает `git worktree add wt -b branch` без start point, значит новая ветка стартует от текущего HEAD основного repo, не обязательно от `main`. Для PAR-веток это ломает “fresh branch from main”. Фикс: передавать явный base ref: `git worktree add wt -b branch main` или проверенный SHA `refs/heads/main`.

suggestion: docs/research/git-branching-design.md:337 + app/session.py:605 — план добавляет только `sessions.task_id`, но в живом коде persistence проходит через `AgentSession._to_db_dict()`, `save_session()`, `_load_from_db()` и `to_dict()`. Если не добавить поле во все эти места, `task_id` будет теряться после первого `save_session()`/resume. Фикс: добавить `task_id` в dataclass, DB insert/update, API response и load path.

suggestion: docs/research/git-branching-design.md:291 — нормализация `task_id.upper().replace("PAR-", "")` принимает мусор вроде `abc`, `PAR-1/foo` или `PAR-1..2` и превращает его в имя branch/ref. Фикс: принимать только `^(PAR-)?\d+$`, хранить нормализованное `PAR-N`, а имя ветки проверять через `git check-ref-format --branch`.

suggestion: docs/research/git-branching-design.md:226 — optional `merge_worker(name, branch=...)` предлагает делать `git checkout {branch}` в worker worktree перед merge. Это лишний write-path и новый источник конфликтов, особенно если worker dirty/running. Фикс для MVP: убрать override или мержить указанный branch из common repo без checkout worktree; текущая ветка покрывает основной сценарий.

suggestion: docs/research/git-branching-design.md:53 + app/db.py:98 — Task Manager уже имеет `worker_session_id`, а `update_task()` умеет его писать, но дизайн оставляет `task_update(PAR-192, status="done") if needed`. Если `spawn_worker(task_id=...)` вводится именно для привязки, стоит минимально связать task lifecycle: spawn ставит `in_progress` + `worker_session_id`, successful merge может предлагать/делать `done` только для этой задачи.

question: docs/research/git-branching-design.md:125 + app/prompts/orchestrator.md:124 — документ говорит, что prompt уже гарантирует “не отправлять новую задачу пока текущая не done/merged”, но текущий prompt в основном говорит “wait for DONE message” и “after merge spawn next worker”, без правила для повторного использования system worker через switch. Нужно явно обновить prompt: один active PAR на worker, sequence `DONE -> merge_worker -> switch_worker_branch -> send next task`.

question: docs/research/git-branching-design.md:71 — внутри документа есть противоречие: flow system worker говорит `git checkout main && git pull (in worktree)`, а ниже строки 153 и 260 правильно говорят не checkout'ить `main`, потому что он может быть checked out в основном repo. Фикс: оставить один канонический алгоритм: dirty check -> `git fetch` optional -> `git checkout -b new_branch refs/heads/main` без checkout main.

thought: docs/research/git-branching-design.md:415 — self-review предлагает тесты на branch naming, но самые рискованные места не naming, а git edge cases. Минимальный набор для уверенности: existing branch collision не удаляет ветку, dirty merge fails, merge while non-main HEAD fails, switch after merge creates branch from updated main, crash/reload reconciles actual branch.

## Вердикт
требует доработки.

## Round 2

### Проверка 12 пунктов

1. FIXED — auto-save при merge убран в дизайне: `merge_worktree_to_main()` теперь должен reject'ить dirty tree без `git add -A`/auto-commit (docs/research/git-branching-design.md:129-138, 255-260). Это закрывает главный риск незаметного попадания WIP в main.

2. FIXED — merge endpoint теперь явно должен проверять idle перед merge (docs/research/git-branching-design.md:62-65, 133-136, 333). В реализации важно проверять именно loaded `AgentSession.status`, а не только строку из DB.

3. STILL BROKEN — crash recovery закрыт только для `session.branch`, но не для `session.task_id`. При crash между `git checkout -b PAR-234/backend` и записью `session.task_id` `_load_from_db()` обновит branch из worktree, но task_id останется старым `PAR-192`; дальше task lifecycle и API response будут врать (docs/research/git-branching-design.md:220-223, 304-318). Фикс: при reconcile парсить `PAR-N/worker` из фактической ветки и обновлять `task_id`, либо хранить switch transaction state.

4. STILL BROKEN — idle guard не заменяет lock. Два параллельных HTTP/MCP вызова `switch_worker_branch` или `merge`/`switch` могут одновременно увидеть `idle + clean` и начать git операции; “orchestrator = single thread” не является системной гарантией, потому что есть HTTP API, MCP, Telegram/background paths и повторные клики (docs/research/git-branching-design.md:195-199). Фикс: per-session/worktree `asyncio.Lock` на уровне manager/API плюс git lock для repo-level merge.

5. FIXED — опасный `branch -D` fallback убран из плана; при `git show-ref` collision возвращается ошибка, ветка не удаляется (docs/research/git-branching-design.md:214-218, 249-253).

6. FIXED — проверка `HEAD=main` перенесена в фазу 1 и стала обязательным merge guard (docs/research/git-branching-design.md:133-136, 205-208, 322-330). При реализации checkout main должен fail'иться явно, если основной repo dirty или `main` checked out в другом worktree.

7. FIXED — `create_worktree()` теперь должен создавать ветку с явным start point `main`, а не от текущего HEAD (docs/research/git-branching-design.md:55-58, 242-253).

8. FIXED — `task_id` добавлен во все persistence paths: dataclass, `_to_db_dict()`, `save_session()`, `_load_from_db()`, `to_dict()` (docs/research/git-branching-design.md:290-302).

9. FIXED — добавлена строгая validation для `task_id` и проверка branch name через `git check-ref-format --branch` (docs/research/git-branching-design.md:45-46, 236-240, 329-331).

10. FIXED — `merge_worker(name, branch=...)` убран из MVP; merge только текущей checked-out ветки (docs/research/git-branching-design.md:129-131, 189-191).

11. FIXED — prompt update теперь явно описан: один active PAR на worker, `DONE -> merge_worker -> switch_worker_branch -> send next task` (docs/research/git-branching-design.md:142-146, 343-346).

12. FIXED — противоречие с `checkout main` в worker worktree убрано; канонический switch алгоритм использует `git checkout -b new refs/heads/main` без checkout main (docs/research/git-branching-design.md:88-101, 160-162, 210-212).

### Новые проблемы

blocking: docs/research/git-branching-design.md:122 — urgent flow говорит при возврате на старую задачу сделать `git merge refs/heads/main`, но алгоритм `switch_worktree_branch()` для существующей ветки только делает `git checkout {new_branch}` и возвращает ok (docs/research/git-branching-design.md:284-288). В итоге либо worker продолжит PAR-192 без изменений из PAR-999, либо merge-main будет неописанным вторым шагом с конфликтами/dirty state. Фикс: добавить явный режим `update_from_main=True` для checkout существующей PAR-ветки или вынести это в отдельный documented command/worker instruction с conflict handling.

suggestion: docs/research/git-branching-design.md:136 — “если repo HEAD не main — `git checkout main`” теперь must-have, но не описан guard на dirty основной repo. Если Максим вручную оставил изменения в основном checkout, `git checkout main` может отказать или смешать состояние с merge flow. Фикс: перед checkout main проверять `git status --porcelain` в основном repo; dirty main repo = reject с понятной ошибкой.

suggestion: docs/research/git-branching-design.md:284 — `switch_worktree_branch()` при existing branch делает `git checkout {new_branch}`, но не описывает случай, когда эта ветка уже checked out в другом worktree. Git откажет, и это нормальный recoverable case. Фикс: перед checkout проверять `git worktree list --porcelain` или просто превращать stderr в понятную ошибку “branch checked out in another worktree”.

### Финальный вердикт

NOT YET — основная архитектура уже рабочая, но до approval нужно закрыть per-session serialization и reconcile `task_id`; без этого остаются race и неверная привязка worker→PAR после crash/switch.

## Round 3

### Проверка 5 пунктов

1. FIXED — reconcile теперь парсит `PAR-N` из фактической ветки и обновляет `session.task_id` вместе с `session.branch` (docs/research/git-branching-design.md:335-356). Небольшая реализационная правка: лучше пересчитывать `task_id` не только при `actual_branch != session.branch`, а также когда branch совпадает, но сохранённый `task_id` пустой/не совпадает.

2. FIXED — добавлен per-session `asyncio.Lock`, и merge/switch/send/stop должны идти через него (docs/research/git-branching-design.md:195-213, 370-374). Это закрывает race двух запросов к одному worker. См. новую проблему ниже про repo-level `main` race между разными workers.

3. STILL BROKEN — идея `update_from_main` добавлена, но в документе осталась несовместимость контракта. `switch_worker_branch()` вызывает `switch_worktree_branch(worktree_path, new_branch, "refs/heads/main")` без флага (docs/research/git-branching-design.md:288-292), сама функция имеет `update_from_main: bool = False` (docs/research/git-branching-design.md:294-300), а urgent-flow ниже говорит “update_from_main=True by default for existing branches” (docs/research/git-branching-design.md:313-318). Фикс: сделать поведение однозначным: либо default `update_from_main=True` при existing branch внутри `switch_worktree_branch`, либо endpoint явно вычисляет `branch_exists` и передаёт `update_from_main=True` при возврате на существующую PAR-ветку.

4. FIXED — dirty guard для основного repo добавлен перед checkout/merge: `git status --porcelain` в основном repo, dirty → reject (docs/research/git-branching-design.md:219-225, 366-369).

5. FIXED — existing branch checkout теперь должен проверять `git worktree list --porcelain` и reject'ить ветку, checked out в другом worktree (docs/research/git-branching-design.md:302-309, 377-380).

### Новые проблемы

suggestion: docs/research/git-branching-design.md:199 — per-session lock не защищает чтение/использование `refs/heads/main` от merge другого worker'а. Например, worker A делает `switch_worker_branch` от `refs/heads/main`, пока worker B держит repo merge lock и двигает main; новая ветка A может стартовать не от самого свежего main. Не потеря коммитов, но нарушает обещание “fresh main”. Фикс: операции switch/create, которые читают `refs/heads/main`, должны брать тот же repo-level `.git/orchestra-merge.lock` хотя бы на время checkout/merge-from-main.

suggestion: docs/research/git-branching-design.md:302 — при конфликте `git merge refs/heads/main --no-edit` оставит worktree на целевой ветке в conflicted/dirty состоянии, а функция вернёт `{"ok": False, "conflicts": [...]}`. Это допустимо, но нужно явно описать contract: после такого ответа worker должен разрулить конфликт в уже переключённой ветке; повторный switch будет reject'иться из-за dirty tree.

### Финальный вердикт

NOT YET — остался один контрактный баг в `update_from_main`. После явного решения default/endpoint behavior для existing branch план можно approve'ить; остальные новые пункты можно закрыть как implementation notes.

## Round 4

### Проверка 3 пунктов

1. FIXED — `update_from_main` как параметр убран, контракт стал однозначным: existing branch всегда делает `git merge refs/heads/main --no-edit`, новая ветка создаётся от `refs/heads/main` (docs/research/git-branching-design.md:294-313). Это закрывает Round 3 `STILL BROKEN`.

2. FIXED — `switch_worktree_branch()` теперь берёт repo-level `orchestra-merge.lock`, общий с merge, перед чтением/использованием `refs/heads/main` (docs/research/git-branching-design.md:301-310, 313). Это закрывает race switch vs merge для main ref.

3. FIXED — конфликтный контракт описан явно: при conflict worktree остаётся на целевой ветке в conflicted state, повторный switch невозможен из-за dirty reject, orchestrator выбирает worker resolve или `git merge --abort` (docs/research/git-branching-design.md:307-308, 315-320).

### Новые проблемы

Новых blocking/suggestion проблем не вижу.

Implementation notes:
- docs/research/git-branching-design.md:303 — lock в коде должен быть через context manager / `try/finally`, чтобы conflict-return не оставил `.git/orchestra-merge.lock` залоченным.
- docs/research/git-branching-design.md:381 — в implementation plan осталось старое слово `update_from_main`; лучше переименовать фразу в “always merge main for existing branches”, чтобы не воскресить удалённый параметр при реализации.

### Финальный вердикт

APPROVED — план рабочий для MVP.
