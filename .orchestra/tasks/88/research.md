# Task #88 — `spawn_worker(repo_path=...)`: трасса, фактическая причина и контракт

## Вопрос

- **Контекст:** `spawn_worker` создаёт worker-сессию в логическом `scope`, а Git worktree — из физического `repo_path`.
- **Изменение под проверкой:** утверждение, что незарегистрированный `repo_path` теряется и заменяется репозиторием текущего Orchestra-проекта.
- **Baseline:** переданный путь должен быть точным корнем Git-репозитория; регистрация в `tm_projects` не должна влиять на выбор Git common dir.
- **Критерий результата:** `git rev-parse --git-common-dir` внутри созданного worktree указывает на `<repo_path>/.git`; несуществующий, standalone non-Git и вложенный non-root путь отклоняются явной ошибкой.

## Гипотезы

### H1 — fallback на зарегистрированный `scope`

`repo_path` незарегистрированного проекта заменяется текущим `scope`.

**Фальсификатор:** production-вызов с незарегистрированным `repo_path`, после которого common dir worktree принадлежит именно этому пути, либо отсутствие любой ветки к `tm_projects` в spawn-трассе.

**Вердикт:** **REFUTED**.

### H2 — физический репозиторий выбирает `repo_path`, а каталог worktree именует `scope`

Путь вида `worktrees/<scope-slug>/<worker>` описывает логическое владение сессией, но не источник Git-объектов.

**Фальсификатор:** `create_worktree()` использует `scope` как `cwd` Git-команд или common dir Inscryption-worktree принадлежит COG.

**Вердикт:** **CONFIRMED**.

### H3 — различие двух инцидентов вызвано различными фактическими аргументами

Inscryption был создан из переданного `inscryption-ai`, а `batch4-food-services` — из явно переданного вызывающим агентом `orchestra`.

**Фальсификатор:** сохранённые tool-call логи показывают одинаковый целевой `repo_path` либо `batch4-food-services` был вызван с Seedon.

**Вердикт:** **CONFIRMED**.

### H4 — настоящий fail-loud пробел находится в проверке Git root

Standalone non-Git путь падает, но каталог внутри существующего Git-репозитория принимается как `repo_path`, потому что Git поднимается к родителю.

**Фальсификатор:** `create_worktree()` проверяет равенство `repo.resolve()` и `git rev-parse --show-toplevel`, либо вложенный каталог отклоняется в эксперименте.

**Вердикт:** **CONFIRMED**.

## Findings

### 1. MCP не теряет `repo_path`

`app/mcp_stdio.py:101-123` кладёт один и тот же аргумент в `cwd` и `repo_path`. Логический `scope` вычисляется отдельно как `SCOPE or repo_path`. `app/routes/sessions.py:107-128` без преобразования передаёт все три значения в `SessionManager.create_session()`. [S1][S2]

**Уверенность: CONFIRMED** — два последовательно открытых участка production-кода, evidence tier 2 (primary source).

### 2. Manager и workspace используют переданный физический путь напрямую

`SessionManager.create_session()` вызывает `_auto_commit_if_dirty(repo_path)`, затем `create_worktree(repo_path, name, scope, ...)`. `create_worktree()` выполняет Git-команды с `cwd=Path(repo_path).resolve()`. `scope` участвует только в `scope_slug` и формирует каталог `WORKTREE_ROOT / scope_slug / name`. [S3][S4]

В spawn-трассе нет чтения `tm_projects` и нет ветки «проект не зарегистрирован → использовать scope». Регистрация проекта используется позже, например для привязки task-коммитов при merge, но не для выбора Git source. [S3][S5]

**Уверенность: CONFIRMED** — production-код и поиск реальных call-sites, evidence tier 2.

### 3. Инцидент Inscryption — ложная диагностика по имени каталога

Сохранённый tool-call `logs.id=299591` содержит:

```text
repo_path=/mnt/data/Projects/Python/inscryption-ai
```

Текущий production-worktree:

```text
/mnt/data/Projects/Python/orchestra/worktrees/home-maxim-cursor-cog-second-brain/impl-inscryption
git-common-dir = /mnt/data/Projects/Python/inscryption-ai/.git
branch = task-1/impl-inscryption
HEAD = c27c7feb84076ed8fe8132652ed3161344dc9650
```

`tm_projects` не содержит `/mnt/data/Projects/Python/inscryption-ai`, но worktree всё равно физически принадлежит этому репозиторию. [M1]

Worker решил, что worktree «из COG», после проверки только `pwd`, имени ветки и наличия тех же перенесённых документов (`logs.id=299636-299663`). Он не проверил `git rev-parse --git-common-dir`. [M1]

