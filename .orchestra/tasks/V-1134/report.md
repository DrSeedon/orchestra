# V-1134 — очередь сообщений под composer

Готово в исходниках. Все данные проверок синтетические; исходный скриншот и переписка не запрашивались. По отсутствующему скриншоту нельзя установить, к какому из описанных ниже состояний относились именно его строки.

## Причина

`GET queued-messages` показывает `mailbox.pending`, а не обычные delivery receipts. В одном списке действительно встречаются:

- Сообщения «После хода»: активному агенту их передают в конце хода; простаивающий агент получает ввод обычным немедленным путём.
- `codex_steer_backup_pending` и `codex_steer_backup`: сохранённые копии ввода в текущий ход Codex. Последняя уже отправлена backend-у и хранится до успешного завершения хода; после сбоя обеспечивает повторную доставку.
- Записи, взятые обработчиком доставки (`claimed_at`). Claim сам по себе не подтверждает доставку и может пережить неудачную попытку.

Прежняя панель не различала эти случаи, показывала только тело и иногда `delivering`. Она предлагала отмену уже отправленной резервной копии; SQL действительно позволял удалить такую копию. Поздние GET могли воскресить исчезнувшую строку, а `cancelled: false` игнорировался. Оснований считать все pending результатом квоты нет.

## Изменения

- `app/routes/sessions.py::get_queued_messages`: добавлены производные `state` и `cancellable`, прежние поля сохранены. Состояния получены только из существующих provenance/claim, без новой таблицы или изменения доставки. Сохраняются фильтр владельца/dashboard и канонический порядок `mailbox.pending` по id.
- `app/mailbox.py::cancel`: атомарный запрет отмены двух типов current-turn backup. Неизвестный результат инъекции тоже не позволяет безопасно обещать отзыв. Обычная отмена по id/recipient/scope и победа claim сохранены.
- `app/static/js/chat.js`: заголовок очереди с выбранным агентом и понятное пояснение каждой стадии; принятая after-turn запись не изображается обычным доставленным сообщением и не подавляет будущий SSE echo. Устаревшие ответы отсекаются по поколению выбора и порядку применённых ответов. Более поздний ещё ожидающий GET не мешает показывать уже пришедший актуальный ответ. DELETE создаёт барьер для старых GET; подтверждённая отмена удаляет текущую строку даже после её перерисовки опросом и при ошибке последующего GET. Отрицательная/неподтверждённая отмена объясняется честно. Временная ошибка чтения сохраняет известные pending и помечает статус устаревшим.
- Отправка фиксирует agent/scope до ожидания uploads; двойной клик во время uploads не создаёт второй send. Поздний ответ не очищает чужую панель, новый текст или состояние кнопки другого агента. Неудачная after-turn отправка сохраняет черновик. Принятый префикс убирается из собственного текущего/сохранённого черновика, сохраняя дописанный текст.
- `app/static/js/i18n.js`: только новые строки около `After turn`. `app.js` не изменён; фоновые задания/ETA V1135 независимы. Координация точных символов отправлена через outbox.

Неочевидный контракт черновика: текущие `selectAgent`/`onOrchestratorChange` сохраняют черновик до `resetChatTransientState`, затем восстанавливают новый до `refreshQueuedMessages`. Код хранит ссылку именно на этот снимок черновика, а не ищет произвольный новый черновик по имени после ответа. Этот порядок воспроизведён в JS регрессиях, включая A→B→A.

Старый Python, возвращающий лишь прежние поля, остаётся совместимым: строки видимы с общим статусом ожидания подтверждения; отмена не предлагается без явного `cancellable`. Новая семантика требует загрузки нового Python штатным жизненным циклом владельца. Сервисы здесь не запускались и не перезапускались.

## Проверено

Использован provisioned uv 0.11.28 через обязательный PATH, default `.venv`, `--frozen`. Без замены runner или lock. Python-тестам задан TMPDIR и basetemp внутри каталога задачи; внешние провайдеры и сеть в тестах не использованы.

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1134/tmp"
uv run --frozen python -m pytest \
  tests/test_composer_queue_status_v1134.py \
  tests/test_composer_queue_frontend_v1134.py \
  tests/test_mailbox.py tests/test_codex_mailbox_703.py \
  tests/test_durable_steering_562.py tests/test_static_js_globals.py \
  tests/test_quota_wait_queue.py tests/test_delivery_queue_block_connection.py \
  -m 'not browser' -q --basetemp=.orchestra/tasks/V-1134/tmp/pytest
