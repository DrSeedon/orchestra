# V-1096 — заметки исследователя

Задача: только факты и сопоставление по коду; решения об adoption оставлены root.

## Выполненные действия и причины

1. Проверены поставленные AGENTS и три обязательных prompt-модуля; найден реальный merge path через rg вместо предположения о существовании app/merges.py.
2. Публичный GitHub HEAD каждого из ub-mode/crapper/dryer/mutator разрешён один раз; затем README/SKILL/docs/source читались по SHA. Это предотвращает смешение разных состояний master.
3. Полностью прочитаны README+SKILL ub-mode и docs companions. Исходники/test bodies читались целевыми диапазонами; имена других тестов найдены rg. Manifest различает эти уровни.
4. Каждый bullet SKILL получил отдельный R-ID. Все 61 строки, включая три фазовых bullet, сохранены аналитическими пересказами, без полной копии стороннего SKILL.
5. Сверены Crapper CLI boundary, Dryer similarity/filters/status, Mutator baseline/selection/caching/worker/runner/recovery и локальный rollback gate; docs не приняты за доказательство механики.
6. Повторные public GET к 43 использованным файлам проверены по Git blob SHA1 дерева, вычислены SHA256; сырые тела остались только в памяти/приватных tool results.
7. Подготовлены report.md, facts.json, source-manifest.json, этот журнал и воспроизводимая shell-проверка артефактов. Её stdout/stderr сохраняются без переписывания в checks.txt; это не pytest и не замена runtime smoke.
8. Ничего не установлено, не активировано, не удалено и не запущено из стороннего executable code. Product prompts/code не изменены.

## Неочевидные факты для передачи root

- CRAP строго <10 в SKILL не совпадает с >threshold в CLI; equality pass и no-scores pass подтверждены source tests.
- Dryer threshold по умолчанию 0.82, а не 0.8; exit 0 при дубликатах. JS extensions в его pinned discovery отсутствуют.
- Crapper Python может сохранить coverage красного тестового прогона; описание «failed run=0%» не универсально.
- Mutator no-selected/all-uncovered может вообще не запускать baseline. Differential cache проверяет текст функции, не digest тестов/зависимостей.
- Killed означает nonzero/timeout, включая некомпилируемую мутацию, а не обязательную поведенческую assertion.
- Null-output oracle и хронология TDD не реализованы самими companion tools; rollback источников Orchestra проверяет иное свойство.
- Mutation INCONCLUSIVE в локальном Orchestra gate не меняет общий PASSED; это явно ожидается существующим тестом. Исследование не превращалось в bugfix.
- Установленный parser package ещё не доказывает offline parse: parser_for вызывает download грамматики. В зависимости от кеша вызов может не требовать сеть; dependency runtime не проверялся.
- Старый bug note Mutator про неправильный Python уже не описывает current runner при существующем project .venv.
- Legacy mutation backup restore пишет файлы без проверки пользовательских изменений после предыдущего interruption.
- Без .git нельзя подтвердить локальную commit SHA, diff относительно parent, commit или clean; платформа импортирует результат после turn.
- Рабочая формула цены дана в числах вызовов; секундных замеров, модельных расходов и квот не выдумывал.

## Ограничения выполнения

Broker uv 0.11.28 доступен по разрешённому пути. .venv отсутствует. Pytest, full suite и импорт app не выполнялись: продуктовый Python не менялся, сторонние CLI не установлены, research-only запрет установки сохранён.
HTTP/hash helper использовал стандартную библиотеку системного python3; его результат не выдаётся за требуемый uv/pytest check.
Ошибки поиска отсутствующих app/worker_lifecycle.py, app/worker_management.py и prompts/modules/testing.md проверены альтернативным rg: реальное кодовое владение находится в merge_operations, routes/sessions и worktree_cleanup. .github/workflows в этой частичной копии нет; текущий CI не исследован.

