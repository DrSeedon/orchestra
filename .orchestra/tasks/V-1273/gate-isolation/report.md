# sanitized-publication-copy
# Prior private originals: private/tasks/V-1273/originals/ (root-held; not accessed).

# V-1273 — изоляция fixture после failed merge gate

Исправлена **только тестовая fixture setup**, четыре строки в `tests/test_hub_untracked_delete_v1273.py`. В synthetic repo `.git/info/exclude` добавлен точный `/app/__pycache__/`: настоящий scanner импортирует скопированные модули и вправе создавать bytecode. Production scanner/hook и `app/hub_workspace.py` не менялись. Строгий `git status --porcelain == ''`, ожидаемый commit/tree и все остальные assertions сохранены дословно и по AST. Никакой зависимости от внешнего `PYTHONDONTWRITEBYTECODE` у fixture теперь нет.

Root сообщил failed merge operation `93796520`: 163 passed, единственный RED — строка 149 с `?? app/__pycache__/`. Эта операция не повторялась; новые merge/live/deploy действия worker не выполнял. Конкретного production defect не обнаружено. Следующий HEAD создаёт broker, новый merge — решение root.

## Проверки без подавления bytecode

Каждая test shell использует provisioned uv 0.11.28, `export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"`, default `.venv`, frozen lock. `PYTHONDONTWRITEBYTECODE` удалён и в shell, и явно из окружения каждого дочернего pytest; runner не выставляет его обратно. Тесты offline, провайдер/SSH — существующие synthetic doubles. Nice=10, oom_score_adj=1000; canonical mapped runner выбирает два файла, два xdist worker, budget 480s, per-test ceiling 120s/signal. Перед запуском cgroup memory 37,086,912,512 / 52,755,525,632 bytes, CPU limit 8, host available 74 GiB; лёгкие мутации выполнялись рядом с mapped, без браузеров.

| Проверка | Фактический результат | Артефакт |
|---|---|---|
| Test-first RED до правки fixture, env отсутствует | **1 failed, 31.88s**, точное `?? app/__pycache__/` на прежней строке 149 | `red.txt` |
| GREEN после четырёх строк fixture | **1 passed, 19.53s**, env отсутствует | `green.txt` |
| Весь mapped набор для product fix + изменённого теста | **163 passed, 1 failed, 355.58s**, exit 1, без skips. Все новые 9 прошли; единственный RED — прежний prompt case из-за отсутствующего role template | `mapped.txt`, `mapped-command.json` |
| Мутация product fix: прежний commit_sync в памяти | **Ожидаемый RED: 1 failed, 22.90s**, exact second-turn NOT COMMITTED/pathspec `duplicate.txt` | `mutation.txt` |
| Мутация fixture: прежняя setup в памяти, production fix остаётся | **Ожидаемый RED: 1 failed, 27.39s**, диагностирован реальный статус `?? app/__pycache__/` | `fixture-mutation.txt` |
| Первый fixture-mutation запуск | **Ожидаемый RED: 1 failed, 23.98s** на том же strict-status assert; in-memory функция не получает pytest assertion rewriting. Повтор добавил только наблюдение фактического статуса, assertion не менялся | `fixture-mutation-first.txt` |
| Проверка границ исключения / сохранности assertions | Исходные assertions AST-identical; synthetic Git показывает `app/unrelated.py`, `native.txt` и `other/__pycache__/visible.pyc`, исключает только точный cache | `scope-proof.txt` |
| Source/artifacts integrity | Product/CHANGELOG без изменений; test delta ровно 4 строки; **все 19 прежних sanitized artifacts неизменны** | `baseline.json`, `source-review.json` |

Canonical mapping/argv получены read-only из `app.merge_test_gate.select_tests` и `pytest_argv(..., orchestra_project=True)` (в копии нет `.git`; флаг явно повторяет режим настоящего Orchestra gate). Исполняется `uv run --frozen python -m pytest` с теми же выбранными тестами/flags, а не настоящий merge/evaluate operation. Точная команда, env absence и exit code записаны в `*-command.json`.

Mapped files: `tests/test_hub_workspace.py`, `tests/test_hub_untracked_delete_v1273.py`. Известное ограничение копии: отсутствующий `.orchestra/pipelines/default/prompts/hub/worker.md` ранее давал один независимый prompt test failure; root full-host control перед этой задачей был зелёный. Он повторился ровно один: `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools`, assertion в `test_hub_workspace.py:1709`. Это видимый RED, не skip; тот же before-fix failure уже сохранён в прежнем неизменённом `prompt-baseline.txt`. Полностью зелёный gate нужно подтвердить у root в полном checkout; в этой копии его не заявляем. Frozen tests/fixture dependencies не подменяются.

## Scope и публикация

Изменённый source: `tests/test_hub_untracked_delete_v1273.py` (4 строки). Новые notes/logs/runners только в `.orchestra/tasks/V-1273/gate-isolation/`. Прежние sanitized logs/report/private-originals pointers сохранены; root-private не читается. Новые stdout/tracebacks нормализуются **в памяти до записи**, исходные account/workspace/system paths не сохраняются в task artifacts. Результаты, RED/failed/exit codes не удаляются. Новые raw originals не объявляются сохранёнными в прежней private папке.

SHA-256:

| Source | SHA-256 |
|---|---|
| `app/hub_workspace.py` (не менялся) | `ad2ad846751a0e5d774366f5ce924d0251d7b5844a67b19d03ce1cb226d2481f` |
| test до | `06836f885a06eca42e6edc19f1d803a603af403763452e5d533d52736dbe13e4` |
| test после | `e86f7551ba1c663ace8624d7a708df8f79831a68c07d227313b687666b3d2e20` |
| `CHANGELOG.md` (не менялся) | `de4d08897c5597d4c843b3b99dec54377c7b64f45952f057fa5ff6b59404632e` |

Полный repository suite и повтор privacy/scanner не запрашивались и не запускались; root уже сообщил зелёный full-host контроль этих 104 проверок. Модель/живая инфраструктура не использовались. Никаких изменений product fix или иных систем.