`worker_wip` работает непосредственно по `found.worktree_path`; merge сначала резолвит common dir из worktree и лишь при провале использует `scope` как fallback. Поэтому утверждение, что оба lifecycle-инструмента обязательно привязаны к COG, также не подтверждается кодом. [S6][S7]

**Уверенность: CONFIRMED** — сохранённый точный tool input, существующий worktree и Git measurement, evidence tier 1.

### 4. Инцидент `batch4-food-services` действительно создал Orchestra-worktree, потому что caller передал Orchestra

Сохранённый tool-call `logs.id=286116`:

```text
caller = sales
logical SCOPE = /mnt/data/Projects/Python/seedon
repo_path = /mnt/data/Projects/Python/orchestra
worker = batch4-food-services
```

Результат был закономерен:

```text
worktree path slug = mnt-data-projects-python-seedon
git-common-dir = /mnt/data/Projects/Python/orchestra/.git
```

Sibling `sales` принадлежал `/mnt/data/Projects/Python/seedon/.git`, потому что он был создан с другим физическим репозиторием. Расхождение «два воркера в одном scope» — следствие разделения `scope` и `repo_path`, а не состояния регистрации или случайного fallback. [M2]

**Уверенность: CONFIRMED** — exact production tool-call и contemporaneous common-dir measurement из `logs.id=286294-286295`, evidence tier 1.

### 5. Незарегистрированные репозитории уже поддерживаются

Три изолированных запуска `create_worktree()` с логическим scope, не равным физическому target, дали:

```text
iteration=1 valid_unregistered common=/tmp/task88-1-.../unregistered-target/.git
iteration=2 valid_unregistered common=/tmp/task88-2-.../unregistered-target/.git
iteration=3 valid_unregistered common=/tmp/task88-3-.../unregistered-target/.git
```

Во всех трёх запусках common dir точно совпал с `.git` переданного target. Production Inscryption является четвёртым подтверждением на реальном незарегистрированном проекте. [M1][M3]

**Продуктовый вывод:** поддержку незарегистрированных репозиториев сохраняем. Она уже работает и не требует отдельной архитектуры. Запрещать `scope != repo_path` нельзя: это сломает валидный сценарий, когда оркестратор одного проекта создаёт worker в новом физическом репозитории, сохраняя parent routing и task scope.

**Уверенность: CONFIRMED** — три повторных измерения плюс production counterexample к исходной гипотезе, evidence tier 1.

### 6. Invalid-path поведение частично fail loud, но root validation неполна

Три повторения дали одинаковые результаты:

```text
missing -> ValueError: repo_path does not exist: <path>
standalone non-git -> RuntimeError: git worktree add failed: fatal: not a git repository ...
nested directory inside git repo -> ACCEPTED; common dir points to parent repo
```

Несущественно, зарегистрирован ли путь: текущая логика регистрации не читает. Невложенный non-Git путь падает явно, хотя сообщение приходит поздно от `git worktree add`. Вложенный non-root путь — реальный тихий fallback Git discovery к родительскому репозиторию. [M3]

**Уверенность: CONFIRMED** — три одинаковых изолированных измерения, evidence tier 1.

### 7. Текущее покрытие проверяет части контракта, но не различает scope и physical repo

Существующие узкие тесты:

```text
tests/test_mcp_stdio.py::test_spawn_passes_base_branch
tests/test_workspace.py::TestCreateWorktree::test_success
tests/test_workspace.py::TestCreateWorktree::test_bad_repo_raises
tests/test_workspace.py::TestCreateWorktree::test_not_git_repo_raises
tests/test_manager.py::TestCreateSession::test_with_worktree
```

Результат: `5 passed in 3.35s`. Они не утверждают, что MCP body сохраняет отличный от `SCOPE` `repo_path`, что common dir равен переданному target, и что вложенный Git non-root отклоняется. [M4]

**Уверенность: CONFIRMED** — test source и прямой прогон, evidence tier 1/2.

## Counter-evidence и ограничения

- В случае `batch4-food-services` наблюдаемое состояние действительно выглядело как «не тот репозиторий». Это подтверждает тяжесть UX-сбоя, но не механизм «параметр проигнорирован»: параметр был равен Orchestra и был честно исполнен.
- Имя worktree содержит slug `scope`, поэтому без `git-common-dir` легко сделать неверный вывод о physical source. Текущий успешный ответ MCP сообщает только имя/model и скрывает `repo_path`, `worktree_path` и common repo; система помогла ложной диагностике.
- Production DB не хранит первоначальный `repo_path` отдельным полем после создания: `cwd` заменяется worktree path. Для расследования пришлось использовать tool-call logs и Git metadata. Это диагностический риск, но расширение схемы не требуется для минимального исправления.
- `_resolve_repo()` имеет fallback на `scope`, если `git rev-parse --git-common-dir` не сработает. На живом корректном worktree этот fallback не используется; менять его без отдельного failure-case теста не следует.

