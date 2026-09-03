## Summary

Синхронизация почти аккуратная — пока `AGENTS.md` не оказывается симлинком или Git не ломается 🙃 Вызов через `asyncio.to_thread` не блокирует event loop; удаление `skills_catalog`, сокращение prompt и обновление `spawn_worker` регрессий не создают. Тесты не запускались по условию.

## Findings

### blocking — Обновление может перезаписать цель симлинка

[app/workspace.py:163](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/app/workspace.py:163)

Если неотслеживаемый `AGENTS.md` — симлинк на существующий файл с отличающимся содержимым, `cp` проходит по симлинку и перезаписывает его цель, включая файл вне worktree. При ошибке записи после truncate также теряется прежнее корректное зеркало. Копируйте во временный файл с последующим атомарным `os.replace()` либо явно отказывайтесь работать с симлинком. Теста на этот сценарий нет.

### blocking — Ошибка Git ошибочно означает «файл не отслеживается»

[app/workspace.py:158](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/app/workspace.py:158)

Любой ненулевой код `git ls-files` трактуется как отсутствие tracked-файла. Для каталога вне Git, повреждённого worktree или ошибки ownership Git возвращает не `1`, а fatal-код; после этого существующий `AGENTS.md` всё равно перезаписывается. Следует разрешать копирование только при ожидаемом `returncode == 1`, а прочие ошибки пробрасывать: `_ensure_backend` уже превратит их в warning и продолжит со старым файлом.

### suggestion — Синхронное старое зеркало остаётся untracked

[app/workspace.py:161](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/app/workspace.py:161)

Для старого worktree без записи в `info/exclude`, но с уже совпадающими файлами, ранний `return False` происходит до `_exclude_claude_dir()`. Поэтому `AGENTS.md` продолжит висеть в `git status` и может блокировать merge. Нужен вызов исключения и в noop-ветке плюс соответствующий тест.

## Verdict

❌ Дифф пока не готов: два edge case приводят к порче данных, а заявленная очистка старых worktree работает только после фактического копирования. Зеркало вышло бодрым, но пока разбивает окно, если дверь Git заклинило.

## Round (2026-07-26T07:19:55Z)

## Summary

Три исходных замечания закрыты, но временный файл решил стать новой точкой приключений 🙃 Проверки tracked-файла, симлинка `AGENTS.md` и noop-exclude теперь корректны. Перенос `_exclude_claude_dir` не ломает `create_worktree`: повторный вызов идемпотентен.

## Findings

### blocking — Фиксированный tmp снова допускает порчу чужого файла

[app/workspace.py:177](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/app/workspace.py:177)

`AGENTS.md.tmp` может уже существовать в стороннем репозитории, включая tracked-файл или симлинк. `_copy_file` перезапишет его либо пройдёт по симлинку к внешней цели, после чего `mv` ещё и удалит исходный путь. Две параллельные синхронизации также пишут в один inode: один вызов может переименовать tmp, пока второй продолжает запись, и backend увидит частичный `AGENTS.md`. Атомарного `mv` достаточно только при уникальном приватном tmp-файле в той же директории. Нужен уникальный путь с гарантией отсутствия коллизии; тесты на конкуренцию и существующий tmp-симлинк отсутствуют.

### suggestion — Ошибка оставляет частичный tmp в worktree

[app/workspace.py:178](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/audit-fullcycle/app/workspace.py:178)

При сбое `cp` или `mv` временный файл не удаляется и остаётся untracked-мусором, способным заблокировать merge. `test_no_tmp_file_left_behind` проверяет только успешный путь, где tmp и так удаляет `mv`; нужен cleanup в `finally` и тест с ошибкой копирования/переименования.

## Verdict

❌ Исходные три дефекта исправлены, но фиксированное имя tmp сохраняет путь к порче данных. После уникального tmp и cleanup схема будет достаточной; атомарная дверь работает, когда два грузчика не тащат через неё один и тот же ящик.
