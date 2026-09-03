## Summary

🧐 План почти готов, но «точный путь» пока местами определяется двумя разными контрактами. Блокирующих проблем нет; вертикальные тикеты, ограниченный scope и preflight до разрушительных действий выбраны правильно. Перед реализацией стоит закрыть четыре неоднозначности.

## Findings

### suggestion: Согласовать missing-path с фактическим порядком валидации

**File:** [docs/tasks/88/plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/plan.md:20) (lines 20–30, 69–73)

В реальном MCP-вызове `cwd == repo_path`, поэтому отсутствующий путь сначала отклонят `CreateSessionRequest.validate_cwd()` либо проверка `cwd` в `manager.create_session()` — обе выполняются до duplicate check и нового helper. Ошибка `repo_path does not exist` и заявленный порядок preflight для этого сценария недостижимы. Нужно либо ограничить этот AC прямым вызовом helper, либо включить изменение ранней проверки `cwd` и `app/routes/sessions.py` в T1.

### suggestion: Добавить bare repository в AC и RED-тест

**File:** [docs/tasks/88/plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/plan.md:23) (lines 23–26, 66–74)

План требует ясного `ValueError` для bare repository, но T1 не закрепляет этот случай тестом. В bare repository `git rev-parse --show-toplevel` завершается ошибкой, поэтому последовательная реализация описанных проверок легко классифицирует его как обычный non-Git directory. Нужны отдельный AC, ожидаемое сообщение и RED-тест.

### suggestion: Определить ошибку для неполного success response

**File:** [docs/tasks/88/plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/plan.md:34) (lines 34–41, 80–83)

План описывает API error, но не успешный ответ без `worktree_path` или `branch`; существующие MCP-тесты как раз возвращают минимальный `{"ok": True}`. Без явного контракта реализация либо напечатает `None`, либо упадёт уже после создания worker и отправки initial task. Следует определить обязательные поля, обновить существующие mock responses и добавить тест, что malformed success response завершается заметной protocol error без ложного success mapping.

### question: Linked/bare input сохраняется или намеренно запрещается?

**File:** [docs/tasks/88/plan.md](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/plan.md:51) (lines 51–57)

Пункт «не трогаем поддержку bare или linked-worktree input» читается как сохранение поведения, тогда как repository preflight и T1 требуют явно отклонять linked worktree и bare repository. Нужно записать однозначно: «не добавляем поддержку; оба вида input намеренно запрещены».

## Verdict

Условно одобрено: блокеров нет, scope и основная последовательность корректны. Перед реализацией желательно уточнить findings выше, иначе тесты смогут подтвердить helper, но пропустить реальные MCP-семантики — точность получится как у карты с двумя северными стрелками. 🗺️
