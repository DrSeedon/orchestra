# V-692 — живое сообщение лимитов

`/limits` владельца отправляет фото с текущей карточкой и подписью, где указаны время обновления и следующее обновление по `Asia/Krasnoyarsk`. ID чата, ID сообщения и `next_update` хранятся одной JSON-записью в таблице `kv` платформенной SQLite (`tg_live_limits_message`). Повторная команда отправляет новый ответ и делает его текущим; на старую запись больше не подписан цикл. При старте моста фоновый цикл ничего не отправляет, пока в `kv` нет ID, а при наличии ID ждёт сохранённый срок и редактирует исходное сообщение. Если Telegram ответил, что редактирование невозможно из-за отсутствующего сообщения, отправляется один новый снимок и сохраняется его ID.

Сбой загрузки данных, рендера или Telegram логируется; для повторной попытки используется минутная задержка. «Message is not modified» считается успешным обновлением расписания. Задача включается созданием `_live_limits_loop` в `start_bridge`; отключить автообновление можно, убрав добавление этой задачи в `_tasks`. Интервал меняется константой `_LIVE_LIMITS_INTERVAL_SECONDS` в `app/tg_bridge.py`.

Проверка: `/home/kesha/orchestra/.venv/bin/python -m pytest -q tests/test_tg_bridge.py tests/test_limits_card.py` — 230 passed. Один warning `PytestUnraisableExceptionWarning` возник в существующем `TestMediaGenerationSafety.test_stale_voice_cannot_overwrite_next_text_generation` при закрытии asyncio event loop и subprocess transport. Импортирован модуль из текущего worktree: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-live-limits/app/tg_bridge.py`. Тесты используют моки, реальный Telegram и БД не задействованы. `git diff --check` прошёл.

После мержа Python-изменения потребуют рестарта Orchestra; рестарт выполняет владелец.
