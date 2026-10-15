# V-860 — голосовой ввод в чате дашборда

## Результат

Голосовая запись теперь сохраняется в IndexedDB порциями раз в секунду. После перезагрузки или закрытия вкладки интерфейс восстанавливает аудио и предлагает расшифровать или удалить его. При остановке записи XHR показывает загрузку с процентом, затем отдельное состояние расшифровки. Ошибка сохраняет запись и оставляет действие повтора.

IndexedDB — необязательная страховка: ошибка открытия или записи не останавливает MediaRecorder и отправку на расшифровку. Пока запись не расшифрована, интерфейс показывает предупреждение, что запись не сохраняется и страницу нужно оставить открытой. Черновик хранит имя агента и scope, записанные при старте; retry использует эти значения, а ответ дописывается в поле или in-memory draft этого агента, даже если открыт другой чат.

Клиент вызывает существующий `POST /api/transcribe` без `send=true`. Серверный обработчик в `app/routes/tg.py:207` уже валидирует аудио, вызывает общий `transcribe_audio` и возвращает `{text}` синхронно. Новый результат дописывается в текущий `#chat-input` как `🎙 Voice transcription:` (в русской локали — «Расшифровка голосового»); запрос отправки сообщения не выполняется. Аудио удаляется из IndexedDB после вставки текста или явного удаления.

## Проверка

Playwright-сценарии запускают Chromium с `--use-fake-device-for-media-stream` и `--use-fake-ui-for-media-stream`. Проверяют: сохранение набранного текста и отсутствие автоотправки; восстановление записи после перезагрузки; сохранение записи и повтор после ответа 502. Скриншоты сохраняются в `screenshots/`.

Команда `uv run --frozen python -m pytest tests/test_frontend.py -q -k 'dashboard_voice_appends_transcript_without_sending or dashboard_voice_recording_survives_reload or dashboard_voice_transcription_failure_keeps_retryable_recording or dashboard_voice_transcribes_when_indexeddb_is_unavailable or dashboard_voice_transcript_stays_with_recording_agent_when_selection_changes'` прошла: **5 passed, 122 deselected, 62.84 s**. Проверены `uploading` и `transcribing`, сохранение введённого текста, восстановление ненулевого аудио после reload с повтором под исходным агентом, переключение агента во время ответа сервера, ошибка 502 и повтор. IndexedDB failure injection ранее краснел на прежнем коде: с `SecurityError` состояние `recording` не наступало; после исправления тест проходит. Реальный импорт тестов: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-voice-input/app/__init__.py`.

`node --check app/static/js/chat.js`, `node --check app/static/js/i18n.js` и `git diff --check` прошли. Скриншоты: `screenshots/recording.png`, `screenshots/transcription-appended.png`, `screenshots/recording-recovered-after-reload.png`, `screenshots/transcription-error-retry-available.png`. Серверная часть не менялась, поэтому рестарт не нужен; JS и CSS подхватываются браузером без перезапуска Python.

## CI follow-up: переключение агента и очистка браузера

В CI run `38704809000`, attempts 1 и 2, четыре первых voice-сценария прошли, но тест переключения агента завершился по 30-секундному таймауту; два последующих теста того же xdist worker тоже упали по таймауту. В тесте ответ `/api/transcribe` задерживался правкой `XMLHttpRequest` listener, а страница закрывалась только в конце успешного сценария.

Тест теперь удерживает ответ на Playwright route, переключает агента, пока запрос остаётся в `uploading`, затем освобождает запрос и проверяет, что расшифровка попала в черновик исходного агента. Route отменяется при ошибке. Каждый voice-тест получает отдельный browser context с teardown fixture; мобильный пропускаемый сценарий тоже регистрирует закрытие контекста как finalizer.

Пять тестов видны в `pytest --collect-only -m browser` и прошли с CI-настройками xdist: `5 passed in 35.05s`. Полный запуск CI browser-команды `uv run --frozen pytest --rootdir=. -n 2 --dist=loadscope -v -rf --timeout=30 -m 'browser' tests/` завершился: **199 passed, 7 skipped, 206 collected, 301.17s**. В нём четыре сценария, шедшие после теста переключения агента, тоже прошли. Исправление только в тестах; приложение и его lifecycle не менялись.

## Ограничение

Запись защищена сохранёнными MediaRecorder-чанками. При аварийном закрытии до первого завершённого чанка восстановить аудио нельзя; в штатной записи чанки пишутся с интервалом 1 секунда.
