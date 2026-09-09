# fix-gate-timeout — личная память

## Прогон тестов в этом репозитории
- Своего `.venv` в worktree воркера НЕТ. Интерпретатор один:
  `/mnt/data/Projects/Python/orchestra/.venv/bin/python`, и ему нужен `PYTHONPATH=$PWD`.
- Полный сьют одним процессом умирает `RC=137` около 80%. Тяжёлые файлы гонять по одному,
  каждый — свой процесс; `bash -lc` обязателен для `bg_create(type="run")` (там `/bin/sh`).
- Базу «моё это падение или нет» брать отдельным worktree main:
  `git worktree add -f /tmp/mainNNN main` и прогонять ТУ ЖЕ команду там. Сравнивать множества
  node id, а не итоговые числа. 04.09 это спасло от разбора семи чужих красных тестов.

## Ошибка, которая стоила времени (04.09, #474)
Запустил фоновый `--durations` по восьми файлам и в это же время правил `app/db.py`. Прогон
подхватил файл в промежуточном состоянии, `tests/test_manager.py` дал `3 failed`, и я пошёл
искать дефект в своей правке. Повторный прогон после правок — `171 passed`. **Фоновый прогон и
редактирование одних и тех же файлов не совмещаются: либо ждать, либо мерить на отдельном
worktree.**

## Конвенции этого кода
- `.orchestra/tasks/<id>/` внутри `.gitignore`-негации `!.orchestra/**`, поэтому `info/exclude`
  на служебные файлы там НЕ действует. Sidecar `codex_sessions.json` от `codex_review` глушится
  только task-local `.orchestra/tasks/<id>/.gitignore` (более глубокий `.gitignore` сильнее).
- Новая колонка в `review_receipts` — это шесть мест в `app/db.py`: `CREATE TABLE`,
  `receipt_additions` в `_migrate`, `_REVIEW_RECEIPT_COLUMNS`, `task_run_receipt_open` (там
  дословный dict и строгий `values[key]` → `KeyError`), `review_receipt_create` (`or ""`),
  `review_receipt_reserve` (`setdefault`). Плюс `stable` в `review_receipt_record_skip`.
  Седьмое место — `scripts/migrate_review_receipts.py::_receipt` (дословный перечень + вставка
  по `_REVIEW_RECEIPT_COLUMNS` = два владельца одного списка). Пропуск там виден ТОЛЬКО на
  `--apply`: dry-run в базу не пишет и зелен всегда.
- Дефолт аргумента, который тест обязан подменять monkeypatch'ем, нельзя писать как
  `def f(x = MODULE_CONST)`: значение связывается на `def`, и подмена константы не действует.
  Писать `x: float | None = None` и разрешать внутри — так уже сделано у `run_pytest(timeout=)`.

## Снимок ревью: два владельца одного рецепта git (05.09, #493)
Команда снимка написана ДВАЖДЫ: `app/review_coverage.py::production_snapshot` и
`tests/test_review_coverage_gate_462.py::_expected_production_snapshot` (свой subprocess, своё
хеширование — это намеренная независимость оракула). Любая правка команды = правка обоих, иначе
шесть тестов #462 краснеют «receipt outcome/snapshot is not enforced exactly».
- `git diff --raw --full-index` даёт СОКРАЩЁННЫЕ object id (7 симв.). `--full-index`
  разворачивает их только в патче. Для `--raw` нужен `--no-abbrev`.

## `tmp_path` + git = свой репозиторий, всегда (04.09, #474)
Тест брал пустой `tmp_path` и рассчитывал, что тот лежит вне git-репозитория. У меня руками
`/tmp` — отдельный tmpfs, обход вверх упирается в границу mount → зелено. У merge-гейта база
временных каталогов оказалась ВНУТРИ чекаута → `main` разрешался, отказ приходил из другого шва,
тест краснел. Один и тот же набор: `192 passed` у меня, `1 failed, 191 passed` у гейта.
- Воспроизвести чужое «у меня зелено»: `TMPDIR=$PWD/.tmpprobe pytest …` — это ровно условие гейта.
- Любой тест, который трогает git из `tmp_path`, обязан делать `git init` сам.
- Утверждаться на тексте, которым владеет НАШ код (`cannot resolve merge target main`), а не на
  формулировке git: она зависит от версии и от точки запуска, и заодно не различает швы.
- Прогон в двух окружениях (обычное + `TMPDIR` внутри чекаута) — дешёвый способ доказать, что
  тест не зависит от машины. Мутация обязана краснеть в ОБОИХ.

## Путь мержа: где искать, когда «мерж падает непонятно» (04.09, #474)
- Admission: `_prepare_admission_snapshot` (accept) и `_revalidate_review_coverage`
  (execution, `_run_operation` ~1801). Оба зовут git; любой неразрешимый ref раньше летел
  исключением наружу. Теперь исход один — `_review_snapshot_unavailable`.
- **`legacy_unpinned = not accepted_admission`** (~1880) — пустой словарь ВКЛЮЧАЕТ исполнение
  зарегистрированной приёмочной команды. Дописать в него что угодно = молча отключить приёмку.
  Проверять это при любой правке, которая трогает `accepted_admission`.
- `changed_paths` считает untracked (`ls-files --others`), `git diff` — нет. Любая логика,
  сравнивающая «что изменилось» с «что в диффе», обязана это учитывать.
- Красноту «моё или чужое» мерить сравнением МНОЖЕСТВ node id:
  `pytest -q <файлы> | grep '^FAILED' | sort` на ветке и в `/tmp/mainNNN`, потом `diff`.