## Рекомендация для Phase 2

Задачу нельзя реализовывать как «добавить поддержку незарегистрированных repo» или «запретить разные scope/repo_path»: это исправит несуществующий механизм и сломает рабочий cross-repo сценарий.

Минимальный полезный vertical slice:

1. Ввести один workspace-validator и вызывать его в manager **до** `save_session()`, перевода task в `in_progress` и `_auto_commit_if_dirty()`. `create_worktree()` также вызывает его защитно для прямых call-sites. Валидатор проверяет:
   - путь существует;
   - `git rev-parse --show-toplevel` после `resolve()` точно равен `repo_path`;
   - `.git` является каталогом этого root, а resolved `--git-common-dir` равен `<repo_path>/.git`.
   Так раздельно и понятно отклоняются missing, standalone non-Git, nested non-root, linked worktree и bare repo.
2. После spawn возвращать в MCP-ответе фактические `repo_path`, `worktree_path` и branch. Это делает разделение logical scope / physical repo наблюдаемым и предотвращает повтор случая 1.
3. TDD зафиксировать четыре запрошенных сценария:
   - валидный registered repo;
   - валидный unregistered repo при `SCOPE != repo_path`, common dir равен target;
   - standalone non-Git;
   - nonexistent;
   - дополнительный regression: directory inside another Git repo отклоняется, а не наследует parent.
4. Отдельно зафиксировать wrapper-contract: MCP отправляет target в `cwd` и `repo_path`, но оставляет `scope=SCOPE`.

## Affected files и риски

- `app/workspace.py` — точная preflight-валидация Git root; риск: bare repo и уже существующий Git worktree являются отдельными формами repo path, контракт надо явно ограничить обычным working-tree root.
- `app/mcp_stdio.py` — прозрачный success response с физическим mapping; обратная совместимость низкого риска, строка только расширяется.
- `tests/test_workspace.py` — root/non-root и registered/unregistered physical mapping.
- `tests/test_mcp_stdio.py` — сохранение отличного от scope target и отображение результата.
- `app/manager.py` — обязательный ранний вызов workspace-validator до первого spawn side effect.

Edge cases:

- symlink на корень Git-репозитория: сравнивать resolved paths;
- `repo_path` с trailing slash: нормализовать;
- linked worktree как входной repo: **не поддерживать**; caller должен передать основной repository root и нужный `base_branch`. Это сохраняет один однозначный lifecycle и exact common-dir contract;
- bare repository: нет working tree и текущий spawn-контракт с auto-commit/copies его фактически не поддерживает;
- пустой repository без `main`: это отдельная ошибка base branch, не смешивать с repo validation.

## Adversarial second opinion

Codex review: `docs/tasks/88/codex-review-research.md`.

- Все пять load-bearing conclusions подтверждены; фактических противоречий не найдено.
- Принято замечание о порядке side effects: manager-level preflight теперь обязательный, а workspace-level вызов остаётся defense in depth.
- Принято замечание о linked worktree: контракт закрыт явным отказом; поддерживается обычный primary working-tree root, включая symlink после `resolve()`.
- Повторный раунд не нужен: blocking findings отсутствуют, обе suggestions внесены без разногласия.

## Источники и измерения

- **[S1] Tier 2, primary:** `app/mcp_stdio.py:101-123`.
- **[S2] Tier 2, primary:** `app/routes/sessions.py:41-87,107-128`.
- **[S3] Tier 2, primary:** `app/manager.py:388-588`, особенно `538-550`.
- **[S4] Tier 2, primary:** `app/workspace.py:224-299`.
- **[S5] Tier 2, primary:** поиск `get_project_by_scope`/`tm_projects` по spawn call-chain; `app/routes/sessions.py:663-676` показывает post-merge task-link use.
- **[S6] Tier 2, primary:** `app/routes/sessions.py:756-770` (`worker_wip`).
- **[S7] Tier 2, primary:** `app/routes/sessions.py:639-710` и `app/workspace.py:303-313` (`merge` + common-dir resolution).
- **[M1] Tier 1, measurement:** read-only запросы к production SQLite `logs.id=299591,299636-299663` и `git rev-parse --git-common-dir` в существующем `impl-inscryption`.
- **[M2] Tier 1, measurement:** read-only production SQLite `logs.id=286116,286294-286295`.
- **[M3] Tier 1, measurement:** три isolated `/tmp/task88-*` запуска `create_worktree()`; raw output записан в Findings 5-6.
- **[M4] Tier 1, measurement:** targeted pytest, `5 passed in 3.35s`.

Внешние URL не использовались: вопрос полностью определяется primary source репозитория, production call logs и воспроизводимым Git-поведением.
