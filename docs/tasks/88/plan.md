# Task #88 — точный `repo_path` и наблюдаемый spawn mapping

## Подход

Сохраняем существующий контракт:

- `scope` — логическое владение, parent routing, task/project context и slug каталога worktree;
- `repo_path` — физический primary Git repository root;
- незарегистрированные репозитории и `scope != repo_path` поддерживаются.

Исправляем только два подтверждённых дефекта:

1. Git не должен молча подняться от переданной подпапки к родительскому repository root.
2. Успешный `spawn_worker` должен показать фактические worktree, repository root, common dir и branch.

## Изменения

### Repository preflight

В `app/workspace.py` добавить один публичный для runtime helper `validate_repo_root(repo_path) -> Path`:

- нормализует путь через `resolve()`;
- различает missing path и non-Git directory;
- отдельно распознаёт bare repository и сообщает, что нужен primary working tree;
- требует `git rev-parse --show-toplevel == resolved repo_path`;
- требует ordinary primary working-tree root: локальная `.git` — реальный каталог, не symlink/gitfile, а resolved `--git-common-dir == <repo>/.git`;
- отклоняет nested directory, linked worktree, gitfile/separate-git-dir, symlinked/external `.git` и bare repository ясным `ValueError`.

`create_worktree()` вызывает helper защитно вместо своей текущей проверки только на `is_dir()`.

В `app/manager.py` при `use_worktree` сначала явно отклоняется пустой/`None` `repo_path`, затем тот же helper вызывается после проверки duplicate worker, но до первого spawn side effect: `delete_archived_session`, `save_session`, task `in_progress`, `_auto_commit_if_dirty` и `create_worktree`.

Canonical repository/common-dir metadata сохраняются в transient полях `Session` до lifecycle commit point. Route возвращает эти значения без повторного fallible Git lookup после запуска worker; DB schema не меняется.

### Наблюдаемый MCP response

В `app/mcp_stdio.py` успешная строка использует фактические поля API response и показывает:

- `Worktree: <result.worktree_path>`;
- `Repository: <result.repo_path>`;
- `Git common dir: <result.git_common_dir>`;
- `Branch: <result.branch>`.

MCP не делает дополнительный Git subprocess: manager preflight уже гарантирует exact mapping, а API возвращает server-validated metadata. Ошибочный create response остаётся `Spawn failed: ...` и initial task не отправляется.

Все четыре поля `worktree_path`, `branch`, `repo_path`, `git_common_dir` обязательны как non-empty strings в successful API response. Если API вернул malformed success-подобный dict, MCP отвечает заметной protocol error с предупреждением, что worker мог быть создан, не печатает ложный mapping и не отправляет initial task. Если create прошёл, но доставка initial task вернула ошибочный/malformed response, MCP честно сообщает, что worker создан, а task не доставлен.

### Исправление incident record

В `BUGS.md` сохранить оба исторических события, но исправить диагноз:

- Inscryption: worktree path был namespaced по COG scope, common dir с самого начала принадлежал `inscryption-ai`; false positive возник из-за непрозрачного success response.
- Seedon: caller `sales` передал `repo_path=/mnt/data/Projects/Python/orchestra`; параметр был исполнен буквально.
- Зафиксировать два реальных дефекта и commit/task, которым они закрыты.

## Что не трогаем

- регистрацию проектов и `tm_projects`;
- DB schema и session persistence;
- правила logical scope, parent routing, task linking и worktree slug;
- merge/worker_wip resolution;
- добавление поддержки bare или linked-worktree input: оба вида намеренно запрещены;
- сервер и deployment;
- соседние BUGS entries.

## Tickets

### T1 — Fail-loud primary repository preflight

- Files: `app/workspace.py`, `app/manager.py`, `app/session.py`, `tests/test_workspace.py`, `tests/test_manager.py`
- AC:
  - valid primary Git root принимается и возвращается как resolved `Path`;
  - valid unregistered Git root при отличном logical scope создаёт worktree с common dir целевого repo;
  - прямой вызов helper с nonexistent path падает с `repo_path does not exist`; обычный MCP request раньше отклоняется существующей `cwd does not exist` validation, что также fail loud;
  - standalone non-Git directory падает с `repo_path is not a Git repository`;
  - bare repository падает с отдельным сообщением, что нужен primary working tree;
  - nested directory внутри Git repo падает с сообщением, содержащим переданный путь и discovered root;
  - linked worktree input падает с явным сообщением, что требуется primary repository root;
  - gitfile/separate-git-dir и symlinked/external `.git` отклоняются, чтобы lifecycle всегда мог восстановить primary checkout как `common_dir.parent`;
  - пустой/`None` `repo_path` при `use_worktree` отклоняется до любых side effects;
  - manager выполняет preflight до `delete_archived_session`, session/task persistence и auto-commit; invalid input не оставляет session row/worktree и не вызывает `_auto_commit_if_dirty`;
  - canonical repository/common-dir metadata retained до worker start и доступны route без повторного Git discovery;
  - `create_worktree()` сохраняет defense-in-depth validation для прямых call-sites.
- blocked-by: none

### T2 — Прозрачный spawn result и честная история инцидента

- Files: `app/routes/sessions.py`, `app/mcp_stdio.py`, `tests/test_api.py`, `tests/test_mcp_stdio.py`, `BUGS.md`
- AC:
  - MCP POST body при `SCOPE != repo_path` сохраняет logical `scope`, а `cwd` и `repo_path` равны физическому target;
  - successful response показывает фактические API `worktree_path`, server-validated repository/common-dir и branch;
  - spawn API error не отправляет initial task и не печатает success mapping;
  - success-подобный API response, где любое из четырёх полей отсутствует, имеет неверный тип или whitespace-only, возвращает protocol error с предупреждением о возможно созданном worker, не отправляет initial task и не печатает ложный mapping;
  - API error/malformed response при доставке initial task не выдаёт ложный `Task sent`, а сообщает, что worker создан, но task не доставлен;
  - обе исторические BUGS entries сохраняют дату/контекст, но исходный диагноз помечен опровергнутым и заменён измеренными причинами;
  - запись называет два исправленных дефекта: nested Git discovery и непрозрачный success response.
- blocked-by: T1

## Проверка

1. Для каждого тикета сначала добавить тесты и зафиксировать ожидаемый RED.
2. Targeted:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
     tests/test_workspace.py tests/test_manager.py tests/test_mcp_stdio.py
   ```

3. Full suite:

   ```bash
   UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q \
     > /tmp/pytest-88.log 2>&1
   ```

4. `git diff --check`.
5. Shared-runtime Codex review точного diff; исправить подтверждённые blockers и обязательно провести второй раунд.

## Риски

- Preflight после session persistence оставил бы orphan row/task state; поэтому порядок manager является acceptance criterion, а не implementation detail.
- Проверка только `--show-toplevel` не отличает linked worktree от primary root; поэтому проверяется `.git` и common dir.
- Реконструировать worktree path в MCP по scope нельзя; показывается только значение API response.
- Формат success response человекочитаемый и не является машинным API-контрактом, но прежняя первая строка сохраняется.

## Codex review плана

Полный review: `docs/tasks/88/codex-review-plan.md`.

- Blocking findings: 0.
- Принято: missing-path AC ограничен helper, потому что MCP раньше валидирует `cwd`.
- Принято: bare repository получил отдельные AC, сообщение и RED-тест.
- Принято: malformed success response получил явный protocol-error contract.
- Принято: bare и linked-worktree input сформулированы как намеренно запрещённые, а не «не трогаемые».
- Повторный раунд не нужен: разногласий и blocking findings нет.
