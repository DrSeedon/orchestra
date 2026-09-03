<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну да, «research-only» — идеальный режим, чтобы спрятать четыре архитектурные мины под словом LIKELY 😏

## Summary

Проверены оба документа и все указанные ссылки на текущий код; логи, BUGS/TODO, git history и посторонние документы не открывались. Направление `scope != project` выглядит обоснованным, но есть 4 blocking findings и 6 non-blocking.

## Findings (blocking/suggestion/question)

### blocking

- `blocking:` В [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:437) `project_wait(question, task_ref="")` не может однозначно выбрать проект для orchestrator, который владеет несколькими проектами. `task_ref` опционален, а номера уникальны только внутри `project_id` (`app/tm.py:569-583`). Нужен явный `project_id` или project-qualified ref; иначе tool может записать wait и подавить watchdog не того проекта.

- `blocking:` [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:117) называет `scope` текущей границей task authorization, но `task_create`/`task_update` принимают явный `project`, который маршруты резолвят без проверки owner (`app/routes/tm.py:48-59,113-136,219-239`; `app/mcp_stdio.py:2762-2764,2823-2824`). Scope сейчас лишь default selector и binding boundary, а не универсальная изоляция.

- `blocking:` Replay в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:409) не содержит команды, скрипта, входного набора или правил pairing. Поэтому он не доказывает ни «верхнюю оценку», ни частоту реальных stalls, ни поведение существующего watchdog — только результат заявленной синтетической модели. Нужен воспроизводимый артефакт либо более узкая формулировка вывода.

- `blocking:` Seedon-процедура в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:284) опасна без явного обновления обоих parent-полей. Runtime перечисляет детей и отображает владельца через `parent_name` (`app/manager.py:1360-1381`; `app/mcp_stdio.py:1662-1671`), тогда как `parent_id` хранится отдельно. Изменение только immutable ID не перепривяжет детей в текущем runtime; изменение только имени создаст рассинхрон.

### suggestion

- `suggestion:` Числа из §6 в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:301) уже не воспроизводятся текущим read-only snapshot: при тех же 78 `in_progress` сейчас получается 26 archived, 17 без binding, 32 idle, 1 running и 2 waiting, тогда как в документе указаны 31 idle и 4 running. Добавьте timestamp, полный SQL и явное правило классификации `waiting`.

- `suggestion:` Оценка варианта B в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:228) не учитывает существующий IA project layer: `app/ia/runtime.py:451-508` поддерживает `scope → canonical_project_id`, а `:544-560` отдельно remap'ит `tm_projects`. Изменение semantics `tm_projects` затронет canonical task/knowledge identity и authorization; это нужно добавить в cost и migration scope.

- `question:` Число «32 scope seams» в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:126) не подтверждено ни перечнем seams, ни командой подсчёта в разрешённых артефактах. Как проверяем знаменатель и какие именно точки входят в эти 32?

- `suggestion:` Предложение удалить `notify_user` в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:479) шире, чем замена project-wait. Текущий tool также обслуживает incidents, reversed conclusions и plan-changing results (`app/mcp_stdio.py:2111-2120`), а TG bridge реально доставляет marker (`app/tg_bridge.py:3278-3280,3392-3409`). Нужен отдельный replacement/taxonomy для этих случаев.

