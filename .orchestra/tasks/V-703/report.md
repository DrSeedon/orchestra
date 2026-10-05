# V-703 — Codex runtime fixes

## Исходы

| Пункт | Исход | Доказательство |
|---|---|---|
| T057 | Исправлено | Codex CLI 0.156.1 принял synthetic payload от `render_codex_history()` через `thread/resume` в отдельном временном `CODEX_HOME`; ответ содержал `cliVersion: 0.156.1`, `historyMode: legacy`, `status: idle`, ошибки отсутствовали. Живые треды не использовались. Pin обновлён на 0.156.1; `_verify_history_version()` проверяется тестом с подменённым выводом, сам CLI в тестах не запускается. |
| T066 | Исправлено | `_get_usage_data()` теперь пишет `repr` исключения, поэтому `TimeoutError()` виден; cleanup гасит `ProcessLookupError` от гонки `kill()` с завершением subprocess. Тесты проверяют строку лога и смоделированную гонку. |
| T067 | Исправлено | Обычный direct input по-прежнему сразу отправляется через `backend.send()` в активный Codex-ход. До отправки создаётся mailbox backup с provider turn id; после принятия steer он помечается. Успешный terminal event удаляет backup этого хода, failed terminal оставляет его для существующей доставки mailbox следующим ходом. Тесты проверяют live steer, отсутствие replay после успеха и ровно одну доставку после failure. Durable receipt steers продолжают использовать восстановление V-562 по provider ref. |
| T098 | Дефекта уже нет | `SessionManager.auto_resume_all()` сначала выбирает строки со статусом `running`/`interrupted`/`waiting`, затем до загрузки переводит их в БД в `idle`. `_load_from_db()` не копирует сохранённый статус в `AgentSession`, поэтому восстановленный объект использует default `IDLE`; попытка resume при залипшем writer проецируется как `broken`/`writer_conflict`. Точечные тесты восстановления и writer conflict прошли. |
| T103 | Исправлено | Terminal marker ставится только для `usageLimitExceeded`/`sessionBudgetExceeded`; обычный retryable 429 не становится terminal. При `utilization >= 100` дата берётся у исчерпанного окна; если исчерпанное окно определить нельзя, выводятся оба reset с подписями `5h`/`7d` (или именами окон при неполной cache-записи). Тесты покрывают оба случая. |
| T171 | Нужна развилка владельца | Часть про видимый залипший writer и typed refusal уже закрыта кодом #536: все новые отправки отказываются при обнаруженном конфликте. Не найден механизм усыновления оставшегося живым Codex app-server после рестарта; его открытые stdio pipes принадлежат прежнему процессу Orchestra. Вариант 1 — завершать старые процессы вместе с сервисом: проще, но прерывает провайдерный ход и требует решения по systemd/process-group lifecycle и рестарта. Вариант 2 — внешний supervisor/передача владения и pipes: сохраняет живой ход, но вводит новый process-ownership протокол и существенно расширяет восстановление. До выбора не менял lifecycle процессов и unit-файлы. |
| T174 | Нужна развилка владельца | Частичное закрытие #536 подтверждено тестом: detached writer виден как `broken`, повторные отправки получают typed conflict, lock не удаляется. Остаток — тот же, что в T171: после рестарта старый живой Codex app-server не усыновляется. Цена и варианты совпадают с T171; зафиксировал одну общую развилку, не дублировал механизм. |

## Проверки

Реальный Codex CLI в тестах не запускался. Изолированная проба формата T057 была отдельной от pytest и использовала только synthetic history в отдельном `CODEX_HOME`; модельный ход не запускался.

Точечная команда после изменений:

```text
/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_backend_codex.py::test_history_import_accepts_verified_0156_1_pin tests/test_codex_usage.py::test_fetch_codex_usage_ignores_process_lookup_race_on_cleanup tests/test_codex_usage.py::test_codex_usage_failure_logs_empty_timeout_repr tests/test_codex_mailbox_703.py tests/test_codex_quota_103.py tests/test_seamless_restart.py::test_t3_auto_resume_wakes_a_gracefully_interrupted_worker tests/test_codex_writer_conflict_536.py::test_detached_conflict_visible_and_every_send_refused tests/test_durable_steering_562.py::test_failed_turn_requeues_all_steers_fifo_and_is_idempotent tests/test_durable_steering_562.py::test_successful_turn_does_not_requeue_regular_delivery tests/test_model_text_control_flow.py::test_typed_transient_rate_limit_can_retry -q
```

Результат финального прогона: `15 passed`, включая live Codex steer с mailbox backup, погашение backup при успешном ходе, единственный replay после failed turn, выбор reset окна и не-terminal обычный 429. Импортированный `app.session` указывал на текущий checkout `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-codex/app/session.py`.

После коммита регрессии мутационно проверены: возврат pin к 0.153.4 дал ожидаемый FAIL T057; замена `%r` на `%s` и удаление защиты от `ProcessLookupError` дали FAIL T066. T067: тесты падают при удалении backup enqueue, успешного completion и failed-turn claim/replay. T103: тесты падают без quota error marker и при выборе reset неисчерпанного окна; обычный retryable 429 остаётся status/retry, не terminal quota. После каждой проверки реализация восстановлена; итоговый прогон зелёный.

Python-изменения требуют рестарта Orchestra владельцем.
