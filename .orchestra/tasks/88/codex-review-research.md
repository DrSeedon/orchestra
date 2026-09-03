Слишком удобная гипотеза про «магический fallback» всё-таки не пережила встречу с кодом 😏

## Summary

Все пять проверяемых выводов подтверждаются доступными доказательствами:

- `repo_path` сохраняется по всей цепочке MCP → route → manager → workspace.
- Spawn не использует `tm_projects`; незарегистрированные репозитории поддерживаются.
- Inscryption физически принадлежал `inscryption-ai`, а COG присутствовал только в slug логического scope.
- `batch4-food-services` получил Orchestra-worktree именно из-за переданного `repo_path`.
- Вложенный non-root каталог действительно молча наследует родительский Git-репозиторий.

Фактических противоречий, меняющих эти выводы, нет. Есть две недоработки в рекомендации Phase 2.

## Findings

suggestion: **Сделать manager-level preflight обязательным**

[research.md:166](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/research.md:166) требует проверки до side effects, но [research.md:182](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/research.md:182) оставляет изменение manager опциональным. Это несовместимо с текущим порядком: сессия сохраняется и задача может получить `in_progress` до вызова workspace, а `_auto_commit_if_dirty(repo_path)` запускается раньше `create_worktree()` ([manager.py:528](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:528), [manager.py:538](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/app/manager.py:538)). Валидатор можно держать в workspace, но manager обязан вызвать его до сохранения сессии, изменения task status и auto-commit.

suggestion: **Закрыть контракт для linked worktree**

Baseline требует, чтобы common dir созданного worker указывал на `<repo_path>/.git` ([research.md:7](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/research.md:7)), однако предложенная проверка только через `--show-toplevel` примет linked worktree, чей common dir принадлежит основному репозиторию ([research.md:166](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/research.md:166), [research.md:188](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-repo-path/docs/tasks/88/research.md:188)). Для заявленного exact mapping следует прямо зафиксировать отказ от linked-worktree input и проверять также соответствие common dir, либо явно изменить baseline.

## Verdict

**Корректно с уточнениями.** Причина инцидентов и все пять load-bearing conclusions доказаны. Перед Phase 2 нужно уточнить расположение preflight и контракт linked worktree; иначе документ верно ставит диагноз, но оставляет рецепт с двумя незакрученными болтами — почти как тот самый scope slug, выглядит убедительнее, чем работает.
