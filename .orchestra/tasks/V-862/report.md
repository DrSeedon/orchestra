# V-862 — снятие quota gate до заданного срока

## Изменение

Ручное снятие сохраняет абсолютное время окончания Unix timestamp-ом в `kv` под ключом `quota_gate_override_until`. `app.main.lifespan` восстанавливает его после `init_db()`. Истёкшее, некорректное или более чем на 14 дней вперёд значение не открывает гейт. Сброс через `minutes: 0` удаляет сохранённое значение; прежний положительный `minutes` продолжает задавать длительность.

`POST /api/usage/quota-override` принимает либо `expires_at` (ISO 8601 с явным часовым поясом), либо `minutes`; одновременная передача полей, naive timestamp, прошлое время и срок свыше 14 суток отклоняются с HTTP 400. Карта квот возвращает и остаток секунд, и ISO время окончания. Существующий `AuthMiddleware` не менялся: API по-прежнему требует текущую dashboard-сессию или `INTERNAL_TOKEN`, если включена авторизация.

Панель показывает `datetime-local`, преобразует локальное время браузера в ISO timestamp для сервера, отображает время возврата гейта в локальном часовом поясе, а при активном снятии показывает кнопку «вернуть гейт сейчас».

## Проверки

В [tests.log](tests.log) записаны целевые прогоны:

- `tests/test_quota_gate.py -k gate_override`: 10 passed; проверены открытый гейт до expiry, закрытие после него, восстановление сохранённого expiry и граница 14 дней.
- `tests/test_quota_map_api.py -k 'rule_constants_travel_with_the_payload or rule_constants_reflect_environment_overrides or panel_sees_the_manual_override_and_its_expiry'`: 3 passed.
- `tests/test_quota_wait_queue.py -k owner_override`: 5 passed; проверены прежний `minutes`, ISO expiry, отказ для прошлого/naive/>14d и немедленная очистка persisted expiry.
- Браузерная проверка `tests/test_t344_quota_lines_browser.py::test_gate_override_uses_a_browser_local_datetime_and_shows_an_expiry`: 1 passed. В часовом поясе `Asia/Krasnoyarsk` ввод `2026-10-20 14:00` отправил `2026-10-20T07:00:00.000Z`; активное снятие показывает локально отформатированный срок и кнопка восстановления отправляет `minutes: 0`.
- После добавления проверки повреждённого KV-значения повторно прошёл `tests/test_quota_gate.py -k 'gate_override or corrupt_persisted_expiry'`: 11 passed.

Итог: 20 уникальных тестов прошли; полное тестовое дерево не запускалось. Скриншот формы — [quota-override-form.png](quota-override-form.png). Импортированный Python-модуль: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-api/app/quota_gate.py`.

Первая проверка восстановления поймала `NameError` из-за оставшейся ссылки на удалённый кэш пути БД; ссылка удалена и полный набор повторно прошёл. Отдельная попытка выбора теста содержала неверный pytest node id и завершилась `no tests ran`; она сохранена в [tests-targeted.log](tests-targeted.log) и в число проверок не включена.

## Развёртывание

После слияния нужен рестарт Orchestra: изменение затрагивает `app/quota_gate.py`, `app/routes/system.py` и `app/main.py`. Самостоятельный рестарт не выполнялся.
