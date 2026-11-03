# V-1197 — Codex steer refusal and target FIFO

Исправлены `app/backend_codex.py`, `app/message_deliveries.py`; добавлены
`tests/test_codex_steer_rejection_v1197.py` и запись Unreleased в CHANGELOG.
`app/session.py`, замороженные acceptance-тесты, политики и V-1160 не менялись.

## Механизм и изменение

`AgentSession.send()` вызывает `delivery.before_submit()` перед `backend.send()`.
JSON-RPC reader сопоставляет ответ с future по id и поднимает
`CodexProtocolError("request", error)`. Прежде любой такой сбой после начала
вызова становился `DELIVERY_UNKNOWN`, а runner запрещает пересекать эту голову FIFO.

Теперь только ответ **-32600 / точное `no active turn to steer`** на ожидаемый
`turn/steer` превращается внутри `CodexBackend.send()` в
`CodexSubmissionRejectedError`. Совпадение текста RuntimeError, ответ на чужой id,
тот же текст в `turn/start`, другой код/текст, внутренний сбой, timeout, EOF или
cancel не являются подтверждением отказа.

Общий путь фиксации исхода сообщения распознаёт этот тип только для DISPATCHING.
В одной `BEGIN IMMEDIATE` транзакции сохраняются терминальный существующий статус
FAILED_BEFORE_SUBMIT, ошибка PROVIDER_REJECTED / outcome_unknown=false и уведомление
отправителю. Отказанный user_message удаляется из восстанавливаемой истории;
исходный payload остаётся в квитанции. Явный повтор с тем же ключом восстанавливает
одну строку истории в prepare. Повторные наблюдатели не меняют терминальную запись.
Runner уведомляет отправителя и продолжает FIFO. Автоматической повторной отправки
отказанного сообщения нет.

Существующие DELIVERY_UNKNOWN и SUBMITTED не переклассифицируются, даже при позднем
типизированном исключении. Восстановление неизвестных исходов после teardown
сохраняет прежний DELIVERY_UNKNOWN_ORPHANED и никогда не повторяет их payload.
Боевые зависшие записи этим патчем не изменяются. Иные явные отказы оставлены
консервативно неизвестными до отдельного подтверждения их семантики.

## Фактические проверки

Runner: provisioned uv **0.11.28**, `uv run --frozen python -m pytest ... -q`;
обычная `.venv`, lock не менялся. TMPDIR для тестов — внутри этой task-папки.
Импортированный app:
`app/__init__.py` (относительно корня репозитория).

- До исправления: backend Codex + head-of-line тесты — **116 passed / 8.02 s** (`baseline.log`).
- 14 новых synthetic-only проверок — **14 passed / 5.33 s** (`regressions.log`).
  Реальные RPC correlation, session.send, SQLite и target runner; подтверждённый
  отказ, неоднозначные исходы, два runner, два потока-наблюдателя, rollback при
  ошибке записи уведомления, повтор того же ключа, восстановление и старая запись.
- Отрицательный контроль: временно отключено только распознавание кода отказа;
  сквозной тест **1 failed / 3.76 s**, получен исходный
  `CodexProtocolError: request: no active turn to steer` (`red.log`). Исправление
  восстановлено через finally, после этого выполнен финальный прогон.
- Финальный целевой набор — **205 passed / 14.31 s** (`final-targeted.log`):
  новый файл, test_backend_codex, test_delivery_head_of_line_block,
  test_message_delivery_receipts_380, test_durable_steering_562,
  test_codex_mailbox_703, test_message_delivery_failure_notices_741,
  test_cron_drain_delivery_v1074, test_initial_delivery_review_regressions,
  test_delivery_queue_block_connection. Timeout проверки 30 s ограничивает зависания.
- Расширенный предыдущий прогон также включал test_undelivered_queue:
  **207 passed, 7 failed / 19.15 s** (`targeted.log`). Все 7 падений — отсутствует
  `.orchestra/pipelines/default/pipeline.yaml` в частичной копии. Эти тесты не
  ослаблялись и отсутствующий pipeline не подменялся.
- Обязательный полный `uv run --frozen python scripts/run_tests.py`:
  **exit 2**, отсутствует сам `scripts/run_tests.py` (`full-suite.log`). Полный gate
  и семь зависимых от pipeline проверок требуют полного checkout у принимающего.
- Финальное чтение изменённых блоков, AST parse трёх Python-файлов и проверка
  четырёх исходных файлов/текстовых артефактов по HUB_SECRET_SHAPES — без находок
  (`final-review.json`). Синтетические временные БД и каталоги тестов удалены.

## Идентичность и ограничения

**Точный HEAD недоступен:** копия предоставлена без `.git`, SHA в задании нет;
`git rev-parse HEAD` реально завершился 128 / not a git repository. SHA не выдуман.
Ветка назначения из задания — `task-V-1197/fix-steer-fifo`; принимающий оркестратор
должен записать фактический base/result HEAD. SHA256 изменённых файлов и uv.lock,
относительные пути app/интерпретатора сохранены в `verification.json`.
Исходные абсолютные пути и сырые доказательства сохранены приватно;
публичные логи содержат `<workspace>` / `<private-path>` вместо них.

Ни live DB, ни реальные сообщения/провайдеры, ни production FIFO не использовались.
Рестарты, деплой, git commit/push/clone не выполнялись. V-1160 из другой ветки не
переносилась. Изменение Python на диске не утверждается работающим в живом сервисе.

## Подготовка к приёмке — 2026-11-02

Исходные 10 артефактов до очистки сохранены побайтно в
`.orchestra/private/V-1197/evidence-before-cleanup/` (каталоги 0700, файлы 0600).
Этот каталог исключён существующим правилом `.orchestra/private` в корневом
`.gitignore`; дополнительно внутри V-1197 стоит приватный `.gitignore` с `*`.
SHA256 оригиналов и список пяти очищенных публичных файлов —
`acceptance-cleanup.json`; результат проверки — `acceptance-check.json`.

Публичные report, verification и логи больше не содержат защищённых абсолютных
путей, аккаунта, host/workspace identifiers хаба. Строки с итогами тестов сохранены.
SHA256 двух изменённых модулей, нового теста, CHANGELOG и uv.lock совпадают с
первоначальной verification: на этом этапе код и тесты не менялись и не запускались.

Остаются ровно ограничения частичной копии: нет `.git` для установления точного
HEAD и проверки индекса/`git check-ignore`, нет полного runner
`scripts/run_tests.py`, нет pipeline для семи ранее упавших проверок. Принимающему
нужно проверить доставку приватных оригиналов и их отсутствие в индексе, записать
фактический HEAD и выполнить полный gate в полном checkout. Новых запусков
production, провайдеров, рестартов или автоматического закрытия задачи не было.
