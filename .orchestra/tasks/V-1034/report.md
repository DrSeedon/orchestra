# V-1034: merge_worker improvements

Предлагаемый заголовок коммита: `V-1034: Improve merge_worker acceptance, squash titles and compact receipts`.

## Реализация

1. Squash берёт первую непустую строку acceptance_note; при её отсутствии — subject последнего коммита. Префиксы V-xxx и канонические task refs, список squashed commits и operation trailer сохраняются. Note проходит из execute_merge_session в workspace.
2. Бюджет 2000 учитывает вставки вне `.orchestra/tasks/**`. Отдельное поле `diff_excluded_insertions` проходит из измерения через Git-результат и нормализацию в компактный ответ. Старый `measure_insertions()` остаётся целочисленным интерфейсом. NUL-разбор корректен для необычных имён и переименований; добавления переименованного файла относятся к новому пути. Остальные generated-файлы автоматически не исключаются.
3. Target guard блокирует пересечение грязных путей с изменёнными путями ветки, включая staged rename и пересечение файл/каталог. Ошибка сохраняет путь target checkout и перечисляет пересекающиеся файлы. Посторонние tracked/untracked изменения допускаются. Отдельный временный Git index не даёт захватить чужие staged-правки в squash; по завершении обновляются только влитые пути реального index. При отказе commit hook применяется сохраняющий постороннюю грязь rollback. Explicit temporary indexes вспомогательных операций, включая `.gitignore` union, имеют приоритет над merge index. Stash не используется.
4. Новая операция требует полный 40-символьный hex SHA и содержательную note длиной от 15 символов; пустая строка, placeholder, tbd, `-` отклоняются. Ошибка SHA дословно: `expected_head must be the full 40-character SHA from worker_wip`. Проверка выполняется до admission; adhoc promotion также проверяет ввод до смены ветки. Полный SHA сверяется с фактическим snapshot. Replay сохранённых операций идёт до новой проверки, поэтому старые квитанции остаются восстанавливаемыми.
5. Default MCP receipt содержит состояние операции, target_after, commits_merged, счётчики diff, статусы test/mutation gate, только failing ids, next_action и необходимые поля восстановления. Логи, списки прошедших тестов и подробности admission отсутствуют. Краткий тип транспортного исключения сохраняется. `verbose=true` возвращает полный результат и не меняет запрос/идемпотентность операции.

## Проверки

Все pytest-прогоны offline: `uv run --offline --frozen python -m pytest ... -q --timeout=45`; последовательно, nice=15, лимит виртуальной памяти 2 GiB. В hub первоначально отсутствовал uv; временный инструмент и зависимости подготовлены внутри копии, затем тесты запускались без сети. Команды используют относительные пути. Импорт app проверен: `Path(app.__file__).resolve() == Path('app/__init__.py').resolve()`.

- Первоначальный целевой прогон реализации: **327 passed in 59.54s**, см. `final-tests.log`. Охват: новые тесты, diff budget, work acceptance, workspace TestMergeTarget, durable operations, completion watch, branch drift, lifecycle, mutation gate, target oracle, MCP, progress, restart recovery, canonical refs и foreign refs.
- Новый набор: **43 passed**, см. `mutation-control.log`.
- **8/8 регрессионных мутаций обнаружены**, см. `mutations.json`, `mutation-*.log`. Проверены первый/последний subject, игнорирование acceptance_note, включение evidence в бюджет, запрет любой грязи, приём placeholder, короткий SHA, полный default output и игнорирование verbose. После каждого прогона исходный файл восстановлен в finally.
- Дополнительно: точная граница 2000, превышение 2001 в прежних тестах, untracked evidence и похожий путь вне tasks, rename accounting, одновременные staged/unstaged изменения, конфликтующие пути с TAB, rename source, commit-hook rollback, `.gitignore` union, передача note через реальный session execution, старые receipts и verbose presentation-only replay.
- Прежние тесты подготовлены к обязательным валидным acceptance inputs и новому subject. Отрицательные проверки и проверки восстановления сохранены.

## Уточнение V-416 по решению Orchestra от 22.10.2026

Оркестратор Orchestra уточнил контракт: блокирует только пересечение путей. Цель V-416 — доставка пути target checkout, конфликтующего файла и действия до вызывающего. Разрешение изменить frozen oracle получено явно 22.10.2026; предмет проверок сохранён.

`test_t2_dirty_target_path_files_and_action_reach_merge_caller` теперь создаёт untracked `worker.txt` в target, пересекающийся с добавленным воркером `worker.txt`. Сохранены assertions пути repo, конкретного файла, неизменного HEAD/содержимого и recovery action в нормализованном результате и MCP-тексте. В `_clean_worktree_error` восстановлен путь checkout в диагностике: первоначальный вариант V-1034 его потерял.