- `suggestion:` Раздел `/goal` в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:490) смешивает CLI/desktop `/goal` с host tool surface `create_goal/get_goal/update_goal`. Официальная документация подтверждает goal и задаёт лимит objective в 4 000 символов, но не подтверждает описанный здесь `blocked`-контракт; эти поверхности и лимиты нужно разделить. [Официальная документация OpenAI](https://learn.chatgpt.com/docs/developer-commands?surface=cli)

### question

- `question:` Формулировка «30 минут = шесть проверок» в [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:22) допускает off-by-one: проверки на `t=0,5,...,25` дают шесть наблюдений, но лишь 25 минут elapsed time. Уточните, что является контрактом — 30 минут по `actionable_since` или шесть интервалов между семью наблюдениями.

## Verdict

**CHANGES REQUESTED.** Исследование нельзя считать APPROVED до устранения неоднозначности `project_wait`, фиксации реальной authorization boundary, добавления воспроизводимого replay и безопасной Seedon migration procedure. Файлы не изменялись.

Пока это не доска проектов, а шкаф с ярлыками `scope`, где часть папок уже ждёт владельца, а остальные просто надеются, что их правильно посчитали.

## Author resolution before Round 2

- ACK blocking 1: `project_wait` now requires exact `project`; owner membership is checked from immutable caller identity.
- ACK blocking 2: research now says scope is only the default selector/binding boundary and names the unguarded explicit-project write branches.
- ACK blocking 3: added `docs/tasks/418/watchdog_replay.py`, exact pairing rules, command, cutoff, biases, and narrowed the result from an upper bound/frequency to a synthetic sensitivity counterexample.
- ACK blocking 4: Seedon reparenting now atomically updates `parent_id` and `parent_name`, refreshes loaded runtime state, and has read-back/list guards before archive.
- ACK suggestions: froze the changed task snapshot at 06:28:16Z with full SQL; added IA registry cost; downgraded the unsupported 32-seam denominator; provided notify taxonomy/integration choice; split public `/goal` from the host tool contract; fixed threshold elapsed-time semantics.
- Attempt 2 started: resumed Luna review of changed prose and replay artifact.

## Round (2026-08-30T06:36:38Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Раунд 2 уже снял часть мин, но replay всё ещё считает время с небольшим читерством 😏

## Summary

IA-cost, explicit `project`, timestamped snapshot, dual-parent Seedon guard, `/goal` surface split и `notify_user` fate исправлены в тексте. Replay script остаётся blocking: его границы окна не соответствуют документированному elapsed-time алгоритму.

## Findings (blocking/suggestion/question)

### Prior blocking status

- **FIXED — `project_wait`:** теперь `project` обязателен, а ownership проверяется по caller session ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:484), строки 488–493).
- **FIXED — authorization wording:** scope явно назван default selector/binding boundary, а explicit-project write bypass зафиксирован ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:118)).
- **STILL BROKEN — replay evidence:** скрипт теперь приложен, но содержит две ошибки границы окна ниже.
- **FIXED as an unexecuted procedure — Seedon:** оба parent-поля обновляются атомарно, добавлены read-back guards и отмена архивации при расхождении ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:299)).

### New findings

- `blocking:` В [watchdog_replay.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/watchdog_replay.py:123) незавершённый run закрывается на `end + 5 минут`. Поэтому run, начавшийся за 25 минут до cutoff, получает искусственную длительность 30 минут и попадает в `edge_triggers`, хотя `elapsed time >=30m` ещё не доказано. Это искажает заявленный output threshold replay.

- `blocking:` SQL в [watchdog_replay.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/watchdog_replay.py:68) фильтрует только `ts >= start`, но не `ts <= end`. Повторный запуск с тем же `--end` прочитает события после cutoff; как минимум `reconstructed_intervals` станет зависеть от момента запуска, поэтому утверждение о воспроизводимом output неверно.

- `suggestion:` Фильтр owners в [watchdog_replay.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/watchdog_replay.py:54) проверяет наличие владельца, а не ровно одного. Значит Seedon с двумя orchestrator'ами участвует в replay, хотя предрегистрированный predicate требует `owner ровно один`. Либо добавьте это условие, либо явно назовите replay sensitivity-тестом без owner quarantine.

- `suggestion:` В [research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:344) «Полный SQL» воспроизводит только распределение 79 `in_progress` по binding. Таблица всех статусов (`backlog/new/done/...`) этим запросом не получается; добавьте отдельный status-count query, иначе часть чисел остаётся неподтверждённой.

- `question:` В H1 всё ещё осталось утверждение, что task resolver выбирает проект «только через session scope» ([research.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-projects-board/docs/tasks/418/research.md:74)), хотя §3.2 уже правильно фиксирует explicit-project branches. Нужно согласовать формулировку: scope ограничивает binding/default lookup, но не все task operations.

## Verdict

**CHANGES REQUESTED.** Предыдущие blocking по tool gate, authorization и Seedon закрыты; replay остаётся blocking из-за искусственного `end + 5m` и отсутствия верхней границы `ts`.

Теперь мина хотя бы подписана, но один таймер всё ещё считает пять минут после окончания фильма.

## Author resolution after Round 2 (review ceiling reached)

- ACK new blocking 1: an open idle run now ends exactly at `end`, never `end + 5m`; a run opened 25 minutes before cutoff remains 25 minutes and cannot meet the 30m threshold.
- ACK new blocking 2: event SQL now enforces `start <= ts <= end`, with `end` passed as a bound parameter.
- ACK suggestions/questions: replay now requires exactly one owner (Seedon excluded), §6 includes the separate all-status SQL, and H1 now distinguishes scoped binding/default lookup from explicit-project operations.
- No Round 3: the prose review ceiling is two rounds. Post-cap fixes are verified locally by the exact replay command and targeted boundary controls; no APPROVED claim is made.

Local boundary evidence:

```text
25m pre-cutoff task + post-cutoff logs:
threshold=30m edge_triggers=0 repeated_5m_triggers=0 projects=0
reconstructed_intervals=0

duplicate-owner project:
threshold=30m edge_triggers=0 repeated_5m_triggers=0 projects=0
reconstructed_intervals=0
```
