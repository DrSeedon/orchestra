# V-1111 — Bash Terminated

Изменения готовы; обязательный полный прогон заблокирован составом hub-копии.

- `app/error_watch.py`: метка `bash child process termination`, условие только
  `source=logs`, `type=tool_result`, `tool_name=Bash`,
  `message.strip() == 'Terminated'`. Проверяется исходный текст, до нормализации.
- `tests/test_error_watch.py`: 18 новых случаев, включая пробелы/переводы строк,
  другой инструмент/регистр, source/type, длинный текст, сбор из SQLite и отчёт.
  Bash и Read с одинаковой сигнатурой проверяются вместе: 10 шумовых событий
  не скрывают 10 настоящих кандидатов.
- `CHANGELOG.md`: строка в Unreleased / Fixed.

## Проверка

Во всех Python-командах использован provisioned uv 0.11.28:

```sh
mkdir -p .orchestra/tasks/V-1111/tmp
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1111/tmp"
uv run --frozen python -m pytest tests/test_error_watch.py -q --basetemp=.orchestra/tasks/V-1111/tmp/required
```

Результат: exit 2, ошибка collection `ModuleNotFoundError: No module named
'app.db'` на `app/error_watch.py:18`. Та же ошибка была до изменений.
В переданной копии из `app/` есть только `error_watch.py`; также отсутствует
`app.secret_mask`. uv и lock исправны; создано стандартное `.venv`, lock не менялся.
Полный файл тестов и глобальные фикстуры НЕ проверены. Нужен повтор команды
в полном checkout оркестратором. Логи: `baseline.log`, `required.log`.

Дополнительный изолированный прогон тем же uv/Python:

```sh
uv run --frozen python -m pytest .orchestra/tasks/V-1111/isolated_checks.py -q --confcutdir=.orchestra/tasks/V-1111 --basetemp=.orchestra/tasks/V-1111/tmp/restored
```

Результат: **18 passed**, `restored.log`. Harness исполняет без изменений
новые определения тестов из `tests/test_error_watch.py` и реальный модуль
`app.error_watch`. Он исключает общий conftest и явно подменяет два отсутствующих
импорта: `DB_PATH` — локальный неиспользуемый путь, `mask_secrets` — identity.
Это дополнительная проверка классификации, SQLite-коллектора и отчёта,
а НЕ успешный обязательный прогон и НЕ проверка маскирования/полного приложения.
Внешние CLI/БД/сеть тестами не используются.

Мутация: `uv run --frozen python .orchestra/tasks/V-1111/check_mutation.py`.
Скрипт добавляет `and False` только к новому условию, запускает те же новые
тесты через изолированный harness и восстанавливает исходник побайтно в `finally`.
Результат: **5 failed, 13 passed**, `mutation.log`: четыре варианта точного
Terminated и тест отчёта краснеют. После восстановления: **18 passed**.
Проверка синтаксиса двух изменённых исходников: OK.

Фактический путь импортированного namespace `app`:
`<hub-workspace>/app`.
Импортирован модуль из
`<hub-workspace>/app/error_watch.py`.
Подтверждение: `import-path.log`.

## Нюансы и границы

`noise_by_class` формируется динамически из меток агрегата: отдельного перечня
классов для отчёта нет, новая метка появляется автоматически (проверено тестом).
`_EXPECTED_HUB_NOISE` — специальный перечень Hub-событий для post-fix verdict,
а не реестр всех шумовых классов; он и остальная логика детектора не менялись.
Схема БД и старые состояния совместимы, миграции не нужны.
Рабочий процесс/cron не запускался и не перезапускался.

Git отсутствует в hub-копии; commit/push не выполнялись согласно роли worker.
Заголовок для коммита платформой: `#V-1111: ignore standalone Bash Terminated in error watch`.