Рядом добавлен `test_t2_unrelated_dirty_target_allows_merge_and_preserves_file`: несвязанный `.orchestra/tasks/49/research.md` допускает merge, сохраняет содержимое и untracked-статус, не попадает в commit. Проверяется реальный target commit с `worker.txt` и SUCCEEDED до MCP-ответа. Публичное изменение записано вручную в CHANGELOG.md.

Исторический `compatibility.log` (**2 failed, 3 passed**) относится к прежней версии oracle. Актуальный прогон уточнённого контракта: **206 passed in 31.60s**, см. `followup-tests.log`. В него входят весь V-416, 43 теста V-1034, workspace TestMergeTarget, diff budget и MCP. **3/3 дополнительные мутации обнаружены**: потеря пути repo, пропуск overlap guard и блокировка несвязанной грязи. Доказательства: `v416-mutations.json` и `v416-mutation-*.log`. Исходник после каждой мутации восстановлен.

## Ограничения окружения

`tests/test_workspace.py::TestCreateWorktree::test_different_repos_no_collision` не изменялся. В этой hub-копии существующий `_slugify` обрезает длинный путь до 80 символов, поэтому fixture repositories сталкиваются; по сообщению Orchestra от 22.10.2026 на main тест зелёный. Это ограничение окружения, а не дополнительная правка V-1034.

Расширенный диагностический прогон (`regression.log`) дополнительно упёрся в неполную поставку: нет `.github/workflows/ci.yml`, `.git`, части scripts/pipeline/probe файлов; один старый тест требует временные пути именно под `/tmp/`, что противоречит ограничению этой копии. Эти тесты не изменялись ради зелёного статуса. Полный `scripts/run_tests.py` и instruction-contract script отсутствуют, полный набор не заявляется пройденным.

Работа выполнена в приватной копии без `.git`: обычный git diff/commit/push недоступен; изменённые блоки просмотрены, Python загружается и выполняется в целевых тестах. Сервис не перезапускался, deploy не выполнялся. Коммит и перенос на `task-V-1034/fix-merge-worker` выполняет платформа. После слияния Python-изменения требуют отдельного разрешённого владельцем рестарта. Live rollout и настоящий рестарт не проверялись. Временные окружения, caches и fixture repositories удаляются перед передачей; остаются исходники и компактные task artifacts.

В уточняющем прогоне временные окружения, dependency caches и fixture repositories убраны из копии через `gio trash` (системная корзина); исходники, отчёт и проверочные логи сохранены. Native Orchestra MCP отсутствует в этой приватной hub-копии; итоговый `send_message` передаётся родителю штатным `.orchestra-outbox.jsonl`.

## Уточнение фикстур merge_stuck по запросу Orchestra

В helper `_merge` файла `tests/test_merge_stuck.py` добавлены `expected_head`, прочитанный через `git rev-parse HEAD` из реального `worktree_path` сессии, и содержательная acceptance_note. HEAD читается заново перед каждым вызовом, включая работу на следующей ветке, отказ из-за активного PARTIAL и merge после явного resolve. Строгая production-проверка не менялась.

Проверки SUCCEEDED/WARNED для отсутствующей задачи, нового operation_id и ветки, обоих новых коммитов, блокировки PARTIAL и восстановления после resolve оставлены. Проверка наличия первого исходного subject перенесена с `--oneline` на `%B`: новый squash headline использует последний subject, а прежний остаётся в теле commit message. Это сохраняет проверку фактически влитого сообщения, а не старого выбора заголовка.

Отдельный прогон `tests/test_merge_stuck.py`: **2 passed in 6.72s**, см. `stuck-focused.log`. Все запрошенные файлы перечислены в `stuck-suite-manifest.json`: 15 файлов `test_merge_*.py`, весь `test_workspace.py` и весь `test_mcp_stdio.py`, без deselect. Командный output сначала собирается в памяти; `run_redacted.py` удаляет домашний путь и логин хаба и маскирует секреты до записи новых логов на диск.

Полный запрошенный набор выполнен: **477 тестов, 471 passed, 6 failed**, без исключений и deselect. Тесты разделены на шесть последовательных pytest-вызовов; все 55 nodes test gate распределены ровно один раз между двумя короткими пакетами. Полный перечень и итоги — `stuck-suite-manifest.json`, `stuck-gate-nodes.json`, `stuck-suite-results.json`. Core: 63 passed; guards: 97 passed; gate: 50 passed / 5 failed; workspace: 121 passed / 1 failed; MCP: 140 passed.

Все шесть отказов относятся к неизменённым условиям hub-копии: нет CI workflow и `.git`, временные файлы находятся внутри копии вместо `/tmp/`, отсутствует часть live/browser inventory исходников, длинный root вызывает известную коллизию `_slugify`. Точные failed ids сохранены в JSON; эти тесты не ослаблялись. Оба исправленных сценария merge_stuck прошли и отдельно, и в core-пакете. SHA-256 всех production-файлов app/ и tests/test_workspace.py совпадает с предыдущей передачей. Все новые stuck-логи проверены на отсутствие домашнего пути и логина хаба.
