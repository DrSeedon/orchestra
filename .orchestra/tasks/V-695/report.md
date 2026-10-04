# V-695: spawn_worker теряет начальную задачу после таймаута

## Выбор подхода
Рассмотрены: (а) «досылка на повторе» без памяти о намерении; (б) приём доставки внутри `POST /api/sessions`; (в) выбранный: интент + резюме.
- (а) не отличает потерянную доставку от чужого воркера с тем же именем: «другое задание — честный отказ» невыполнимо.
- (б) сообщение воркеру включает кросс-репо предупреждение, зависящее от ответа создания (`git_common_dir`) → хеш сообщения при повторе разошёлся бы.
- (в) `delivery_id` выбирается до создания и уходит в create; сервер пишет `kv spawn_intent:<session_id>` = {delivery_id, sha(task)} (без миграции схемы). После таймаута/409 клиент зовёт `POST /api/sessions/{name}/spawn-resume`: сервер соглашается, только если интент совпал и (доставка уже есть, или воркер idle с 0 ходов). Дальше обычная идемпотентная доставка (`initial_deliveries` PK по delivery_id) → ровно один раз. Отказы: `SPAWN_NAME_TAKEN`, `SPAWN_SESSION_NOT_FRESH`. Если create не дошёл (404 на resume), ошибка несёт `next_action` с delivery_id.

## Тесты (`tests/test_spawn_resume_695.py`, через TestClient + реальные роуты/БД, менеджер подменён)
Таймаут на create после создания → доставлено; потерянный запрос доставки → повтор + двойной повтор = 1 строка и 1 wake; другое задание / другой delivery_id → SPAWN_NAME_TAKEN; воркер с ходами без строки доставки → SPAWN_SESSION_NOT_FRESH, строк нет; create не дошёл → next_action.
Мутации (каждая краснит ровно относящиеся тесты): отключение клиентского resume → 5/5 красных; интент-проверка → name_taken; fresh-проверка → already_ran; next_action → never_reached.
Прогон: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_mcp_stdio.py tests/test_initial_deliveries.py tests/test_initial_delivery_review_regressions.py tests/test_spawn_resume_695.py tests/test_validate_spawn_unknown_role.py` → 161 passed; app импортирован из `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-spawn-delivery/app/__init__.py`. Лог: `pytest.log`.

## Ограничения
- Воркеры, уже потерявшие доставку до фикса, интента не имеют: повтор откажет (задачу слать `send_message`).
- Окно между созданием сессии и записью интента в роуте (микросекунды): падение сервера в нём оставляет воркера без интента.
- Почему create >30 с: не исследовано и не измерено. Из кода: `_create_session_locked` под локом имени делает worktree, `create_task_for_scope` и привязку задачи через `to_thread`; конкретное узкое место не найдено. Лечить не требовалось.
- Python-правки (`app/**`) вступят в силу только после рестарта Orchestra (делает владелец).
