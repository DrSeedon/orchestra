Ну конечно, симлинки решили притвориться обычными файлами ровно после проверки 😏

## Summary

Основной сценарий реализован верно: Codex получает индекс без тел skills, pipeline-дубликат побеждает ambient, `skills: all` поддержан, а копирование ограничено Claude. Но остаются три нарушения контракта, одно из которых позволяет репозиторию уронить создание Codex backend.

Проверка: 31 целевой тест пройден. `TestInjectSkillsGating` завис до первого результата, поэтому его не засчитываю.

## Findings

### blocking: Reject pipeline skill symlinks before resolving them

[app/prompting.py:318](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:318)

И `skills: all`, и явный список сразу вызывают `resolve()`, стирая информацию о том, что исходный файл был симлинком. Симлинк на другой файл внутри `skills_root` проходит containment-проверку и индексируется, хотя контракт требует отклонять симлинки. Проверять `candidate.is_symlink()` нужно до `resolve()` в обеих ветках; тесты сейчас покрывают только escape наружу.

### blocking: Treat multiline frontmatter names as malformed

[app/prompting.py:198](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:198)

`name` только обрезается по краям, поэтому значение вроде `"safe\n## injected"` создаёт дополнительные строки в system prompt. Такой ambient skill должен предупреждаться и пропускаться, а required skill — падать, иначе нарушается формат однострочного индекса и появляется канал инъекции структуры промпта.

### blocking: Handle symlink cycles during ambient discovery

[app/prompting.py:241](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:241)

На Python 3.12 симлинк-цикл в `.claude/skills` вызывает `RuntimeError` из `Path.resolve()` до логирования и skip, поэтому специально подготовленный worktree роняет создание Codex backend. Аналогичный риск есть при `candidate.resolve(strict=True)` на строке 271. Ошибки разрешения ambient-путей должны приводить к warning+skip.

### suggestion: Separate the generated index from the base prompt

[app/runtime_registry.py:223](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/runtime_registry.py:223)

`build_skills_index()` больше не добавляет начальные переводы строк, поэтому результат сейчас выглядит как `BASE## Available skills`. Заголовок перестаёт быть Markdown-заголовком и может слиться с последней инструкцией. Добавьте `\n\n` только при непустом `skills_block` и зафиксируйте точную границу в runtime-тесте.

## Verdict

Request changes. Основной маршрут рабочий, но политика отклонения симлинков и fail-safe для ambient entries пока не соблюдена полностью.

Индекс уже поставил турникет, только пара симлинков проходит через него в чужом пальто.

## Round (2026-07-26T11:00:12Z)

Ну вот, симлинкам наконец проверяют документы до прохода 😏

## Re-review status

1. **FIXED** — pipeline skill symlinks отклоняются до `resolve()` для `skills: all` и явного списка ([app/prompting.py:332](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:332)).
2. **FIXED** — multiline frontmatter names считаются malformed; required падает, optional предупреждает и пропускается ([app/prompting.py:198](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:198)).
3. **FIXED** — ошибки и циклы при разрешении ambient-путей обрабатываются через warning+skip ([app/prompting.py:243](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/prompting.py:243)).
4. **FIXED** — непустой индекс отделяется от базового промпта двумя переводами строк ([app/runtime_registry.py:215](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/feat-skill-index/app/runtime_registry.py:215)).

`git diff` и `git diff HEAD` по разрешённым файлам пусты; проверено текущее содержимое. Локально: **36 passed** по двум разрешённым тестовым модулям.

## New findings

Новых blocking-регрессий не найдено.

## Verdict

**APPROVE.** Все прежние блокеры закрыты.

Теперь турникет действительно проверяет симлинки, а не восхищается их гибкостью.
