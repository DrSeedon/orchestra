# V-1103 — expected_head full-SHA refusal in error-watch

Правка готова в рабочей копии. Предлагаемый заголовок коммита платформы:
`#V-1103: исключить штатный отказ merge с коротким SHA из error-watch`.
Git-команды не выполнялись: по контракту hub copy коммит создаёт платформа.

## Изменения и границы

- `app/error_watch.py`: отдельный полностью ограниченный шаблон сообщения
  `Merge operation ...: FAILED — expected_head must be the full ...-character SHA
  from worker_wip. Inspect worker_wip and supply its full SHA and a meaningful
  acceptance_note, then start a new operation.`. Класс шума:
  `merge refused: full expected_head required`.
- Поддержаны исходный текст с числом символов и нормализованный с `<ID>`/`<N>`.
  Совпадение требует полного сообщения вместе с инструкцией восстановления;
  иной префикс, дополнительная ошибка или другая причина отказа не совпадают.
- Как для V-1068, точный отказ исключён также из `post_fix_verdict`: старая
  зарегистрированная запись исправления не превращает шум в ложный рецидив.
  Остальные классы шума и существующие правила гейтов не изменены.
- `tests/test_error_watch.py`: 10 новых параметризованных сценариев. Проверены
  исходная/нормализованная формы, 40/64 символа, префикс логгера, порог 12 событий,
  другие отказы expected_head, конфликт, ошибка acceptance gate, дополнительная
  ошибка после штатного текста, смешанная выборка, сохранённая запись исправления
  и повторный запуск сканирования без дублирования настоящей находки.
- Добавлена запись в `CHANGELOG.md`. Merge-код и проверка приёмки не менялись.

Наблюдение: одного добавления класса в `_NOISE` недостаточно для старых записей
`fixes`: путь `post_fix_verdict` намеренно не исключает все классы шума. Поэтому
новое узкое исключение повторяет решение V-1068 и на этом пути.

## Обязательный прогон — заблокирован неполной копией

В обоих тестовых shell использован provisioned uv 0.11.28:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
mkdir -p .orchestra/tasks/V-1103/tmp
export TMPDIR="$PWD/.orchestra/tasks/V-1103/tmp"
uv run --frozen python -m pytest tests/test_error_watch.py -q
```

Перед финальным повтором дополнительно установлен `UV_OFFLINE=1`; `.venv`
создана самим uv из неизменённого `uv.lock`. Другой runner не использовался.

Финальный вывод (полностью сохранён в `pytest-after.log`), exit 2:

```text
ERROR collecting tests/test_error_watch.py
tests/test_error_watch.py:10: in <module>
    from app import error_watch as watch
app/error_watch.py:18: in <module>
    from app.db import DB_PATH
E   ModuleNotFoundError: No module named 'app.db'
ERROR tests/test_error_watch.py
Interrupted: 1 error during collection
1 error in 0.72s
```

В `app/` передан только `error_watch.py`: нет `app/db.py`, `app/secret_mask.py`
и остальных зависимостей глобального `tests/conftest.py`. Обязательный полный
целевой прогон НЕ выполнен; нужен повтор в полной копии репозитория. Начальная
попытка с тем же блокером записана в `pytest-before.log`.

## Дополнительная изолированная проверка — не замена обязательному прогону

`check_isolated.py` под тем же `uv run --frozen python` подключает заглушки только
для отсутствующих `app.db.DB_PATH` и `app.secret_mask.mask_secrets`, затем запускает
реальные тесты из `tests/test_error_watch.py` с `--noconftest`. Маскирование секретов,
общие autouse-фикстуры и интеграция с остальным приложением этим не проверяются.
Коллекторы в scan-тесте подменены синтетическими событиями; боевые БД, journalctl,
сервисы и сеть тестами не использовались.

```sh
uv run --frozen python .orchestra/tasks/V-1103/check_isolated.py
```

- До изменения классификатора: **4 failed, 6 passed, 68 deselected in 1.38s**
  (`isolated-before.log`). Падает именно ожидание исключения сигнатуры из находок;
  контроли настоящих отказов проходят. Это подтверждает чувствительность теста
  к отсутствию нового правила.
- После изменения: **10 passed, 68 deselected in 0.58s**
  (`isolated-after.log`).

Дополнительно проверены соседние правила Codex/квот и ожидаемых отказов хаба:

```sh
UV_OFFLINE=1 uv run --frozen python .orchestra/tasks/V-1103/check_isolated.py 'merge_full_sha_refusal or other_merge_failures or quota or codex or other_noise or expected_hub or hub_finish_post_fix or marker_without_db'
```

Результат: **45 passed, 33 deselected in 1.25s** (`isolated-neighbors.log`).

Абсолютный путь импортированного пространства `app`:
`<hub-workspace>/app`.
Фактически исполнявшийся модуль:
`<hub-workspace>/app/error_watch.py`.

Изменённые участки просмотрены: существующие тесты не ослаблены, соседний merge-код
не менялся, реальные секреты в артефакты не копировались. Живой процесс не трогался.
AST-разбор и проверка отсутствия концевых пробелов трёх изменённых Python-файлов
прошли; временные данные тестов из каталога задачи удалены.
Остаётся обязательный прогон в полной копии; статус готовности к приёмке должен
учитывать этот блокер.