```

**91 passed, 19 deselected, 1 warning, 25.57 s.** Из новых проверок: 9 backend/API и 19 actual-JavaScript сценариев. JS проверки выполняют целиком production `chat.js` в Node 22.23.3 с минимальным DOM double и управляемыми синтетическими API promises. Существующие mailbox, Codex recovery, durable steering, quota queue и delivery blocking также прошли. Warning из существующей фикстуры `tests/test_mailbox.py`: `_S._notify_scope_idle` coroutine was never awaited.

Проверены FIFO, старый provenance без subtype, scope/recipient изоляция, запрет ранней отправки активному агенту, idle immediate path, claim/cancel, release/retry, исчезновение delivered/cancelled, защита backup, stale GET и 404, медленные перекрывающиеся опросы, переключения agent/scope/A→B→A, отмена при перерисовке/ошибке сети, uploads/double-click, SSE dedup и сохранение черновиков. Проверок конкретной формулировки текста нет.

`node --check` для обоих изменённых production JS и трёх JS тестового стенда — успешно. AST parsing двух изменённых Python-файлов и двух новых Python-тестов — успешно. Путь импортированного `app` проверен через `Path(app.__file__).resolve()`: он равен текущей worker-copy + `/app/__init__.py`. Абсолютный путь наблюдался при запуске; host-specific префикс исключён из трекаемых артефактов по более узкому требованию V-1134 «no remotehubidentities».

Логи: `targeted.log`, `source-checks.log`, `frontend-collection.log`, `browser-tests.log`. Это синтетические task artifacts без клиентской переписки; host-specific пути в логах нормализованы перед передачей.

## Обязательная проверка родителем после DONE

Браузерный запуск предпринят для `test_actual_browser_dom[chromium-states_order_content]`, но остановился до выполнения JS: **`BrowserType.launch: Executable doesn't exist`**, отсутствует Playwright `chromium_headless_shell-1223`. Chromium не устанавливался. Все **19 реальных браузерных сценариев остаются непроверенными**; Node/DOM double не выдаётся за реальный браузер. Эти же сценарии добавлены в Playwright с настоящим DOM, viewport 390×844 и синтетическим API, без live-сервера.

На полном хосте выполнить:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
uv run --frozen python -m pytest tests/test_composer_queue_frontend_v1134.py -m browser -q
```

Полный `scripts/run_tests.py` и проверка живого dashboard не выполнялись. Не было push/merge, deploy, рестартов, доступа к клиентским данным, платных вызовов или публичной публикации. Импорт, визуальная компоновка и интеграция с полным dashboard требуют приёмки родителем на полном хосте. Протокол at-least-once, claim lease, runtime routing, quota exception и hub lifecycle не менялись.

Проверка передачи: изменённые source/test файлы и task artifacts просканированы `scripts.secret_scan.scan_text` и `HUB_SECRET_SHAPES`; совпадений форм секретов нет. Новые тесты/артефакты дополнительно проверены на приватные пути и host identities, пути в evidence нормализованы. Сводка — `artifact-checks.log`. Временные базы, браузерная проба и служебные скрипты редактирования удалены.

## Продолжение: changelog и focused-check после обновления базы

По повторному поручению оркестратора добавлена одна запись V-1134 в `CHANGELOG.md`, раздел `Unreleased`. Запись описывает различие after-turn/current-turn backup/claim, честную отмену и защиту от устаревших ответов. Остальные записи и implementation-файлы в этом продолжении не менялись. Повторное исследование, внешние обращения и операции Git не выполнялись.

Повторён приведённый выше focused pytest command через provisioned **uv 0.11.28** с `--frozen`, default `.venv` и временными данными внутри задачи. Результат: **91 passed, 19 deselected, 1 warning in 14.36s**. Предупреждение прежнее: фикстура `_S._notify_scope_idle` в существующем `tests/test_mailbox.py`. Отдельно прошли `node --check` для пяти JS-файлов и AST parsing четырёх Python-файлов; импорт `app` проверен на принадлежность текущей worker-copy. Установка зависимостей/runner не подменялась, lock не менялся.

Новые свидетельства: `followup-runner.log`, `followup-focused.log`, `followup-source-checks.log`. Все 19 browser-сценариев по-прежнему требуют реального Chromium и приёмки родителем на полном хосте; в этом focused-прогоне browser marker явно исключён. Ранее зафиксированный блокер запуска браузера не перепроверялся и не объявляется устранённым.

## Parent host acceptance

Accepted integrated source after the real Chromium run: 19 passed, 19 deselected. Required full host suite: 6854 passed, 54 skipped, 6 warnings; four ownership tests require passwordless sudo and did not run. Imported app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-composer-queue-status/app/__init__.py`. Instruction contract passed. Parent process-local restoration of old mailbox cancellation failed the committed recovery-backup test; disabling GET ordering failed the committed production-JS scenario. Evidence is retained locally under `.orchestra/private/V-1134/`; generated historical screenshots were preserved there before restoring tracked originals. All 19 changed files passed shape, literal and forbidden-string publication scans. Python behavior remains pending the authorized idle watcher; no service restart was performed. Live full-dashboard visual integration remains unverified.
