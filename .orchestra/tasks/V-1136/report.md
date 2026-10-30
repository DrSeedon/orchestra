# V-1136 — standalone Codex reset

## Изменения

- Добавлен `scripts/codex_reset.py`, независимый от Orchestra/app и сторонних пакетов. Импорт не запускает процессов.
- Недельное окно выбирается только по `windowDurationMins == 10080` среди `rateLimits.primary/secondary`. Поддерживаются недельный primary с secondary=null и прежняя пара 300/10080. Нет недели или есть два недельных окна — ошибка и ноль consume.
- Только первый по expiresAt бонус со status=available; политика `weekly usedPercent >= 95 OR expiresAt - now < 540` сохранена буквально, включая строгое сравнение времени. Ключ всегда `orchestra-<creditid>`; один consume за запуск, без повторов после ошибки/неопределённого результата. На следующих запусках ключ того же бонуса остаётся прежним. Дополнительных видов расходов и маршрутов нет.
- Пустой список доступных бонусов обрабатывается до чтения недельных полей.
- JSON-RPC клиент сопоставляет id, пропускает уведомления и чужие ответы, сохраняет уже прочитанные строки. Ожидание ответа ограничено 30 секундами. RPC/EOF/JSON/timeout/ошибки очистки видны как `REDEEM_FAILED`, код выхода 1. `REDEEMED` печатается только при outcome=reset. Ошибка чтения после подтверждённого reset оставляет обе записи (успех операции и ошибка проверки), повторного consume нет.
- В finally закрывается selector, убивается и reap-ится именно запущенный дочерний процесс, закрываются stdin/stdout; ошибка закрытия selector не мешает очистке процесса. После kill ожидание ограничено пятью секундами.
- Добавлены 61 синтетический офлайн-тест и запись в CHANGELOG. Пятичасовое окно с usage=100 в старой раскладке специально проверяет отсутствие ошибочного расходования при weekly usage<95.

## Wire-контракт (исправлено по источнику родителя)

Первая версия ошибочно использовала `account/rateLimits/resetCredits/consume`. По точному источнику, предоставленному родителем (существующий standalone-скрипт), контракт:

```text
initialize params = {clientInfo: {name: 'orchestra', title: 'Orchestra', version: '1'}}
notification initialized params = {}
account/rateLimits/read -> result.rateLimits, result.rateLimitResetCredits.credits[] = {id, status, expiresAt}
account/rateLimitResetCredit/consume params = {creditId: credit.id, idempotencyKey: 'orchestra-' + credit.id}
result.outcome == 'reset'
```

Скрипт, fixtures и CHANGELOG исправлены. Добавлен `test_actual_wire_matches_supplied_legacy_contract`: реальный `AppServer` поверх pipe, фактически отправленные JSON-RPC строки сравниваются с литералами (константа `CONSUME_METHOD` не импортируется в ожидание). Политика, выбор недели по 10080 и отсутствие реальных вызовов не менялись.

## Проверки и команды

Все Python-команды выполнялись через предоставленный runner:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
uv --version
# uv 0.11.28 (x86_64-unknown-linux-gnu)
```

`uv run --frozen` создал стандартную `.venv`, интерпретатор CPython 3.12.3. Установка использовала неизменённые pyproject.toml/uv.lock. Для временных файлов тестов задан TMPDIR внутри каталога задачи; никаких тестовых данных вне копии не создавалось.

Обычный целевой запуск:

```sh
TMPDIR="$PWD/.orchestra/tasks/V-1136/tmp" \
uv run --frozen python -m pytest tests/test_codex_reset.py -q \
  --basetemp="$PWD/.orchestra/tasks/V-1136/tmp/pytest-default"
```

Результат: **61 ошибка setup**, один общий блокер: `tests/conftest.py:665`, `import app.routes.sessions`, `ModuleNotFoundError: No module named 'app'`. Пакет app отсутствует в предоставленной source-only копии. Полный вывод сохранён в `pytest-default.log`; общие fixtures не менялись. Полный набор приложения и запуск с общими fixtures остаются непроверенными.

Изолированный целевой запуск тем же обязательным runner:

```sh
TMPDIR="$PWD/.orchestra/tasks/V-1136/tmp" \
uv run --frozen python -m pytest tests/test_codex_reset.py -q --noconftest \
  --basetemp="$PWD/.orchestra/tasks/V-1136/tmp/pytest"
```

Результат после финальных правок: **62 passed**, `pytest-isolated.log`. `--noconftest` нужен только из-за отсутствующих исходников app; тесты используют собственные pipes/mocks, не вызывают CLI провайдера, не читают credentials и не выполняют сетевых запросов.

Дополнительно тем же `uv run --frozen python` выполнен in-memory mutation check: исходный тест primary успешно проходит на новой реализации и падает с TypeError при возвращении `week = secondary`; secondary-контроль остаётся зелёным. Подмена выбора недели на primary при паре 300/10080 вызывает AssertionError в тесте запрета лишнего расхода. Файлы исходников не мутировались. Результат и проверка синтаксиса обоих новых файлов: `mutation-check.log`.

Путь реально импортированного скрипта:

```text
<WORKSPACE>/scripts/codex_reset.py
```

Путь импортированного `app`: **отсутствует**, `importlib.util.find_spec('app') is None`. Это не запуск приложения другим интерпретатором и не успешная проверка общего набора.

Проверены формы секретов из канонического `scripts/secret_scan.py`: его чистые определения RULES/_SEP/_PLACEHOLDERS/_is_mention/scan_text загружены через AST без импорта отсутствующего app и без host inventory. Проверены новые исходники, файлы отчёта/логов и только добавленная строка CHANGELOG: **0 находок**, `secret-form-check.log`. Полный Git/forbidden-string publication gate здесь не запускался: нет Git и app. Исходники и состав правок просмотрены вручную; debug/TODO отсутствуют.

## Передача

Изменены только новый скрипт, новый тест, одна запись CHANGELOG и артефакты этой задачи. Чужие исходники не переписывались. На данный момент живой consume, Codex app-server, провайдеры, cron, сервисы, установка и рестарты не запускались; платных расходов нет. На параллельных запусках защита от повторного consume опирается на прежний серверный idempotency key, локальный lock/новый планировщик не добавлялся.

Git в этой копии отсутствует. Commit/push/clone не выполнялись. Платформа должна импортировать и закоммитить изменения в `task-V-1136/fix-codex-reset-window` после завершения хода; проверить коммит и подтвердить wire-контракт может родитель. Статус: реализация и изолированные проверки готовы к ревью, установка требует сверки указанного контракта.

## Повторный прогон после исправления (нормализация)

- `pytest-isolated.log` (`--noconftest`): **62 passed**.
- `pytest-default.log` (обычный запуск): **62 errors** на setup — отсутствует пакет `app` в source-only копии (conftest его импортирует); это не успех обычного прогона, родитель запустит его на хосте.
- Нормализация публикации: в tracked-артефактах пути рабочей копии и идентификаторы хоста/пользователя заменены плейсхолдерами `<WORKSPACE>`, `<HOST>`, `<USER>`; результаты тестов не менялись. Оригиналы сохраняет родитель.
- `mutation-check.log` относится к прогону до исправления wire-контракта и не перезапускался.
