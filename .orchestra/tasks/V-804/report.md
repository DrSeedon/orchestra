# V-804: Telegram waiting status

## Что показывал интерфейс

В Telegram running/idle — это custom-иконки заголовка топика: `⚡` (`_ICON_RUNNING`) и `☕` (`_ICON_IDLE`) в `app/tg_bridge.py`; отдельного сообщения статуса для них нет. Фронтенд определяет общее состояние оркестратора в `app/static/js/app.js`: `running` при работающем scope, затем `waiting` при `any_waiting`, иначе `idle`. `app/static/js/chat.js:2397` показывает `⏳` у отдельной workflow-задачи со статусом `waiting`; `app/static/js/usage.js:189–210` показывает `⏳` рядом с оценкой времени до quota limit.

Read-only вызов Telegram `getForumTopicIconStickers` вернул 112 доступных topic icon stickers, среди которых не было `⏳` или `⌛`. Поэтому waiting отображается префиксом `⏳ ` в существующем названии топика, а иконка `⚡`/`☕` продолжает показывать running/idle. Это редактирование метаданных топика, не отправка нового сообщения.

## Реализация

`_waiting_scopes()` объединяет активные сессии `WAITING`, их in-memory `_pending_messages`, невыданные owner/dashboard записи mailbox, scope доставок `WAITING_QUOTA` из `message_deliveries` и `initial_deliveries`, а также workflow calls, ожидающие shared scheduler slot. Для последних `workflow_scheduler.waiting_run_ids()` читает активные невыданные leases, а bridge связывает run id с активным `bg_jobs.target_scope` через `--run-id` в сохранённой команде запуска. `mailbox.pending_owner_scopes()` использует тот же фильтр происхождения, что UI чата: сообщения владельца и dashboard; сообщения агента, которые не показаны там как owner queue, не создают ложную отметку. `quota_queue.waiting_scopes()` читает обе durable-таблицы без изменения строк.

Полная сверка статусов идёт раз в 30 секунд; событие `message queued` отмечает ожидание сразу. Переходы проходят существующий гистерезис V-785: новое состояние должно продержаться 60 секунд, попытки изменения одного топика разделены минимум 60 секундами. Основание для порога: в V-785 после одного хода было зафиксировано 14 service notices от смены topic icon; задача добавляет долговременный сигнал ожидания, но не должна возвращать реакцию на кратковременные running/idle колебания. Удаление ⏳ проходит тот же гистерезис, поэтому краткая пауза не мигает. Неудачный API вызов не обновляет локальный cache; интервал попытки не позволяет зациклить повтор. Перед `edit_forum_topic` расходуется общий group rate slot через `_tg_reserve_rate_slot`, так что статус учитывает лимит группы 20 запросов за 60 секунд и не отправляет отдельные сообщения.

## Проверки

Из worktree `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-telegram`:

```text
uv run --frozen python -m pytest tests/test_tg_bridge.py -k topic -q
51 passed, 172 deselected

uv run --frozen python -m pytest tests/test_tg_bridge.py tests/test_mailbox.py tests/test_quota_wait_queue.py tests/test_workflow_scheduler.py -q
269 passed, 1 warning in 10.25s
```

Добавлены проверки добавления/снятия префикса, объединения runtime и durable причин ожидания, отображаемого фильтра mailbox, очистки quota scopes после выпуска, а также выборки и привязки ожидающего workflow run к scope. Единственное предупреждение полного прогона — `RuntimeWarning` в `tests/test_mailbox.py`: coroutine `_S._notify_scope_idle` was never awaited.

Импортированный модуль: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-telegram/app/tg_bridge.py`.

## Состояние запуска

Python-правка требует рестарта Orchestra, чтобы попасть в живой процесс; рестарт не выполнялся.
